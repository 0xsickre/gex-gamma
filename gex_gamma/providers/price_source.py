"""Spot price source for GEX — Yahoo daily close only.

GEX needs only the index spot (``^GSPC`` / ``^NDX``); the Massive EOD price
provider lives in the monolith's price router and is intentionally not ported.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from gex_gamma.providers.yahoo_history import history_close_series as _yahoo_close


def history_close_series(
    ticker: str,
    *,
    start: Any = None,
    end: Any = None,
    period: str | None = None,
    interval: str = "1d",
    auto_adjust: bool = True,
) -> pd.Series:
    sym = str(ticker or "").strip()
    if not sym:
        return pd.Series(dtype=float)
    return _yahoo_close(
        sym,
        start=start,
        end=end,
        period=period,
        interval=interval,
        auto_adjust=auto_adjust,
    )
