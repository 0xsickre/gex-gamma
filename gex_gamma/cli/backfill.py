"""Resumable GEX backfill / coverage driver (entry point: ``gex-backfill``).

The Massive free Basic tier exposes a *live* option-chain snapshot (current OI +
prices) but no historical option open-interest, so dealer-GEX history cannot be
reconstructed retroactively. This driver therefore:

1. is RESUMABLE — already-stored (snapshot_date, instrument) rows are skipped;
2. captures TODAY's snapshot (forward accumulation — the panel grows one trading
   day at a time until it is long enough for the IC harness);
3. reports coverage gaps over the requested window.

Usage (PowerShell, from repo root):
    $env:MASSIVE_API_KEY = "..."
    gex-backfill --days 730
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, timedelta

os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from gex_gamma.core.reference_data import GEX_TICKERS  # noqa: E402
from gex_gamma.data.backend import ensure_schema, read_sql_pandas, use_postgresql  # noqa: E402
from gex_gamma.domain.gex_engine import compute_gex_for_instrument, persist_gex_snapshot  # noqa: E402


def _existing_dates(instrument: str) -> set[str]:
    try:
        df = read_sql_pandas(
            "SELECT snapshot_date FROM gex_snapshots WHERE instrument = ?",
            (str(instrument),),
        )
    except Exception:
        return set()
    if df is None or df.empty:
        return set()
    return {str(x)[:10] for x in df["snapshot_date"].tolist()}


def _business_days(days_back: int) -> list[str]:
    today = date.today()
    out = []
    for i in range(int(days_back) + 1):
        d = today - timedelta(days=i)
        if d.weekday() < 5:  # Mon-Fri
            out.append(d.isoformat())
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resumable GEX coverage / forward backfill")
    ap.add_argument("--days", type=int, default=730, help="window for coverage report (default 730 ~= 2y)")
    ap.add_argument(
        "--instruments",
        nargs="+",
        default=list(GEX_TICKERS.keys()),
        help=f"index short codes (default: {' '.join(GEX_TICKERS)})",
    )
    args = ap.parse_args(argv)

    ensure_schema()
    backend = "Supabase/PostgreSQL" if use_postgresql() else "lokalni SQLite"
    print(f"=== GEX backfill -> {backend} | window={args.days}d | instruments={args.instruments} ===")
    print("  (Napomena: free tier nema istorijski OI — istorija se gradi unapred, dan po dan.)")

    today_iso = date.today().isoformat()
    for code in args.instruments:
        window = _business_days(args.days)
        have = _existing_dates(code)
        missing = [d for d in window if d not in have]
        covered = len(window) - len(missing)
        print(f"\n[{code}] pokrivenost: {covered}/{len(window)} radnih dana u prozoru.")

        if today_iso in have:
            print(f"  danasnji snapshot ({today_iso}) vec postoji — preskacem.")
            continue

        profile = compute_gex_for_instrument(code)
        if not profile:
            print("  danasnji snapshot nije moguc (nema spot/chain).")
            continue
        if persist_gex_snapshot(profile, snapshot_date=today_iso, source="backfill"):
            print(
                f"  upisan danasnji snapshot: net_gex={profile.get('net_gex'):,.0f} "
                f"regime={profile.get('gamma_regime')}"
            )
        else:
            print("  upis danasnjeg snapshota nije uspeo.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
