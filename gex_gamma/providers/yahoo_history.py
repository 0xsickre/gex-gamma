"""Yahoo Ticker.history close series."""
from __future__ import annotations

from typing import Any

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

from gex_gamma.providers.retry_util import run_with_retries


def _strip_tz_index(obj: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    idx = obj.index
    if getattr(idx, "tz", None) is not None:
        out = obj.copy()
        out.index = pd.DatetimeIndex(idx).tz_localize(None)
        return out
    return obj


def yahoo_history_close_series(
    ticker: str,
    *,
    start=None,
    end=None,
    period: str | None = None,
    interval: str = "1d",
    auto_adjust: bool = True,
) -> pd.Series:
    if yf is None or not str(ticker or "").strip():
        return pd.Series(dtype=float)
    sym = str(ticker).strip()

    def _pull():
        kw: dict[str, Any] = {"interval": interval, "auto_adjust": auto_adjust}
        if period:
            kw["period"] = period
        else:
            kw["start"] = start
            kw["end"] = end
        return yf.Ticker(sym).history(**kw)

    try:
        hist = run_with_retries(_pull, attempts=4, base_seconds=1.5, max_sleep=45.0, default=None)
    except Exception:
        return pd.Series(dtype=float)
    if hist is None or hist.empty or "Close" not in hist.columns:
        return pd.Series(dtype=float)
    s = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    if s.empty:
        return pd.Series(dtype=float)
    return _strip_tz_index(s).sort_index()


def history_close_series(
    ticker: str,
    *,
    start=None,
    end=None,
    period: str | None = None,
    interval: str = "1d",
    auto_adjust: bool = True,
) -> pd.Series:
    return yahoo_history_close_series(
        ticker,
        start=start,
        end=end,
        period=period,
        interval=interval,
        auto_adjust=auto_adjust,
    )
