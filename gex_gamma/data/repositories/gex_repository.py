"""GEX snapshot persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from gex_gamma.data.backend import ensure_schema, get_connection, read_sql_pandas


def load_recent_net_gex(instrument: str, limit: int) -> list[float]:
    try:
        df = read_sql_pandas(
            "SELECT net_gex FROM gex_snapshots WHERE instrument = ? "
            "ORDER BY snapshot_date DESC LIMIT ?",
            (str(instrument), int(limit)),
        )
    except Exception:
        return []
    if df is None or df.empty or "net_gex" not in df.columns:
        return []
    return [float(x) for x in df["net_gex"].dropna().tolist()]


def load_gex_panel_df():
    import pandas as pd

    try:
        return read_sql_pandas(
            "SELECT snapshot_date, instrument, net_gex_norm, spot_vs_flip FROM gex_snapshots"
        )
    except Exception:
        return pd.DataFrame()


def persist_gex_snapshot(profile: dict, *, snapshot_date: Optional[str] = None, source: str = "massive") -> bool:
    if not isinstance(profile, dict) or not profile.get("instrument"):
        return False
    snap_date = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        ensure_schema()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO gex_snapshots (
                    snapshot_date, instrument, spot, net_gex, net_gex_norm, gamma_flip,
                    spot_vs_flip, gamma_regime, call_wall, put_wall, near_term_gex,
                    dte0_share, n_contracts, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_date, instrument) DO UPDATE SET
                    spot = excluded.spot,
                    net_gex = excluded.net_gex,
                    net_gex_norm = excluded.net_gex_norm,
                    gamma_flip = excluded.gamma_flip,
                    spot_vs_flip = excluded.spot_vs_flip,
                    gamma_regime = excluded.gamma_regime,
                    call_wall = excluded.call_wall,
                    put_wall = excluded.put_wall,
                    near_term_gex = excluded.near_term_gex,
                    dte0_share = excluded.dte0_share,
                    n_contracts = excluded.n_contracts,
                    source = excluded.source,
                    created_at = excluded.created_at
                """,
                (
                    snap_date,
                    str(profile["instrument"]),
                    profile.get("spot"),
                    profile.get("net_gex"),
                    profile.get("net_gex_norm"),
                    profile.get("gamma_flip"),
                    profile.get("spot_vs_flip"),
                    profile.get("gamma_regime"),
                    profile.get("call_wall"),
                    profile.get("put_wall"),
                    profile.get("near_term_gex"),
                    profile.get("dte0_share"),
                    profile.get("n_contracts"),
                    source,
                    now_iso,
                ),
            )
            conn.commit()
        return True
    except Exception:
        return False


def load_latest_gex(instrument: str) -> Optional[dict]:
    try:
        df = read_sql_pandas(
            "SELECT snapshot_date, instrument, spot, net_gex, net_gex_norm, gamma_flip, "
            "spot_vs_flip, gamma_regime, call_wall, put_wall, near_term_gex, dte0_share "
            "FROM gex_snapshots WHERE instrument = ? ORDER BY snapshot_date DESC LIMIT 1",
            (str(instrument),),
        )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return df.iloc[0].to_dict()
