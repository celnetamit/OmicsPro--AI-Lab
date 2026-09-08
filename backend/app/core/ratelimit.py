"""Per-client sliding-window rate limiting.

In-process and therefore per-replica: with N replicas the effective limit is N
times the configured one. That is the honest trade for having no Redis
dependency, and it is sufficient for its purpose here — blunting credential
stuffing and runaway clients, not metering a public API. Moving to a shared
store means replacing ``_HITS`` and nothing else.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status


def parse_limit(spec: str) -> Tuple[int, float]:
    """Parse an "attempts/seconds" limit specification."""
    attempts, _, window = spec.partition("/")
    return int(attempts), float(window)


_HITS: Dict[str, Deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()
#: Buckets untouched for longer than this are dropped so memory cannot grow
#: without bound across many client addresses.
_SWEEP_AFTER_SECONDS = 3600.0
_last_sweep = 0.0


def client_key(request: Request) -> str:
    """Identify the caller.

    ``request.client.host`` is the proxy's address unless the ASGI server is
    started with ``--proxy-headers`` and a trusted forwarded-for list, which is
    how the container runs it.
    """
    return request.client.host if request.client else "unknown"


def _sweep(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < _SWEEP_AFTER_SECONDS:
        return
    _last_sweep = now
    for key in [k for k, hits in _HITS.items() if not hits or now - hits[-1] > _SWEEP_AFTER_SECONDS]:
        _HITS.pop(key, None)


def check(bucket: str, key: str, spec: str) -> Tuple[bool, int]:
    """Record a hit. Returns ``(allowed, retry_after_seconds)``."""
    attempts, window = parse_limit(spec)
    if attempts <= 0:
        return True, 0
    now = time.monotonic()
    slot = f"{bucket}:{key}"
    with _LOCK:
        _sweep(now)
        hits = _HITS[slot]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= attempts:
            return False, max(1, int(window - (now - hits[0])) + 1)
        hits.append(now)
        return True, 0


def enforce(request: Request, bucket: str, spec: str) -> None:
    """Raise 429 with a Retry-After header when the caller is over the limit."""
    allowed, retry_after = check(bucket, client_key(request), spec)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def reset() -> None:
    """Clear every bucket. For tests and for the admin console."""
    with _LOCK:
        _HITS.clear()
