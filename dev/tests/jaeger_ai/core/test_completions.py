"""Background work reaches the agent — as a new turn, never mid-turn.

``delegate_task`` used to hold the parent's turn open until every child
finished. Stage 00 widened the fan-out; this makes it optional to wait
at all.

The invariant everything here defends: a completion NEVER lands inside
a turn already in flight. Spliced between an assistant message and its
tool results it breaks role alternation (cloud providers reject the
next call outright) and invalidates the prompt prefix every local lane
depends on for a warm KV cache. So completions queue, and the turn
worker converts them into a fresh user turn once the current one is
done.

Delivery is at-most-once: a queue that redelivered would have the agent
re-reacting to the same finished job every turn for the rest of the
session.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import jaeger_ai.main as main
from jaeger_ai.core.runtime import completions


@pytest.fixture(autouse=True)
def _clean_queue():
    completions.reset()
    yield
    completions.reset()


def _ok(answer="the answer"):
    return {"delegated": True, "answer": answer}


# ── the queue ───────────────────────────────────────────────────────


def test_a_finished_delegation_waits_to_be_collected():
    completions.record_delegation(task="count the notes", result=_ok("41"))
    assert completions.pending_count() == 1

    events = completions.consume_pending()
    assert len(events) == 1
    assert events[0]["kind"] == "delegation"
    assert events[0]["task"] == "count the notes"


def test_delivery_is_at_most_once():
    """A redelivering queue would have the agent re-reacting to the same
    finished job every turn."""
    completions.record_delegation(task="t", result=_ok())
    assert len(completions.consume_pending()) == 1
    assert completions.consume_pending() == []
    assert completions.pending_count() == 0


def test_completions_arrive_oldest_first():
    completions.record_delegation(task="first", result=_ok())
    time.sleep(0.01)
    completions.record_delegation(task="second", result=_ok())
    tasks = [e["task"] for e in completions.consume_pending()]
    assert tasks == ["first", "second"]


def test_nothing_waiting_means_no_turn():
    assert completions.next_completion_turn() is None


# ── the payload is self-contained ───────────────────────────────────


def test_the_original_task_travels_with_the_answer():
    """By delivery time the parent may be several turns into something
    else — a bare result would be unattributable."""
    completions.record_delegation(
        task="summarise the Q3 notes", result=_ok("three actions"),
    )
    prompt = completions.next_completion_turn()
    assert "summarise the Q3 notes" in prompt
    assert "three actions" in prompt


def test_a_failed_delegation_says_so():
    completions.record_delegation(
        task="reach the API",
        result={"delegated": False, "error": "connection refused"},
    )
    prompt = completions.next_completion_turn()
    assert "FAILED" in prompt
    assert "connection refused" in prompt


def test_the_notice_tells_the_agent_to_use_judgement():
    """Stale results are the expected case, not the exception — work
    dispatched several turns ago may have been overtaken."""
    completions.record_delegation(task="t", result=_ok())
    prompt = completions.next_completion_turn()
    assert "overtaken" in prompt
    assert "do not restart" in prompt.lower()
    assert "verbatim" in prompt


def test_a_flood_is_capped_and_the_rest_follow():
    for i in range(9):
        completions.record_delegation(task=f"task {i}", result=_ok())
    prompt = completions.completion_prompt(completions.consume_pending())
    assert prompt.count("- Subagent") == 5
    assert completions.pending_count() == 4
    follow = completions.next_completion_turn()
    assert "task 8" in follow
    assert completions.pending_count() == 0


def test_process_completions_merge_onto_the_same_rail(monkeypatch):
    """Background processes and background subagents are the same kind
    of event to the agent, so they share one rail and one shape."""
    from jaeger_agent.background import processes

    monkeypatch.setattr(
        processes, "consume_pending_completions",
        lambda layout, **kwargs: [{"id": "p1", "name": "render", "status": "exited",
                         "exit_code": 0, "finished_at": time.time()}],
    )
    completions.record_delegation(task="a subagent task", result=_ok())

    prompt = completions.next_completion_turn(SimpleNamespace(root="/tmp"))
    assert "render" in prompt
    assert "a subagent task" in prompt


def test_a_broken_process_queue_never_blocks_a_turn(monkeypatch):
    from jaeger_agent.background import processes

    def _boom(layout, **kwargs):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(processes, "consume_pending_completions", _boom)
    completions.record_delegation(task="t", result=_ok())
    assert "t" in (completions.next_completion_turn(SimpleNamespace(root="/tmp")) or "")


# ── dispatch returns immediately ────────────────────────────────────


def test_background_delegation_requires_execution_owner():
    result = main._delegate_background(object(), ["do work"])
    assert not result["ok"]
    assert "Gateway" in result["error"]


def test_background_dispatch_admits_children_without_local_execution(monkeypatch):
    from jaeger_agent.task_port import task_scope
    admitted = []
    def submit(goal, *, context, key):
        admitted.append((goal, context, key))
        return {"task_id": key, "status": "queued"}
    monkeypatch.setattr(main, "_delegate_internal", lambda *a: pytest.fail("local detached execution"))
    with task_scope(SimpleNamespace(submit=submit), session_id="parent", request_id="request",
                    execution={"workspace":"/tmp/work", "model":"configured"}, user_text="Build"):
        result = main._delegate_background(object(), ["a", "b", "c"])
    assert result["dispatched"] == 3
    assert len({h["id"] for h in result["handles"]}) == 3
    assert all(c["execution"]["model"] == "configured" for _, c, _ in admitted)
    assert all(c["execution"]["options"]["delegation_depth"] == 1 for _, c, _ in admitted)
    assert all(c["session_id"] == "parent" for _, c, _ in admitted)


def test_background_dispatch_respects_the_depth_limit():
    from jaeger_agent.task_port import task_scope
    with task_scope(None, session_id="parent", request_id="request", user_text="Build",
                    execution={"options":{"delegation_depth":main._DELEGATE_MAX_DEPTH}}):
        result = main._delegate_background(object(), ["nested"])
    assert not result["ok"]
    assert "recursion" in result["error"]


def test_background_dispatch_rejects_empty_work():
    assert main._delegate_background(object(), [])["ok"] is False
    assert main._delegate_background(object(), ["  "])["ok"] is False


def test_unacknowledged_batch_survives_reload_and_replays_with_same_id():
    import importlib
    completions.record_delegation(task="durable", result=_ok(), delegation_id="stable-child")
    first = completions.pending_batch()
    ident = completions.batch_id(first)
    importlib.reload(completions)
    assert completions.batch_id(completions.pending_batch()) == ident
    completions.acknowledge(first)
    assert completions.pending_count() == 0
    completions.record_delegation(task="durable", result=_ok(), delegation_id="stable-child")
    assert completions.pending_count() == 0
