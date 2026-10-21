"""Native controls use real isolated stores, including lost-write recovery."""
import json
from types import SimpleNamespace

import pytest
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_agent.memory import sqlite_store


@pytest.fixture
def gateway(tmp_path):
    sqlite_store.bind(InstanceLayout(root=tmp_path / "instance"))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app._current_tier = lambda: "agent"
    yield app
    sqlite_store.close()


async def call(app, path, *, action=None, body=None, method="POST", query=None):
    async def payload():
        return body
    route = next(r for r in app.app.router.routes() if r.resource.canonical == path and r.method == method)
    response = await route.handler(SimpleNamespace(match_info={"action": action}, query=query or {}, json=payload))
    return response.status, json.loads(response.text)


@pytest.mark.asyncio
async def test_schedule_create_edit_pause_replay_and_run_are_owned(gateway):
    body = {"operation_id": "create-1", "name": "native-test", "prompt": "Return a harmless status", "schedule": "0 9 * * *"}
    code, receipt = await call(gateway, "/v1/schedules/{action}", action="create", body=body)
    assert code == 200 and receipt["ok"]
    assert (await call(gateway, "/v1/schedules/{action}", action="create", body=body))[1] == receipt
    assert (await call(gateway, "/v1/schedules/{action}", action="create", body={**body, "prompt": "changed"}))[0] == 400
    assert (await call(gateway, "/v1/schedules/{action}", action="pause", body={"operation_id": "pause-1", "job_id": "native-test"}))[0] == 200
    assert (await call(gateway, "/v1/schedules/{action}", action="update", body={**body, "operation_id": "edit-1", "job_id": "native-test", "prompt": "edited"}))[0] == 200
    jobs = (await call(gateway, "/v1/schedules", method="GET"))[1]["jobs"]
    assert len(jobs) == 1 and not jobs[0]["enabled"] and jobs[0]["prompt"] == "edited"
    _, run = await call(gateway, "/v1/schedules/{action}", action="run", body={"operation_id": "run-1", "job_id": "native-test"})
    assert run["result"]["status"] == "queued"
    history = (await call(gateway, "/v1/schedules/history", method="GET", query={"job_id": "native-test"}))[1]
    assert history["tasks"][0]["task_id"] == run["result"]["task_id"]
    assert history["tasks"][0]["run_history"] == []  # Admission is not execution.


@pytest.mark.asyncio
async def test_lost_write_is_not_repeated_after_store_reopen(gateway, monkeypatch):
    from jaeger_ai.core.runtime import schedules
    original = schedules.create_job
    writes = []
    def lost_response(**values):
        writes.append(values)
        original(**values)
        raise OSError("response lost after write")
    monkeypatch.setattr(schedules, "create_job", lost_response)
    body = {"operation_id": "lost-1", "name": "lost", "prompt": "harmless", "schedule": "0 9 * * *"}
    assert (await call(gateway, "/v1/schedules/{action}", action="create", body=body))[0] == 503
    gateway.store = GatewaySessionStore(gateway.store.path)
    assert (await call(gateway, "/v1/schedules/{action}", action="create", body=body))[0] == 409
    assert len(writes) == 1
    assert schedules.list_jobs()["schedules"][0]["name"] == "lost"


@pytest.mark.asyncio
async def test_proposal_edit_invalidates_old_approval(gateway):
    gateway.store.ensure_session("parent", title="parent")
    receipt = gateway.task_owner.submit("original", context={"session_id": "parent", "source": "client"}, proposal=True)
    tid = receipt["task_id"]
    old = gateway.store.list_pending_approvals()[0]
    task = gateway.task_owner.store.get_task(tid)
    gateway.task_owner.edit_proposal(tid, goal="revised", expected_updated_at=task.updated_at)
    assert gateway.store.resolve_approval(old["approval_id"], approved=True, decision="once") is None
    pending = gateway.store.list_pending_approvals()
    assert len(pending) == 1 and "revised" in pending[0]["prompt"]
    assert not gateway.task_owner.store.get_task(tid).provenance["authorized"]


@pytest.mark.asyncio
async def test_paused_schedule_cancel_and_restore_preserve_definition_without_running(gateway):
    from jaeger_ai.core.runtime import schedules
    body = {'operation_id': 'recover-create', 'name': 'recoverable', 'prompt': 'Keep this definition', 'schedule': '0 9 * * *'}
    assert (await call(gateway, '/v1/schedules/{action}', action='create', body=body))[0] == 200
    for action in ('pause', 'delete'):
        assert (await call(gateway, '/v1/schedules/{action}', action=action, body={'operation_id': 'recover-' + action, 'job_id': 'recoverable'}))[0] == 200
    assert schedules.list_jobs()['schedules'] == []
    deleted = (await call(gateway, '/v1/schedules', method='GET', query={'include_deleted': '1'}))[1]['jobs']
    assert len(deleted) == 1 and deleted[0]['state'] == 'cancelled' and not deleted[0]['enabled']
    assert deleted[0]['prompt'] == 'Keep this definition'
    assert (await call(gateway, '/v1/schedules/{action}', action='create', body={**body, 'operation_id': 'replacement-attempt'}))[0] == 400
    assert (await call(gateway, '/v1/schedules/{action}', action='restore', body={'operation_id': 'recover-restore', 'job_id': 'recoverable'}))[0] == 200
    restored = schedules.list_jobs()['schedules'][0]
    assert restored['status'] == 'paused' and restored['prompt'] == 'Keep this definition'
    assert gateway.task_owner.store.list_tasks() == []
