"""Deep Think runner Phase 1 — verify-before-done.

The old daemon marked a task "completed" whenever run_command RETURNED.
These tests pin the new contract: completion requires OBSERVABLE evidence
(successful mutating tool calls in the task's session, no failure
admission), with exactly one bounded replan cycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from jaeger_os.agent.background.deepthink_verify import (
    RETRY_TAG,
    settle_task,
    verify_outcome,
)
from jaeger_os.core.memory import sqlite_store


@pytest.fixture()
def layout(tmp_path):
    lay = SimpleNamespace(root=tmp_path, memory_dir=tmp_path / "memory")
    lay.memory_dir.mkdir(parents=True)
    sqlite_store.bind(lay)
    yield lay
    sqlite_store.close()


def _log_call(session: str, tool: str, ok: bool = True) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite_store.writer() as conn:
        conn.execute(
            "INSERT INTO tool_calls (session_key, tool_name, ok, ts) "
            "VALUES (?, ?, ?, ?)",
            (session, tool, 1 if ok else 0, now),
        )


class _FakeQueue:
    """Records lifecycle calls; add() returns a task with a fresh id."""

    def __init__(self):
        self.done: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []
        self.added: list[dict] = []

    def mark_done(self, task_id, result=""):
        self.done.append((task_id, result))

    def mark_failed(self, task_id, result=""):
        self.failed.append((task_id, result))

    def add(self, description, *, source="user", approved=None):
        self.added.append({"description": description, "source": source,
                           "approved": approved})
        return SimpleNamespace(id=f"retry-{len(self.added)}",
                               description=description)


def _task(desc="Build the weather-fix skill", task_id="t1"):
    return SimpleNamespace(id=task_id, description=desc)


# ── verify_outcome: the evidence truth table ───────────────────────


def test_mutations_and_clean_answer_verify(layout):
    _log_call("daemon_t1", "write_file")
    _log_call("daemon_t1", "reload_skills")
    ok, evidence = verify_outcome(layout, "t1", "Skill built and reloaded.")
    assert ok and "write_file" in evidence


def test_no_mutations_fails_verification(layout):
    _log_call("daemon_t1", "read_file")        # read-only doesn't count
    _log_call("daemon_t1", "write_file", ok=False)   # failed write doesn't
    ok, reason = verify_outcome(layout, "t1", "All done, I promise!")
    assert not ok and "no successful mutating" in reason


def test_failure_admission_fails_even_with_mutations(layout):
    _log_call("daemon_t1", "write_file")
    ok, reason = verify_outcome(
        layout, "t1", "I wrote a draft but I was unable to complete the task.")
    assert not ok and "admits failure" in reason


def test_other_sessions_evidence_does_not_leak(layout):
    _log_call("daemon_OTHER", "write_file")
    ok, _ = verify_outcome(layout, "t1", "Done.")
    assert not ok


# ── settle_task: done / one retry / then failed ────────────────────


def test_verified_task_is_marked_done(layout):
    _log_call("daemon_t1", "write_file")
    q = _FakeQueue()
    assert settle_task(q, layout, _task(), "Built it.") == "done"
    assert q.done and not q.failed and not q.added


def test_unverified_task_gets_one_informed_preapproved_retry(layout):
    q = _FakeQueue()
    action = settle_task(q, layout, _task(), "I was unable to complete it.")
    assert action.startswith("retried:")
    assert q.failed and len(q.added) == 1
    retry = q.added[0]
    assert retry["approved"] is True                    # inherits approval
    assert retry["description"].startswith(RETRY_TAG)   # tagged: no loops
    assert "DID NOT VERIFY" in retry["description"]     # informed retry
    assert "unable to complete" in retry["description"]  # carries evidence


def test_retry_that_fails_again_is_marked_failed_not_requeued(layout):
    q = _FakeQueue()
    task = _task(desc=f"{RETRY_TAG} Build the weather-fix skill", task_id="t2")
    assert settle_task(q, layout, task, "Still nothing worked.") == "failed"
    assert q.failed and not q.added                     # never loops
    assert "after retry" in q.failed[0][1]
