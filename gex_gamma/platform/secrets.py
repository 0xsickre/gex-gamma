"""Secret resolution — env first, optional Streamlit secrets when in a script run."""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    v = (os.environ.get(key) or os.environ.get(key.upper()) or "").strip()
    if v:
        return v
    return default


def streamlit_secrets_mapping() -> Optional[Mapping[str, Any]]:
    """Return ``st.secrets`` only inside an active Streamlit script run, else ``None``.

    Outside ``streamlit run`` (pytest, CI, plain ``python``) touching
    ``st.secrets`` would load ``.streamlit/secrets.toml`` from disk and can force
    Postgres — breaking local tests. The runtime guard prevents that.
    """
    try:
        from streamlit.runtime import exists as _runtime_exists

        if not _runtime_exists():
            return None
        import streamlit as st  # type: ignore

        return getattr(st, "secrets", None)
    except Exception:
        return None
