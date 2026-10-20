"""Per-agent status for the Agents View, computed from what already exists.

Supervisor decision D2: there is no ``agent_status`` table. An agent's status
is derived from its durable tasks (``agent_id``/``eta``/``runner`` on
``/v1/tasks``), its newest handoff and its direct-chat sessions.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Iterable

PREVIEW_CHARS = 140

#: Handoff and task states mapped onto the board's status vocabulary.
_HANDOFF_STATUS = {
    "pending_approval": "waiting_approval",
    "admitted": "queued", "approved": "queued", "running": "working",
    "failed": "error", "execution_unknown": "error", "rejected": "error",
}
_TASK_STATUS = {
    "queued": "queued", "running": "working",
    "needs_owner": "waiting_approval", "paused": "waiting_approval",
    "blocked": "blocked", "failed": "error",
}
#: Most urgent first; the summary reports the most urgent live signal.
_PRIORITY = ("waiting_approval", "blocked", "error", "working", "queued")


def _preview(text: Any) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[: PREVIEW_CHARS - 1] + "…"


def agent_status(handoff: dict[str, Any] | None, active_tasks: Iterable[dict[str, Any]], active_requests: Iterable[dict[str, Any]] = ()) -> str:
    signals = {_TASK_STATUS.get(str(t.get("state") or "")) for t in active_tasks}
    signals.update({
        "admitted": "queued", "queued": "queued", "running": "working",
        "awaiting_approval": "waiting_approval", "cancelling": "blocked",
    }.get(str(r.get("status") or "")) for r in active_requests)
    if handoff is not None:
        signals.add(_HANDOFF_STATUS.get(str(handoff.get("status") or "")))
    for status in _PRIORITY:
        if status in signals:
            return status
    return "idle"


def summarize_agents(
    agents: list[dict[str, Any]],
    *,
    tasks: list[dict[str, Any]],
    handoffs: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    last_message: Callable[[str], str] | None = None,
    seen: dict[str, dict[str, Any]] | None = None,
    requests: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = []
    for agent in agents:
        aid = agent["id"]
        own_handoffs = [h for h in handoffs if h.get("to_agent_id") == aid]
        handoff = max(own_handoffs, key=lambda h: h.get("updated_at") or 0, default=None)
        own_tasks = [t for t in tasks if (t.get("agent_id") or t.get("owning_agent")) == aid]
        active = [t for t in own_tasks if t.get("state") in _TASK_STATUS]
        task = max(active or own_tasks, key=lambda t: t.get("updated_at") or 0, default=None)
        chats = [s for s in sessions if s.get("agent_id") == aid]
        own_sessions = {s["session_id"] for s in chats}
        live_requests = [r for r in (requests or []) if r.get("session_id") in own_sessions]
        chat = max(chats, key=lambda s: s.get("updated_at") or 0, default=None)

        candidates: list[tuple[float, str, str | None]] = []
        if handoff is not None:
            candidates.append((float(handoff.get("updated_at") or 0),
                               (handoff.get("result") or {}).get("summary") or handoff.get("task") or "",
                               "handoff"))
        if task is not None:
            candidates.append((float(task.get("updated_at") or 0), task.get("goal") or "", "task"))
        if chat is not None:
            text = chat.get("last_message_preview")
            if text is None and last_message is not None:
                text = last_message(chat["session_id"])
            candidates.append((float(chat.get("updated_at") or 0), text or chat.get("title") or "", "chat"))
        latest = max(candidates, key=lambda c: c[0], default=None)
        rows.append({
            "id": aid,
            "display_name": agent.get("display_name"),
            "role": agent.get("role"),
            "status": agent_status(handoff, active, live_requests),
            "last_activity_at": latest[0] if latest else None,
            "last_preview": _preview(latest[1]) if latest else "",
            "last_source": latest[2] if latest else None,
            "last_handoff_id": handoff.get("id") if handoff else None,
            "session_id": chat.get("session_id") if chat else None,
            "seen_at": (seen or {}).get(aid, {}).get("seen_at"),
            "unseen": bool((seen or {}).get(aid, {}).get("unread") or (latest and latest[0] > float((seen or {}).get(aid, {}).get("seen_at") or 0))),
            "task": ({key: task.get(key) for key in ("task_id", "goal", "state", "eta", "runner", "updated_at")}
                     if task else None),
        })
    lead = [r for r in rows if r["role"] == "lead"]
    rest = sorted((r for r in rows if r["role"] != "lead"),
                  key=lambda r: r["last_activity_at"] or 0, reverse=True)
    return {"agents": lead + rest, "generated_at": time.time()}


__all__ = ["PREVIEW_CHARS", "agent_status", "summarize_agents"]
