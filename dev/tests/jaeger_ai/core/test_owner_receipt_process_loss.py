"""Real child SIGKILL across the qualified request proof boundary.

Only the model and nominated fault barrier are scripted. Gateway execution,
file tool, approval, effect ledger, atomic seal and startup projection are real.
"""
import json
import sqlite3
import re
from html import unescape
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener
import time

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def wait_until(predicate, gateway, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError((gateway.root / 'gateway.log').read_text())


def sql(gateway, query, params=()):
    with sqlite3.connect(gateway.root / 'gateway_sessions.sqlite3') as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def native_evidence(gateway, runs):
    """Keep original runs plus target-file evidence under ANY run/session.

    Unrelated background traffic is excluded; replays with new IDs are not.
    """
    found = {}
    for path in [*gateway.root.rglob('*.sqlite3'), *gateway.root.rglob('*.db')]:
        with sqlite3.connect(path) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('effects', 'tool_calls'):
                if table not in tables:
                    continue
                cols = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
                if table == 'tool_calls':
                    rows = conn.execute("SELECT * FROM tool_calls WHERE session_key='loss' "
                                        "OR args_json LIKE '%durable-report.txt%' "
                                        "OR args_json LIKE '%DURABLE-VERIFIED-CONTENT%' ORDER BY id").fetchall()
                    found[(str(path.relative_to(gateway.root)), table)] = rows
                    continue
                if 'run_id' not in cols:
                    continue
                rows = conn.execute(f'SELECT * FROM {table} WHERE run_id IN ({",".join("?" for _ in runs)}) OR key LIKE ? OR result_json LIKE ? ORDER BY rowid', [*runs, '%durable-report.txt%', '%durable-report.txt%']).fetchall()
                found[(str(path.relative_to(gateway.root)), table)] = rows
    return found


def request_calls(gateway):
    return [json.loads(line) for line in (gateway.root / 'provider-requests.jsonl').read_text().splitlines()
            if json.loads(line)['request_id'] == 'lost-request'
            or 'CONTRACT-DURABLE' in json.loads(line)['request']]


def finishes(gateway):
    return [r for r in sql(gateway, "SELECT * FROM events WHERE event IN ('turn.finish', 'turn.reconciled', 'turn.failed', 'turn.cancelled', 'turn.unknown')")
            if json.loads(r['data_json']).get('request_id') == 'lost-request']


def queue_calls(gateway):
    return [json.loads(line) for line in (gateway.root / 'provider-requests.jsonl').read_text().splitlines()
            if json.loads(line)['request_id'] == 'queued-request'
            or 'QUEUED-AFTER-RECOVERY' in json.loads(line)['request']]


def assistant_projection(gateway):
    return sql(gateway, "SELECT * FROM messages WHERE role='assistant' AND "
               "(session_id IN ('loss', 'foreign') OR content IN "
               "('Durable report verified', 'QUEUED-AFTER-RECOVERY')) ORDER BY id")


def assert_restart_evidence(gateway, expected, before_calls, before_native, runs, target, before_file):
    assert sql(gateway, "SELECT status FROM client_requests WHERE request_id='lost-request'")[0]['status'] == expected
    assert request_calls(gateway) == before_calls
    assert native_evidence(gateway, runs) == before_native
    assert (target.stat().st_mtime_ns, target.read_bytes()) == before_file
    assert len(sql(gateway, "SELECT * FROM client_requests WHERE input_text LIKE '%CONTRACT-DURABLE%'")) == 1
    valid = expected == 'completed'
    assert sql(gateway, "SELECT status FROM client_requests WHERE request_id='queued-request'")[0]['status'] == ('completed' if valid else 'queued')
    calls = queue_calls(gateway)
    assert len(calls) == int(valid)
    assert all(call['request_id'] == 'queued-request' for call in calls)
    projected = assistant_projection(gateway)
    assert len(projected) == (2 if valid else 0)
    if valid:
        assert [message['content'] for message in projected] == ['Durable report verified', 'QUEUED-AFTER-RECOVERY']
        assert all(message['session_id'] == 'loss' for message in projected)
    events = finishes(gateway)
    assert len(events) == int(valid)
    if valid:
        assert events[0]['session_id'] == 'loss' and events[0]['event'] == 'turn.reconciled'
        assert json.loads(events[0]['data_json'])['status'] == 'completed'


@pytest.mark.parametrize('phase,drift', [
    ('after_seal', None), ('before_seal', None),
    ('after_seal', 'authority'), ('after_seal', 'session'),
])
def test_owned_process_loss_at_request_seal(tmp_path, phase, drift):
    gateway = OwnedGateway(tmp_path, webui=True, receipt_fault={
        'phase': phase, 'session_id': 'loss', 'request_id': 'lost-request',
    })
    try:
        gateway.start()
        browser = build_opener(HTTPCookieProcessor(CookieJar()))
        with browser.open(Request(gateway.webui_url + '/api/auth/login',
                data=json.dumps({'password': 'synthetic-contract-password'}).encode(),
                headers={'Content-Type': 'application/json'}), timeout=5) as response:
            assert json.load(response) == {'ok': True}
        def proxy(path, body=None):
            headers = {'Content-Type': 'application/json'}
            if body is not None:
                with browser.open(gateway.webui_url + '/', timeout=5) as response:
                    headers['X-Hermes-CSRF-Token'] = unescape(re.search(
                        r'<meta name="jaeger-csrf" content="([^"]*)">', response.read().decode()).group(1))
            prefix = '/v1' if path.startswith('/agents') else '/api/jaeger'
            with browser.open(Request(gateway.webui_url + prefix + path,
                    data=None if body is None else json.dumps(body).encode(), headers=headers), timeout=10) as response:
                return response.status, json.load(response)
        proxy('/agents')
        # Actual explicit UI new-chat selection is pinned by the create handler.
        proxy('/sessions', {'session_id': 'loss', 'source': 'webui', 'title': 'New chat', 'agent_id': 'native:jaeger'})
        proxy('/sessions', {'session_id': 'foreign', 'source': 'webui', 'title': 'Other chat'})
        session = proxy('/sessions/loss')[1]
        assert session['agent_id'] == 'native:jaeger' and session['role'] == 'lead'
        proxy('/sessions/loss/turns', {
            'text': 'Create and verify the CONTRACT-DURABLE report', 'request_id': 'lost-request',
        })
        approval = wait_until(lambda: proxy('/approvals')[1]['approvals'], gateway)[0]
        # Queue through normal admission while the real tool waits for approval.
        code, queued = proxy('/sessions/loss/queue', {
            'text': 'Say QUEUED-AFTER-RECOVERY', 'request_id': 'queued-request',
        })
        assert code == 202 and queued['queued']
        proxy('/approvals/' + approval['approval_id'], {'approved': True, 'decision': 'once'})
        marker = tmp_path / 'receipt-fault-ready.json'
        wait_until(marker.exists, gateway)
        assert json.loads(marker.read_text()) == {**gateway.receipt_fault, 'pid': gateway.process.pid}
        assert gateway.process.poll() is None
        assert gateway.identity is not None
        # Separate connection proves transaction visibility BEFORE SIGKILL.
        journal = sql(gateway, 'SELECT * FROM owner_request_journal WHERE request_id=?', ('lost-request',))[0]
        assert bool(journal['terminal_json']) == (phase == 'after_seal')
        authority = json.loads(json.loads(journal['identity_json'])['execution_json'])['_owner_agent']
        assert authority == {'id': 'native:jaeger', 'kind': 'jaeger_native', 'role': 'lead', 'disabled': False}
        if phase == 'after_seal':
            assert json.loads(journal['terminal_json'])['result']['task_state'] == 'completed_verified'
        assert not finishes(gateway)
        assert assistant_projection(gateway) == []
        assert queue_calls(gateway) == []
        assert sql(gateway, "SELECT status FROM client_requests WHERE request_id='queued-request'")[0]['status'] == 'queued'
        runs = json.loads(journal['native_runs_json'])
        assert runs
        before_calls = request_calls(gateway)
        before_native = native_evidence(gateway, runs)
        assert len(before_calls) == 6
        assert all(call['request_id'] == 'lost-request' for call in before_calls)
        assert any(rows for (_, table), rows in before_native.items() if table == 'effects')
        assert sum(len(rows) for (_, table), rows in before_native.items() if table == 'tool_calls') == 5
        target = tmp_path / 'instances/contract/workspace/durable-report.txt'
        assert target.read_text() == 'DURABLE-VERIFIED-CONTENT'
        before_file = (target.stat().st_mtime_ns, target.read_bytes())
        old_pid = gateway.process.pid
        gateway.stop()  # OwnedGateway.kill()+wait(); no signal to another PID.
        assert gateway.process.pid == old_pid and gateway.process.returncode is not None
        if drift:
            with sqlite3.connect(tmp_path / 'gateway_sessions.sqlite3') as conn:
                if drift == 'authority':
                    conn.execute("UPDATE client_requests SET digest='foreign-authority' WHERE request_id='lost-request'")
                else:
                    conn.execute("UPDATE client_requests SET session_id='foreign' WHERE request_id='lost-request'")
        gateway.receipt_fault = None
        gateway.start()
        expected = 'completed' if phase == 'after_seal' and drift is None else 'execution_unknown'
        row = sql(gateway, "SELECT * FROM client_requests WHERE request_id='lost-request'")[0]
        assert row['status'] == expected
        if expected == 'completed':
            assert len(finishes(gateway)) == 1
            assert finishes(gateway)[0]['event'] == 'turn.reconciled'
            assert json.loads(finishes(gateway)[0]['data_json'])['status'] == 'completed'
            assert gateway.wait_for_terminal('loss', 'queued-request')['status'] == 'completed'
        else:
            assert not finishes(gateway)
            assert sql(gateway, "SELECT status FROM client_requests WHERE request_id='queued-request'")[0]['status'] == 'queued'
        assert_restart_evidence(gateway, expected, before_calls, before_native, runs, target, before_file)
        projection = assistant_projection(gateway)
        gateway.stop()
        gateway.start()
        assert assistant_projection(gateway) == projection
        assert_restart_evidence(gateway, expected, before_calls, before_native, runs, target, before_file)
        assert sql(gateway, 'SELECT terminal_json FROM owner_request_journal WHERE request_id=?', ('lost-request',))[0]['terminal_json'] == journal['terminal_json']
    finally:
        gateway.stop()
