"""Dual backend: PostgreSQL (Supabase) when ``DATABASE_URL`` is set, else SQLite file.

Set in environment or Streamlit Secrets (first match wins):
  DATABASE_URL, SUPABASE_DB_URL, SUPABASE_POSTGRES_URL
  st.secrets["supabase"] -> db_url / database_url / postgres_url
  st.secrets["connections"]["postgresql"] -> url (string or dict)

Use the **Transaction** pooler URI from Supabase (port **6543**, host
``*.pooler.supabase.com``) for serverless hosts. Decoupled copy of the cot-report
backend — only the ``gex_snapshots`` table is in scope here.
"""
from __future__ import annotations

import os
import re
import socket
import sqlite3
from contextlib import contextmanager
from typing import Any, List, Optional, Sequence, Tuple, Union
from urllib.parse import urlparse

from gex_gamma.platform.secrets import streamlit_secrets_mapping

_USE_PG: Optional[bool] = None
_DSN: Optional[str] = None
_SA_ENGINE = None
_SA_ENGINE_DSN: Optional[str] = None

# Tables with BIGSERIAL id — get auto ``RETURNING id`` for lastrowid compat.
_PG_SERIAL_ID_TABLES = frozenset({"gex_snapshots"})


def reset_db_backend_cache() -> None:
    global _USE_PG, _DSN, _SA_ENGINE, _SA_ENGINE_DSN
    _USE_PG = None
    _DSN = None
    _SA_ENGINE = None
    _SA_ENGINE_DSN = None


def _strip_secret(val: object) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    return s


def _read_dsn() -> str:
    global _DSN
    if _DSN is not None:
        return _DSN
    dsn = ""
    for env_key in ("DATABASE_URL", "SUPABASE_DB_URL", "SUPABASE_POSTGRES_URL"):
        dsn = _strip_secret(os.environ.get(env_key, ""))
        if dsn:
            break
    if not dsn:
        try:
            sec = streamlit_secrets_mapping()
            if sec is not None:
                for k in ("DATABASE_URL", "SUPABASE_DB_URL", "SUPABASE_POSTGRES_URL"):
                    if k in sec:
                        dsn = _strip_secret(sec[k])
                        if dsn:
                            break
                if not dsn:
                    sb = sec.get("supabase")
                    if isinstance(sb, dict):
                        for k in ("db_url", "database_url", "postgres_url"):
                            if k in sb:
                                dsn = _strip_secret(sb.get(k))
                                if dsn:
                                    break
                if not dsn:
                    conn_sec = sec.get("connections") or {}
                    pg = conn_sec.get("postgresql") or {}
                    if isinstance(pg, dict):
                        u = pg.get("url")
                        if u:
                            dsn = _strip_secret(u)
                    elif isinstance(pg, str):
                        dsn = _strip_secret(pg)
        except Exception:
            pass
    _DSN = dsn
    return dsn


def _dsn_for_libpq(dsn: str) -> str:
    """Normalize URI for psycopg2 / SQLAlchemy against Supabase."""
    if not dsn:
        return dsn
    out = re.sub(r"^postgresql\+[^:/]+://", "postgresql://", dsn.strip(), flags=re.IGNORECASE)
    low = out.lower()
    if "supabase.com" in low or "supabase.co" in low:
        if "sslmode=" not in low:
            out = f"{out}{'&' if '?' in out else '?'}sslmode=require"
    if "hostaddr=" not in low:
        try:
            parsed = urlparse(out)
            host = (parsed.hostname or "").lower()
            port = parsed.port or 5432
            if host.startswith("db.") and host.endswith(".supabase.co") and port == 5432:
                infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                if infos:
                    ipv4 = infos[0][4][0]
                    out = f"{out}{'&' if '?' in out else '?'}hostaddr={ipv4}"
        except OSError:
            pass
    return out


def use_postgresql() -> bool:
    global _USE_PG
    if _USE_PG is not None:
        return _USE_PG
    dsn = _read_dsn()
    _USE_PG = bool(dsn and dsn.lower().startswith("postgres"))
    return _USE_PG


def _qmarks_to_percent_s(sql: str) -> str:
    """SQLite ? placeholders -> PostgreSQL %s (no % in our SQL except LIKE)."""
    return re.sub(r"\?(?=(?:[^']*'[^']*')*[^']*$)", "%s", sql)


