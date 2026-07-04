"""Deep Think runner Phase 2 — the staged assembly line.

Pins the stage contracts: the plan is generated AND saved as an artifact
before execution, the execute prompt carries the plan, plan failure
degrades gracefully to Phase-1 behaviour, and the per-task-type verify
(skill-review receipts) gates completion on top of the generic evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from jaeger_os.agent.background.deepthink_runner import run_one_task
from jaeger_os.core.memory import sqlite_store
from jaeger_os.core.skill_improvement import skill_revisions


@pytest.fixture()
def layout(tmp_path):
    lay = SimpleNamespace(root=tmp_path, memory_dir=tmp_path / "memory")
    lay.memory_dir.mkdir(parents=True)
    sqlite_store.bind(lay)
    yield lay
    sqlite_store.close()


def _log_mutation(session: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite_store.writer() as conn:
        conn.execute(
            "INSERT INTO tool_calls (session_key, tool_name, ok, ts) "
            "VALUES (?, ?, 1, ?)", (session, "write_file", now),
        )


class _PlanClient:
    def __init__(self, plan="1. write the file\n2. reload skills"):
        self._plan = plan

    def chat(self, messages, **kwargs):
        if isinstance(self._plan, Exception):
            raise self._plan
        return SimpleNamespace(text=self._plan)


class _FakeQueue:
    def __init__(self):
        self.done, self.failed, self.added = [], [], []

    def mark_done(self, tid, result=""):
        self.done.append((tid, result))

    def mark_failed(self, tid, result=""):
        self.failed.append((tid, result))

    def add(self, description, *, source="user", approved=None):
        self.added.append(description)
        return SimpleNamespace(id="r1", description=description)


def _task(desc="Build the weather-fix skill", tid="t9"):
    return SimpleNamespace(id=tid, description=desc)


def test_plan_is_saved_and_rides_the_execute_prompt(layout):
    prompts = []

    def fake_run(client, prompt, session_key=None):
        prompts.append(prompt)
        _log_mutation(session_key)          # the run "did work"
        return "Built and verified."

    q = _FakeQueue()
    out = run_one_task(_PlanClient(), q, layout, _task(), fake_run)
    assert out == "done"
    # plan artifact persisted BEFORE execution
    plan_file = layout.memory_dir / "deepthink_plans" / "t9.md"
    assert plan_file.exists()
    assert "write the file" in plan_file.read_text()
    # the execute prompt carries the plan
    assert "YOUR EXECUTION PLAN" in prompts[0]
    assert "1. write the file" in prompts[0]


def test_plan_failure_degrades_to_planless_execution(layout):
    prompts = []

    def fake_run(client, prompt, session_key=None):
        prompts.append(prompt)
        _log_mutation(session_key)
        return "Done."

    q = _FakeQueue()
    out = run_one_task(_PlanClient(RuntimeError("planner died")),
                       q, layout, _task(), fake_run)
    assert out == "done"                       # execution still happened
    assert "YOUR EXECUTION PLAN" not in prompts[0]
    assert not (layout.memory_dir / "deepthink_plans" / "t9.md").exists()


def test_skill_review_task_requires_a_new_revision_receipt(layout):
    """Mutations alone aren't enough for a [skill-review:x] task — the
    measured loop's receipt (a NEW revision record) gates completion."""
    def fake_run(client, prompt, session_key=None):
        _log_mutation(session_key)             # wrote files, but…
        return "Improved the skill."           # …never recorded a revision

    q = _FakeQueue()
    task = _task(desc="[skill-review:arxiv] Improve the 'arxiv' skill.")
    out = run_one_task(_PlanClient(), q, layout, task, fake_run)
    assert out.startswith("retried:")
    assert "no new revision" in q.failed[0][1]


def test_skill_review_task_with_receipt_completes(layout):
    def fake_run(client, prompt, session_key=None):
        _log_mutation(session_key)
        # the measured loop kept a new version and recorded it
        skill_revisions.record(layout, skill="arxiv", version="1.2.0",
                               summary="tightened SOP", delta="+1")
        return "Improved, benchmarked, kept."

    q = _FakeQueue()
    task = _task(desc="[skill-review:arxiv] Improve the 'arxiv' skill.")
    out = run_one_task(_PlanClient(), q, layout, task, fake_run)
    assert out == "done"
    assert "new revision v1.2.0" in q.done[0][1]


def test_pre_existing_revision_does_not_count_as_receipt(layout):
    """The receipt must be NEW — a revision recorded before the run
    (stale state) can't complete this task."""
    skill_revisions.record(layout, skill="arxiv", version="1.1.0")

    def fake_run(client, prompt, session_key=None):
        _log_mutation(session_key)
        return "All good, trust me."

    q = _FakeQueue()
    task = _task(desc="[skill-review:arxiv] Improve the 'arxiv' skill.")
    out = run_one_task(_PlanClient(), q, layout, task, fake_run)
    assert out.startswith("retried:")
