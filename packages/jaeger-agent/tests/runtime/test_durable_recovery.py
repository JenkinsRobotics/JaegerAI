"""Durability against a real process death, not a simulated one.

The rest of the suite fakes liveness with a lambda. This module kills an
actual interpreter with SIGKILL — no atexit, no flush, no cleanup — and
then asks a fresh process to pick the work up. That is the scenario the
whole runtime layer exists for, and it is the one a mocked test cannot
honestly claim to cover.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.runs import pid_is_alive
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store


def _bind(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))


def test_run_and_checkpoint_survive_a_rebind(tmp_path):
    _bind(tmp_path)
    try:
        commitment = SqliteCommitmentStore().create("migrate the archive")
        runs = SqliteRunStore()
        run = runs.create(commitment.id, provider="claude")
        runs.transition(run.id, "active")
        runs.checkpoint(run.id, {"processed": 300, "cursor": "batch-7"})
        runs.transition(run.id, "paused")
        run_id, commitment_id = run.id, commitment.id
    finally:
        sqlite_store.close()

    _bind(tmp_path)
    try:
        restored, checkpoint = SqliteRunStore().resume(run_id)
        assert restored.state == "active"
        assert restored.commitment_id == commitment_id
        assert checkpoint.cursor == {"processed": 300, "cursor": "batch-7"}
        assert SqliteCommitmentStore().get(commitment_id).title == "migrate the archive"
    finally:
        sqlite_store.close()


def test_waiting_run_survives_a_rebind_and_still_wakes(tmp_path):
    """A run can wait longer than the process that started it."""
    _bind(tmp_path)
    try:
        commitment = SqliteCommitmentStore().create("await review")
        runs = SqliteRunStore()
        run = runs.create(commitment.id)
        runs.transition(run.id, "active")
        runs.transition(run.id, "waiting_for_event", wake_key="pr:123:merged")
        run_id = run.id
    finally:
        sqlite_store.close()

    _bind(tmp_path)
    try:
        runs = SqliteRunStore()
        assert runs.get(run_id).state == "waiting_for_event"
        woken = runs.deliver_event("pr:123:merged")
        assert [r.id for r in woken] == [run_id]
        assert runs.get(run_id).state == "active"
    finally:
        sqlite_store.close()


# ── the real thing ─────────────────────────────────────────────────


_WORKER = textwrap.dedent(
    """
    import os, signal, sys
    from types import SimpleNamespace

    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from jaeger_agent.memory import sqlite_store

    memory_dir, pid_file = sys.argv[1], sys.argv[2]
    sqlite_store.bind(SimpleNamespace(memory_dir=__import__("pathlib").Path(memory_dir)))

    commitment = SqliteCommitmentStore().create("process the backlog")
    runs = SqliteRunStore()
    run = runs.create(commitment.id, provider="claude", owner_pid=os.getpid())
    runs.transition(run.id, "active")
    runs.heartbeat(run.id, owner_pid=os.getpid())

    # Work happens; progress is checkpointed as it goes.
    for processed in (100, 200, 300):
        runs.checkpoint(run.id, {"processed": processed})

    with open(pid_file, "w") as handle:
        handle.write(f"{os.getpid()}\\n{run.id}\\n{commitment.id}\\n")
        handle.flush()
        os.fsync(handle.fileno())

    # Die the way a killed process dies: no unwinding, no final write.
    os.kill(os.getpid(), signal.SIGKILL)
    """
)


def test_sigkilled_run_is_recovered_and_resumes_from_its_checkpoint(tmp_path):
    handoff = tmp_path / "handoff.txt"
    worker = tmp_path / "worker.py"
    worker.write_text(_WORKER)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)

    result = subprocess.run(
        [sys.executable, str(worker), str(tmp_path), str(handoff)],
        env=env, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == -signal.SIGKILL, (
        f"worker did not die by SIGKILL: rc={result.returncode} "
        f"stderr={result.stderr}"
    )
    assert handoff.exists(), f"worker never got to work: {result.stderr}"
    dead_pid, run_id, commitment_id = handoff.read_text().split()
    dead_pid = int(dead_pid)

    if pid_is_alive(dead_pid):
        pytest.skip("pid was recycled between the kill and the check")

    # A brand-new process opens the same database and finds the wreck.
    _bind(tmp_path)
    try:
        runs = SqliteRunStore()

        stranded = runs.get(run_id)
        assert stranded.state == "active", (
            "the killed process left its run marked active — that is the "
            "state recovery has to reconcile"
        )
        assert stranded.owner_pid == dead_pid

        recovered = runs.recover()  # real liveness probe, no mocks

        assert [r.id for r in recovered] == [run_id]
        assert runs.get(run_id).reason == "owner_lost"

        resumed, checkpoint = runs.resume(run_id, owner_pid=os.getpid())
        assert resumed.state == "active"
        assert checkpoint.cursor == {"processed": 300}, (
            "progress written before the kill did not survive it"
        )

        # And the intention outlived the attempt.
        assert SqliteCommitmentStore().get(commitment_id).title == "process the backlog"
    finally:
        sqlite_store.close()


def test_recovery_does_not_touch_a_live_process_run(tmp_path):
    """Recovery must not steal work from a healthy sibling process."""
    _bind(tmp_path)
    try:
        commitment = SqliteCommitmentStore().create("long job")
        runs = SqliteRunStore()
        run = runs.create(commitment.id, owner_pid=os.getpid())
        runs.transition(run.id, "active")

        assert runs.recover() == []
        assert runs.get(run.id).state == "active"
    finally:
        sqlite_store.close()
