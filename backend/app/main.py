"""OmicsLab Pro API.

All three phases are implemented; ``ACTIVE_PHASE`` decides what is routable.
This module is the deployment surface: configuration, logging, the security
headers, the error boundary, and the lifecycle of the run worker pool.
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import (
    admin,
    auth,
    billing,
    capstone,
    copilot,
    datasets,
    design,
    entitlements,
    program,
    reports,
    runs,
)
from app.constants import ACTIVE_PHASE
from app.core import jobs, ratelimit
from app.core.logging import configure_logging, log_context, new_request_id, request_id_var
from app.db import engine, init_db
from app.settings import settings

log = logging.getLogger("omicslab.api")

#: Paths excluded from the access log: the platform's own liveness traffic
#: would otherwise be the bulk of it.
_QUIET_PATHS = {"/api/health", "/api/health/ready"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    log.info(
        "starting",
        extra=log_context(
            environment=settings.environment,
            release=settings.release,
            phase=ACTIVE_PHASE,
            runExecution=settings.run_execution_mode,
        ),
    )
    if settings.database_url.startswith("sqlite"):
        #: Deployments migrate with Alembic; SQLite development creates tables
        #: in place so a clone runs without a migration step.
        init_db()
    jobs.reap_orphaned_runs()
    if settings.run_execution_mode != "inline":
        jobs.start_pool()
    try:
        yield
    finally:
        log.info("shutting down; waiting for in-flight runs")
        jobs.shutdown_pool(wait=True)


app = FastAPI(
    title=settings.app_name,
    version=f"phase-{ACTIVE_PHASE}",
    lifespan=lifespan,
    #: The interactive docs expose the whole surface; useful in development,
    #: not something to publish alongside a production deployment.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)


@app.middleware("http")
async def observability(request: Request, call_next):
    """Assign a request id, time the request, and log its outcome.

    The id is echoed on the response and included in error bodies so a learner
    can quote it and have the exact request found in the log.
    """
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming[:64] if incoming else new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((time.perf_counter() - started) * 1000)
        log.exception(
            "unhandled error",
            extra=log_context(
                method=request.method, path=request.url.path, durationMs=duration_ms
            ),
        )
        request_id_var.reset(token)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Something went wrong on our side. Nothing you submitted was lost. "
            "Quote this reference if you report it.",
            request_id,
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    if request.url.path not in _QUIET_PATHS:
        log.info(
            "request",
            extra=log_context(
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                durationMs=duration_ms,
            ),
        )
    request_id_var.reset(token)
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """A blanket per-client ceiling. The auth endpoints add tighter limits."""
    if request.method != "OPTIONS" and request.url.path.startswith("/api"):
        allowed, retry_after = ratelimit.check(
            "global", ratelimit.client_key(request), settings.global_rate_limit
        )
        if not allowed:
            return _error_response(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests. Wait a moment and try again.",
                request_id_var.get(),
                headers={"Retry-After": str(retry_after)},
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers that cost nothing and close whole classes of attack.

    The API serves JSON only, so its own CSP can forbid everything; the front
    end is a separate origin with its own policy set at the web server.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
    )
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    response.headers.setdefault("Cache-Control", "no-store")
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security",
            f"max-age={settings.hsts_max_age_seconds}; includeSubDomains",
        )
    return response


app.add_middleware(GZipMiddleware, minimum_size=1024)

if settings.trusted_host_list != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


def _error_response(code: int, message: str, request_id, headers: dict = None) -> JSONResponse:
    body = {"detail": {"error": "internal_error", "message": message}}
    if request_id:
        body["detail"]["requestId"] = request_id
    return JSONResponse(body, status_code=code, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException):
    """Preserve the routers' structured entitlement bodies, add the request id."""
    detail = exc.detail
    if isinstance(detail, dict):
        body = {"detail": {**detail, "requestId": request_id_var.get()}}
    else:
        body = {"detail": detail, "requestId": request_id_var.get()}
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    """A malformed request is the client's bug; say which field, not why the
    server's parser objected."""
    fields = {}
    for error in exc.errors():
        location = ".".join(str(p) for p in error.get("loc", []) if p not in ("body", "query"))
        fields[location or "request"] = error.get("msg", "Invalid value")
    return JSONResponse(
        {
            "detail": {
                "error": "invalid_request",
                "message": "Some of the values sent were not valid.",
                "fields": fields,
                "requestId": request_id_var.get(),
            }
        },
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
    log.exception("unhandled error", extra=log_context(path=request.url.path))
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Something went wrong on our side. Nothing you submitted was lost.",
        request_id_var.get(),
    )


for router in (
    auth.router,
    entitlements.router,
    program.router,
    design.router,
    datasets.router,
    runs.router,
    copilot.router,
    billing.router,
    capstone.router,
    reports.router,
    admin.router,
):
    app.include_router(router)


@app.get("/api/health", tags=["ops"])
def health() -> dict:
    """Liveness. Deliberately does not touch the database: a database blip
    should not make the orchestrator kill a process that is running fine."""
    return {
        "status": "ok",
        "activePhase": ACTIVE_PHASE,
        "release": settings.release,
        "environment": settings.environment,
    }


@app.get("/api/health/ready", tags=["ops"])
def readiness() -> JSONResponse:
    """Readiness: can this process actually serve requests?"""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        log.exception("readiness check failed")
        database_ok = False

    body = {
        "status": "ok" if database_ok else "degraded",
        "database": "ok" if database_ok else "unavailable",
        "runsInFlight": jobs.in_flight_count(),
        "release": settings.release,
    }
    return JSONResponse(body, status_code=200 if database_ok else 503)
