"""Durable owner races use real SQLite receipts and synthetic workers, never a model."""
import asyncio
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.models import TaskState
from jaeger_ai.core.tasks.owner import GatewayTaskOwner


@pytest.fixture
def owner(tmp_path):
    store = GatewaySessionStore(tmp_path / 'gateway.sqlite3')
    store.ensure_session('parent', profile='jaeger', workspace=str(tmp_path))
    gateway = SimpleNamespace(store=store, event_bus=GatewayEventBus(store=store),
        _running_tasks={}, _cancellations=SimpleNamespace(cancel=lambda rid: None))
    gateway._start_admitted_turn = lambda *args: None
    return GatewayTaskOwner(gateway)


def submit(owner):
    return owner.submit('Build a synthetic report', context={
        'session_id': 'parent', 'request_id': 'request', 'source': 'client',
        'execution': {'workspace': str(owner.store.db_path.parent)}})['task_id']


def test_cancellation_committed_before_admission_prevents_dispatch(owner, monkeypatch):
    tid = submit(owner)
    original = owner.gateway.store.admit_request
    launches = []

    def race(*args, **kwargs):
        # Another connection commits cancellation after _execute's initial read.
        def cancel(task):
            task.cancellation = 'Cancelled by user'
            task.state = TaskState.CANCELLED
        owner.store.update_task(tid, cancel)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner.gateway.store, 'admit_request', race)
    owner.gateway._start_admitted_turn = lambda *args: launches.append(args)
    asyncio.run(owner._execute(tid))
    assert launches == []
    assert owner.gateway.store.get_request(f'{tid}:0') is None
    assert owner.store.get_task(tid).state == TaskState.CANCELLED


def test_two_reconcilers_consume_failed_attempt_only_once(owner):
    tid = submit(owner)
    rid = f'{tid}:0'

    async def run():
        release = asyncio.Event()

        async def work():
            await release.wait()
            owner.gateway.store.complete_request(rid, status='failed', result={'error': 'synthetic failure'})

        def start(*args):
            owner.gateway._running_tasks[rid] = asyncio.create_task(work())

        owner.gateway._start_admitted_turn = start
        first = asyncio.create_task(owner._execute(tid))
        await asyncio.sleep(0)
        second = asyncio.create_task(owner._execute(tid))
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(first, second)

    asyncio.run(run())
    task = owner.store.get_task(tid)
    assert task.retry_policy.current_retries == 1
    assert task.payload['attempt'] == 1
    assert task.state == TaskState.QUEUED
    assert len(task.run_history) == 1
    assert task.run_history[0].status == 'failed'
    assert task.payload['blocker'] == 'synthetic failure'
    assert task.payload['next_action'].startswith('Resume')


def test_retry_history_and_next_action_survive_fresh_owner(owner):
    tid = submit(owner)
    launches = []

    def fail(admitted, *args):
        rid = admitted['request_id']
        launches.append(rid)
        owner.gateway.store.complete_request(rid, status='failed', result={'error': 'synthetic failure'})

    owner.gateway._start_admitted_turn = fail
    for _ in range(6):
        asyncio.run(GatewayTaskOwner(owner.gateway)._execute(tid))
    task = GatewayTaskOwner(owner.gateway).store.get_task(tid)
    assert task.state == TaskState.FAILED
    assert len(launches) == 4  # Initial attempt plus the configured three retries.
    assert task.retry_policy.current_retries == 3
    assert [run.run_id for run in task.run_history] == launches
    assert all(run.status == 'failed' and run.completed_at for run in task.run_history)
    assert task.payload['last_progress']['request_id'] == launches[-1]
    assert task.payload['last_progress']['task_state'] == 'failed'
    assert task.payload['blocker'] == 'synthetic failure'
    assert task.payload['next_action'] == 'Review the retained result'
    assert task.goal == 'Build a synthetic report'
    assert task.payload['execution']['workspace'] == str(owner.store.db_path.parent)


def test_proposal_persists_completion_criteria_and_approval_next_action(owner):
    tid = owner.submit('Create synthetic output', proposal=True, context={
        'session_id': 'parent', 'source': 'client',
        'execution': {'workspace': str(owner.store.db_path.parent)}})['task_id']
    task = GatewayTaskOwner(owner.gateway).store.get_task(tid)
    assert task.state == TaskState.PAUSED
    assert task.payload['completion_criteria']['objective'] == task.goal
    assert task.payload['completion_criteria']['verification']
    assert task.payload['last_progress']['request_status'] == 'not_admitted'
    assert task.payload['next_action'].startswith('Await approval')
    assert task.payload['blocker'] == 'Approval required'
    assert task.run_history == []

    owner.edit_proposal(tid, goal='Revised synthetic output', expected_updated_at=task.updated_at)
    owner.resolve(tid, True)
    approved = GatewayTaskOwner(owner.gateway).store.get_task(tid)
    assert approved.payload['completion_criteria']['objective'] == 'Revised synthetic output'
    assert approved.payload['next_action'].startswith('Resume')
    assert approved.payload['blocker'] is None


def test_stale_cancellation_cannot_resurrect_cancelled_task(owner, monkeypatch):
    tid = submit(owner)

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def children(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
                return [{'handoff_id': 'child', 'outcome': 'requested',
                         'cancellation_confirmed': False}]
            return [{'handoff_id': 'child', 'outcome': 'terminal',
                     'cancellation_confirmed': True}]

        monkeypatch.setattr(owner, '_cancel_owned_children', children)
        stale = asyncio.create_task(owner.cancel(tid))
        await entered.wait()
        pending = owner.store.get_task(tid)
        assert pending.state == TaskState.PAUSED
        assert not pending.payload.get('delivered')
        await owner.cancel(tid)
        assert owner.store.get_task(tid).state == TaskState.CANCELLED
        release.set()
        await stale

    asyncio.run(run())
    task = owner.store.get_task(tid)
    assert task.state == TaskState.CANCELLED
    assert task.payload['delivered'] is True
    assert task.payload['cancellation_children'][0]['cancellation_confirmed'] is True
    assert len(owner.gateway.store.get_session('parent')['messages']) == 1
