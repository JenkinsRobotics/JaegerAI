"""Interrupted explicit Research retains evidence, never silently replays.

Real owned Gateway SIGKILL after native tool receipts, before completion.
Synthetic provider/retrieval only. Recovery is intentionally owner-mediated.
"""
import hashlib
import json
import sqlite3
import time

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway
from dev.tests.fixtures.research_contract import terminal_command
from jaeger_ai.core.tasks.research import RESEARCH_CONTRACT, artifact_paths

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def events(root):
    with sqlite3.connect(f'file:{root / "gateway_sessions.sqlite3"}?mode=ro', uri=True) as db:
        return [(e, json.loads(d)) for e, d in db.execute(
            "SELECT event,data_json FROM events WHERE event LIKE 'tool.%' ORDER BY rowid")]


def durable_admissions(root):
    with sqlite3.connect(f'file:{root / "gateway_sessions.sqlite3"}?mode=ro', uri=True) as db:
        return {
            'approvals': db.execute('SELECT * FROM approvals ORDER BY approval_id').fetchall(),
            'requests': db.execute('SELECT request_id,session_id FROM client_requests ORDER BY request_id').fetchall(),
        }


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('after_tools', [4, 8], ids=['retrieval-file', 'report-readback'])
def test_interrupted_explicit_research_preserves_contract_without_replay(tmp_path, after_tools):
    gateway = OwnedGateway(tmp_path, research=True)
    (tmp_path / 'research-cut.json').write_text(json.dumps({'after_tools': after_tools}))
    sid = 'interrupted-research-parent'
    body = {'session_id': sid, 'goal': 'Deep research: CONTRACT-RESEARCH synthetic observations',
            'request_id': 'interrupted-research-once', 'proposal': True,
            'research_contract': dict(RESEARCH_CONTRACT)}
    approved = []
    try:
        gateway.start()
        gateway.request('/v1/sessions', {'session_id': sid, 'profile': 'jaeger'})
        tid = gateway.request('/v1/tasks', body, caller='webui')[1]['task_id']
        proposed = gateway.request('/v1/tasks/' + tid)[1]
        gateway.request('/v1/tasks/' + tid + '/approve',
                        {'expected_updated_at': proposed['updated_at']}, caller='webui')
        deadline = time.monotonic() + 90
        ready = tmp_path / 'research-cut-ready.json'
        while not ready.exists() and time.monotonic() < deadline:
            for approval in gateway.request('/v1/approvals')[1]['approvals']:
                assert approval['session_id'] == 'task:' + tid
                assert approval['request_id'] == tid + ':0'
                call = json.loads((tmp_path / 'research-provider-tools.jsonl').read_text().splitlines()[-1])
                pairs = [line.split('=', 1) for line in approval['metadata']['target'].splitlines()]
                shown = {key: json.loads(value) for key, value in pairs}
                assert len(shown) == len(pairs) and shown == call['args']
                if approval['metadata']['tool'] == 'files.write_file':
                    expected = {'research-3': 'retrieval.json', 'research-4': 'page.txt',
                                'research-5': 'research-report.md'}
                    assert call['name'] == 'write_file'
                    assert shown['path'] == 'workspace/research/' + tid + '/' + expected[call['call_id']]
                    assert set(shown) == {'path', 'content'}
                else:
                    assert approval['metadata']['tool'] == 'shell.run_shell'
                    assert call == {'call_id': 'research-6', 'name': 'terminal', 'args': {
                        'command': terminal_command('research/' + tid), 'timeout_s': 60.0}}
                gateway.request('/v1/approvals/' + approval['approval_id'], {'approved': True, 'decision': 'once'})
                approved.append(approval)
            time.sleep(.05)
        assert ready.exists(), (tmp_path / 'gateway.log').read_text()[-10000:]
        boundary = json.loads(ready.read_text())
        assert boundary == {'pid': gateway.process.pid, 'after_tools': after_tools,
                            'directory': 'research/' + tid,
                            'tool_call_ids': ['research-' + str(i) for i in range(after_tools)]}
        before_task = gateway.request('/v1/tasks/' + tid)[1]
        assert before_task['state'] not in {'completed_verified', 'completed', 'failed', 'cancelled'}
        before_receipt = gateway.request('/v1/sessions/task:' + tid + '/requests/' + tid + ':0')[1]
        assert before_receipt['status'] in {'running', 'admitted'}
        assert before_task['payload']['research_contract'] == RESEARCH_CONTRACT
        assert before_task['payload']['research_artifacts'] == artifact_paths(tid)
        admissions = durable_admissions(tmp_path)
        assert admissions['requests'] == [(tid + ':0', 'task:' + tid)]
        before_events = events(tmp_path)
        completed = [d for e, d in before_events if e == 'tool.completed']
        assert len(completed) == after_tools and all(d['success'] for d in completed)
        assert all(d['request_id'] == tid + ':0' for _, d in before_events)
        assert not any(d['tool'] == 'complete_task' for d in completed)
        assert len(approved) == (1 if after_tools == 4 else 4)
        evidence_root = tmp_path / 'instances/contract/workspace/research' / tid
        files = snapshot(evidence_root)
        assert 'retrieval.json' in files
        assert ('sources.json' in files) == (after_tools == 8)
        calls = (tmp_path / 'provider-calls.jsonl').read_bytes()
        issued = (tmp_path / 'research-provider-tools.jsonl').read_bytes()
        # SIGKILL only the process started by this fixture. No graceful shutdown.
        gateway.stop()
        assert gateway.process.returncode == -9
        for restart in range(2):
            gateway.start()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                task = gateway.request('/v1/tasks/' + tid)[1]
                if task['state'] == 'paused':
                    break
                time.sleep(.05)
            (tmp_path / f'recovery-{restart}.json').write_text(json.dumps(task, indent=2))
            assert task['state'] == 'paused', task
            assert 'reconcile effects before retry' in task['error']
            assert task['payload']['next_action']
            assert task['payload']['research_contract'] == RESEARCH_CONTRACT
            assert task['payload']['research_artifacts'] == artifact_paths(tid)
            assert task['payload'].get('attempt', 0) == 0
            assert task['retry_policy']['current_retries'] == 0
            assert len(task['run_history']) == 1
            assert task['run_history'][0]['run_id'] == tid + ':0'
            receipt = gateway.request('/v1/sessions/task:' + tid + '/requests/' + tid + ':0')[1]
            assert receipt['status'] == 'execution_unknown'
            assert receipt['request_id'] == tid + ':0'
            parent = gateway.request('/v1/sessions/' + sid)[1]
            assert parent.get('session', parent)['messages'] == []
            assert gateway.request('/v1/tasks', body, caller='webui')[1]['replayed']
            # Bounded observation window spans three nominal one-second owner polls;
            # this is not a claim of indefinite nonreplay.
            time.sleep(3)
            assert (tmp_path / 'provider-calls.jsonl').read_bytes() == calls
            assert (tmp_path / 'research-provider-tools.jsonl').read_bytes() == issued
            assert snapshot(evidence_root) == files
            assert events(tmp_path) == before_events
            assert durable_admissions(tmp_path) == admissions
            assert gateway.request('/v1/approvals')[1]['approvals'] == []
            gateway.stop()
    finally:
        gateway.stop()
