"""Background execution of pipeline runs.

A real Core or Advanced run takes minutes. Executing it inside the HTTP request
means the client sits on an open connection until a proxy times it out and the
learner sees a network error for a run that is actually still going, so the API
records the run, hands back its id, and executes on this pool while the client
polls the run record.

The pool is in-process and bounded. That makes this a single-container design:
scaling out means moving ``submit`` onto a real queue, and nothing else in the
application changes, because status already lives in the database rather than
in the worker.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select

from app.constants import RunStatus
from app.core.logging import log_context, new_request_id, request_id_var
from app.db import SessionLocal
from app.models import Run
from app.pipelines import runner
from app.pipelines.base import DataObject
from app.settings import settings

log = logging.getLogger("omicslab.jobs")

_pool: Optional[ThreadPoolExecutor] = None
_lock = threading.Lock()
#: Run ids currently executing on this worker, for the health endpoint.
_in_flight: set = set()


def start_pool() -> None:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=settings.run_worker_threads, thread_name_prefix="omicslab-run"
            )


def shutdown_pool(wait: bool = True) -> None:
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=wait)


def in_flight_count() -> int:
    return len(_in_flight)


def submit(
    db,
    run: Run,
    data: DataObject,
    on_complete: Optional[Callable[[object, Run], None]] = None,
) -> None:
    """Execute a run, in the background or inline depending on configuration.

    ``on_complete`` runs in the same session and thread as the execution, after
    the run reaches a terminal state. It is how work that depends on a run's
    outputs — reconciling a perturbation against its original — happens without
    the request having waited for the pipeline.

    Inline mode executes on the caller's session so the result is visible in the
    response that created the run; it is what the test suite asserts against.
    """
    if settings.run_execution_mode == "inline":
        _run_one(db, run, data, on_complete)
        return
    start_pool()
    assert _pool is not None
    _pool.submit(_execute_detached, run.id, data, on_complete, request_id_var.get())


def _run_one(session, run: Run, data: DataObject, on_complete) -> None:
    """Execute one run and its completion hook, converting any escape to a
    recorded failure rather than a lost run."""
    run_id = run.id
    _in_flight.add(run_id)
    started = datetime.utcnow()
    try:
        runner.execute(session, run, data)
        if on_complete is not None:
            on_complete(session, run)
        log.info(
            "run finished",
            extra=log_context(
                runId=run_id,
                status=str(run.status),
                durationMs=int((datetime.utcnow() - started).total_seconds() * 1000),
            ),
        )
    except Exception:
        #: runner.execute records step failures itself; reaching here means the
        #: executor broke, and the run must not be left claiming to be running.
        log.exception("run executor failed", extra=log_context(runId=run_id))
        _mark_failed(
            session,
            run_id,
            "The analysis stopped because of an internal error. No results were "
            "produced, and nothing you submitted was lost.",
        )
    finally:
        _in_flight.discard(run_id)


def _execute_detached(
    run_id: str, data: DataObject, on_complete, parent_request_id: Optional[str] = None
) -> None:
    """Worker-thread entry point: its own session, its own error boundary."""
    #: A worker thread has its own context; tie its lines to the request that
    #: queued the work so a run can be traced end to end.
    request_id_var.set(parent_request_id or new_request_id())
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if run is None:
            log.error("queued run vanished", extra=log_context(runId=run_id))
            return
        if run.status not in (RunStatus.QUEUED, RunStatus.VALIDATING):
            #: Cancelled between submission and pick-up, or already executed.
            return
        _run_one(session, run, data, on_complete)
    finally:
        session.close()


def _mark_failed(session, run_id: str, message: str) -> None:
    try:
        session.rollback()
        run = session.get(Run, run_id)
        if run is not None and run.status not in (RunStatus.COMPLETED, RunStatus.CANCELLED):
            run.status = RunStatus.FAILED
            run.error_message = message
            run.finished_at = datetime.utcnow()
            session.commit()
    except Exception:  # pragma: no cover - the database itself is unavailable
        log.exception("could not record run failure", extra=log_context(runId=run_id))


def reap_orphaned_runs() -> int:
    """Fail runs left mid-flight by a crash or a redeploy.

    A run marked RUNNING with no worker behind it is a lie the workspace would
    otherwise show forever, so on boot every run still claiming to be in flight
    is closed out with an explanation the learner can act on.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=settings.run_stale_after_minutes)
    session = SessionLocal()
    try:
        stale = session.scalars(
            select(Run).where(
                Run.status.in_([RunStatus.QUEUED, RunStatus.VALIDATING, RunStatus.RUNNING])
            )
        ).all()
        reaped = 0
        for run in stale:
            #: Only runs from before this process started; a fresh boot has none
            #: of its own in flight, so the cutoff only spares long-running work
            #: in a deployment where the pool outlives the check.
            if run.started_at and run.started_at > cutoff:
                continue
            run.status = RunStatus.FAILED
            run.error_message = (
                "This run was interrupted when the service restarted. Its inputs "
                "and parameters are unchanged, so it can be started again."
            )
            run.error_detail = "interrupted; reaped at startup"
            run.finished_at = datetime.utcnow()
            reaped += 1
        if reaped:
            session.commit()
            log.warning("reaped interrupted runs", extra=log_context(count=reaped))
        return reaped
    finally:
        session.close()