def _insert_target_table(sql: str) -> Optional[str]:
    m = re.search(r"INSERT\s+INTO\s+[\"']?(\w+)", sql.strip(), re.IGNORECASE)
    return m.group(1).lower() if m else None


class _PgCursor:
    def __init__(self, raw):
        self._raw = raw
        self._insert_id: Optional[int] = None

    def execute(self, sql: str, params: Union[Sequence[Any], Tuple, None] = None) -> "_PgCursor":
        self._insert_id = None
        q = _qmarks_to_percent_s(sql)
        p = list(params) if params is not None else None
        sql_up = sql.strip().upper()
        tbl = _insert_target_table(sql)
        if (
            sql_up.startswith("INSERT")
            and "RETURNING" not in sql_up
            and "ON CONFLICT" not in sql_up
            and tbl in _PG_SERIAL_ID_TABLES
        ):
            q_ins = q.rstrip().rstrip(";") + " RETURNING id"
            self._raw.execute(q_ins, p)
            row = self._raw.fetchone()
            self._insert_id = int(row[0]) if row and row[0] is not None else None
        else:
            self._raw.execute(q, p)
        return self

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        q = _qmarks_to_percent_s(sql)
        self._raw.executemany(q, seq_of_params)

    def fetchone(self) -> Optional[Tuple]:
        return self._raw.fetchone()

    def fetchall(self) -> List[Tuple]:
        return self._raw.fetchall()

    @property
    def rowcount(self) -> int:
        return self._raw.rowcount or 0

    @property
    def lastrowid(self) -> Optional[int]:
        return self._insert_id


class _PgConnectionAdapter:
    def __init__(self, raw_conn):
        self._raw = raw_conn

    def cursor(self) -> _PgCursor:
        return _PgCursor(self._raw.cursor())

    def execute(self, sql: str, params: Union[Sequence[Any], Tuple, None] = None) -> _PgCursor:
        c = self.cursor()
        c.execute(sql, params)
        return c

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        c = self.cursor()
        c.executemany(sql, seq_of_params)


@contextmanager
def get_connection():
    """Yields a DB-API-like connection: .cursor(), .execute(), .commit() for both backends."""
    if use_postgresql():
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED

        dsn = _dsn_for_libpq(_read_dsn())
        conn = psycopg2.connect(dsn)
        conn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
        try:
            yield _PgConnectionAdapter(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        from gex_gamma.platform.settings import get_sqlite_db_path

        path = get_sqlite_db_path()
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            yield conn  # native sqlite3 — ? placeholders, cursor.lastrowid
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def ensure_schema() -> None:
    """Create the ``gex_snapshots`` table (idempotent) on the active backend."""
    from gex_gamma.data.schema import PG_SCHEMA_STATEMENTS, SCHEMA_SQL

    with get_connection() as conn:
        if use_postgresql():
            for stmt in PG_SCHEMA_STATEMENTS:
                conn.execute(stmt)
        else:
            conn.executescript(SCHEMA_SQL)
        conn.commit()


def sqlalchemy_engine():
    """For pandas read_sql when using PostgreSQL (singleton per DSN)."""
    global _SA_ENGINE, _SA_ENGINE_DSN
    if not use_postgresql():
        return None
    dsn = _dsn_for_libpq(_read_dsn())
    if _SA_ENGINE is not None and _SA_ENGINE_DSN == dsn:
        return _SA_ENGINE
    from sqlalchemy import create_engine

    _SA_ENGINE = create_engine(dsn, pool_pre_ping=True)
    _SA_ENGINE_DSN = dsn
    return _SA_ENGINE


def read_sql_pandas(sql: str, params: Optional[Sequence[Any]] = None):
    """pandas DataFrame from SQL (works for both backends)."""
    import pandas as pd

    if use_postgresql():
        eng = sqlalchemy_engine()
        q = _qmarks_to_percent_s(sql) if "?" in sql else sql
        p = tuple(params) if params is not None else None
        if p is None:
            from sqlalchemy import text

            with eng.connect() as conn:
                return pd.read_sql_query(text(q), conn)
        conn = eng.raw_connection()
        try:
            return pd.read_sql_query(q, conn, params=p)
        finally:
            conn.close()

    from gex_gamma.platform.settings import get_sqlite_db_path

    with sqlite3.connect(get_sqlite_db_path()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def ping_database() -> Tuple[bool, str]:
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, "ok"
    except Exception as e:
        return False, str(e)
