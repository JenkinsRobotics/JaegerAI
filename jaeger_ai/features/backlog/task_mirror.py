"""Mirror Gateway durable tasks into the Backlog (J-087).

Tasks created through /v1/tasks (chat proposals, workflow runs) used to live only in the Gateway's task
store, so they never showed up in Work > Backlog. Each top-level task gets one backlog row keyed by
import_key "task:<task_id>" whose status follows the task. Internal turn records ("turn:...") are skipped.
"""
from __future__ import annotations

from .store import BacklogError, BacklogStore

_STATUS = {"queued": "in_progress", "running": "in_progress", "paused": "needs_ok", "needs_owner": "needs_ok",
           "completed": "done", "completed_verified": "done", "cancelled": "done", "failed": "open"}


def _status(state: str) -> str:
    return _STATUS.get(str(state or "").lower(), "open")


def mirror_tasks(store: BacklogStore, tasks: list[dict]) -> int:
    """Upserts one backlog row per top-level task; returns rows created or changed."""
    changed = 0
    for t in tasks:
        tid = str(t.get("task_id") or "")
        if not tid.startswith("task_"):
            continue
        goal = " ".join(str(t.get("goal") or "").split())
        title = (goal.splitlines()[0] if goal else tid)[:160] or tid
        status = _status(t.get("state"))
        note = str(t.get("error") or "")[:500] if status == "open" else ""
        try:
            row = store.add(title=title, detail=f"Gateway task {tid}", source="task", status=status,
                            worker="", import_key=f"task:{tid}")
        except BacklogError:
            continue
        if not row.get("existing"):
            changed += 1
            if note:
                store.update(row["id"], last_note=note)
        elif row.get("status") != status:
            store.update(row["id"], status=status, last_note=note)
            changed += 1
    return changed
