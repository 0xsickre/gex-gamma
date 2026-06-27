"""HTTP GET with retries."""
from __future__ import annotations

from typing import Any

import requests

from gex_gamma.providers.retry_util import run_with_retries


def requests_get_retry(
    url: str,
    *,
    attempts: int = 4,
    base_seconds: float = 1.5,
    max_sleep: float = 45.0,
    default: Any = None,
    **kwargs,
):
    kwargs.setdefault("timeout", kwargs.get("timeout", 15))

    def call():
        r = requests.get(url, **kwargs)
        r.raise_for_status()
        return r

    return run_with_retries(
        call,
        attempts=attempts,
        base_seconds=base_seconds,
        max_sleep=max_sleep,
        exponential=True,
        default=default,
    )
