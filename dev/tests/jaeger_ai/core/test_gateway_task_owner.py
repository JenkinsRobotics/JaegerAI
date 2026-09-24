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
    assert restored.store.get_task(tid).state == TaskState.COMPLETED
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
        assert restored.store.get_task(tid).state == TaskState.COMPLETED
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
