"""Cache TTL + Massive fetch fence flags."""
from __future__ import annotations

import os

STREAMLIT_YAHOO_CACHE_TTL_SEC = 300


def massive_fetch_enabled() -> bool:
    """Whether live Massive calls are allowed. Default on; set to 0 to fence the UI."""
    raw = (os.environ.get("GEX_MASSIVE_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")
