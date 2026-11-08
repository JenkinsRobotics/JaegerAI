"""Real process death and fresh-owner recovery with local synthetic file effects.

Exercises production task owner and request store, not a live model or UI.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]
REPO = Path(__file__).resolve().parents[4]

BOOT = '''
import asyncio, json, sys
from pathlib import Path
from types import SimpleNamespace
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.tasks.owner import GatewayTaskOwner
store = GatewaySessionStore(Path(sys.argv[1]))
assert store.claim_process()['ok']
gateway = SimpleNamespace(store=store, event_bus=GatewayEventBus(store=store),
    _running_tasks={}, _cancellations=SimpleNamespace(cancel=lambda rid: None))
owner = GatewayTaskOwner(gateway)
'''

WORKER = BOOT + '''
root = Path(sys.argv[1]).parent
store.ensure_session('parent', workspace=str(root))
tid = owner.submit('Create synthetic proof', context={'source': 'client',
    'session_id': 'parent', 'execution': {'workspace': str(root)}}, artifacts=['proof.txt'])['task_id']
rid = tid + ':0'
store.admit_request('task:' + tid, 'synthetic work', request_id=rid)
(root / 'proof.txt').write_text('one synthetic effect\\n')
if sys.argv[2] == 'completed':
    store.complete_request(rid, status='completed', result={'output': 'Synthetic proof produced'})
elif sys.argv[2] == 'cancelled':
    asyncio.run(owner.cancel(tid))
print(json.dumps({'task_id': tid, 'request_id': rid}), flush=True)
sys.stdin.read()
'''

SUCCESSOR = BOOT + '''
store.recover_interrupted_sessions()
def no_dispatch(*args):
    raise AssertionError('A crashed request must not be replayed')
gateway._start_admitted_turn = no_dispatch
async def reconcile():
    # Exercise the actual owner tick, then drain only this owner's workers.
    for _ in range(3):
        await owner.tick()
        if owner._active:
            await asyncio.gather(*list(owner._active.values()))
        await asyncio.sleep(0)
asyncio.run(reconcile())
task = owner.store.get_task(sys.argv[2])
print(json.dumps({'task': task.to_dict(), 'requests': store.list_requests(),
    'messages': store.get_session('parent')['messages']}))
assert store.release_process()
'''


@pytest.mark.parametrize('outcome', ['completed', 'uncertain', 'cancelled'])
def test_killed_owner_reconciles_without_repeating_effect(tmp_path, outcome):
    environment = {**os.environ, 'JAEGER_STATE_DIR': str(tmp_path / 'state'),
        'JAEGER_HOME': str(tmp_path / 'home'), 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONPATH': os.pathsep.join([str(REPO), str(REPO / 'packages/jaeger-agent'),
                                     str(REPO / 'packages/jaeger-os')])}
    database = tmp_path / 'gateway.sqlite3'
    process = subprocess.Popen([sys.executable, '-c', WORKER, str(database), outcome],
        cwd=tmp_path, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 15)
        assert ready, 'synthetic worker did not commit its effect'
        line = process.stdout.readline()
        assert line, process.stderr.read()
        admitted = json.loads(line)
        # Kill only this test-owned process after its committed file effect.
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
    for _ in range(2):
        successor = subprocess.run([sys.executable, '-c', SUCCESSOR, str(database), admitted['task_id']],
            cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=15)
        assert successor.returncode == 0, successor.stderr
        recovered = json.loads(successor.stdout)
        task = recovered['task']
        assert (tmp_path / 'proof.txt').read_text() == 'one synthetic effect\n'
        assert task['payload'].get('attempt', 0) == 0
        assert task['retry_policy']['current_retries'] == 0
        assert len(recovered['requests']) == 1
        assert task['payload']['last_progress']['request_id'] == admitted['request_id']
        assert task['payload']['next_action']
        if outcome != 'cancelled':
            assert len(task['run_history']) == 1
            assert task['run_history'][0]['run_id'] == admitted['request_id']
        assert recovered['requests'][0]['request_id'] == admitted['request_id']
        if outcome == 'completed':
            assert task['state'] == 'completed_verified'
            assert len(recovered['messages']) == 1
            assert task['payload']['verification'][0]['sha256']
        else:
            assert task['state'] == 'paused'
            assert recovered['requests'][0]['status'] == 'execution_unknown'
            assert task['error']  # Retain the unknown-outcome or pending-cancellation blocker.
            assert recovered['messages'] == []
            if outcome == 'cancelled':
                assert task['cancellation'] == 'Cancelled by user'
