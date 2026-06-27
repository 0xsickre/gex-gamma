"""Build and publish the gex_signal contract.

Orchestrates per-instrument :func:`compute_gex_for_instrument` into a single
snapshot document, plus a thin public contract for downstream consumers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from gex_gamma.core.reference_data import GEX_TICKERS
from gex_gamma.domain.gex_engine import compute_gex_for_instrument

# Thin public contract keys per instrument.
_PUBLIC_KEYS = (
    "gamma_regime",
    "net_gex_norm",
    "spot_vs_flip",
    "gamma_flip",
    "call_wall",
    "put_wall",
)


def build_gex_signal(instruments: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Compute the full GEX profile for each instrument and assemble the snapshot doc."""
    codes = [str(c).upper().strip() for c in (instruments or GEX_TICKERS.keys())]

    # Drop the memoized cache so a refresh re-fetches the live chain.
    try:
        compute_gex_for_instrument.clear()
    except Exception:
        pass

    profiles: dict[str, dict] = {}
    for code in codes:
        profile = compute_gex_for_instrument(code)
        if profile:
            profiles[code] = profile

    computed_at = datetime.now(timezone.utc).isoformat()
    as_of = datetime.now(timezone.utc).date().isoformat()

    return {
        "as_of": as_of,
        "computed_at": computed_at,
        "instruments": profiles,
    }


def public_gex_signal(row: dict[str, Any]) -> dict[str, Any]:
    """Reduce the full doc to the thin published contract per instrument."""
    out_instruments: dict[str, dict] = {}
    for code, profile in (row.get("instruments") or {}).items():
        out_instruments[code] = {k: profile.get(k) for k in _PUBLIC_KEYS}
    return {
        "as_of": row.get("as_of"),
        "computed_at": row.get("computed_at"),
        "instruments": out_instruments,
    }
