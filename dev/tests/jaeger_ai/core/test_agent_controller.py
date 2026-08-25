"""OpenHands-style state machine: the controller, not the model's prose,
decides when a job is done."""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime import execution, work_ledger
from jaeger_ai.core.runtime.agent_controller import AgentState, JaegerAgentController
from jaeger_ai.core.runtime.work_ledger import complete_task, work_ledger as ledger_tool


@pytest.fixture(autouse=True)
def _clean():
    execution.reset()
    work_ledger.reset()
    yield
    execution.reset()
    work_ledger.reset()


def _batch_turn(total: int, per_turn: int = 10):
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
            action="update", completed_ids=done, remaining_count=leftover,
            in_progress_ids=[],
        )
        if leftover == 0:
            complete_task(
                task_id=current.task_id,
                summary=f"processed {total} items",
                evidence=f"ids 0-{total - 1}",
            )
            return {"text": "all done", "error": None,
                    "tool_activity": ["  ▸ complete_task()"]}
        return {"text": f"{len(done)}/{total} done, more remaining.",
                "error": None, "tool_activity": ["  ▸ work_ledger()"]}
    return _turn


def test_run_to_completion_reaches_completed_on_complete_task():
    ctrl = JaegerAgentController(
        object(), max_steps=20, turn_fn=_batch_turn(50, 10),
        isolated=True, batch=True,
    )
    packed = ctrl.run_to_completion(
        "process all 50 items. do not stop until done.", "delegate",
    )
    assert packed["status"] == AgentState.COMPLETED
    assert packed["state"] is AgentState.COMPLETED
    assert packed["steps"] == 5
    assert packed["output"]["halt_reason"] == "complete_task"
    assert packed["output"]["summary"] == "processed 50 items"


def test_prose_complete_does_not_exit_an_open_batch():
    """The donor-loop lesson: 'all done' without complete_task is not a
    terminal action while the ledger still has remaining items."""
    calls = {"n": 0}

    def _turn(client, text, *, session_key, allow_persona=True):
        calls["n"] += 1
        if calls["n"] == 1:
            ledger_tool(action="create", task_name="x", total_items=4,
                        remaining_count=4)
            return {"text": "All items processed. Here is the final summary.",
                    "error": None, "tool_activity": []}
        leftover = 4 - calls["n"]
        done = [str(i) for i in range(calls["n"])]
        ledger_tool(action="update", completed_ids=done,
                    remaining_count=max(0, leftover), in_progress_ids=[])
        if leftover <= 0:
            complete_task(evidence="four files written", summary="four done")
            return {"text": "done", "error": None,
                    "tool_activity": ["  ▸ complete_task()"]}
        return {"text": "continuing", "error": None, "tool_activity": []}

    packed = JaegerAgentController(
        object(), max_steps=10, turn_fn=_turn, isolated=True, batch=True,
    ).run_to_completion("process all 4 items", "delegate")
    assert calls["n"] > 1
    assert packed["status"] == AgentState.COMPLETED
    assert packed["output"]["halt_reason"] == "complete_task"


def test_a_question_is_awaiting_approval_not_completed():
    def _turn(client, text, *, session_key, allow_persona=True):
        return {"text": "Which folder should I start with?",
                "error": None, "tool_activity": []}

    packed = JaegerAgentController(
        object(), max_steps=8, turn_fn=_turn, isolated=True, batch=True,
    ).run_to_completion("process all 20 items", "delegate")
    assert packed["status"] == AgentState.AWAITING_APPROVAL
    assert packed["reason"] == "question"
    assert packed["steps"] == 1


def test_a_tool_error_is_failed():
    def _turn(client, text, *, session_key, allow_persona=True):
        return {"text": "", "error": "boom", "tool_activity": []}

    packed = JaegerAgentController(
        object(), max_steps=8, turn_fn=_turn, isolated=True, batch=True,
    ).run_to_completion("process all 20 items", "delegate")
    assert packed["status"] == AgentState.FAILED
    assert packed["reason"] == "error"


def test_short_chat_completes_in_one_step_without_a_ledger():
    def _turn(client, text, *, session_key, allow_persona=True):
        return {"text": "Paris.", "error": None, "tool_activity": []}

    packed = JaegerAgentController(
        object(), max_steps=8, turn_fn=_turn, isolated=True, batch=False,
    ).run_to_completion("capital of France?", "delegate")
    assert packed["status"] == AgentState.COMPLETED
    assert packed["reason"] == "settled"
    assert packed["steps"] == 1


def test_controller_compacts_between_batch_steps(monkeypatch):
    calls = {"n": 0}

    def _compact(agent, **kwargs):
        calls["n"] += 1
        return False

    monkeypatch.setattr(
        "jaeger_ai.core.runtime.agent_controller.compact_agent", _compact,
    )
    packed = JaegerAgentController(
        object(), max_steps=20, turn_fn=_batch_turn(20, 10),
        isolated=True, batch=True, agent=object(),
    ).run_to_completion(
        "process all 20 items. do not stop until done.", "delegate",
    )
    assert packed["status"] == AgentState.COMPLETED
    assert packed["steps"] == 2
    assert calls["n"] >= 1


def test_on_progress_includes_ledger_counts():
    ticks = []

    def _on_progress(info):
        ticks.append(info)

    packed = JaegerAgentController(
        object(), max_steps=20, turn_fn=_batch_turn(20, 10),
        isolated=True, batch=True, on_progress=_on_progress,
    ).run_to_completion("process all 20 items. do not stop until done.", "delegate")
    assert packed["status"] == AgentState.COMPLETED
    assert ticks
    last = ticks[-1]
    assert last["ledger"]["done_count"] == 20
    assert last["ledger"]["total"] == 20
    assert last["ledger"]["completed"] is True


def test_inner_cap_halt_continues_instead_of_settling():
    """Hitting the inner tool fuse is the next step, not a finished job.
    A wind-down summary that looks settled must not stop the controller."""
    calls = {"n": 0}

    def _turn(client, text, *, session_key, allow_persona=True):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "text": "Here is a summary of the first batch.",
                "error": None, "tool_activity": [],
                "halt_reason": "hit max_iterations=24 without a final answer",
            }
        return {"text": "Paris.", "error": None, "tool_activity": []}

    packed = JaegerAgentController(
        object(), max_steps=8, turn_fn=_turn, isolated=True, batch=False,
    ).run_to_completion("capital of France?", "delegate")
    assert calls["n"] == 2
    assert packed["status"] == AgentState.COMPLETED


def test_loop_breaker_halt_does_not_continue():
    """Identical/timeout backstop is terminal — unlike max_iterations."""
    calls = {"n": 0}

    def _turn(client, text, *, session_key, allow_persona=True):
        calls["n"] += 1
        return {
            "text": "Let me try a different AppleScript.",
            "error": None, "tool_activity": [],
            "halt_reason": "hit the same execute_code failure 2 times",
        }

    packed = JaegerAgentController(
        object(), max_steps=8, turn_fn=_turn, isolated=True, batch=False,
    ).run_to_completion("organize my mail", "delegate")
    assert calls["n"] == 1
    assert packed["status"] == AgentState.FAILED


def test_controller_does_not_flip_main_execution_mode():
    assert execution.current_mode() == "interactive"
    JaegerAgentController(
        object(), max_steps=3,
        turn_fn=lambda *a, **k: {"text": "ok", "error": None, "tool_activity": []},
        isolated=True,
    ).run_to_completion("hello", "delegate")
    assert execution.current_mode() == "interactive"
    assert execution.run_active() is False
