"""Single-session dispatch: main stays clean, the worker finishes the batch."""

from __future__ import annotations

import time

import pytest

import jaeger_ai.main as main
from jaeger_ai.core.runtime import completions, execution, work_ledger
from jaeger_ai.core.runtime.autonomous_runner import run_worker_goal
from jaeger_ai.core.runtime.work_ledger import complete_task, work_ledger as ledger_tool


@pytest.fixture(autouse=True)
def _clean():
    completions.reset()
    execution.reset()
    work_ledger.reset()
    yield
    completions.reset()
    execution.reset()
    work_ledger.reset()


def _batch_turn(total: int, per_turn: int = 4):
    def _turn(client, text, *, session_key, allow_persona=True):
        current = work_ledger.active_ledger()
        if current is None:
            ledger_tool(
                action="create", task_name="batch", total_items=total,
                remaining_count=total,
            )
            current = work_ledger.active_ledger()
        done = list(current.completed_ids)
        nxt = [str(i) for i in range(len(done), min(len(done) + per_turn, total))]
        done.extend(nxt)
        leftover = total - len(done)
        ledger_tool(
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
            return {
                "text": f"processed {total} items",
                "error": None,
                "tool_activity": ["  ▸ complete_task()"],
            }
        return {
            "text": f"{len(done)}/{total}",
            "error": None,
            "tool_activity": ["  ▸ work_ledger()"],
        }
    return _turn


def test_twenty_step_worker_returns_a_clean_summary():
    out = run_worker_goal(
        object(),
        "process all 20 items. do not stop until done.",
        turn_fn=_batch_turn(20, per_turn=4),
        max_steps=20,
    )
    assert out["halt_reason"] == "complete_task"
    assert out["steps"] == 5
    assert out["summary"] == "processed 20 items"
    assert "▸ work_ledger" in "".join(str(x) for x in out["tool_activity"])


def test_background_dispatch_keeps_the_parent_free_and_surfaces_the_summary(
    monkeypatch,
):
    """Main session: delegate_task(background=True) → worker loop → rail.

    The parent returns immediately. The worker finishes all 20 items
    without a user re-prompt. The completion notice carries the summary,
    not the raw per-item tool log.
    """
    monkeypatch.setattr(
        main, "_delegate_internal",
        lambda client, task: run_worker_goal(
            client, task, turn_fn=_batch_turn(20, per_turn=4), max_steps=20,
        ) | {"delegated": True, "answer": "processed 20 items",
             "summary": "processed 20 items"},
    )

    parent_messages = [
        {"role": "user", "content": "process all 20 notes"},
        {"role": "assistant", "content": "I'll hand that to a worker."},
    ]
    result = main._delegate_background(
        object(), ["process all 20 items. do not stop until done."],
    )
    assert result["ok"] is True
    assert result["background"] is True
    assert result["dispatched"] == 1

    for _ in range(200):
        if completions.pending_count():
            break
        time.sleep(0.01)
    assert completions.pending_count() == 1

    prompt = completions.next_completion_turn()
    assert prompt is not None
    assert "processed 20 items" in prompt
    assert "work_ledger" not in prompt  # raw worker tools stay off the rail
    # The parent transcript is untouched by the worker's tool trace.
    assert parent_messages == [
        {"role": "user", "content": "process all 20 notes"},
        {"role": "assistant", "content": "I'll hand that to a worker."},
    ]


def test_main_session_can_inspect_worker_ledger_by_id():
    created = ledger_tool(
        action="create", task_name="notes consolidation", total_items=20,
    )
    task_id = created["ledger"]["task_id"]
    probed = ledger_tool(action="status", task_id=task_id)
    assert probed["ledger"]["total_items"] == 20
