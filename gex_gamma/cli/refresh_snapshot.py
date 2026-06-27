"""Nightly EOD GEX snapshot job (entry point: ``gex-refresh``).

Reads the live Massive option chain (rate-limited), computes dealer gamma features
locally, and upserts into ``gex_snapshots``. Idempotent per (snapshot_date,
instrument): safe to re-run.

Usage (PowerShell, from repo root):
    $env:MASSIVE_API_KEY = "..."          # required
    # optional: write to Supabase instead of local SQLite
    $env:DATABASE_URL = "postgresql://...pooler.supabase.com:6543/postgres?sslmode=require"
    gex-refresh
    gex-refresh --instruments SPX
"""
from __future__ import annotations

import argparse
import json
import logging
import os

os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from gex_gamma.core.reference_data import GEX_TICKERS  # noqa: E402
from gex_gamma.data.backend import ensure_schema, use_postgresql  # noqa: E402
from gex_gamma.domain.gex_engine import compute_gex_for_instrument, persist_gex_snapshot  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nightly EOD dealer-GEX snapshot")
    ap.add_argument(
        "--instruments",
        nargs="+",
        default=list(GEX_TICKERS.keys()),
        help=f"index short codes (default: {' '.join(GEX_TICKERS)})",
    )
    ap.add_argument("--date", default=None, help="override snapshot_date (YYYY-MM-DD); default = today UTC")
    ap.add_argument("--json", action="store_true", help="print summary JSON on stdout")
    args = ap.parse_args(argv)

    ensure_schema()
    backend = "Supabase/PostgreSQL" if use_postgresql() else "lokalni SQLite"
    print(f"=== GEX snapshot -> {backend} | instruments={args.instruments} ===")

    ok = 0
    failed: list[str] = []
    for code in args.instruments:
        profile = compute_gex_for_instrument(code)
        if not profile:
            failed.append(code)
            print(f"  [{code}] preskocen (nema spot/chain ili nije konfigurisan).")
            continue
        if persist_gex_snapshot(profile, snapshot_date=args.date):
            ok += 1
            print(
                f"  [{code}] net_gex={profile.get('net_gex'):,.0f} "
                f"regime={profile.get('gamma_regime')} flip={profile.get('gamma_flip')} "
                f"contracts={profile.get('n_contracts')}"
            )
        else:
            failed.append(code)
            print(f"  [{code}] upis nije uspeo.")

    summary = {
        "ok": ok > 0,
        "written": ok,
        "instruments": list(args.instruments),
        "failed": failed,
        "backend": backend,
        "snapshot_date": args.date,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"\nUpisano {ok}/{len(args.instruments)} snapshotova.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
