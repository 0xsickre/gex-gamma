"""In-process / Streamlit memoization."""
from __future__ import annotations

import functools
import os
import threading
import time
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

F = TypeVar("F", bound=Callable[..., Any])


@runtime_checkable
class Cache(Protocol):
    def memoize(self, *, ttl: int | None = None, show_spinner: bool = False) -> Callable[[F], F]:
        ...


class InProcessCache:
    def memoize(self, *, ttl: int | None = None, show_spinner: bool = False) -> Callable[[F], F]:
        del show_spinner

        def decorator(fn: F) -> F:
            store: dict[Any, tuple[float, Any]] = {}
            lock = threading.Lock()

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    key = (args, tuple(sorted(kwargs.items())))
                    hash(key)
                except TypeError:
                    return fn(*args, **kwargs)
                now = time.monotonic()
                with lock:
                    hit = store.get(key)
                    if hit is not None:
                        ts, value = hit
                        if ttl is None or (now - ts) <= ttl:
                            return value
                result = fn(*args, **kwargs)
                with lock:
                    store[key] = (time.monotonic(), result)
                return result

            def clear() -> None:
                with lock:
                    store.clear()

            wrapper.clear = clear  # type: ignore[attr-defined]
            return wrapper  # type: ignore[return-value]

        return decorator


class StreamlitCache:
    def memoize(self, *, ttl: int | None = None, show_spinner: bool = False) -> Callable[[F], F]:
        import streamlit as st

        return st.cache_data(ttl=ttl, show_spinner=show_spinner)


_active: Cache | None = None
_lock = threading.Lock()


def _streamlit_runtime_active() -> bool:
    return bool(os.environ.get("STREAMLIT_RUNTIME_ENV"))


def get_cache() -> Cache:
    global _active
    if _active is None:
        with _lock:
            if _active is None:
                choice = (os.environ.get("GEX_GAMMA_CACHE_BACKEND") or "auto").strip().lower()
                if choice == "streamlit":
                    _active = StreamlitCache()
                elif choice == "inprocess":
                    _active = InProcessCache()
                elif _streamlit_runtime_active():
                    _active = StreamlitCache()
                else:
                    _active = InProcessCache()
    return _active


def memoize(*, ttl: int | None = None, show_spinner: bool = False) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        state: dict[str, Any] = {}

        def _resolve() -> Callable[..., Any]:
            if "fn" not in state:
                state["fn"] = get_cache().memoize(ttl=ttl, show_spinner=show_spinner)(fn)
            return state["fn"]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return _resolve()(*args, **kwargs)

        def clear() -> None:
            inner = state.get("fn")
            clear_fn = getattr(inner, "clear", None)
            if callable(clear_fn):
                clear_fn()
            state.clear()

        wrapper.clear = clear  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
