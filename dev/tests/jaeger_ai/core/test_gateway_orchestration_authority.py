"""A task handed to an external-agent worker is still the task owner's task.

The orchestration service tracks the dispatch. The worker's own ``completed`` is a
transport status; the owner's card settles only from evidence it can check.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.models import TaskState
from jaeger_ai.features.ide_orchestration.adapters import DeterministicFakeWorkerAdapter
from jaeger_ai.features.ide_orchestration.service import IDEOrchestrationService


class _Writer(DeterministicFakeWorkerAdapter):
    """A worker that really produces a file, after it has been dispatched."""

    def __init__(self, path: Path | None = None, content: str = "# report\nfiles: 4\n", **kw):
        super().__init__(**kw)
        self.path, self.content = path, content

    async def submit(self, task):
        if self.path is not None:
            self.path.write_text(self.content)
        return await super().submit(task)


def _app(tmp_path, adapter):
    orchestration = IDEOrchestrationService({adapter.worker_id: adapter})
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "g.sqlite3"), orchestration=orchestration)
    app._current_tier = lambda: "agent"          # orchestration is refused in Chat mode
    return app


async def _call(handler, body=None, *, match=None):
    async def read_json():
        return body or {}

    response = await handler(SimpleNamespace(json=read_json, match_info=match or {}, can_read_body=True))
    return response.status, json.loads(response.text)


async def _dispatch(app, worker, workspace, **extra):
    status, body = await _call(app.handle_create_orchestration_task, {
        "task_id": "t1", "goal": "inspect this project and write the report", "worker": worker,
        "workspace": str(workspace), **extra})
    return status, body


async def _settled(app, task_id="t1"):
    operation = app._running_tasks.get(("orchestration", task_id))
    if operation is not None:
        await asyncio.wait([operation], timeout=10)
    await asyncio.sleep(0.05)
    status, body = await _call(app.handle_get_orchestration_task, match={"id": task_id})
    assert status == 200
    return body


@pytest.mark.asyncio
async def test_a_dispatched_task_is_verified_from_the_artifacts_the_owner_can_check(tmp_path):
    report = tmp_path / "report.md"
    app = _app(tmp_path, _Writer(report, worker_id="fake"))
    status, _ = await _dispatch(app, "fake", tmp_path, artifacts=["report.md"])
    assert status == 201

    body = await _settled(app)

    card = app.task_owner.store.get_task("orch:t1")
    assert body["state"] == "completed"                          # the worker's own status
    assert card.state == TaskState.COMPLETED_VERIFIED            # the owner's verdict
    assert body["task_state"] == "completed_verified"
    assert card.payload["verification"][0]["sha256"]
    assert card.provenance["turn_owned"] and card.provenance["source"] == "worker_dispatch"


@pytest.mark.asyncio
async def test_a_worker_saying_completed_proves_nothing_without_declared_evidence(tmp_path):
    app = _app(tmp_path, DeterministicFakeWorkerAdapter(worker_id="fake", outcome_text="All done, trust me."))
    await _dispatch(app, "fake", tmp_path)

    body = await _settled(app)

    assert body["state"] == "completed"
    assert app.task_owner.store.get_task("orch:t1").state == TaskState.FAILED
    assert body["task_state"] == "failed"


@pytest.mark.asyncio
async def test_a_declared_artifact_the_worker_never_wrote_does_not_verify(tmp_path):
    app = _app(tmp_path, DeterministicFakeWorkerAdapter(worker_id="fake"))
    await _dispatch(app, "fake", tmp_path, artifacts=["report.md"])
    await _settled(app)
    assert app.task_owner.store.get_task("orch:t1").state == TaskState.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome, expected", [
    ("failed", TaskState.FAILED), ("blocked", TaskState.BLOCKED),
    ("approval", TaskState.NEEDS_OWNER), ("auth", TaskState.NEEDS_OWNER),
])
async def test_worker_outcomes_map_to_distinct_owner_states(tmp_path, outcome, expected):
    app = _app(tmp_path, DeterministicFakeWorkerAdapter(worker_id="fake", outcome_state=outcome))
    await _dispatch(app, "fake", tmp_path)
    await _settled(app)
    assert app.task_owner.store.get_task("orch:t1").state == expected


@pytest.mark.asyncio
async def test_cancelling_a_dispatch_cancels_the_owners_card(tmp_path):
    app = _app(tmp_path, DeterministicFakeWorkerAdapter(worker_id="fake", delay_seconds=0.2))
    await _dispatch(app, "fake", tmp_path)
    await asyncio.sleep(0.05)
    await _call(app.handle_cancel_orchestration_task, match={"id": "t1"})
    await _settled(app)
    assert app.task_owner.store.get_task("orch:t1").state in {TaskState.CANCELLED, TaskState.PAUSED}
    assert app.task_owner.store.get_task("orch:t1").state != TaskState.COMPLETED_VERIFIED


@pytest.mark.asyncio
async def test_an_artifact_outside_the_workspace_is_refused_before_any_worker_runs(tmp_path):
    adapter = DeterministicFakeWorkerAdapter(worker_id="fake")
    app = _app(tmp_path, adapter)
    status, body = await _dispatch(app, "fake", tmp_path / "ws", artifacts=["../escape.txt"])
    assert status == 400 and "outside" in body["error"]
    assert adapter.submissions == [] and app.task_owner.store.list_tasks() == []


@pytest.mark.asyncio
async def test_the_scheduler_never_runs_a_dispatch_card(tmp_path, monkeypatch):
    app = _app(tmp_path, DeterministicFakeWorkerAdapter(worker_id="fake", delay_seconds=0.2))
    await _dispatch(app, "fake", tmp_path)
    started = []
    monkeypatch.setattr(app.task_owner, "_execute", lambda tid: started.append(tid))
    await app.task_owner.tick()
    assert started == []
    await _settled(app)
