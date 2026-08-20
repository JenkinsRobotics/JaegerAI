"""OpenClaw-style standing heartbeat — wake even when the board is empty.

``task_liveness.heartbeat`` answers "is this in-progress worker still
alive?" This module answers a different question: "the user has not
typed, the board may be empty, should the agent still look around?"

Standing instructions live in ``<instance>/memory/HEARTBEAT.md``. The
operator edits that file. A beat that finds nothing to do replies
exactly ``HEARTBEAT_OK``, which surfaces drop rather than turning into
a chat bubble.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

HEARTBEAT_OK = "HEARTBEAT_OK"
_CHECKLIST_NAME = "HEARTBEAT.md"
_STATE_NAME = "heartbeat_state.json"

DEFAULT_CHECKLIST = """\
# Standing heartbeat checklist

On every heartbeat, in this order:

1. Look at the kanban board (`board_view`). If a ready or in_progress
   card can be worked now, leave it — the idle worker will pick it up.
   If something important is missing from the board, add one card.
2. Check blocked cards. If you can unblock one without the user, do
   that; otherwise leave it.
3. If nothing needs doing, reply with exactly HEARTBEAT_OK and nothing
   else.

Do not invent work. Quality over volume — at most one card per beat.
"""

_SILENT = frozenset({
    "HEARTBEAT_OK",
    "HEARTBEAT OK",
    "[SILENT]",
    "SILENT",
})


def _memory_dir(layout: Any) -> Path | None:
    mem = getattr(layout, "memory_dir", None)
    if mem is not None:
        return Path(mem)
    root = getattr(layout, "root", None)
    if root is None:
        return None
    return Path(str(root)) / "memory"


def checklist_path(layout: Any) -> Path | None:
    mem = _memory_dir(layout)
    return None if mem is None else mem / _CHECKLIST_NAME


def state_path(layout: Any) -> Path | None:
    mem = _memory_dir(layout)
    return None if mem is None else mem / _STATE_NAME


def seed_checklist(layout: Any) -> Path | None:
    """Write the default checklist if none exists. Never overwrites."""
    path = checklist_path(layout)
    if path is None:
        return None
    if path.is_file():
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CHECKLIST, encoding="utf-8")
    except Exception:  # noqa: BLE001 — a missing checklist degrades, never crashes
        return None
    return path


def load_checklist(layout: Any) -> str:
    """Operator-authored standing instructions, or the default seed."""
    path = seed_checklist(layout)
    if path is None or not path.is_file():
        return DEFAULT_CHECKLIST.strip()
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return DEFAULT_CHECKLIST.strip()
    return text or DEFAULT_CHECKLIST.strip()


def is_silent_ok(text: str) -> bool:
    """True when the beat found nothing worth saying to the user."""
    cleaned = (text or "").strip().strip("`").strip()
    if not cleaned:
        return True
    return cleaned.upper() in _SILENT


def _load_state(layout: Any) -> dict[str, Any]:
    path = state_path(layout)
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(layout: Any, state: dict[str, Any]) -> bool:
    path = state_path(layout)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        return False
    return True


def last_beat_at(layout: Any) -> float:
    try:
        return float(_load_state(layout).get("last_beat_at") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def mark_beat(layout: Any, *, now: float | None = None, silent: bool = False) -> None:
    state = _load_state(layout)
    state["last_beat_at"] = float(time.time() if now is None else now)
    state["last_silent"] = bool(silent)
    _save_state(layout, state)


def is_due(
    layout: Any,
    *,
    interval_minutes: int,
    enabled: bool = True,
    now: float | None = None,
) -> bool:
    """True when a standing beat should fire.

    Interval 0, or ``enabled=False``, never fires. The first beat waits
    a full interval after boot (or after the last recorded beat) rather
    than firing the moment the process starts.
    """
    if not enabled or interval_minutes <= 0:
        return False
    stamp = last_beat_at(layout)
    if stamp <= 0:
        # No beat on record — treat "now" as the start of the wait so a
        # freshly booted process is not immediately chatty.
        mark_beat(layout, now=now, silent=True)
        return False
    current = time.time() if now is None else now
    return (current - stamp) >= (interval_minutes * 60)


def status(
    layout: Any,
    *,
    interval_minutes: int = 30,
    enabled: bool = True,
) -> dict[str, Any]:
    """Projection for the bridge ``heartbeat`` query."""
    last = last_beat_at(layout)
    path = checklist_path(layout)
    interval_s = max(0, int(interval_minutes)) * 60
    next_at = (last + interval_s) if last > 0 and interval_s > 0 and enabled else 0.0
    return {
        "enabled": bool(enabled),
        "interval_minutes": int(interval_minutes),
        "last_at": last or None,
        "next_at": next_at or None,
        "checklist_present": bool(path is not None and path.is_file()),
        "silent_ok": HEARTBEAT_OK,
    }


_HEARTBEAT_PREAMBLE = (
    "(Heartbeat) This is a standing check, not a live user. Read the "
    "checklist. Do real tool work only if something needs it. If "
    "nothing needs doing, reply with exactly HEARTBEAT_OK and nothing "
    "else — that reply is dropped, not shown as a chat bubble. At most "
    "one board card per beat. Do not invent work."
)


def heartbeat_prompt(checklist: str, *, board_digest: str = "") -> str:
    """The user-role message for one standing heartbeat turn."""
    body = (checklist or "").strip()
    digest = (board_digest or "").strip()
    parts = [_HEARTBEAT_PREAMBLE]
    if body:
        parts.append("CHECKLIST:\n" + body)
    if digest:
        parts.append(digest)
    return "\n\n".join(parts)


def build_prompt(layout: Any) -> str:
    """The synthetic user-role message for one standing beat."""
    from jaeger_agent.background.board import board_digest

    digest = ""
    try:
        digest = board_digest(layout) or ""
    except Exception:  # noqa: BLE001
        digest = ""
    return heartbeat_prompt(load_checklist(layout), board_digest=digest)


__all__ = [
    "DEFAULT_CHECKLIST",
    "HEARTBEAT_OK",
    "build_prompt",
    "heartbeat_prompt",
    "checklist_path",
    "is_due",
    "is_silent_ok",
    "last_beat_at",
    "load_checklist",
    "mark_beat",
    "seed_checklist",
    "status",
]
