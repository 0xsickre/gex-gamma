"""Client-side rate limiting + 429 handling for strict free-tier APIs.

Massive (Polygon-compatible) free Basic tier caps at 5 requests/minute. Exceeding
it returns HTTP 429 — but the body text (``"maximum requests"`` / ``"rate limit"``)
must be matched too, since the status is not always preserved. This module provides:

- :class:`TokenBucket` — a thread-safe token bucket (default 4.5 req/min) that
  *blocks* until a token is available.
- :func:`is_rate_limit_response` — detect a 429 by status **or** body text.
- :func:`retry_after_seconds` — parse the ``Retry-After`` header.
- :class:`CircuitBreaker` — trip open after consecutive failures, half-open after cooldown.

Pure stdlib; no I/O, no framework imports.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any, Optional

_RATE_LIMIT_BODY_MARKERS = ("maximum requests", "rate limit", "too many requests")


class TokenBucket:
    """Thread-safe token bucket; :meth:`acquire` blocks until a token is free."""

    def __init__(self, rate_per_min: float = 4.5, *, burst: Optional[float] = None) -> None:
        if rate_per_min <= 0:
            raise ValueError("rate_per_min must be > 0")
        self._rate_per_sec = float(rate_per_min) / 60.0
        self._capacity = float(burst) if burst is not None else max(1.0, float(rate_per_min))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill_locked(self, now: float) -> None:
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_sec)
            self._updated = now

    def acquire(self, tokens: float = 1.0, *, timeout: Optional[float] = None) -> bool:
        """Block until ``tokens`` are available. Returns False if ``timeout`` elapses."""
        deadline = None if timeout is None else (time.monotonic() + float(timeout))
        while True:
            with self._lock:
                now = time.monotonic()
                self._refill_locked(now)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                missing = tokens - self._tokens
                wait = missing / self._rate_per_sec
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)
            time.sleep(max(0.0, wait))


def is_rate_limit_response(status_code: Any = None, body: Any = None) -> bool:
    """True if the response looks rate-limited by status code *or* body text."""
    try:
        if status_code is not None and int(status_code) == 429:
            return True
    except (TypeError, ValueError):
        pass
    if body is None:
        return False
    text = str(body).lower()
    return any(marker in text for marker in _RATE_LIMIT_BODY_MARKERS)


def retry_after_seconds(headers: Any, *, default: Optional[float] = None) -> Optional[float]:
    """Parse ``Retry-After`` (delta-seconds only) from a headers mapping."""
    if not headers:
        return default
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return default
    if raw is None:
        return default
    try:
        secs = float(str(raw).strip())
        return max(0.0, secs)
    except (TypeError, ValueError):
        return default


def backoff_delay(attempt: int, *, base_seconds: float = 2.0, max_sleep: float = 60.0, jitter: float = 0.3) -> float:
    """Exponential backoff with full-ish jitter for retry attempt ``attempt`` (0-based)."""
    raw = min(float(max_sleep), float(base_seconds) * (2 ** max(0, int(attempt))))
    spread = raw * float(jitter)
    return max(0.0, raw - spread + random.uniform(0.0, 2.0 * spread))


class CircuitBreaker:
    """Trip open after ``fail_threshold`` consecutive failures; half-open after cooldown."""

    def __init__(self, *, fail_threshold: int = 5, cooldown_seconds: float = 120.0) -> None:
        self._fail_threshold = max(1, int(fail_threshold))
        self._cooldown = float(cooldown_seconds)
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """False while the breaker is open and still inside the cooldown window."""
        with self._lock:
            if self._opened_at is None:
                return True
            if (time.monotonic() - self._opened_at) >= self._cooldown:
                self._opened_at = None  # half-open: let one probe through
                self._failures = 0
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._fail_threshold and self._opened_at is None:
                self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None and (time.monotonic() - self._opened_at) < self._cooldown
