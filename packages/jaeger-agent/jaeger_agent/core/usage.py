"""Core usage counters — the module's own, with a seam for the host's.

Which tools and skills actually get used is the AGENT's telemetry. It was
being recorded by importing ``jaeger_ai.core.runtime.usage_stats`` from
four places inside the loop and the skill registry, which put the mind's
own counters in the application and left an embedder that is not JaegerAI
with no usage data at all.

Inverted here. The module keeps counters in memory by default, so
``skill(action="stats")`` works in any host. An application that wants
them PERSISTED registers its own sink:

    from jaeger_agent.core import usage
    from jaeger_ai.core.runtime import usage_stats
    usage.set_sink(usage_stats)          # writes <instance>/logs/usage.json

A sink is any object with the functions it wants to provide —
``record_tool``, ``record_skill``, ``snapshot``, ``top_tools``,
``top_skills``. Missing ones fall back to the in-memory default, so a
host can override just persistence without reimplementing the readers.

Every call here is best-effort: telemetry must never break a turn. A sink
that raises is ignored, and the in-memory counters still get the event.
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_tools: dict[str, dict[str, Any]] = {}
_skills: dict[str, dict[str, Any]] = {}

#: Host-registered sink, or ``None`` for in-memory only.
_sink: Any = None


def set_sink(sink: Any) -> None:
    """Register the host's usage backend. ``None`` restores in-memory."""
    global _sink
    _sink = sink


def _forward(fn_name: str, *args: Any, **kwargs: Any) -> Any:
    """Call ``fn_name`` on the sink if it has one. Never raises."""
    fn = getattr(_sink, fn_name, None) if _sink is not None else None
    if fn is None:
        return None
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 — telemetry never breaks a turn
        return None


def record_tool(name: str, *, ok: bool = True, elapsed: float = 0.0) -> None:
    """Count one tool call. ``ok=False`` marks it a failure."""
    if not name:
        return
    with _lock:
        row = _tools.setdefault(name, {"calls": 0, "failures": 0, "seconds": 0.0})
        row["calls"] += 1
        if not ok:
            row["failures"] += 1
        row["seconds"] = round(row["seconds"] + float(elapsed or 0.0), 3)
    _forward("record_tool", name, ok=ok, elapsed=elapsed)


def record_skill(name: str) -> None:
    """Count one skill view / use."""
    if not name:
        return
    with _lock:
        row = _skills.setdefault(name, {"views": 0})
        row["views"] += 1
    _forward("record_skill", name)


def snapshot() -> dict[str, dict[str, Any]]:
    """Current counters — ``{"tools": {...}, "skills": {...}}``.

    The sink wins when it has one: a persisted history spanning restarts
    is strictly better than this process's slice of it.
    """
    from_sink = _forward("snapshot")
    if from_sink:
        return from_sink
    with _lock:
        return {
            "tools": {k: dict(v) for k, v in _tools.items()},
            "skills": {k: dict(v) for k, v in _skills.items()},
        }


def top_tools(limit: int = 10) -> list[dict[str, Any]]:
    """Tools by call count, most-used first."""
    from_sink = _forward("top_tools", limit)
    if from_sink:
        return from_sink
    rows = [{"name": n, **r} for n, r in snapshot()["tools"].items()]
    rows.sort(key=lambda r: r.get("calls", 0), reverse=True)
    return rows[:limit]


def top_skills(limit: int = 10) -> list[dict[str, Any]]:
    """Skills by view count, most-used first."""
    from_sink = _forward("top_skills", limit)
    if from_sink:
        return from_sink
    rows = [{"name": n, **r} for n, r in snapshot()["skills"].items()]
    rows.sort(key=lambda r: r.get("views", 0), reverse=True)
    return rows[:limit]


def reset() -> None:
    """Clear the in-memory counters. Does not touch the sink."""
    with _lock:
        _tools.clear()
        _skills.clear()


__all__ = [
    "record_skill",
    "record_tool",
    "reset",
    "set_sink",
    "snapshot",
    "top_skills",
    "top_tools",
]
