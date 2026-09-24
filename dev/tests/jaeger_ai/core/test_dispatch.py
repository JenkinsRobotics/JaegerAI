"""Single-session dispatch: main stays clean, the worker finishes the batch."""

from __future__ import annotations

import time
from contextlib import contextmanager

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
    assert out["halt_reason"] is None
    assert out["controller_reason"] == "complete_task"
    assert out["steps"] == 5
    assert out["summary"] == "processed 20 items"
    assert "▸ work_ledger" in "".join(str(x) for x in out["tool_activity"])


class _Owner:
    """The Gateway task owner, reduced to what background delegation uses."""

    def __init__(self):
        self.submitted = []

    def submit(self, objective, *, context, key, **_):
        self.submitted.append((objective, context, key))
        return {"task_id": f"task_{len(self.submitted)}", "status": "queued"}


def _scope(owner, depth=0):
    from jaeger_agent.task_port import task_scope

    return task_scope(owner, session_id="s", request_id="r1", user_text="process all 20 notes",
                      execution={"options": {"delegation_depth": depth}})


def test_background_dispatch_admits_durable_child_tasks_and_keeps_the_parent_free():
    """Main session: delegate_task(background=True) hands each objective to the
    Gateway's durable task owner and returns at once with handles. The worker runs
    later under the owner (results return through the completion outbox), not on a
    daemon thread that would die with the process."""
    owner = _Owner()
    with _scope(owner):
        result = main._delegate_background(object(), ["process all 20 items", "  ", "then summarise"])
    assert result["ok"] is True and result["background"] is True and result["dispatched"] == 2
    assert [h["id"] for h in result["handles"]] == ["task_1", "task_2"]
    (first, ctx, key), _second = owner.submitted
    assert first == "process all 20 items"
    assert key == "delegate:r1:process all 20 items"  # idempotent per request + objective
    # The child keeps the parent's admission but is one level deeper, so a worker
    # cannot fan out forever.
    assert ctx["source"] == "client"
    assert ctx["execution"]["options"]["delegation_depth"] == 1


def test_background_dispatch_stops_at_the_recursion_limit_and_without_an_owner():
    owner = _Owner()
    with _scope(owner, depth=main._DELEGATE_MAX_DEPTH):
        limited = main._delegate_background(object(), ["x"])
    assert limited["ok"] is False and "recursion limit" in limited["error"] and owner.submitted == []
    outside = main._delegate_background(object(), ["x"])  # no Gateway task context
    assert outside["ok"] is False and "Gateway execution owner" in outside["error"]
    with _scope(owner):
        assert main._delegate_background(object(), ["   "])["error"] == "no subtasks given"


def test_main_session_can_inspect_worker_ledger_by_id():
    created = ledger_tool(
        action="create", task_name="notes consolidation", total_items=20,
    )
    task_id = created["ledger"]["task_id"]
    probed = ledger_tool(action="status", task_id=task_id)
    assert probed["ledger"]["total_items"] == 20


def test_delegate_failure_surfaces_worktree_result_after_teardown(monkeypatch):
    """A failed child must still tell its parent where preserved work lives."""
    from jaeger_agent import subagent_worktree
    from jaeger_agent.loop import runtime_bridge

    info = {"context_note": "\n[isolated]"}

    @contextmanager
    def _isolated_child(_child_id):
        try:
            yield info
        finally:
            info["result"] = {
                "path": "/tmp/child",
                "branch": "jaeger-subagent/child",
                "commits": 0,
                "dirty": True,
                "pruned": False,
            }

    monkeypatch.setattr(subagent_worktree, "isolated_child", _isolated_child)
    monkeypatch.setattr(main, "_context_budget_for", lambda _cfg: (8192, 1024))
    monkeypatch.setitem(main._pipeline, "system_prompt", "test")
    monkeypatch.setattr(
        runtime_bridge,
        "build_jaeger_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("child failed")),
    )

    result = main._delegate_internal(object(), "do work")

    assert result["delegated"] is False
    assert result["error"] == "RuntimeError: child failed"
    assert result["worktree"] == info["result"]
