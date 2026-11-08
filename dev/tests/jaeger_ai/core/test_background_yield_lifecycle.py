"""Observe the actual native lifecycle after a canonical background producer yields."""
import json
import sqlite3
import time
from urllib.error import HTTPError

import pytest
from dev.tests.fixtures.owned_gateway import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_canonical_yield_transfers_active_native_only_with_live_producer_ownership(tmp_path):
    gateway = OwnedGateway(tmp_path)
    try:
        gateway.start()
        gateway.request('/v1/sessions', {'session_id':'yield-parent', 'profile':'jaeger'})
        admitted = gateway.request('/v1/tasks', {'session_id':'yield-parent',
            'goal':'Execute CONTRACT-BACKGROUND-YIELD and retain observable progress',
            'request_id':'yield-once'})[1]
        tid = admitted['task_id']
        deadline = time.monotonic()+60
        while time.monotonic() < deadline:
            task = gateway.request('/v1/tasks/'+tid)[1]
            if task['payload'].get('attempt', 0) >= 1:
                try:
                    rows = gateway.request('/v1/sessions/task:'+tid+'/requests/'+tid+':1')[1]
                except HTTPError as exc:
                    if exc.code != 404:
                        raise
                else:
                    if rows.get('native_run_id'):
                        break
            time.sleep(.1)
        else:
            raise AssertionError((task, (tmp_path/'gateway.log').read_text()))
        assert task['payload']['background_admission_version'] == 1
        _, first = gateway.request('/v1/sessions/task:'+tid+'/requests/'+tid+':0')
        assert first['status'] == 'completed'
        assert first['result']['halt_reason'] == 'yielded'
        observed = []
        for path in [*tmp_path.rglob('*.sqlite3'), *tmp_path.rglob('*.db')]:
            with sqlite3.connect(path) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                    continue
                row = conn.execute('SELECT state, owner_pid FROM runs WHERE id=?', (first['native_run_id'],)).fetchone()
                if row:
                    observed.append({'state':row[0], 'owner_pid':row[1]})
        assert observed == [{'state':'active', 'owner_pid':gateway.process.pid}]
        _, next_request = gateway.request('/v1/sessions/task:'+tid+'/requests/'+tid+':1')
        assert next_request['native_run_id'] == first['native_run_id']
        assert task['state'] != 'paused'
        (tmp_path/'yield-lifecycle-observation.json').write_text(json.dumps({
            'task_id':tid, 'request':first, 'task':task, 'native':observed}, indent=2))
    finally:
        gateway.stop()
