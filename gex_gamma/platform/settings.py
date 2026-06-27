"""Runtime settings — SQLite path + snapshot path resolution."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_DB_FILENAME = os.environ.get("GEX_GAMMA_DB_FILENAME", "gex_gamma.db")
_DB_PATH_RESOLVED: Optional[str] = None


def get_sqlite_db_path() -> str:
    global _DB_PATH_RESOLVED
    if _DB_PATH_RESOLVED is not None:
        return _DB_PATH_RESOLVED

    env_full = os.environ.get("GEX_GAMMA_DB_PATH", "").strip()
    if env_full:
        _DB_PATH_RESOLVED = os.path.abspath(env_full)
        return _DB_PATH_RESOLVED

    data_dir = os.environ.get("GEX_GAMMA_DATA_DIR", "").strip()
    if data_dir:
        _DB_PATH_RESOLVED = os.path.join(os.path.abspath(data_dir), _DB_FILENAME)
        return _DB_PATH_RESOLVED

    root = Path(__file__).resolve().parents[2]
    _DB_PATH_RESOLVED = str(root / _DB_FILENAME)
    return _DB_PATH_RESOLVED


def get_snapshot_dir() -> str:
    data_dir = os.environ.get("GEX_GAMMA_DATA_DIR", "").strip()
    if data_dir:
        return os.path.join(os.path.abspath(data_dir), "snapshots")
    return "/var/lib/gex-gamma/snapshots"


def default_snapshot_path() -> str:
    custom = os.environ.get("GEX_SNAPSHOT_PATH", "").strip()
    if custom:
        return os.path.abspath(custom)
    return os.path.join(get_snapshot_dir(), "latest.json")


def reset_sqlite_db_path_cache() -> None:
    global _DB_PATH_RESOLVED
    _DB_PATH_RESOLVED = None
