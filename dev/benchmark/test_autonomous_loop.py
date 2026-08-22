#!/usr/bin/env python3
"""Batch-loop + single-session dispatch acceptance (no live model).

Exercises the worker GoalRunner the same way a 20- or 50-item
``delegate_task(background=True)`` job does: the main session hands off,
the worker loops until ``complete_task``, and the parent transcript
never sees the per-item tool trace.

    python dev/benchmark/test_autonomous_loop.py
    python -m pytest dev/benchmark/test_autonomous_loop.py dev/tests/jaeger_ai/core/test_dispatch.py
"""

from __future__ import annotations

from jaeger_ai.core.runtime.autonomous_runner import run_worker_goal
from jaeger_ai.core.runtime.work_ledger import (
    active_ledger,
    complete_task,
    reset,
    work_ledger,
)


def _batch_turn(total: int, per_turn: int):
    def _turn(client, text, *, session_key, allow_persona=True):
        current = active_ledger()
        if current is None:
            work_ledger(
                action="create", task_name="batch", total_items=total,
                remaining_count=total,
            )
            current = active_ledger()
        done = list(current.completed_ids)
        nxt = [str(i) for i in range(len(done), min(len(done) + per_turn, total))]
        done.extend(nxt)
        leftover = total - len(done)
        work_ledger(
            action="update",
            completed_ids=done,
            remaining_count=leftover,
            in_progress_ids=[],
        )
        if leftover == 0:
            complete_task(
                task_id=current.task_id,
                summary=f"processed {total} items",
                evidence=f"ids 0-{total - 1}",
            )
            return {"text": "done", "error": None,
                    "tool_activity": ["  ▸ complete_task()"]}
        return {"text": f"{len(done)}/{total}", "error": None,
                "tool_activity": ["  ▸ work_ledger()"]}
    return _turn


def test_fifty_item_worker_loop():
    reset()
    out = run_worker_goal(
        object(),
        "process all 50 items. do not stop until done.",
        turn_fn=_batch_turn(50, 10),
        max_steps=20,
    )
    assert out["halt_reason"] == "complete_task"
    assert out["steps"] == 5
    assert out["summary"] == "processed 50 items"
    reset()


def test_twenty_item_dispatch_summary():
    reset()
    out = run_worker_goal(
        object(),
        "process all 20 items. do not stop until done.",
        turn_fn=_batch_turn(20, 4),
        max_steps=20,
    )
    assert out["halt_reason"] == "complete_task"
    assert out["steps"] == 5
    assert "20" in out["summary"]
    reset()


if __name__ == "__main__":
    test_fifty_item_worker_loop()
    test_twenty_item_dispatch_summary()
    print("ok: 50-item loop and 20-item dispatch both completed via complete_task")
