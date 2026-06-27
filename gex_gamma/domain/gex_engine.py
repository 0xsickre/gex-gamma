"""Dealer GEX feature engine for SPX / NDX.

Orchestrates: Yahoo spot -> Massive option chain -> :mod:`gex_gamma.core.gex_math`
profile -> persisted ``gex_snapshots`` row. Defensive ``None``-on-failure contract.
"""
from __future__ import annotations

import logging
from typing import Optional

from gex_gamma.core.gex_math import compute_gex_profile
from gex_gamma.core.reference_data import GEX_TICKERS
from gex_gamma.data.repositories import gex_repository as gex_repo
from gex_gamma.platform.cache import memoize
from gex_gamma.platform.live_config import STREAMLIT_YAHOO_CACHE_TTL_SEC
from gex_gamma.platform.secrets import get_secret
from gex_gamma.providers.massive_provider import chain_to_option_quotes, fetch_chain_snapshot
from gex_gamma.providers.price_source import history_close_series

_log = logging.getLogger(__name__)

_NORM_HISTORY_LIMIT = 120


def _risk_free_rate() -> float:
    try:
        return float(get_secret("GEX_RISK_FREE_RATE", "0.04"))
    except (TypeError, ValueError):
        return 0.04


def fetch_spot(yahoo_ticker: str) -> Optional[float]:
    """Latest daily close for the index spot, or None."""
    s = history_close_series(yahoo_ticker, period="5d")
    if s is None or s.empty:
        return None
    try:
        return float(s.iloc[-1])
    except (TypeError, ValueError, IndexError):
        return None


def load_recent_net_gex(instrument: str, limit: int = _NORM_HISTORY_LIMIT) -> list[float]:
    return gex_repo.load_recent_net_gex(instrument, limit)


@memoize(ttl=STREAMLIT_YAHOO_CACHE_TTL_SEC, show_spinner=False)
def compute_gex_for_instrument(short_code: str) -> Optional[dict]:
    """Compute the current GEX profile for an index short code (e.g. ``SPX``)."""
    code = str(short_code or "").upper().strip()
    cfg = GEX_TICKERS.get(code)
    if not cfg:
        return None
    underlying, yahoo_ticker = cfg

    spot = fetch_spot(yahoo_ticker)
    if spot is None or spot <= 0:
        _log.warning("GEX: no spot for %s (%s)", code, yahoo_ticker)
        return None

    rows = fetch_chain_snapshot(underlying, spot=spot)
    if not rows:
        _log.warning("GEX: no option chain for %s (%s)", code, underlying)
        return None

    quotes = chain_to_option_quotes(rows)
    if not quotes:
        return None

    history = load_recent_net_gex(code)
    profile = compute_gex_profile(
        quotes,
        spot=spot,
        r=_risk_free_rate(),
        instrument=code,
        history=history or None,
    )
    if profile is None:
        return None
    profile["instrument"] = code
    profile["underlying"] = underlying
    return profile


def persist_gex_snapshot(
    profile: dict,
    *,
    snapshot_date: Optional[str] = None,
    source: str = "massive",
) -> bool:
    """Upsert one GEX profile into ``gex_snapshots`` (keyed by date + instrument)."""
    return gex_repo.persist_gex_snapshot(profile, snapshot_date=snapshot_date, source=source)


def load_latest_gex(instrument: str) -> Optional[dict]:
    return gex_repo.load_latest_gex(instrument)
