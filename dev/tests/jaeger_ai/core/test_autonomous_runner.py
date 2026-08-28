"""Autonomous worker loop — keep going until complete_task, not prose."""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime import execution, work_ledger
from jaeger_ai.core.runtime.autonomous_runner import (
    ACCEPTANCE_GUIDANCE,
    HARNESS_PREFIX,
    ensure_autonomous_ledger,
    looks_like_batch,
    next_continuation_prompt,
    run_worker_goal,
    should_run_autonomous,
)
from jaeger_ai.core.runtime.work_ledger import (
    complete_task,
    work_ledger as ledger_tool,
)


@pytest.fixture(autouse=True)
def _clean():
    execution.reset()
    work_ledger.reset()
    yield
    execution.reset()
    work_ledger.reset()


def test_batch_phrasing_is_detected():
    positives = [
        "process all 50 items and do not stop until done",
        "consolidate every 20 notes",
        "process these 300 notes",
        "do not stop until done",
        "keep going until every file is finished",
        "batch-process the export",
        "/goal finish the notes",
        "go through all 14 folders",
        "sync my Safari and Chrome bookmarks with no duplicates",
        "audit and restructure the bookmarks into folders",
    ]
    for text in positives:
        assert looks_like_batch(text), text
    assert should_run_autonomous("process these 300 notes")


def test_batch_phrasing_rejects_casual_chat():
    """A false positive costs a 100-step loop. Extend this list before
    widening the regex."""
    negatives = [
        "what's the capital of France?",
        "I have 20 items in my backpack",
        "the 2020 notes from that trip",
        "remind me in 20 minutes",
        "keep going, I like this conversation",
        "wait until dinner is ready",
        "process all the logs in that folder quickly",
        "batch of cookies recipe",
        "every 20 seconds ping the host",
        "finish this sentence for me",
        "handle the exception in main.py",
        "go through the options with me",
        "audit this function",
        "sync the clock",
    ]
    for text in negatives:
        assert not looks_like_batch(text), text


def test_durable_request_opens_counted_ledger_automatically():
    ledger = ensure_autonomous_ledger("process these 436 records")
    assert ledger is not None
    assert ledger.total() == 436
    assert ledger.remaining() == 436


def test_uncounted_durable_request_uses_acceptance_phases():
    ledger = ensure_autonomous_ledger(
        "sync my Safari and Chrome bookmarks with no duplicates"
    )
    assert ledger is not None
    assert ledger.remaining_ids == ["inspect", "execute", "verify"]
    assert ledger.remaining() == 3
    assert "prose claim" in ACCEPTANCE_GUIDANCE


def test_inner_cap_forces_continuation_on_settled_prose():
    """Wind-down summaries look finished. The fuse is not a job end."""
    nxt = next_continuation_prompt(
        "Here is a summary of the first batch.",
        isolated=True,
        halt_reason="hit max_iterations=24 without a final answer",
        steps_left=5,
        objective="process notes",
    )
    assert nxt is not None
    assert next_continuation_prompt(
        "Here is a summary of the first batch.",
        isolated=True,
        steps_left=5,
    ) is None


@pytest.mark.parametrize("halt", [
    "made 24 tool calls in a single turn",
    "empty_response",
])
def test_recoverable_halt_forces_outer_continuation(halt):
    nxt = next_continuation_prompt(
        "Here is the progress so far.", isolated=True,
        halt_reason=halt, steps_left=5, objective="finish the audit",
    )
    assert nxt is not None
    assert "finish the audit" in nxt


def test_short_worker_task_exits_after_one_settled_turn():
    calls: list[str] = []

    def _turn(client, text, *, session_key, allow_persona=True):
        calls.append(text)
        return {
            "text": "The capital of France is Paris.",
            "error": None, "tool_activity": [],
        }

    out = run_worker_goal(
        object(), "what's the capital of France?", turn_fn=_turn, max_steps=10,
    )
    assert len(calls) == 1
    assert out["halt_reason"] == "settled"
    assert out["steps"] == 1


def test_worker_loops_fifty_items_without_a_reprompt():
    """The original batch acceptance case: 50 items, no user in the loop."""
    total = 50
    batch = 10

    def _turn(client, text, *, session_key, allow_persona=True):
        current = work_ledger.active_ledger()
        if current is None:
            ledger_tool(
                action="create", task_name="fifty", total_items=total,
                remaining_count=total,
            )
            current = work_ledger.active_ledger()
        done = list(current.completed_ids)
        nxt = [str(i) for i in range(len(done), min(len(done) + batch, total))]
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
                evidence="ids 0-49 on disk",
            )
            return {
                "text": "all done",
                "error": None,
                "tool_activity": ["  ▸ complete_task(evidence='ids 0-49')"],
            }
        return {
            "text": f"processed {len(done)}/{total}",
            "error": None,
            "tool_activity": ["  ▸ work_ledger(action='update')"],
        }

    out = run_worker_goal(
        object(),
        "process all 50 items. do not stop until done.",
        turn_fn=_turn,
        max_steps=20,
    )
    assert out["halt_reason"] == "complete_task"
    assert out["steps"] == 5  # 10 items per turn × 5
    assert out["summary"] == "processed 50 items"
    assert out["text"] == "processed 50 items"
    assert work_ledger.active_ledger().completed is True


def test_isolated_worker_does_not_flip_main_execution_mode():
    assert execution.current_mode() == "interactive"

    def _turn(client, text, *, session_key, allow_persona=True):
        return {"text": "ok", "error": None, "tool_activity": []}

    run_worker_goal(object(), "hello", turn_fn=_turn, max_steps=3)
    assert execution.current_mode() == "interactive"
    assert execution.run_active() is False


def test_question_stops_the_worker():
    def _turn(client, text, *, session_key, allow_persona=True):
        return {
            "text": "Which folder should I start with?",
            "error": None, "tool_activity": [],
        }

    out = run_worker_goal(
        object(), "process all 20 items", turn_fn=_turn, max_steps=10,
    )
    assert out["halt_reason"] == "settled" or out["steps"] == 1
    assert out["steps"] == 1


def test_harness_prompt_carries_progress():
    ledger_tool(action="create", task_name="x", total_items=8)
    ledger_tool(action="update", completed_ids=["1", "2"], remaining_count=6)
    from jaeger_ai.core.runtime.autonomous_runner import harness_prompt
    prompt = harness_prompt()
    assert HARNESS_PREFIX in prompt
    assert "2/8" in prompt
