"""DDL for the ``gex_snapshots`` table (SQLite + PostgreSQL)."""
from __future__ import annotations

# SQLite — single script (executescript).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS gex_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    instrument TEXT NOT NULL,
    spot REAL,
    net_gex REAL,
    net_gex_norm REAL,
    gamma_flip REAL,
    spot_vs_flip REAL,
    gamma_regime TEXT,
    call_wall REAL,
    put_wall REAL,
    near_term_gex REAL,
    dte0_share REAL,
    n_contracts INTEGER,
    source TEXT,
    created_at TEXT,
    UNIQUE(snapshot_date, instrument)
);
CREATE INDEX IF NOT EXISTS idx_gex_snapshots_instr_date ON gex_snapshots(instrument, snapshot_date);
"""

# PostgreSQL — statements run one by one (psycopg2 adapter has no executescript).
PG_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS gex_snapshots (
        id BIGSERIAL PRIMARY KEY,
        snapshot_date DATE NOT NULL,
        instrument TEXT NOT NULL,
        spot DOUBLE PRECISION,
        net_gex DOUBLE PRECISION,
        net_gex_norm DOUBLE PRECISION,
        gamma_flip DOUBLE PRECISION,
        spot_vs_flip DOUBLE PRECISION,
        gamma_regime TEXT,
        call_wall DOUBLE PRECISION,
        put_wall DOUBLE PRECISION,
        near_term_gex DOUBLE PRECISION,
        dte0_share DOUBLE PRECISION,
        n_contracts INTEGER,
        source TEXT,
        created_at TIMESTAMPTZ,
        UNIQUE(snapshot_date, instrument)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_gex_snapshots_instr_date ON gex_snapshots(instrument, snapshot_date)",
]
