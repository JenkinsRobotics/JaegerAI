"""Resolve the authoritative Jaeger sessions SQLite path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jaeger_ai.core.sessions import SessionStore, get_store


def sessions_db_path(layout: Any = None) -> Path | None:
    """Return ``<instance>/memory/sessions.db`` for the bound layout.

    Matches :func:`jaeger_ai.core.sessions.get_store` — that is the single
    durable transcript store Jaeger owns (not Hermes ``state.db``).
    """
    if layout is None:
        from jaeger_ai.main import _pipeline

        layout = _pipeline.get("layout")
    if layout is None:
        return None
    memory_dir = getattr(layout, "memory_dir", None)
    if memory_dir is None:
        return None
    return Path(memory_dir) / "sessions.db"


def open_session_store(layout: Any = None) -> SessionStore | None:
    """Open (or reuse) the instance SessionStore via the core singleton."""
    return get_store(layout)
