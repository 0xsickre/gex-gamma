"""Domain reference data — GEX universe only (pure, no I/O).

The dealer-GEX domain only needs the index option underlyings and their Yahoo
spot proxies. The full COT display map stays in ``cot-report``.
"""
from __future__ import annotations

# Short code -> (Massive option-chain underlying, Yahoo spot ticker).
GEX_TICKERS = {
    "SPX": ("I:SPX", "^GSPC"),
    "NDX": ("I:NDX", "^NDX"),
}
