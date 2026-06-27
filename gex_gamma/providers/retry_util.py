"""Retry with exponential backoff."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


def run_with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_seconds: float = 2.0,
    max_sleep: float = 60.0,
    exponential: bool = True,
    default: T | None = None,
) -> T | None:
    last: T | None = default
    n = max(1, int(attempts))
    for i in range(n):
        try:
            return fn()
        except Exception:
            if i < n - 1:
                delay = (
                    min(float(max_sleep), float(base_seconds) * (2**i))
                    if exponential
                    else min(float(max_sleep), float(base_seconds) * (i + 1))
                )
                time.sleep(delay)
            last = default
    return last
