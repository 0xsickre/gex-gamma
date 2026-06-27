"""gex-gamma Streamlit dashboard — Dealer Gamma Exposure (port 8504)."""
from __future__ import annotations

import json
import os

import streamlit as st

from gex_gamma.core.reference_data import GEX_TICKERS
from gex_gamma.data.repositories.gex_repository import load_gex_panel_df
from gex_gamma.domain.gex_engine import persist_gex_snapshot
from gex_gamma.platform.settings import default_snapshot_path
from gex_gamma.services.build_gex_signal import build_gex_signal, public_gex_signal


def _load_snapshot() -> dict:
    path = default_snapshot_path()
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _fmt(v, spec: str = ",.0f") -> str:
    if v is None:
        return "—"
    try:
        return format(float(v), spec)
    except (TypeError, ValueError):
        return str(v)


st.set_page_config(page_title="GEX Gamma", layout="wide")
st.title("GEX Gamma")
st.caption("Dealer Gamma Exposure for SPX / NDX — Massive option chain, BS gamma recomputed locally")

snap = _load_snapshot()

if st.button("Refresh now"):
    try:
        row = build_gex_signal()
        snap = {**public_gex_signal(row), "instruments_full": row.get("instruments")}
        n = 0
        for profile in (row.get("instruments") or {}).values():
            if persist_gex_snapshot(profile, snapshot_date=snap.get("as_of")):
                n += 1
        path = default_snapshot_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, indent=2, default=str)
        st.success(f"Updated {path} ({n} instrument(s) persisted)")
    except Exception as e:
        st.error(str(e))

# Full per-instrument profiles live under instruments_full (snapshot) or instruments (live doc).
full = snap.get("instruments_full") or {}
public = snap.get("instruments") or {}

if not full and not public:
    st.warning("No snapshot — run `gex-signal` / `gex-refresh` or click Refresh now.")
    st.stop()

codes = list(full.keys()) or list(public.keys()) or list(GEX_TICKERS.keys())
code = st.selectbox("Instrument", codes, index=0)

prof = full.get(code) or public.get(code) or {}
st.caption(f"As of {snap.get('as_of', '—')} · computed {snap.get('computed_at', '—')}")

regime = prof.get("gamma_regime", "—")
st.metric("Gamma regime", regime)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Net GEX ($)", _fmt(prof.get("net_gex")))
c2.metric("Net GEX (z)", _fmt(prof.get("net_gex_norm"), "+.2f"))
c3.metric("Spot", _fmt(prof.get("spot"), ",.2f"))
c4.metric("Spot vs flip", _fmt(prof.get("spot_vs_flip"), "+.2%"))

c5, c6, c7, c8 = st.columns(4)
c5.metric("Gamma flip", _fmt(prof.get("gamma_flip"), ",.0f"))
c6.metric("Call wall", _fmt(prof.get("call_wall"), ",.0f"))
c7.metric("Put wall", _fmt(prof.get("put_wall"), ",.0f"))
c8.metric("0DTE share", _fmt(prof.get("dte0_share"), ".1%"))

c9, c10 = st.columns(2)
c9.metric("Near-term GEX", _fmt(prof.get("near_term_gex")))
c10.metric("Contracts", _fmt(prof.get("n_contracts"), ",.0f"))

st.subheader("History — net_gex_norm")
try:
    panel = load_gex_panel_df()
except Exception:
    panel = None
if panel is not None and not panel.empty:
    df = panel[panel["instrument"] == code].copy()
    if not df.empty and "net_gex_norm" in df.columns:
        df = df.dropna(subset=["net_gex_norm"]).sort_values("snapshot_date")
        if not df.empty:
            df = df.set_index("snapshot_date")
            st.line_chart(df["net_gex_norm"])
        else:
            st.info("No net_gex_norm history yet (panel needs ≥2 snapshots).")
    else:
        st.info("No history rows for this instrument yet.")
else:
    st.info("No history panel yet — run a few daily snapshots.")

with st.expander("Full profile JSON"):
    st.json(prof or {})
