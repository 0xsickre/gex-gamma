"""Build and publish the gex_signal (entry point: ``gex-signal``)."""
from __future__ import annotations

import argparse
import json
import os
import sys

from gex_gamma.domain.gex_engine import persist_gex_snapshot
from gex_gamma.services.build_gex_signal import build_gex_signal, public_gex_signal


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build gex_signal from the live Massive option chain")
    p.add_argument("--instruments", nargs="+", default=None, help="index short codes (default: all)")
    p.add_argument("--persist", action="store_true", help="Upsert gex_snapshots per instrument")
    p.add_argument("--out", metavar="FILE", help="Write JSON snapshot")
    args = p.parse_args(argv)

    try:
        row = build_gex_signal(args.instruments)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1

    public = public_gex_signal(row)
    out_doc = {**public, "instruments_full": row.get("instruments")}
    print(json.dumps(public, indent=2, default=str))

    instruments = row.get("instruments") or {}
    if not instruments:
        print("No instruments computed (missing MASSIVE_API_KEY / spot / chain).", file=sys.stderr)
        return 1

    if args.persist:
        n = 0
        for profile in instruments.values():
            if persist_gex_snapshot(profile, snapshot_date=public.get("as_of")):
                n += 1
        print(f"Persisted {n}/{len(instruments)} gex_snapshots as_of={public['as_of']}")

    out_path = args.out
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out_doc, f, indent=2, default=str)
        print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
