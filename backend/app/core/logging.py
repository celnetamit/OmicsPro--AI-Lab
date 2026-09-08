"""Structured logging.

Every line carries the request id, so a learner reporting "run 3 failed at
10:42" can be traced from the access log to the exception that caused it.
"""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

from app.settings import settings

#: Set by the request-id middleware; read by the formatter and the handlers.
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["requestId"] = rid
        for key, value in getattr(record, "context", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        prefix = f"[{rid}] " if rid else ""
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {prefix}{record.getMessage()}"
        context = getattr(record, "context", {})
        if context:
            base += " " + " ".join(f"{k}={v}" for k, v in context.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if settings.log_json else _TextFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    #: uvicorn keeps its own handlers otherwise, and every line is logged twice.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    #: The access log is emitted by our own middleware, with the request id.
    logging.getLogger("uvicorn.access").disabled = True


def log_context(**fields) -> dict:
    """Build the ``extra`` argument for a contextual log call."""
    return {"context": fields}
