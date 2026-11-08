"""Foreground ownership transfer: real SQLite, native checkpoints and process death.

Only local worker effects are scripted. Unknown original outcomes never replay.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
from jaeger_agent.memory import sqlite_store
from jaeger_ai.core.gateway.server import JaegerGatewayApp, OWNER_RUN_SESSION_PREFIX
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.fixture
def gateway(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path / 'memory'))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'gateway.sqlite3'))
    app.store.ensure_session('parent', workspace=str(tmp_path))
    yield app
    sqlite_store.close()


def seed(gateway, *, status='completed', halt='yielded', checkpoint=True, tools=None):
    root = gateway.store.path.parent
    row = gateway.store.admit_request('parent', 'Create a verified report', request_id='foreground',
        requested={'workspace': str(root), 'caller': 'owner:webui', 'model': 'frozen-model',
                   'provider': 'frozen-provider',
                   'allowed_tools': ['read_file', 'write_file'] if tools is None else tools,
                   'attachment_ids': [], 'interaction_tier': 'jaeger'})
    task = gateway.task_owner.open_turn(session_id='parent', request_id=row['request_id'],
        text=row['input_text'], strategy='react_loop', owner='owner:webui',
        workspace=str(root), execution=row['execution'])
    runs = SqliteRunStore()
    commitment = SqliteCommitmentStore().create('Original foreground work')
    run = runs.create(commitment.id, owner_pid=os.getpid())
    runs.transition(run.id, 'active')
    if checkpoint:
        runs.checkpoint(run.id, {'messages': [{'role': 'assistant', 'content': 'Saved partial work'}]})
    gateway.store.bind_native(row['request_id'], native_run_id=run.id,
        native_session=OWNER_RUN_SESSION_PREFIX + 'parent')
    gateway.task_owner.close_turn(task.task_id, {'text': 'Saved partial work', 'halt_reason': halt},
        status='completed')
    if status is not None:
        gateway.store.complete_request(row['request_id'], status=status,
            result={'output': 'Saved partial work', 'halt_reason': halt})
    return task.task_id, run.id


async def drain(owner, times=3):
    for _ in range(times):
        await owner.tick()
        if owner._active:
            await asyncio.gather(*list(owner._active.values()))
        await asyncio.sleep(0)


def no_dispatch(*_):
    pytest.fail('Unfinished or uncertain original request must not be replayed')


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['execution_unknown', 'cancelled', 'failed'])
async def test_noncompleted_original_receipt_never_transfers(gateway, outcome):
    tid, _ = seed(gateway, status=outcome)
    gateway._start_admitted_turn = no_dispatch
    await drain(gateway.task_owner)
    task = gateway.task_owner.store.get_task(tid)
    assert task.state.value != 'queued'
    assert task.provenance['turn_owned']
    assert len(gateway.store.list_requests()) == 1
    assert not task.payload.get('delivered')


@pytest.mark.asyncio
async def test_pending_native_effect_blocks_transfer(gateway):
    tid, native = seed(gateway)
    ledger = SqliteEffectLedger()
    def interrupted_effect():
        raise RuntimeError('Synthetic process interruption after claim')
    with pytest.raises(RuntimeError):
        ledger.once('uncertain-effect', 'synthetic-local-write', interrupted_effect, run_id=native)
    gateway._start_admitted_turn = no_dispatch
    await drain(gateway.task_owner)
    task = gateway.task_owner.store.get_task(tid)
    assert task.state.value in {'paused', 'failed'}
    assert ledger.get('uncertain-effect').status == 'pending'
    assert len(gateway.store.list_requests()) == 1


@pytest.mark.asyncio
async def test_missing_native_checkpoint_is_nonresumable(gateway):
    tid, _ = seed(gateway, checkpoint=False)
    gateway._start_admitted_turn = no_dispatch
    await drain(gateway.task_owner)
    task = gateway.task_owner.store.get_task(tid)
    assert task.state.value == 'failed'
    assert task.error
    assert len(gateway.store.list_requests()) == 1


@pytest.mark.asyncio
async def test_original_still_executing_cannot_transfer(gateway):
    tid, _ = seed(gateway)
    gateway._running_tasks['foreground'] = object()
    gateway._start_admitted_turn = no_dispatch
    await drain(gateway.task_owner)
    assert gateway.task_owner.store.get_task(tid).provenance['turn_owned']
    assert len(gateway.store.list_requests()) == 1


def owned_pending_child(app):
    """A qualified, pre-admission child using the production binding contract."""
    approval = app.store.create_approval(kind='agent_handoff', prompt='Synthetic child',
        options=['once', 'deny'], session_id='parent', metadata={'request_id': 'child-request'})
    record = {'id': 'child-handoff', 'request_id': 'child-request',
        'from_agent_id': 'native:jaeger', 'to_agent_id': 'native:builder',
        'parent_run_id': 'foreground', 'session_id': 'parent',
        'task': 'Synthetic pending child', 'status': 'pending_approval',
        'require_approval': True, 'approval_id': approval['approval_id'],
        'metadata': {'caller_actor': 'owner:webui', 'parent_binding': {
            'request_id': 'foreground', 'session_id': 'parent', 'root_actor': 'owner:webui',
            'child_actor': 'owner:webui', 'source_agent_id': 'native:jaeger'}}}
    return app.store.save_handoff(record)


@pytest.mark.asyncio
@pytest.mark.parametrize('promoted', [False, True])
async def test_cancel_includes_original_foreground_children(gateway, promoted):
    tid, _ = seed(gateway)
    child = owned_pending_child(gateway)
    if promoted:
        # The first tick may promote and schedule; keep its execution pending
        # until cancel below, without invoking a synthetic effect.
        gate = asyncio.Event()
        async def hold(_):
            await gate.wait()
        gateway.task_owner._execute = hold
        await gateway.task_owner.tick()
        assert not gateway.task_owner.store.get_task(tid).provenance.get('turn_owned')
    try:
        assert await gateway.task_owner.cancel(tid)
        saved = gateway.store.get_handoff(child['id'])
        assert saved['status'] == 'cancelled'
        assert saved['metadata']['cancelled_before_admission']
        assert saved['metadata']['cancel_origin_request_id'] == 'foreground'
        assert len(gateway.store.list_requests()) == 1
    finally:
        if promoted:
            gate.set()
            if gateway.task_owner._active:
                await asyncio.gather(*list(gateway.task_owner._active.values()))


@pytest.mark.asyncio
@pytest.mark.parametrize('promoted', [False, True])
async def test_stop_original_request_cancels_transferred_work(gateway, promoted):
    tid, _ = seed(gateway)
    child = owned_pending_child(gateway)
    continuation = None
    if promoted:
        # First tick transfers but does not execute the old slice. The saved
        # continuation admission below represents an in-flight new slice.
        await gateway.task_owner.tick()
        task = gateway.task_owner.store.get_task(tid)
        assert not task.provenance.get('turn_owned')
        sid = 'task:' + tid
        gateway.task_owner._execution_session(task)
        continuation = tid + ':' + str(task.payload.get('attempt', 0))
        owner = gateway.task_owner
        prompt = owner._continuation_prompt(task)
        execution = owner._continuation_execution(task)
        gateway.store.admit_request(sid, prompt, request_id=continuation,
            requested=execution, admission_guard=lambda conn: owner._admission_guard(
                conn, task, execution=execution, prompt=prompt))
        gateway.store.bind_native(continuation, native_run_id=task.payload['native_run_id'],
            native_session=OWNER_RUN_SESSION_PREFIX + sid)
    class Request(dict):
        can_read_body = True
        match_info = {'id': 'parent'}
        async def json(self):
            return {'request_id': 'foreground'}
    response = await gateway.handle_cancel_turn(Request())
    assert response.status == 200
    assert gateway.task_owner.store.get_task(tid).cancellation == 'Cancelled by user'
    assert gateway.store.get_handoff(child['id'])['status'] == 'cancelled'
    result = json.loads(response.text)
    assert result['status'] == 'completed'
    assert result['already_terminal'] is True  # Original slice, not the objective.
    assert result['foreground_task_id'] == tid
    assert any(row['handoff_id'] == child['id'] for row in result['owned_handoff_cancellations'])
    if continuation:
        assert result['cancel_requested'] is True
        assert result['foreground_task_state'] == 'paused'
        assert result['continuation_request_id'] == continuation
        assert tid in result['unconfirmed_task_ids']
        assert gateway.store.get_request('foreground')['status'] == 'completed'
        assert gateway.store.get_request(continuation)['status'] == 'running'
        assert gateway._cancellations.is_cancelled(continuation)
        assert gateway.task_owner.store.get_task(tid).state.value == 'paused'
        gateway.store.complete_request(continuation, status='cancelled', result={})
    gateway._start_admitted_turn = no_dispatch
    await drain(gateway.task_owner)
    assert gateway.task_owner.store.get_task(tid).state.value == 'cancelled'
    assert len(gateway.store.list_requests()) == (2 if promoted else 1)


@pytest.mark.asyncio
async def test_live_foreground_child_blocks_cancel_completion(gateway):
    from jaeger_ai.contract.handoffs import child_request_id
    from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
    tid, _ = seed(gateway)
    child = owned_pending_child(gateway)
    sid = specialist_session(child['to_agent_id'], child['request_id'])
    rid = child_request_id(child['request_id'])
    gateway.store.ensure_session(sid, metadata={'handoff_id': child['id'],
        'agent_id': child['to_agent_id'], 'parent_session_id': 'parent'})
    gateway.store.admit_request(sid, 'Synthetic running child', request_id=rid,
        requested={'caller': 'owner:webui', 'is_subordinate': True})
    assert await gateway.task_owner.cancel(tid)
    task = gateway.task_owner.store.get_task(tid)
    assert task.state.value == 'paused'
    assert 'child' in task.error.lower()
    assert gateway._cancellations.is_cancelled(rid)
    assert task.payload['cancellation_children'][0]['cancellation_confirmed'] is False
    gateway.store.complete_request(rid, status='cancelled', result={})
    assert await gateway.task_owner.cancel(tid)
    assert gateway.task_owner.store.get_task(tid).state.value == 'cancelled'


@pytest.mark.asyncio
async def test_revoked_card_never_transfers(gateway):
    tid, _ = seed(gateway)
    gateway.task_owner.store.update_task(tid, lambda t: t.provenance.update(authorized=False))
    gateway._start_admitted_turn = no_dispatch
    await drain(gateway.task_owner)
    assert len(gateway.store.list_requests()) == 1
    assert gateway.task_owner.store.get_task(tid).provenance['turn_owned']


PROCESS = r'''
import asyncio, hashlib, json, os, sys
from pathlib import Path
from types import SimpleNamespace
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store
from jaeger_ai.core.gateway.server import JaegerGatewayApp, OWNER_RUN_SESSION_PREFIX
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
root = Path(sys.argv[1])
mode = sys.argv[2]
sqlite_store.bind(SimpleNamespace(memory_dir=root / 'memory'))
store = GatewaySessionStore(root / 'gateway.sqlite3')
assert store.claim_process()['ok']
app = JaegerGatewayApp(store=store)
owner = app.task_owner
if mode.startswith('seed_'):
    store.ensure_session('parent', workspace=str(root))
    row = store.admit_request('parent', 'Create a verified report', request_id='foreground',
        requested={'workspace': str(root), 'caller':'owner:webui', 'allowed_tools':['read_file','write_file'],
                   'model':'frozen-model', 'provider':'frozen-provider', 'attachment_ids':[],
                   'interaction_tier':'jaeger'})
    task = owner.open_turn(session_id='parent', request_id='foreground', text=row['input_text'],
        strategy='react_loop', owner='owner:webui', workspace=str(root), execution=row['execution'])
    runs=SqliteRunStore()
    commitment=SqliteCommitmentStore().create('Synthetic foreground')
    run=runs.create(commitment.id, owner_pid=os.getpid())
    runs.transition(run.id,'active')
    runs.checkpoint(run.id, {'messages':[{'role':'assistant','content':'Saved partial work'}]})
    store.bind_native('foreground',native_run_id=run.id,native_session=OWNER_RUN_SESSION_PREFIX+'parent')
    (root/'effects.txt').write_text('foreground\n')
    owner.close_turn(task.task_id, {'text':'Saved partial work','halt_reason':'yielded'},status='completed')
    if mode in {'seed_after_receipt', 'seed_after_transfer'}:
        store.complete_request('foreground',status='completed',result={'output':'Saved partial work','halt_reason':'yielded'})
    if mode=='seed_after_transfer':
        asyncio.run(owner.tick())
        assert not owner.store.get_task(task.task_id).provenance.get('turn_owned')
        assert len(store.list_requests())==1
    print(json.dumps({'task_id':task.task_id,'native_run_id':run.id}),flush=True)
    os._exit(0)
store.recover_interrupted_sessions()
tid=sys.argv[3]
launches=[]
def finish(admitted,sid,prompt):
    assert mode=='finish', 'Unknown outcome must not redispatch'
    assert admitted['request_id']!='foreground'
    assert 'Saved partial work' in prompt
    execution=admitted['execution']
    assert execution['caller']=='owner:webui'
    assert execution['allowed_tools']==['read_file','write_file']
    assert execution['model']=='frozen-model' and execution['provider']=='frozen-provider'
    assert store.get_request(admitted['request_id'])['native_run_id']==store.get_request('foreground')['native_run_id']
    launches.append(admitted['request_id'])
    with (root/'effects.txt').open('a') as stream: stream.write('continuation\n')
    report=root/'report.txt'
    report.write_text('finished report')
    store.complete_request(admitted['request_id'],status='completed',result={
        'output':'Finished report','task_completion':{'ok':True,'verification_receipts':[
            {'kind':'file_sha256','path':str(report),'sha256':hashlib.sha256(report.read_bytes()).hexdigest()}]}})
app._start_admitted_turn=finish
async def reconcile():
    for _ in range(4):
        await owner.tick()
        if owner._active: await asyncio.gather(*list(owner._active.values()))
        await asyncio.sleep(0)
asyncio.run(reconcile())
print(json.dumps({'task':owner.store.get_task(tid).to_dict(),'requests':store.list_requests(),
    'messages':store.get_session('parent')['messages'],'launches':launches}))
assert store.release_process()
'''


@pytest.mark.integration
@pytest.mark.subprocess
@pytest.mark.parametrize('window', ['before_receipt', 'after_receipt', 'after_transfer'])
def test_process_exit_at_foreground_transfer_boundary(tmp_path, window):
    repo = Path(__file__).resolve().parents[4]
    environment = {**os.environ, 'JAEGER_STATE_DIR': str(tmp_path/'state'),
        'JAEGER_HOME': str(tmp_path/'home'), 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONPATH': os.pathsep.join([str(repo),str(repo/'packages/jaeger-agent'),str(repo/'packages/jaeger-os')])}
    def run(mode, tid=''):
        result = subprocess.run([sys.executable,'-c',PROCESS,str(tmp_path),mode,tid],
            cwd=tmp_path,env=environment,capture_output=True,text=True,timeout=25)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    original=run('seed_'+window)
    tid=original['task_id']
    if window=='before_receipt':
        for _ in range(2):
            recovered=run('unknown',tid)
            assert recovered['launches']==[]
            assert len(recovered['requests'])==1
            assert recovered['requests'][0]['status']=='execution_unknown'
            assert recovered['task']['state'] in {'paused','failed'}
            assert (tmp_path/'effects.txt').read_text()=='foreground\n'
    else:
        recovered=run('finish',tid)
        assert len(recovered['launches'])==1
        for result in (recovered,run('reconcile',tid)):
            assert result['task']['state']=='completed_verified'
            assert len(result['requests'])==2
            assert result['task']['payload']['native_run_id']==original['native_run_id']
            assert result['task']['retry_policy']['current_retries']==0
            assert [m['content'] for m in result['messages'] if m['role']=='assistant']==['Finished report']
            assert (tmp_path/'effects.txt').read_text()=='foreground\ncontinuation\n'
