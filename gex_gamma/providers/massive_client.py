"""Massive (Polygon-compatible) REST client — rate-limited HTTP helpers.

Used by :mod:`gex_gamma.providers.massive_provider` (option chain). One process-local
token bucket keeps callers under the free-tier budget (default 4.0 req/min, hard
5/min ceiling). Decoupled standalone copy — no Supabase global gate, no monolith
``data_refresh_policy``; the UI fence is a simple :func:`live_config.massive_fetch_enabled`.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from gex_gamma.platform.secrets import get_secret
from gex_gamma.providers.massive_rate_limiter import (
    CircuitBreaker,
    TokenBucket,
    backoff_delay,
    is_rate_limit_response,
    retry_after_seconds,
)
from gex_gamma.providers.retry_http import requests_get_retry

_log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.massive.com"
_MAX_RATE_LIMIT_WAITS = 6
_REQUEST_TIMEOUT = 20
_PAGINATION_HARD_CAP = 25
_RATE_LIMIT_BACKOFF_BASE = 20.0
_BREAKER_COOLDOWN_SEC = 180.0

_bucket: Optional[TokenBucket] = None
_breaker: Optional[CircuitBreaker] = None


class MassiveError(RuntimeError):
    """Non-retryable provider failure (missing key, open circuit, exhausted retries)."""


def rate_per_min() -> float:
    raw = get_secret("MASSIVE_RATE_PER_MIN", "4.0")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 4.0


def get_bucket() -> TokenBucket:
    global _bucket
    if _bucket is None:
        _bucket = TokenBucket(rate_per_min=rate_per_min(), burst=1.0)
    return _bucket


def get_breaker() -> CircuitBreaker:
    global _breaker
    if _breaker is None:
        _breaker = CircuitBreaker(fail_threshold=5, cooldown_seconds=_BREAKER_COOLDOWN_SEC)
    return _breaker


def api_key() -> Optional[str]:
    key = get_secret("MASSIVE_API_KEY", "")
    return key or None


def base_url() -> str:
    return (get_secret("MASSIVE_API_BASE", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")


def _streamlit_blocked() -> bool:
    try:
        from gex_gamma.platform.live_config import massive_fetch_enabled

        return not massive_fetch_enabled()
    except Exception:
        return False


def get_json(url: str, params: Optional[dict] = None) -> Optional[dict]:
    """GET with token-bucket throttle, 429 handling, circuit breaker."""
    if _streamlit_blocked():
        _log.debug("Massive fetch fenced (GEX_MASSIVE_ENABLED=0)")
        return None

    breaker = get_breaker()
    if not breaker.allow():
        _log.warning("Massive circuit breaker open — skipping request to %s", url)
        return None

    bucket = get_bucket()

    for attempt in range(_MAX_RATE_LIMIT_WAITS):
        bucket.acquire()
        try:
            resp = requests_get_retry(
                url,
                params=params,
                timeout=_REQUEST_TIMEOUT,
                attempts=3,
                base_seconds=1.0,
                default=None,
            )
            if resp is None:
                raise requests.RequestException("exhausted retries")
        except requests.RequestException as e:
            breaker.record_failure()
            _log.warning("Massive request error (%s): %s", url, e)
            time.sleep(backoff_delay(attempt))
            continue

        body_preview = resp.text[:512] if resp.content else ""
        if is_rate_limit_response(resp.status_code, body_preview):
            wait = retry_after_seconds(
                resp.headers, default=backoff_delay(attempt, base_seconds=_RATE_LIMIT_BACKOFF_BASE)
            )
            _log.info("Massive rate-limited; backing off %.1fs (attempt %d)", wait, attempt + 1)
            time.sleep(max(0.0, float(wait)))
            continue

        if resp.status_code >= 500:
            breaker.record_failure()
            time.sleep(backoff_delay(attempt))
            continue

        if resp.status_code >= 400:
            breaker.record_failure()
            raise MassiveError(f"Massive {resp.status_code} for {url}: {body_preview}")

        try:
            data = resp.json()
        except ValueError as e:
            breaker.record_failure()
            raise MassiveError(f"Massive non-JSON response for {url}: {e}") from e
        breaker.record_success()
        return data

    breaker.record_failure()
    _log.warning("Massive: rate-limit retries exhausted for %s", url)
    return None


def paginate(first_url: str, params: dict) -> list[dict]:
    """Follow Polygon-style ``next_url`` pagination."""
    results: list[dict] = []
    key = api_key()
    data = get_json(first_url, params)
    pages = 0
    while data is not None and pages < _PAGINATION_HARD_CAP:
        rows = data.get("results")
        if isinstance(rows, list):
            results.extend(rows)
        next_url = data.get("next_url")
        if not next_url:
            break
        sep = "&" if "?" in next_url else "?"
        data = get_json(f"{next_url}{sep}apiKey={key}" if key else next_url)
        pages += 1
    return results
