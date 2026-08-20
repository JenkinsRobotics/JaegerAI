"""A wedged background task becomes visible instead of invisible.

Deep Think marked a card ``in_progress`` and ran it in-process with no
claim, no heartbeat, and no ceiling. Every failure mode below therefore
looked identical to healthy work: the daemon killed mid-task, a tool
blocked on a socket, a model call that never returned. The card stayed
``in_progress`` forever and the queue behind it never moved.

Three primitives fix it — a claim, a heartbeat, a ceiling — and the
judgement order matters: a dead process is a fact, a silent one is an
inference, an over-budget one is a policy call.
"""

from __future__ import annotations

import os
import platform
import time
import types

import pytest

from jaeger_ai.core.runtime import task_liveness as live


@pytest.fixture
def layout(tmp_path):
    return types.SimpleNamespace(root=tmp_path)


def _foreign(record):
    """Same record, attributed to another machine."""
    return {**record, "host": "some-other-host"}


# ── claiming ────────────────────────────────────────────────────────


def test_a_claim_records_who_and_when(layout):
    record = live.claim(layout, "dt_1", detail="build the thing")
    assert record["pid"] == os.getpid()
    assert record["host"] == platform.node()
    assert record["detail"] == "build the thing"
    assert live.active_claims(layout)[0]["task_id"] == "dt_1"


def test_a_fresh_claim_is_healthy(layout):
    assert live.stale_reason(live.claim(layout, "dt_1")) is None


def test_release_drops_it(layout):
    live.claim(layout, "dt_1")
    assert live.release(layout, "dt_1") is True
    assert live.active_claims(layout) == []
    assert live.release(layout, "dt_1") is False


def test_claims_survive_a_restart(layout):
    """The point of a sidecar rather than memory: reclaim after a crash
    is the case this exists for."""
    live.claim(layout, "dt_1")
    fresh = types.SimpleNamespace(root=layout.root)
    assert [c["task_id"] for c in live.active_claims(fresh)] == ["dt_1"]


def test_a_corrupt_store_does_not_stop_work(layout):
    path = layout.root / "memory" / "task_claims.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert live.active_claims(layout) == []
    assert live.claim(layout, "dt_1")["task_id"] == "dt_1"


# ── judging staleness ───────────────────────────────────────────────


def test_a_dead_worker_is_stale(layout):
    """The most certain signal, so it is checked first."""
    record = live.claim(layout, "dt_1")
    record["pid"] = 999_999_999  # never a live PID
    reason = live.stale_reason(record)
    assert reason is not None and "is gone" in reason


def test_a_silent_worker_is_stale(layout):
    record = live.claim(layout, "dt_1")
    record["heartbeat_at"] = time.time() - (live.HEARTBEAT_GRACE_S + 60)
    reason = live.stale_reason(_foreign(record))
    assert reason is not None and "no heartbeat" in reason


def test_an_over_budget_worker_is_stale_even_while_healthy(layout):
    """A task that has gone wrong in a way it cannot self-detect will
    not stop on its own — the ceiling is what stops it."""
    record = live.claim(layout, "dt_1", max_runtime_s=10)
    now = time.time() + 60
    record["heartbeat_at"] = now  # chatty and alive
    reason = live.stale_reason(record, now=now)
    assert reason is not None and "runtime ceiling" in reason


def test_a_live_chatty_worker_inside_budget_is_left_alone(layout):
    record = live.claim(layout, "dt_1", max_runtime_s=3600)
    assert live.is_stale(record) is False


def test_a_foreign_pid_is_judged_by_heartbeat_not_liveness(layout):
    """A PID from another machine says nothing about a local process —
    worse, it may collide with an unrelated one."""
    record = live.claim(layout, "dt_1")
    record["pid"] = 999_999_999
    assert live.stale_reason(_foreign(record)) is None


# ── reclaiming ──────────────────────────────────────────────────────


def test_reclaim_releases_the_dead_and_keeps_the_living(layout):
    live.claim(layout, "healthy")
    live.claim(layout, "dead")
    claims = live._load(layout)
    claims["dead"]["pid"] = 999_999_999
    live._save(layout, claims)

    reclaimed = live.reclaim_stale(layout)

    assert [e["task_id"] for e in reclaimed] == ["dead"]
    assert [c["task_id"] for c in live.active_claims(layout)] == ["healthy"]


def test_reclaim_reports_a_reason_a_person_can_read(layout):
    live.claim(layout, "dt_1")
    claims = live._load(layout)
    claims["dt_1"]["pid"] = 999_999_999
    live._save(layout, claims)

    line = live.describe_reclaim(live.reclaim_stale(layout)[0])
    assert "dt_1" in line and "reclaimed" in line and "gone" in line


def test_reclaim_on_an_empty_store_is_a_no_op(layout):
    assert live.reclaim_stale(layout) == []


def test_the_in_process_worker_is_never_signalled(layout):
    """Deep Think's worker IS the daemon — signalling it to reclaim one
    task would take the whole queue down."""
    record = live.claim(layout, "dt_1", max_runtime_s=1)
    time.sleep(0.01)
    action = live.terminate_worker(record)
    assert "in-process" in action


def test_a_worker_on_another_host_is_left_alone(layout):
    record = _foreign(live.claim(layout, "dt_1"))
    assert "not this host" in live.terminate_worker(record)


def test_an_over_budget_claim_is_reclaimed_without_killing_ourselves(layout):
    live.claim(layout, "dt_1", max_runtime_s=0.01)
    time.sleep(0.05)
    reclaimed = live.reclaim_stale(layout)
    assert len(reclaimed) == 1
    assert "in-process" in reclaimed[0]["action"]
    assert live.active_claims(layout) == []


# ── heartbeats ──────────────────────────────────────────────────────


def test_a_heartbeat_refreshes_the_claim(layout):
    live.claim(layout, "dt_1")
    claims = live._load(layout)
    claims["dt_1"]["heartbeat_at"] = time.time() - 300
    live._save(layout, claims)

    assert live.heartbeat(layout, "dt_1") is True
    assert time.time() - live._load(layout)["dt_1"]["heartbeat_at"] < 5


def test_a_heartbeat_on_a_reclaimed_task_reports_failure(layout):
    """The signal a worker needs to stop: something else already took
    this task, so continuing would duplicate the work."""
    assert live.heartbeat(layout, "never_claimed") is False


def test_beating_keeps_a_long_task_alive(layout):
    """A Deep Think step is one long blocking call with no place to
    check in from — without the thread, the grace window would have to
    exceed the slowest imaginable task."""
    live.claim(layout, "dt_1")
    claims = live._load(layout)
    claims["dt_1"]["heartbeat_at"] = time.time() - 300
    live._save(layout, claims)

    with live.beating(layout, "dt_1", interval_s=0.05):
        time.sleep(0.25)

    assert time.time() - live._load(layout)["dt_1"]["heartbeat_at"] < 5


def test_beating_stops_when_the_block_ends(layout):
    live.claim(layout, "dt_1")
    with live.beating(layout, "dt_1", interval_s=0.05):
        pass
    resting = live._load(layout)["dt_1"]["heartbeat_at"]
    time.sleep(0.2)
    assert live._load(layout)["dt_1"]["heartbeat_at"] == resting


def test_beating_survives_an_unwritable_store(layout):
    """A store that will not write costs a heartbeat, never the task."""
    live.claim(layout, "dt_1")
    with live.beating(types.SimpleNamespace(root=None), "dt_1", interval_s=0.05):
        time.sleep(0.15)
