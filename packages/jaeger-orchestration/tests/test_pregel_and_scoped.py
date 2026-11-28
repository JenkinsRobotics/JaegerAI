"""Tests for Slice 7 PregelGraph (Send/interrupt/Command), RunAuthorization, AttemptFencedQueue, ScopedVariables."""

from __future__ import annotations

import pytest

from jaeger_orchestration import (
    AttemptFencedQueue,
    Command,
    PregelGraph,
    RunAuthorization,
    ScopedVariables,
    Send,
    StaleAttemptError,
    VarScope,
    bind_authorization,
    current_authorization,
    interrupt,
)


def test_pregel_map_reduce_send_and_interrupt_resume() -> None:
    def split_node(state: dict) -> dict:
        return {"chunks": state.get("items", [])}

    def route_chunks(state: dict):
        return [Send("worker", {"chunk": item}) for item in state["chunks"]]

    def worker_node(payload: dict) -> dict:
        return {"results": [payload["chunk"] * 2]}

    def gate_node(state: dict) -> dict:
        approval = interrupt({"question": "Approve results?", "results": state["results"]})
        return {"approved": approval}

    g = PregelGraph(reducers={"results": lambda old, new: list(old) + list(new)})
    g.add_node("split", split_node)
    g.add_node("worker", worker_node)
    g.add_node("gate", gate_node)
    g.set_entry("split")
    g.add_conditional_edges("split", route_chunks)
    g.add_edge("worker", "gate")

    # Note: after 3 worker fan-outs, gate interrupts on first arrival
    paused = g.invoke({"items": [1, 2, 3], "results": []}, run_id="run-pregel-1")
    assert paused.status == "interrupted"
    assert paused.interrupted_node == "gate"
    assert sorted(paused.state["results"]) == [2, 4, 6]

    resumed = g.invoke(Command(resume="YES"), run_id="run-pregel-1")
    assert resumed.status == "completed"
    assert resumed.state["approved"] == "YES"


def test_run_authorization_contextvar_and_attempt_fenced_queue() -> None:
    assert current_authorization() is None
    auth = RunAuthorization(actor="owner:matt", run_id="r-9", scopes=frozenset({"mail.read"}))
    with bind_authorization(auth):
        assert current_authorization() == auth
        assert current_authorization().has_scope("mail.read")
        assert not current_authorization().has_scope("mail.delete")
    assert current_authorization() is None

    q = AttemptFencedQueue()
    job = q.enqueue({"task": "reindex"})
    claimed1 = q.claim()
    assert claimed1 is not None and claimed1[1] == 1
    # Simulate timeout/re-claim by a fresh worker (attempt 2)
    claimed2 = q.claim(job.job_id)
    assert claimed2 is not None and claimed2[1] == 2
    # Zombie worker from attempt 1 must be fenced out!
    with pytest.raises(StaleAttemptError):
        q.complete(job.job_id, attempt=1, result={"stale": True})
    done = q.complete(job.job_id, attempt=2, result={"fresh": True})
    assert done.status == "completed" and done.result == {"fresh": True}


def test_scoped_variables_local_copied_shared_semantics() -> None:
    parent = ScopedVariables()
    parent.set("secret_local", "only-parent", scope=VarScope.LOCAL)
    parent.set("config", {"mode": "strict"}, scope=VarScope.COPIED)
    parent.set("shared_log", ["init"], scope=VarScope.SHARED)

    child = parent.fork_for_child()
    assert child.get("secret_local") is None
    assert child.get("config") == {"mode": "strict"}
    # Mutating copied dict in child must NOT mutate parent
    child.get("config")["mode"] = "relaxed"
    assert parent.get("config")["mode"] == "strict"
    # Mutating shared list in child MUST be visible to parent
    child.get("shared_log").append("child-step")
    assert parent.get("shared_log") == ["init", "child-step"]
