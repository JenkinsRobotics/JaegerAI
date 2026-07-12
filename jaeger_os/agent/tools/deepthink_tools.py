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

from jaeger_os.core.context import _require_layout
from jaeger_os.agent.background.deep_think import queue_for_layout
from jaeger_os.core.tools.tool_registry import register_tool_from_function


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


@register_tool_from_function(name="propose_deep_think_task")
def _t_propose_deep_think_task(description: str) -> dict:
    """Hand a build/fix job to the DEEP THINK model — the ONLY way to
    queue work for it. Call this the moment the user says "note it so the
    deep think model can fix it later", "that's too big to fix now", or
    you spot a skill/feature worth building that's too big for this turn
    (e.g. "the weather skill keeps crashing on bad input"). This is NOT
    the kanban board: adding a board card does NOT queue Deep Think — call
    THIS to actually hand off the work (you can ALSO board it to track it).
    The task lands UNAPPROVED; the user approves before Deep Think runs
    it. You propose; the user decides."""
    return propose_deep_think_task(description=description)


@register_tool_from_function(name="list_deep_think_queue", side_effect="read")
def _t_list_deep_think_queue() -> dict:
    """Read the Deep Think task queue with status counts. Read-only."""
    return list_deep_think_queue()
