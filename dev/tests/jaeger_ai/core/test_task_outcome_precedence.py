"""Partial artifacts cannot override a durable worker's unfinished outcome."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.models import TaskState
from jaeger_ai.core.tasks.owner import GatewayTaskOwner


@pytest.fixture
def owner(tmp_path):
    store = GatewaySessionStore(tmp_path / 'gateway.sqlite3')
    store.ensure_session('parent', workspace=str(tmp_path))
    gateway = SimpleNamespace(store=store, event_bus=GatewayEventBus(store=store),
        _running_tasks={}, _cancellations=SimpleNamespace(cancel=lambda rid: None))
    gateway._start_admitted_turn = lambda *args: pytest.fail('Unexpected replay')
    return GatewayTaskOwner(gateway)


def partial_receipt(owner, *, status='completed', **result):
    tid = owner.submit('Finish the report', context={'source': 'client',
        'session_id': 'parent', 'execution': {'workspace': str(owner.store.db_path.parent)}},
        artifacts=['report.txt'])['task_id']
    owner.gateway.store.admit_request('task:' + tid, 'work', request_id=tid + ':0')
    (owner.store.db_path.parent / 'report.txt').write_text('unfinished first paragraph')
    owner.gateway.store.complete_request(tid + ':0', status=status,
        result={'output': 'Retained checkpoint', **result})
    return tid


@pytest.mark.parametrize('result,status,expected,retries,attempt', [
    ({'halt_reason': 'yielded'}, 'completed', TaskState.QUEUED, 0, 1),
    ({'halt_reason': 'blocked'}, 'completed', TaskState.BLOCKED, 0, 0),
    ({'halt_reason': 'needs_owner'}, 'completed', TaskState.NEEDS_OWNER, 0, 0),
    ({'error': 'synthetic failure'}, 'completed', TaskState.QUEUED, 1, 1),
    ({'error': 'synthetic failure'}, 'failed', TaskState.QUEUED, 1, 1),
    ({}, 'execution_unknown', TaskState.PAUSED, 0, 0),
    ({}, 'cancelled', TaskState.CANCELLED, 0, 0),
    ({}, 'completed', TaskState.COMPLETED_VERIFIED, 0, 0),
    ({'halt_reason': None}, 'completed', TaskState.COMPLETED_VERIFIED, 0, 0),
    ({'halt_reason': ''}, 'completed', TaskState.COMPLETED_VERIFIED, 0, 0),
    ({'halt_reason': 'hit max_iterations=8 without a final answer'}, 'completed', TaskState.FAILED, 0, 0),
    ({'halt_reason': 'made 24 tool calls in a single turn'}, 'completed', TaskState.FAILED, 0, 0),
    ({'halt_reason': 'stalled'}, 'execution_unknown', TaskState.PAUSED, 0, 0),
])
def test_receipt_outcome_precedes_partial_artifact(owner, result, status, expected, retries, attempt):
    tid = partial_receipt(owner, status=status, **result)
    restored = GatewayTaskOwner(owner.gateway)
    asyncio.run(restored._execute(tid))
    task = restored.store.get_task(tid)
    assert task.state == expected
    assert task.retry_policy.current_retries == retries
    assert task.payload.get('attempt', 0) == attempt
    messages = owner.gateway.store.get_session('parent')['messages']
    if expected in {TaskState.QUEUED, TaskState.PAUSED}:
        assert messages == []
        assert not task.payload.get('delivered')
    else:
        assert len(messages) == 1
        assert messages[0]['status'] == expected.value
    assert len(owner.gateway.store.list_requests()) == 1
    if expected == TaskState.COMPLETED_VERIFIED:
        assert task.payload['verification'][0]['sha256']


def test_partial_yield_resumes_checkpoint_without_failure_retry(owner):
    tid = partial_receipt(owner, halt_reason='yielded')
    asyncio.run(owner._execute(tid))
    assert owner.store.get_task(tid).state == TaskState.QUEUED
    assert owner.gateway.store.get_session('parent')['messages'] == []
    launches = []

    def finish(admitted, sid, prompt):
        launches.append(admitted['request_id'])
        assert 'Retained checkpoint' in prompt
        (owner.store.db_path.parent / 'report.txt').write_text('finished report')
        owner.gateway.store.complete_request(admitted['request_id'], status='completed',
            result={'output': 'Finished report'})

    owner.gateway._start_admitted_turn = finish
    restored = GatewayTaskOwner(owner.gateway)
    asyncio.run(restored._execute(tid))
    asyncio.run(GatewayTaskOwner(owner.gateway).tick())
    task = restored.store.get_task(tid)
    assert task.state == TaskState.COMPLETED_VERIFIED
    assert task.retry_policy.current_retries == 0
    assert launches == [tid + ':1']
    assert len(task.run_history) == 2
    assert [m['content'] for m in owner.gateway.store.get_session('parent')['messages']] == ['Finished report']


@pytest.mark.parametrize('halt', [
    'context_overflow', 'stalled', 'empty_response', 'error: RuntimeError',
    'thinking_exhausted', 'interrupted', 'future_unknown_halt',
])
def test_runtime_loop_breaker_cannot_verify_or_restart_partial_work(owner, halt):
    from jaeger_ai.core.runtime.autonomous_runner import run_continued_turn
    from jaeger_ai.core.runtime.work_ledger import ledger_scope

    with ledger_scope('loop-breaker-test'):
        result = run_continued_turn(lambda _: {'text': 'Stopped midway', 'halt_reason': halt},
            'Finish the report', durable=True, max_steps=1)
    assert result['halt_reason'] == halt
    assert not result.get('error')
    tid = partial_receipt(owner, halt_reason=result['halt_reason'])
    for _ in range(2):
        restored = GatewayTaskOwner(owner.gateway)
        asyncio.run(restored._execute(tid))
        asyncio.run(restored.tick())
        task = restored.store.get_task(tid)
        assert task.state == TaskState.FAILED
        assert halt in task.error
        assert task.payload.get('attempt', 0) == 0
        assert task.retry_policy.current_retries == 0
        assert len(owner.gateway.store.list_requests()) == 1
        messages = owner.gateway.store.get_session('parent')['messages']
        assert len(messages) == 1
        assert messages[0]['status'] == 'failed'


def test_runtime_budget_boundary_still_yields_instead_of_failing(owner):
    from jaeger_ai.core.runtime.autonomous_runner import run_continued_turn
    from jaeger_ai.core.runtime.work_ledger import ledger_scope

    with ledger_scope('budget-boundary-test'):
        result = run_continued_turn(lambda _: {'text': 'Checkpoint',
            'halt_reason': 'hit max_iterations=8 without a final answer'},
            'Finish the report', durable=True, max_steps=1)
    assert result['halt_reason'] == 'yielded'
    tid = partial_receipt(owner, halt_reason=result['halt_reason'])
    asyncio.run(owner._execute(tid))
    task = owner.store.get_task(tid)
    assert task.state == TaskState.QUEUED
    assert task.payload['attempt'] == 1
    assert task.retry_policy.current_retries == 0
    assert owner.gateway.store.get_session('parent')['messages'] == []


PROCESS = '''
import asyncio, json, os, sys
from pathlib import Path
from types import SimpleNamespace
from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.owner import GatewayTaskOwner
root = Path(sys.argv[1])
store = GatewaySessionStore(root / 'gateway.sqlite3')
assert store.claim_process()['ok']
store.recover_interrupted_sessions()
gateway = SimpleNamespace(store=store, event_bus=GatewayEventBus(store=store),
    _running_tasks={}, _cancellations=SimpleNamespace(cancel=lambda rid: None))
def no_dispatch(*args):
    raise AssertionError('Unexpected replay of persisted receipt')
gateway._start_admitted_turn = no_dispatch
owner = GatewayTaskOwner(gateway)
if sys.argv[2] == 'seed':
    store.ensure_session('parent', workspace=str(root))
    tid = owner.submit('Finish the report', context={'source': 'client',
        'session_id': 'parent', 'execution': {'workspace': str(root)}},
        artifacts=['report.txt'])['task_id']
    store.admit_request('task:' + tid, 'work', request_id=tid + ':0')
    (root / 'report.txt').write_text('partial')
    (root / 'effects.txt').write_text('slice 0\\n')
    store.complete_request(tid + ':0', status='completed', result={
        'halt_reason': 'yielded', 'output': 'Retained checkpoint'})
    print(json.dumps({'task_id': tid}), flush=True)
    os._exit(0)  # Abrupt exit with the lease held, before owner settlement.
tid = sys.argv[3]
if sys.argv[2] == 'finish':
    def finish(admitted, sid, prompt):
        assert admitted['request_id'] == tid + ':1'
        assert 'Retained checkpoint' in prompt
        with (root / 'effects.txt').open('a') as stream:
            stream.write('slice 1\\n')
        (root / 'report.txt').write_text('finished report')
        store.complete_request(admitted['request_id'], status='completed',
            result={'output': 'Finished report'})
    gateway._start_admitted_turn = finish
asyncio.run(owner._execute(tid))
print(json.dumps({'task': owner.store.get_task(tid).to_dict(),
    'requests': store.list_requests(), 'messages': store.get_session('parent')['messages']}))
assert store.release_process()
'''


@pytest.mark.integration
@pytest.mark.subprocess
def test_process_exit_after_partial_yield_continues_once(tmp_path):
    repo = Path(__file__).resolve().parents[4]
    environment = {**os.environ, 'JAEGER_STATE_DIR': str(tmp_path / 'state'),
        'JAEGER_HOME': str(tmp_path / 'home'), 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONPATH': os.pathsep.join([str(repo), str(repo / 'packages/jaeger-agent'),
                                     str(repo / 'packages/jaeger-os')])}

    def run(mode, tid=''):
        result = subprocess.run([sys.executable, '-c', PROCESS, str(tmp_path), mode, tid],
            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    tid = run('seed')['task_id']
    recovered = run('reconcile', tid)
    assert recovered['task']['state'] == 'queued'
    assert recovered['task']['payload']['attempt'] == 1
    assert recovered['task']['retry_policy']['current_retries'] == 0
    assert len(recovered['requests']) == 1
    assert recovered['messages'] == []
    assert (tmp_path / 'effects.txt').read_text() == 'slice 0\n'
    for mode in ('finish', 'reconcile'):
        finished = run(mode, tid)
        assert finished['task']['state'] == 'completed_verified'
        assert len(finished['requests']) == 2
        assert [m['content'] for m in finished['messages']] == ['Finished report']
        assert (tmp_path / 'effects.txt').read_text() == 'slice 0\nslice 1\n'
        assert (tmp_path / 'report.txt').read_text() == 'finished report'
