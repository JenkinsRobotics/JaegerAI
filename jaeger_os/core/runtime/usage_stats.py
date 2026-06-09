"""Tool + skill usage telemetry (audit gap #4).

JROS keeps a tamper-evident audit *trail* (every op in ``logs/audit.log``)
but no usage *counters* — nothing answers "which tools fail most" or
"which skills are dead weight." This module is the counter layer.

A small JSON sidecar at ``<instance>/logs/usage.json`` holds:

  • per tool  — ``{calls, failures, total_s, last_used}``
  • per skill — ``{views, last_used}``

It is best-effort: a telemetry write must never break a turn, so every
path swallows its own errors. Surfaced through the ``skill`` tool's
``stats`` action and the ``/usage`` slash command.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

# In-memory accumulator, lazily seeded from disk, flushed on each record.
_stats: dict[str, dict[str, Any]] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path() -> Any:
    """The usage.json path for the bound instance, or None."""
    try:
        from jaeger_os.agent.tools._common import get_layout
        layout = get_layout()
        layout.logs_dir.mkdir(parents=True, exist_ok=True)
        return layout.logs_dir / "usage.json"
    except Exception:  # noqa: BLE001
        return None


def _load() -> dict[str, dict[str, Any]]:
    global _stats
    if _stats is not None:
        return _stats
    _stats = {"tools": {}, "skills": {}}
    path = _path()
    if path is not None and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _stats["tools"] = data.get("tools", {}) or {}
                _stats["skills"] = data.get("skills", {}) or {}
        except Exception:  # noqa: BLE001
            pass
    return _stats


def _flush() -> None:
    path = _path()
    if path is None or _stats is None:
        return
    try:
        path.write_text(json.dumps(_stats, indent=2, default=str),
                        encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def record_tool(name: str, *, ok: bool = True, elapsed: float = 0.0) -> None:
    """Count one tool call. ``ok=False`` marks it a failure."""
    if not name:
        return
    try:
        stats = _load()
        row = stats["tools"].setdefault(
            name, {"calls": 0, "failures": 0, "total_s": 0.0, "last_used": ""})
        row["calls"] += 1
        if not ok:
            row["failures"] += 1
        row["total_s"] = round(row["total_s"] + max(0.0, elapsed), 2)
        row["last_used"] = _now()
        _flush()
    except Exception:  # noqa: BLE001
        pass


def record_skill(name: str) -> None:
    """Count one skill view / use."""
    if not name:
        return
    try:
        stats = _load()
        row = stats["skills"].setdefault(name, {"views": 0, "last_used": ""})
        row["views"] += 1
        row["last_used"] = _now()
        _flush()
    except Exception:  # noqa: BLE001
        pass


def snapshot() -> dict[str, dict[str, Any]]:
    """The current counters — ``{"tools": {...}, "skills": {...}}``."""
    stats = _load()
    return {"tools": dict(stats["tools"]), "skills": dict(stats["skills"])}


def top_tools(limit: int = 10) -> list[dict[str, Any]]:
    """Tools by call count, most-used first."""
    rows = [{"name": n, **r} for n, r in _load()["tools"].items()]
    rows.sort(key=lambda r: r.get("calls", 0), reverse=True)
    return rows[:limit]


def top_skills(limit: int = 10) -> list[dict[str, Any]]:
    """Skills by view count, most-used first."""
    rows = [{"name": n, **r} for n, r in _load()["skills"].items()]
    rows.sort(key=lambda r: r.get("views", 0), reverse=True)
    return rows[:limit]


def reset() -> None:
    """Clear all counters (used by tests and a fresh session)."""
    global _stats
    _stats = {"tools": {}, "skills": {}}
    _flush()
