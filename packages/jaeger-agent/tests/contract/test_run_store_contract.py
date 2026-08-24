"""Shared RunStore contract — runs, checkpoints, waiting, recovery.

Runs against the in-memory reference and the SQLite adapter both. A new
backend passes this file or it is not a RunStore.
"""

from __future__ import annotations

import pytest

from jaeger_agent.cognition.runs import RunError, RunStore


COMMITMENT = "c-durable-runtime"


def test_adapter_satisfies_the_protocol(run_store):
    assert isinstance(run_store, RunStore)


def test_create_starts_in_created(run_store):
    run = run_store.create(COMMITMENT)
    assert run.state == "created"
    assert run.attempt == 1
    assert run_store.get(run.id).id == run.id


def test_attempts_number_upwards_per_commitment(run_store):
    first = run_store.create(COMMITMENT)
    second = run_store.create(COMMITMENT)
    other = run_store.create("c-unrelated")
    assert (first.attempt, second.attempt) == (1, 2)
    assert other.attempt == 1


def test_illegal_transition_does_not_mutate(run_store):
    run = run_store.create(COMMITMENT)
    with pytest.raises(RunError, match="cannot move"):
        run_store.transition(run.id, "completed")
    assert run_store.get(run.id).state == "created"


def test_unknown_state_is_rejected(run_store):
    run = run_store.create(COMMITMENT)
    with pytest.raises(RunError, match="unknown state"):
        run_store.transition(run.id, "vibing")


def test_missing_run_is_an_error(run_store):
    with pytest.raises(RunError, match="no run"):
        run_store.transition("nope", "active")


def test_completed_is_terminal(run_store):
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    run_store.transition(run.id, "completed")
    with pytest.raises(RunError):
        run_store.transition(run.id, "active")


# ── checkpoints ────────────────────────────────────────────────────


def test_checkpoints_are_append_only_and_ordered(run_store):
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    first = run_store.checkpoint(run.id, {"item": 1})
    second = run_store.checkpoint(run.id, {"item": 2})
    assert (first.seq, second.seq) == (1, 2)
    assert run_store.latest_checkpoint(run.id).cursor == {"item": 2}


def test_no_checkpoint_is_none_not_an_error(run_store):
    run = run_store.create(COMMITMENT)
    assert run_store.latest_checkpoint(run.id) is None


def test_checkpoint_sequences_are_per_run(run_store):
    a = run_store.create(COMMITMENT)
    b = run_store.create(COMMITMENT)
    run_store.checkpoint(a.id, {"n": "a1"})
    assert run_store.checkpoint(b.id, {"n": "b1"}).seq == 1


def test_checkpoint_cursor_is_copied_not_aliased(run_store):
    """A caller mutating its dict afterwards must not rewrite history."""
    run = run_store.create(COMMITMENT)
    cursor = {"processed": 10}
    run_store.checkpoint(run.id, cursor)
    cursor["processed"] = 999
    assert run_store.latest_checkpoint(run.id).cursor == {"processed": 10}


# ── waiting and waking ─────────────────────────────────────────────


def test_waiting_for_event_requires_a_wake_key(run_store):
    """A run nothing can wake is a leak, not a state."""
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    with pytest.raises(RunError, match="requires a wake_key"):
        run_store.transition(run.id, "waiting_for_event")
    assert run_store.get(run.id).state == "active"


def test_deliver_event_wakes_only_matching_runs(run_store):
    waiting = run_store.create(COMMITMENT)
    other = run_store.create(COMMITMENT)
    for run in (waiting, other):
        run_store.transition(run.id, "active")
    run_store.transition(waiting.id, "waiting_for_event", wake_key="pr:merged")
    run_store.transition(other.id, "waiting_for_event", wake_key="mail:arrived")

    woken = run_store.deliver_event("pr:merged")

    assert [r.id for r in woken] == [waiting.id]
    assert run_store.get(waiting.id).state == "active"
    assert run_store.get(other.id).state == "waiting_for_event"


def test_delivering_an_event_twice_wakes_nothing_the_second_time(run_store):
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    run_store.transition(run.id, "waiting_for_event", wake_key="pr:merged")
    assert len(run_store.deliver_event("pr:merged")) == 1
    assert run_store.deliver_event("pr:merged") == []


