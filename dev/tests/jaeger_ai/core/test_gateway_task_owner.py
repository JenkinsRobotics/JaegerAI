"""Real durable admission and receipts; model execution replaced by a bounded worker."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.tasks.owner import GatewayTaskOwner
from jaeger_ai.core.tasks.models import TaskState


@pytest.fixture
def owner(tmp_path):
    store = GatewaySessionStore(tmp_path/'gateway.sqlite3')
    store.ensure_session('parent', profile='jaeger', workspace=str(tmp_path))
    gateway = SimpleNamespace(store=store, event_bus=GatewayEventBus(store=store), _running_tasks={},
                              _cancellations=SimpleNamespace(cancel=lambda rid:None))
    owner = GatewayTaskOwner(gateway)
    gateway._start_admitted_turn = lambda *args: None
    return owner


def context(owner, source='user'):
    return dict(session_id='parent', request_id='parent-request', user_text='Queue this work in the background',
                source=source, execution={'workspace':str(owner.store.db_path.parent), 'model':'configured-model'})


def test_explicit_request_admits_authorized_and_persists(owner):
    result = owner.submit('Build the report', context=context(owner), proposal=True)
    restored = GatewayTaskOwner(owner.gateway).store.get_task(result['task_id'])
    assert restored.state == TaskState.QUEUED
    assert restored.payload['execution']['model'] == 'configured-model'
    assert restored.notification_policy.recipient_session_id == 'parent'
    assert owner.gateway.store.list_pending_approvals() == []


def test_unsolicited_work_stays_a_proposal(owner):
    result = owner.submit('An unsolicited idea', context=context(owner, 'background'), proposal=True)
    assert result['status'] == 'paused'
    assert len(owner.gateway.store.list_pending_approvals()) == 1


def test_repeated_submission_does_not_replace_progress(owner):
    first = owner.submit('Build', context=context(owner))
    owner.store.update_task(first['task_id'], lambda t:t.payload.update(attempt=2))
    again = owner.submit('Build', context=context(owner))
    assert again['replayed']
    assert owner.store.get_task(first['task_id']).payload['attempt'] == 2


def test_artifact_scope_cannot_escape_workspace(owner):
    with pytest.raises(ValueError, match='outside'):
        owner.submit('Write', context=context(owner), artifacts=['../escape.txt'])


def test_cancellation_survives_late_result(owner):
    tid = owner.submit('Write', context=context(owner))['task_id']
    asyncio.run(owner.cancel(tid))
    asyncio.run(owner._execute(tid))
    assert owner.store.get_task(tid).state == TaskState.CANCELLED


def test_verified_receipt_recovered_and_delivered_once(owner):
    tid = owner.submit('Write proof', context=context(owner), artifacts=['proof.txt'])['task_id']
    task = owner.store.get_task(tid)
    path = Path(task.payload['artifacts'][0]); path.write_text('actual output')
    sid = f'task:{tid}'; rid=f'{tid}:0'
    owner.gateway.store.ensure_session(sid)
    admitted=owner.gateway.store.admit_request(sid, 'already dispatched', request_id=rid)
    owner.gateway.store.complete_request(rid, status='completed', result={'output':'Verified proof written'})
    # Fresh owner sees existing completed request; no second tool execution.
    owner.gateway._start_admitted_turn=lambda *a:pytest.fail('duplicate execution')
    restored=GatewayTaskOwner(owner.gateway)
    asyncio.run(restored._execute(tid))
    finished = restored.store.get_task(tid)
    assert finished.state == TaskState.COMPLETED_VERIFIED
    assert finished.payload["verification"][0]["sha256"]
    restored._deliver(restored.store.get_task(tid))
    messages=owner.gateway.store.get_session('parent')['messages']
    assert [m['content'] for m in messages] == ['Verified proof written']


def test_a_message_returning_does_not_complete_work(owner):
    tid=owner.submit('Benchmark every model', context=context(owner))['task_id']
    task=owner.store.get_task(tid)
    assert owner.verify(task, {'output':'Done'})[0] is False


def test_preexisting_artifact_is_not_completion(owner):
    path=owner.store.db_path.parent/'old.txt';path.write_text('old')
    import os
    os.utime(path, (1,1))
    tid=owner.submit('Write new artifact', context=context(owner), artifacts=['old.txt'])['task_id']
    assert not owner.verify(owner.store.get_task(tid), {'output':'Done'})[0]


def test_receipt_is_rechecked_against_current_artifact(owner):
    import hashlib
    tid = owner.submit('Produce report', context=context(owner))['task_id']
    path = owner.store.db_path.parent / 'report.txt'
    path.write_text('verified output')
    result = {'task_completion': {'ok': True, 'verification_receipts': [
        {'kind': 'file_sha256', 'path': 'report.txt',
         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}}
    assert owner.verify(owner.store.get_task(tid), result)[0]
    path.write_text('changed')
    assert not owner.verify(owner.store.get_task(tid), result)[0]
    path.unlink()
    assert not owner.verify(owner.store.get_task(tid), result)[0]


def test_approval_cannot_restart_uncertain_execution(owner):
    tid = owner.submit('Perform effect', context=context(owner))['task_id']
    def uncertain(task):
        task.state = TaskState.PAUSED
        task.error = 'Execution outcome unknown'
    owner.store.update_task(tid, uncertain)
    owner.resolve(tid, True)
    assert owner.store.get_task(tid).state == TaskState.PAUSED
    assert owner.store.get_task(tid).error == 'Execution outcome unknown'


def test_budget_yield_continues_then_delivers_one_verified_answer(owner):
    launches = []
    tid = owner.submit('Build report', context=context(owner), artifacts=['report.txt'])['task_id']
    async def run():
        def start(admitted, sid, prompt):
            rid = admitted['request_id']
            launches.append(rid)
            async def work():
                if len(launches) == 1:
                    result = {'output': 'First checkpoint', 'halt_reason': 'yielded'}
                else:
                    (owner.store.db_path.parent / 'report.txt').write_text('verified report')
                    result = {'output': 'Report built and checked'}
                owner.gateway.store.complete_request(rid, status='completed', result=result)
            owner.gateway._running_tasks[rid] = asyncio.create_task(work())
        owner.gateway._start_admitted_turn = start
        await owner._execute(tid)
        assert owner.store.get_task(tid).state == TaskState.QUEUED
        assert owner.gateway.store.get_session('parent')['messages'] == []
        # A new owner resumes the next persisted attempt, with the prior checkpoint.
        restored = GatewayTaskOwner(owner.gateway)
        await restored._execute(tid)
        await restored.tick()
        assert restored.store.get_task(tid).state == TaskState.COMPLETED_VERIFIED
    asyncio.run(run())
    assert launches == [f'{tid}:0', f'{tid}:1']
    assert [m['content'] for m in owner.gateway.store.get_session('parent')['messages']] == ['Report built and checked']


def test_cancellation_during_execution_waits_for_receipt(owner):
    tid = owner.submit('Build', context=context(owner), artifacts=['report.txt'])['task_id']
    async def run():
        started = asyncio.Event()
        release = asyncio.Event()
        def start(admitted, sid, prompt):
            async def work():
                started.set()
                await release.wait()
                (owner.store.db_path.parent / 'report.txt').write_text('late output')
                owner.gateway.store.complete_request(admitted['request_id'], status='completed', result={'output':'Late success'})
            owner.gateway._running_tasks[admitted['request_id']] = asyncio.create_task(work())
        owner.gateway._start_admitted_turn = start
        executing = asyncio.create_task(owner._execute(tid))
        await started.wait()
        await owner.cancel(tid)
        assert owner.store.get_task(tid).state == TaskState.PAUSED
        release.set()
        await executing
        assert owner.store.get_task(tid).state == TaskState.CANCELLED
    asyncio.run(run())


def test_legacy_board_moves_do_not_count_as_worker_execution(owner, tmp_path):
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml
    from jaeger_agent.background.board import board_for_layout
    layout = InstanceLayout(tmp_path/'instance'); layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(instance_name="test", model=ModelConfig(model_path="/dev/null")))
    board = board_for_layout(layout)
    card = board.add('Produce benchmark report', column='in_progress', source='deepthink', tags=['deepthink'])
    assert card.attempts == 0
    owner.migrate_legacy(layout)
    tasks = owner.store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].state == TaskState.QUEUED
    assert tasks[0].provenance['authorized']
    assert 'gateway-owned' in board.get(card.id).tags
    assert owner.migrate_legacy(layout) == 0


def _finish_worker(owner, tid, result, *, status='completed', exhaust=False):
    """Record a worker Result and run the real owner settle path."""
    if exhaust:
        owner.store.update_task(
            tid,
            lambda task: setattr(task.retry_policy, 'current_retries', task.retry_policy.max_retries),
        )
    sid = f'task:{tid}'
    rid = f'{tid}:0'
    owner.gateway.store.ensure_session(sid)
    owner.gateway.store.admit_request(sid, 'worker', request_id=rid)
    owner.gateway.store.complete_request(rid, status=status, result=result)
    owner.gateway._start_admitted_turn = lambda *args: pytest.fail('worker ran again')
    asyncio.run(owner._execute(tid))
    return owner.store.get_task(tid)


def test_worker_evidence_is_the_only_completed_verified_path(owner):
    """task -> worker Result -> verifier -> authoritative_transition."""
    bare = (
        {},
        {'output': ''},
        {'output': 'success'},
        {'output': 'ok'},
        {'output': 'done'},
        {'ok': True, 'success': True, 'status': 'done'},
    )
    for result in bare:
        tid = owner.submit(f'Finish {result}', context=context(owner))['task_id']
        finished = _finish_worker(owner, tid, result, exhaust=True)
        assert finished.state == TaskState.FAILED
        assert finished.state != TaskState.COMPLETED_VERIFIED

    tid = owner.submit('Write the proof', context=context(owner), artifacts=['missing.txt'])['task_id']
    failed_check = _finish_worker(owner, tid, {'output': 'success'}, exhaust=True)
    assert failed_check.state == TaskState.FAILED

    needs = _finish_worker(
        owner,
        owner.submit('Ask first', context=context(owner))['task_id'],
        {'halt_reason': 'needs_owner', 'error': 'which file?', 'evidence': {'question': 'which file?'}},
        status='failed',
    )
    blocked = _finish_worker(
        owner,
        owner.submit('Wait', context=context(owner))['task_id'],
        {'halt_reason': 'blocked', 'error': 'approval missing', 'evidence': {'waiting_on': 'approval'}},
        status='failed',
    )
    failed = _finish_worker(
        owner,
        owner.submit('Crash', context=context(owner))['task_id'],
        {'error': 'tool crashed', 'output': 'success'},
        status='failed',
        exhaust=True,
    )
    cancelled = _finish_worker(
        owner,
        owner.submit('Stop', context=context(owner))['task_id'],
        {'error': 'operator cancelled'},
        status='cancelled',
    )
    assert [needs.state, blocked.state, failed.state, cancelled.state] == [
        TaskState.NEEDS_OWNER, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED,
    ]


def test_a_result_for_a_missing_parent_is_reported_once_not_every_tick(owner, monkeypatch, caplog):
    import logging
    terminal = SimpleNamespace(task_id='t-orphan', provenance={}, is_terminal=True,
                               updated_at=0.0, state=TaskState.COMPLETED)
    monkeypatch.setattr(owner.store, 'list_tasks', lambda: [terminal])

    def gone(task):
        raise ValueError('parent session unavailable')

    monkeypatch.setattr(owner, '_deliver', gone)
    with caplog.at_level(logging.WARNING, logger='jaeger_ai.core.tasks.owner'):
        for _ in range(5):
            asyncio.run(owner.tick())
    assert sum('result retained' in r.getMessage() for r in caplog.records) == 1


def test_terminal_proposal_approval_cannot_claim_queued(owner):
    import json
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    result = owner.submit('Cancelled proposal', context=context(owner, 'background'), proposal=True)
    asyncio.run(owner.cancel(result['task_id']))
    request = SimpleNamespace(match_info={'id': result['task_id']}, can_read_body=False)
    response = asyncio.run(JaegerGatewayApp.handle_task_approve(SimpleNamespace(task_owner=owner), request))
    assert response.status == 409
    assert json.loads(response.body)['status'] == 'cancelled'
    assert owner.store.get_task(result['task_id']).state is TaskState.CANCELLED


def test_client_nonce_survives_edit_and_rejects_changed_submission(owner):
    from jaeger_ai.core.tasks.store import TaskConflict
    ctx = {**context(owner, 'client'), 'client_submission_id': 'owned-nonce', 'request_id': 'owned-nonce'}
    first = owner.submit('Original proposal', context=ctx, proposal=True)
    task = owner.store.get_task(first['task_id'])
    owner.edit_proposal(task.task_id, goal='Edited saved proposal', expected_updated_at=task.updated_at)
    repeated = owner.submit('Original proposal', context=ctx, proposal=True)
    assert repeated['replayed'] and repeated['task_id'] == first['task_id']
    assert owner.store.get_task(task.task_id).goal == 'Edited saved proposal'
    with pytest.raises(TaskConflict):
        owner.submit('Different original command', context=ctx, proposal=True)
    assert len(owner.store.list_tasks()) == 1
    assert len(owner.gateway.store.list_pending_approvals()) == 1
    assert owner.gateway.store.list_requests() == []


def test_native_multi_task_identity_and_legacy_lookup_remain_unchanged(owner):
    from jaeger_ai.core.tasks.store import TaskConflict
    ctx = context(owner, 'client')
    first = owner.submit('First intentional objective', context=ctx, proposal=True)
    second = owner.submit('Second intentional objective', context=ctx, proposal=True)
    assert first['task_id'] != second['task_id']
    assert {t.task_id for t in owner.store.client_submissions('parent', ctx['request_id'])} == {first['task_id'], second['task_id']}
    with pytest.raises(TaskConflict, match='Multiple legacy'):
        owner.submit('First intentional objective', context={**ctx, 'client_submission_id': ctx['request_id']}, proposal=True)
    assert len(owner.store.list_tasks()) == 2


@pytest.mark.asyncio
async def test_http_proposal_nonce_lookup_and_authoritative_actor(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml
    layout = InstanceLayout(root=tmp_path/'instance'); layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(instance_name='proposal-fixture', model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR', str(layout.root))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-proposal-home', metadata={'agent_id': 'native:builder'})
    body = {'session_id': 'owned-proposal-home', 'request_id': 'owned-proposal-nonce', 'goal': 'Review supplied material', 'proposal': True, 'execution': {'caller': 'forged-actor'}}
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        response = await client.post('/v1/tasks', json=body)
        assert response.status == 201
        receipt = await response.json()
        assert receipt['request_id'] == body['request_id'] and receipt['origin_session_id'] == body['session_id']
        task = gateway.task_owner.store.get_task(receipt['task_id'])
        assert task.payload['execution']['caller'] == 'owner:webui'
        assert task.agent_id == 'native:builder' and task.state is TaskState.PAUSED
        repeated = await client.post('/v1/tasks', json=body)
        assert repeated.status == 200 and (await repeated.json())['task_id'] == task.task_id
        assert (await client.post('/v1/tasks', json={**body, 'goal': 'Changed command'})).status == 409
        lookup = await client.get('/v1/task-submissions/owned-proposal-nonce', params={'session_id': body['session_id']})
        found = await lookup.json()
        assert found['session_id'] == body['session_id'] and found['request_id'] == body['request_id']
        assert [t['task_id'] for t in found['tasks']] == [task.task_id]
        assert len(gateway.store.list_pending_approvals()) == 1
        assert gateway.store.list_requests() == []
    async with TestClient(TestServer(gateway.app), headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/task-submissions/owned-proposal-nonce', params={'session_id': body['session_id']})).status == 403
        assert (await client.post('/v1/tasks', json=body)).status == 403


@pytest.mark.asyncio
async def test_skill_inspection_uses_exact_registry_identity_without_loading_tools(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_agent.skill_registry.playbook_skills import PlaybookSkill
    import jaeger_agent.skill_registry.playbook_skills as skills
    skill = PlaybookSkill('owned-skill', 'owned-category', 'Local fixture', tmp_path/'never-read.md', origin='user', requires_tools=['fixture_read'], requires_toolsets=['fixture-set'], requires_plugins=['fixture-plugin'])
    monkeypatch.setattr(skills, 'discover_playbooks', lambda: [skill])
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        response = await client.get('/v1/runtime/skills/detail', params={'name': skill.name, 'category': skill.category})
        assert response.status == 200
        data = await response.json()
        assert data['requires_tools'] == ['fixture_read'] and data['origin'] == 'user'
        assert data['availability'] == 'not_probed' and not data['execution_authorized'] and not data['origin_verified']
        assert 'path' not in data and 'body' not in data and not skill.path.exists()
        assert (await client.get('/v1/runtime/skills/detail', params={'name': skill.name, 'category': 'other'})).status == 404
        assert (await client.get('/v1/runtime/skills/detail', params={'name': skill.name})).status == 400
        monkeypatch.setattr(skills, 'discover_playbooks', lambda: [skill, skill])
        assert (await client.get('/v1/runtime/skills/detail', params={'name': skill.name, 'category': skill.category})).status == 409
    async with TestClient(TestServer(gateway.app), headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/runtime/skills/detail', params={'name': skill.name, 'category': skill.category})).status == 403
