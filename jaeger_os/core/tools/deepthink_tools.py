"""Deep Think agent tools.

  • propose_deep_think_task(description) — the agent queues a skill-
    development job for Deep Think to work later. The job is recorded
    ``source=agent, approved=False`` — it won't run until the user
    approves it (``/deepthink approve <id>``).
  • list_deep_think_queue()             — read the current queue.

This is the "agent-proposed" half of Deep Think's task sourcing (the
user-queued half is the ``/deepthink add`` slash command). Locked
design: BOTH sources, agent jobs gated behind approval.
"""

from __future__ import annotations

from typing import Any

from ._common import _require_layout
from jaeger_os.core.background.deep_think import queue_for_layout


def propose_deep_think_task(description: str) -> dict[str, Any]:
    """Queue a skill-development task for Deep Think to work later.

    Use this when, during normal work, you notice something worth
    building or fixing but it's too big for the current turn — "the
    weather skill keeps failing on bad input", "we should have a skill
    for X". The task is added UNAPPROVED: the user must approve it
    (``/deepthink approve <id>``) before Deep Think will run it. You are
    proposing, not committing.

    Returns ``{ok, task_id, description, status}``."""
    desc = (description or "").strip()
    if not desc:
        return {"ok": False, "error": "empty task description"}
    layout = _require_layout()
    queue = queue_for_layout(layout)
    task = queue.add(desc, source="agent", approved=False)
    return {
        "ok": True,
        "task_id": task.id,
        "description": task.description,
        "status": "pending — awaiting user approval",
    }


def list_deep_think_queue() -> dict[str, Any]:
    """Read the Deep Think task queue with status counts. Read-only."""
    layout = _require_layout()
    queue = queue_for_layout(layout)
    tasks = queue.all_tasks()
    return {
        "ok": True,
        "summary": queue.summary(),
        "tasks": [
            {
                "id": t.id,
                "description": t.description,
                "status": t.status,
                "source": t.source,
                "approved": t.approved,
            }
            for t in tasks
        ],
    }