def test_woken_run_clears_its_wake_key(run_store):
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    run_store.transition(run.id, "waiting_for_event", wake_key="pr:merged")
    run_store.deliver_event("pr:merged")
    assert run_store.get(run.id).wake_key is None


def test_unknown_event_is_a_no_op(run_store):
    assert run_store.deliver_event("nothing:waits-on-this") == []


# ── resume ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        ["active", "paused"],
        ["active", "blocked"],
        ["active", "waiting_for_user"],
        ["active", "failed"],
    ],
)
def test_resume_from_every_resumable_state(run_store, path):
    run = run_store.create(COMMITMENT)
    for state in path:
        run_store.transition(run.id, state)
    resumed, _ = run_store.resume(run.id)
    assert resumed.state == "active"


def test_resume_returns_the_latest_checkpoint(run_store):
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    run_store.checkpoint(run.id, {"processed": 1})
    run_store.checkpoint(run.id, {"processed": 47})
    run_store.transition(run.id, "paused")

    resumed, checkpoint = run_store.resume(run.id)

    assert resumed.state == "active"
    assert checkpoint.cursor == {"processed": 47}


def test_cannot_resume_a_running_run(run_store):
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    with pytest.raises(RunError, match="cannot resume"):
        run_store.resume(run.id)


def test_cannot_resume_a_completed_run(run_store):
    run = run_store.create(COMMITMENT)
    run_store.transition(run.id, "active")
    run_store.transition(run.id, "completed")
    with pytest.raises(RunError, match="cannot resume"):
        run_store.resume(run.id)


# ── crash recovery ─────────────────────────────────────────────────


def test_recover_blocks_runs_whose_owner_died(run_store):
    run = run_store.create(COMMITMENT, owner_pid=4242)
    run_store.transition(run.id, "active")
    run_store.heartbeat(run.id, owner_pid=4242)

    recovered = run_store.recover(is_alive=lambda pid: False)

    assert [r.id for r in recovered] == [run.id]
    stored = run_store.get(run.id)
    assert stored.state == "blocked"
    assert stored.reason == "owner_lost"


def test_recover_leaves_live_owners_alone(run_store):
    run = run_store.create(COMMITMENT, owner_pid=4242)
    run_store.transition(run.id, "active")
    run_store.heartbeat(run.id, owner_pid=4242)

    assert run_store.recover(is_alive=lambda pid: True) == []
    assert run_store.get(run.id).state == "active"


def test_recover_ignores_runs_that_are_not_active(run_store):
    """A paused run has no owner to lose."""
    run = run_store.create(COMMITMENT, owner_pid=4242)
    run_store.transition(run.id, "active")
    run_store.transition(run.id, "paused")

    assert run_store.recover(is_alive=lambda pid: False) == []
    assert run_store.get(run.id).state == "paused"


def test_recover_is_idempotent(run_store):
    run = run_store.create(COMMITMENT, owner_pid=4242)
    run_store.transition(run.id, "active")
    assert len(run_store.recover(is_alive=lambda pid: False)) == 1
    assert run_store.recover(is_alive=lambda pid: False) == []


def test_recovered_run_is_resumable_with_its_checkpoint(run_store):
    """The whole point: a crash costs the process, not the progress."""
    run = run_store.create(COMMITMENT, owner_pid=4242)
    run_store.transition(run.id, "active")
    run_store.checkpoint(run.id, {"processed": 120})
    run_store.recover(is_alive=lambda pid: False)

    resumed, checkpoint = run_store.resume(run.id, owner_pid=99)

    assert resumed.state == "active"
    assert resumed.owner_pid == 99
    assert checkpoint.cursor == {"processed": 120}


def test_leaving_active_releases_the_process_claim(run_store):
    """A stopped run holding a pid would look alive to the next recover."""
    run = run_store.create(COMMITMENT, owner_pid=4242)
    run_store.transition(run.id, "active")
    run_store.transition(run.id, "paused")
    assert run_store.get(run.id).owner_pid is None
