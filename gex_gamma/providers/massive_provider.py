"""Massive (Polygon-compatible) options data provider — rate-limited, cached.

See :mod:`gex_gamma.providers.massive_client` for shared HTTP / rate limiting.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from gex_gamma.platform.cache import memoize

from .massive_client import MassiveError, api_key, base_url, paginate

_log = logging.getLogger(__name__)

REFERENCE_CACHE_TTL_SEC = 24 * 3600
_STRIKE_BAND = 0.15
_MAX_DTE_DAYS = 90


def _normalize_contract(row: dict) -> Optional[dict]:
    """Map a Massive/Polygon snapshot contract to the minimal GEX row, or None if unusable."""
    details = row.get("details") if isinstance(row.get("details"), dict) else row
    ctype = str(details.get("contract_type") or details.get("type") or "").lower()
    if ctype not in ("call", "put"):
        return None
    try:
        strike = float(details.get("strike_price") or details.get("strike"))
    except (TypeError, ValueError):
        return None
    expiration = details.get("expiration_date") or details.get("expiration")

    oi = row.get("open_interest")
    if oi is None and isinstance(row.get("day"), dict):
        oi = row["day"].get("open_interest")
    try:
        oi = float(oi) if oi is not None else 0.0
    except (TypeError, ValueError):
        oi = 0.0

    iv = row.get("implied_volatility")
    if iv is None and isinstance(row.get("greeks"), dict):
        iv = row["greeks"].get("iv")
    try:
        iv = float(iv) if iv is not None else None
    except (TypeError, ValueError):
        iv = None

    mid = None
    day = row.get("day") if isinstance(row.get("day"), dict) else {}
    last_quote = row.get("last_quote") if isinstance(row.get("last_quote"), dict) else {}
    bid, ask = last_quote.get("bid"), last_quote.get("ask")
    try:
        if bid is not None and ask is not None and float(bid) > 0 and float(ask) > 0:
            mid = 0.5 * (float(bid) + float(ask))
        elif day.get("close") is not None:
            mid = float(day.get("close"))
    except (TypeError, ValueError):
        mid = None

    return {
        "strike": strike,
        "is_call": ctype == "call",
        "open_interest": oi,
        "iv": iv,
        "mid": mid,
        "expiration": str(expiration) if expiration else None,
    }


@memoize(ttl=REFERENCE_CACHE_TTL_SEC, show_spinner=False)
def fetch_chain_snapshot(underlying: str, spot: Optional[float] = None) -> Optional[list[dict]]:
    """Live option-chain snapshot for an index underlying (e.g. ``I:SPX``)."""
    key = api_key()
    if not key:
        _log.warning("MASSIVE_API_KEY not set — GEX snapshot unavailable.")
        return None

    params: dict[str, Any] = {"apiKey": key, "limit": 250}
    exp_max = (date.today() + timedelta(days=_MAX_DTE_DAYS)).isoformat()
    params["expiration_date.lte"] = exp_max
    if spot and spot > 0:
        params["strike_price.gte"] = round(spot * (1.0 - _STRIKE_BAND), 2)
        params["strike_price.lte"] = round(spot * (1.0 + _STRIKE_BAND), 2)

    url = f"{base_url()}/v3/snapshot/options/{underlying}"
    try:
        rows = paginate(url, params)
    except MassiveError as e:
        _log.warning("Massive chain snapshot failed for %s: %s", underlying, e)
        return None

    out = [c for c in (_normalize_contract(r) for r in rows) if c is not None]
    return out or None


def chain_to_option_quotes(rows: list[dict], asof: Optional[datetime] = None) -> list:
    """Convert normalized rows into :class:`OptionQuote` with year-fraction DTE."""
    from gex_gamma.core.gex_math import OptionQuote

    ref = asof or datetime.utcnow()
    quotes: list[OptionQuote] = []
    for r in rows:
        exp = r.get("expiration")
        if not exp:
            continue
        try:
            exp_dt = datetime.strptime(str(exp)[:10], "%Y-%m-%d")
        except ValueError:
            continue
        dte_days = (exp_dt - ref).total_seconds() / 86400.0
        if dte_days <= 0:
            continue
        quotes.append(
            OptionQuote(
                strike=float(r["strike"]),
                is_call=bool(r["is_call"]),
                open_interest=float(r.get("open_interest") or 0.0),
                dte_years=dte_days / 365.0,
                iv=r.get("iv"),
                mid=r.get("mid"),
            )
        )
    return quotes
