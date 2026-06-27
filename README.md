# gex-gamma

Standalone dealer **Gamma Exposure (GEX)** domain for SPX / NDX. Measures dealer
gamma from the Massive (Polygon-compatible) option chain, recomputes Greeks from
first principles (free tier ships no Greeks), persists `gex_snapshots`, and
publishes a snapshot JSON contract for downstream consumers.

Measurement-first: this repo only *publishes* the signal. The score overlay stays
in `cot-report` (`GEX_OVERLAY_ENABLED`), which reads the snapshot JSON.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# requires a Massive API key for the live option chain
set MASSIVE_API_KEY=...        # PowerShell: $env:MASSIVE_API_KEY="..."
gex-refresh                    # snapshot all GEX_TICKERS -> gex_snapshots
gex-signal --out snapshots/latest.json --persist
```

## Environment

| Variable | Purpose |
|----------|---------|
| `MASSIVE_API_KEY` | Required for the live option chain |
| `MASSIVE_API_BASE` | Massive REST base (default `https://api.massive.com`) |
| `MASSIVE_RATE_PER_MIN` | Token-bucket rate (default `4.0`, hard ceiling 5/min) |
| `GEX_RISK_FREE_RATE` | Risk-free rate for BS gamma/IV (default `0.04`) |
| `GEX_GAMMA_DATA_DIR` | Data root (default: repo root) |
| `GEX_GAMMA_DB_PATH` | SQLite file path |
| `GEX_SNAPSHOT_PATH` | Override `latest.json` path |
| `DATABASE_URL` | Supabase Postgres (pooler `:6543`) — switches backend to PG |

## CLI

| Command | Purpose |
|---------|---------|
| `gex-refresh [--instruments SPX NDX] [--date YYYY-MM-DD]` | Nightly EOD snapshot per index |
| `gex-signal [--persist] [--out FILE]` | Build signal doc, optionally persist + write `latest.json` |
| `gex-backfill --days N` | Forward-only coverage report + today's snapshot |

> **Backfill is forward-only:** the Massive free tier exposes a *live* chain (current
> OI) but no historical option open interest — the panel grows one trading day at a time.

## Dashboard

```bash
streamlit run app.py    # http://127.0.0.1:8504
```

## VPS

```bash
bash scripts/vps-setup.sh
systemctl enable --now gex-refresh.timer
systemctl enable --now gex-deploy.timer
systemctl enable --now gex-streamlit
```

Refresh timer: Mon–Fri 23:30 UTC.

## Published contract (`gex_signal`)

```json
{
  "as_of": "...", "computed_at": "...",
  "instruments": {
    "SPX": {"gamma_regime", "net_gex_norm", "spot_vs_flip", "gamma_flip", "call_wall", "put_wall"},
    "NDX": {"..."}
  }
}
```

Full per-instrument profile is in the snapshot JSON under `instruments`.
