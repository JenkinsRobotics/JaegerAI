"""In-session task list — the agent's planning scratchpad.

A single ``todo`` tool: pass ``todos`` to write the plan, omit the
argument to read it. The store is per-process (one running instance =
one session), in memory — a *within-session* scratchpad for keeping a
multi-step task on track. It is NOT durable cross-session work; that is
the kanban board's job.

Ported from hermes-agent's ``todo_tool`` — the standard fix for a small
model losing the thread on a long task: a written plan it re-reads each
step, with an explicit "all items done → stop" signal.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function

_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


def _validate(item: dict[str, Any]) -> dict[str, str]:
    """Normalize one todo item to ``{id, content, status}``."""
    tid = str(item.get("id", "")).strip() or "?"
    content = str(item.get("content", "")).strip() or "(no description)"
    status = str(item.get("status", "pending")).strip().lower()
    if status not in _STATUSES:
        status = "pending"
    return {"id": tid, "content": content, "status": status}


def _dedupe_by_id(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate ids, keeping the last occurrence's position."""
    last: dict[str, int] = {}
    for i, item in enumerate(todos):
        last[str(item.get("id", "")).strip() or "?"] = i
    return [todos[i] for i in sorted(last.values())]


class TodoStore:
    """In-memory ordered task list. List position is priority."""

    def __init__(self) -> None:
        self._items: list[dict[str, str]] = []

    def write(self, todos: list[dict[str, Any]],
              merge: bool = False) -> list[dict[str, str]]:
        """Write the list. ``merge=False`` replaces it entirely;
        ``merge=True`` updates existing items by id and appends new ones."""
        clean = _dedupe_by_id(todos or [])
        if not merge:
            self._items = [_validate(t) for t in clean]
            return self.read()
        existing = {it["id"]: it for it in self._items}
        for t in clean:
            tid = str(t.get("id", "")).strip()
            if not tid:
                continue
            if tid in existing:
                if t.get("content"):
                    existing[tid]["content"] = str(t["content"]).strip()
                status = str(t.get("status", "")).strip().lower()
                if status in _STATUSES:
                    existing[tid]["status"] = status
            else:
                v = _validate(t)
                existing[v["id"]] = v
                self._items.append(v)
        seen: set[str] = set()
        rebuilt: list[dict[str, str]] = []
        for it in self._items:
            cur = existing.get(it["id"], it)
            if cur["id"] not in seen:
                rebuilt.append(cur)
                seen.add(cur["id"])
        self._items = rebuilt
        return self.read()

    def read(self) -> list[dict[str, str]]:
        return [it.copy() for it in self._items]

    def clear(self) -> None:
        self._items = []


# One store per process = one per session (the TUI is single-session).
_store = TodoStore()


def reset_todos() -> None:
    """Clear the session task list (session reset / factory reset)."""
    _store.clear()


def todo(todos: list[dict[str, Any]] | None = None,
         merge: bool = False) -> dict[str, Any]:
    """Read (``todos`` omitted) or write the session task list. Always
    returns the full current list plus status counts."""
    items = _store.write(todos, merge) if todos is not None else _store.read()
    counts = {
        s: sum(1 for i in items if i["status"] == s)
        for s in ("pending", "in_progress", "completed", "cancelled")
    }
    return {"ok": True, "todos": items,
            "summary": {"total": len(items), **counts}}


@register_tool_from_function(name="todo")
def _t_todo(todos: list[dict] | None = None, merge: bool = False) -> dict:
    """Session task list — a scratchpad for multi-step jobs (3+
    steps or several things at once). No args = read current
    list. ``todos`` = list of ``{id, content, status}`` items
    (pending / in_progress / completed / cancelled). ``merge=False``
    (default) replaces the list; ``merge=True`` updates by id.

    Keep exactly ONE item in_progress at a time; use the kanban
    board for cross-session work. See ``describe_tool("todo")``
    for the full contract."""
    return todo(todos=todos, merge=merge)
