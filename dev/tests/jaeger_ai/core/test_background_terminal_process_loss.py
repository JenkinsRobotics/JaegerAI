"""Synthetic-provider HTTP work, real SIGKILL at background terminal boundary."""
import json
import sqlite3
import time

import pytest
from dev.tests.fixtures.owned_gateway import OwnedGateway
from dev.tests.jaeger_ai.core.test_owner_receipt_process_loss import native_evidence

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def sql(root, statement, args=()):
    with sqlite3.connect(root/'gateway_sessions.sqlite3') as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(statement, args)]



def checkpoint_snapshot(path, runs):
    with sqlite3.connect(path) as conn:
        slots = ','.join('?' for _ in runs)
        stable_runs = conn.execute('SELECT id,commitment_id,attempt,provider,payload_json,parent_run_id,root_run_id,relation,created_at '
            + 'FROM runs WHERE id IN ('+slots+') ORDER BY id', runs).fetchall()
        checkpoints = conn.execute('SELECT * FROM checkpoints WHERE run_id IN ('+slots+') ORDER BY run_id,seq', runs).fetchall()
        assert len(stable_runs) == len(runs)
        assert all(any(row[0] == native for row in checkpoints) for native in runs)
        return stable_runs, checkpoints


def wait(predicate, gateway, timeout=50):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        found = predicate()
        if found:
            return found
        time.sleep(.04)
    raise AssertionError((gateway.root/'gateway.log').read_text()[-18000:])


@pytest.mark.parametrize('phase,drift,research,rotate', [
    ('after_seal', None, False, False), ('before_seal', None, False, False),
    ('after_seal', 'cancel', False, False), ('after_seal', 'artifact', False, False),
    ('after_seal', 'goal', False, False), ('after_seal', None, True, False),
    ('native_settled', None, False, False),
    ('after_seal', None, False, True), ('native_settled', None, False, True),
])
def test_background_terminal_seal_survives_only_exact_proved_completion(tmp_path, phase, drift, research, rotate):
    gateway = OwnedGateway(tmp_path, research=research, receipt_fault={'background': True, 'phase': phase, 'rotate': rotate})
    try:
        gateway.start()
        gateway.request('/v1/sessions', {'session_id': 'seal-parent', 'profile': 'jaeger'})
        body = {'session_id': 'seal-parent', 'goal': 'CONTRACT-DURABLE: produce and verify report'}
        if research:
            from jaeger_ai.core.tasks.research import RESEARCH_CONTRACT
            body['goal'] = 'CONTRACT-RESEARCH: compare the supplied synthetic evidence and deliver a report'
            body['research_contract'] = dict(RESEARCH_CONTRACT)
        tid = gateway.request('/v1/tasks', body)[1]['task_id']
        rid, sid = tid+':0', 'task:'+tid
        marker = tmp_path/'receipt-fault-ready.json'
        approved = set()
        def approve_and_ready():
            if marker.exists(): return True
            try:
                approvals = gateway.request('/v1/approvals')[1]['approvals']
            except TimeoutError:
                if marker.exists(): return True  # Barrier blocks this child's event loop.
                raise
            for approval in approvals:
                if approval['approval_id'] in approved: continue
                assert approval['session_id'] == sid and approval['request_id'] == rid
                if approval['metadata']['tool'] == 'shell.run_shell' and research:
                    from dev.tests.fixtures.research_contract import terminal_command
                    call = json.loads((tmp_path/'research-provider-tools.jsonl').read_text().splitlines()[-1])
                    assert call == {'call_id': 'research-6', 'name': 'terminal', 'args': {
                        'command': terminal_command('research/'+tid), 'timeout_s': 60.0}}
                else:
                    assert approval['metadata']['tool'] == 'files.write_file'
                assert 'once' in approval['options']
                gateway.request('/v1/approvals/'+approval['approval_id'], {'approved': True, 'decision': 'once'})
                approved.add(approval['approval_id'])
        wait(approve_and_ready, gateway)
        assert json.loads(marker.read_text())['pid'] == gateway.process.pid
        assert json.loads(marker.read_text())['request_id'] == rid
        request = sql(tmp_path, 'SELECT * FROM client_requests WHERE request_id=?', (rid,))[0]
        assert request['status'] == 'running'
        assert sql(tmp_path, "SELECT * FROM messages WHERE session_id=? AND role='assistant'", (sid,)) == []
        before_calls = (tmp_path/'provider-requests.jsonl').read_bytes()
        before_events = sql(tmp_path, "SELECT * FROM events WHERE event LIKE 'tool.%'")
        assert len([e for e in before_events if e['event'] == 'tool.completed']) == (10 if research else 5)
        enrollment = sql(tmp_path, 'SELECT native_runs_json FROM background_native_enrollments WHERE request_id=?', (rid,))[0]
        runs = json.loads(enrollment['native_runs_json'])
        assert len(runs) == len(set(runs)) == (2 if rotate else 1)
        assert request['native_run_id'] == runs[-1]
        if rotate:
            assert json.loads((tmp_path/'rotation-returned.json').read_text())['native_run_id'] == runs[0]
        native_db = tmp_path/'instances/contract/memory/state.db'
        with sqlite3.connect(native_db) as conn:
            states = dict(conn.execute('SELECT id,state FROM runs'))
        if phase in {'after_seal', 'native_settled'}:
            assert all(states[native] == 'completed' for native in runs)
        else:
            assert states[runs[-1]] == 'active'

        before_native = native_evidence(gateway, runs)
        before_checkpoints = checkpoint_snapshot(native_db, runs)
        files = {str(path.relative_to(tmp_path)): (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in (tmp_path/'instances/contract/workspace').rglob('*') if path.is_file()}
        assert files
        journals = sql(tmp_path, "SELECT name FROM sqlite_master WHERE name='background_request_journal'")
        journal = sql(tmp_path, 'SELECT * FROM background_request_journal WHERE request_id=?', (rid,))[0] if journals else None
        if journal:
            assert bool(journal['terminal_json']) == (phase == 'after_seal')
        gateway.stop()
        if drift == 'cancel':
            # Model a persisted request cancellation racing just after the seal.
            from jaeger_ai.core.gateway.session_store import GatewaySessionStore
            GatewaySessionStore(tmp_path/'gateway_sessions.sqlite3').mark_request_status(rid, 'cancelling')
        elif drift == 'artifact':
            path = next(path for path in (tmp_path/'instances/contract/workspace').rglob('durable-report.txt'))
            path.write_text('SUBSTITUTED-AFTER-SEAL')
            files[str(path.relative_to(tmp_path))] = (path.read_bytes(), path.stat().st_mtime_ns)
        elif drift == 'goal':
            with sqlite3.connect(tmp_path/'gateway_sessions.sqlite3') as conn:
                task = json.loads(conn.execute('SELECT task_json FROM durable_tasks WHERE task_id=?', (tid,)).fetchone()[0])
                task['goal'] = 'Changed objective after seal'
                conn.execute('UPDATE durable_tasks SET task_json=? WHERE task_id=?', (json.dumps(task), tid))
        gateway.receipt_fault = None
        good = phase == 'after_seal' and drift is None
        for restart_number in range(2):
            gateway.start()
            row = gateway.request('/v1/requests/'+rid)[1]
            if row['status'] != ('completed' if good else 'execution_unknown'):
                (tmp_path/'recovery-debug.json').write_text(json.dumps({'row': row, 'journal': journal,
                    'task': gateway.request('/v1/tasks/'+tid)[1]}, indent=2))
            assert row['status'] == ('completed' if good else 'execution_unknown'), (row, journal)
            if good:
                task = wait(lambda: (t if (t := gateway.request('/v1/tasks/'+tid)[1])['state'] == 'completed_verified' else None), gateway)
                assert task['payload']['verification'] == json.loads(journal['terminal_json'])['verification']
                assert row['result'] == json.loads(journal['terminal_json'])['result']
                assert len(gateway.request('/v1/library/artifacts?task_id='+tid)[1]['artifacts']) == (2 if research else 1)
            else:
                task = gateway.request('/v1/tasks/'+tid)[1]
                assert task['state'] != 'completed_verified'
                if drift == 'goal': assert task['goal'] == 'Changed objective after seal'
            # Two scheduler opportunities after restart, not just a startup snapshot.
            time.sleep(2.2)
            assert (tmp_path/'provider-requests.jsonl').read_bytes() == before_calls
            assert sql(tmp_path, "SELECT * FROM events WHERE event LIKE 'tool.%'") == before_events
            assert native_evidence(gateway, runs) == before_native
            assert checkpoint_snapshot(native_db, runs) == before_checkpoints
            if phase in {'after_seal', 'native_settled'}:
                with sqlite3.connect(native_db) as conn:
                    terminal_roots = {row[0]: (row[1], row[2]) for row in conn.execute('SELECT id,state,owner_pid FROM runs')}
                assert all(terminal_roots[native] == ('completed', None) for native in runs)
            assert all((tmp_path/name).read_bytes() == content and (tmp_path/name).stat().st_mtime_ns == stamp
                       for name, (content, stamp) in files.items())
            terminal = sql(tmp_path, "SELECT * FROM events WHERE session_id=? AND event IN ('turn.finish','turn.reconciled')", (sid,))
            assert len(terminal) == int(good)
            assert len(sql(tmp_path, "SELECT * FROM messages WHERE session_id=? AND role='assistant'", (sid,))) == int(good)
            assert len(sql(tmp_path, "SELECT * FROM messages WHERE session_id='seal-parent' AND role='assistant'")) == int(good)
            if journal:
                saved = sql(tmp_path, 'SELECT terminal_json FROM background_request_journal WHERE request_id=?', (rid,))[0]
                assert saved['terminal_json'] == journal['terminal_json']
            gateway.stop()
    finally:
        gateway.stop()


def test_research_normal_projection_uses_the_same_sealed_report_bytes(tmp_path):
    from jaeger_ai.core.tasks.research import RESEARCH_CONTRACT
    from dev.tests.fixtures.research_contract import terminal_command
    gateway = OwnedGateway(tmp_path, research=True)
    try:
        gateway.start()
        gateway.request('/v1/sessions', {'session_id': 'research-normal', 'profile': 'jaeger'})
        tid = gateway.request('/v1/tasks', {'session_id': 'research-normal',
            'goal': 'CONTRACT-RESEARCH: compare the supplied synthetic evidence and deliver a report',
            'research_contract': dict(RESEARCH_CONTRACT)})[1]['task_id']
        rid, sid = tid+':0', 'task:'+tid
        approved = set()
        def completed():
            for approval in gateway.request('/v1/approvals')[1]['approvals']:
                if approval['approval_id'] in approved: continue
                assert approval['session_id'] == sid and approval['request_id'] == rid
                tool = approval['metadata']['tool']
                if tool == 'shell.run_shell':
                    call = json.loads((tmp_path/'research-provider-tools.jsonl').read_text().splitlines()[-1])
                    assert call['args']['command'] == terminal_command('research/'+tid)
                else:
                    assert tool == 'files.write_file'
                gateway.request('/v1/approvals/'+approval['approval_id'], {'approved': True, 'decision': 'once'})
                approved.add(approval['approval_id'])
            task = gateway.request('/v1/tasks/'+tid)[1]
            return task if task['state'] == 'completed_verified' else None
        task = wait(completed, gateway)
        row = gateway.request('/v1/requests/'+rid)[1]
        journal = sql(tmp_path, 'SELECT * FROM background_request_journal WHERE request_id=?', (rid,))[0]
        proof = json.loads(journal['terminal_json'])
        report = (tmp_path/'instances/contract/workspace/research'/tid/'research-report.md').read_text()
        assert row['result'] == proof['result']
        assert row['result']['output'] == proof['assistant_text'] == report
        assert task['payload']['verification'] == proof['verification']
        messages = sql(tmp_path, "SELECT * FROM messages WHERE session_id=? AND role='assistant'", (sid,))
        assert len(messages) == 1 and messages[0]['content'] == report
        assert len(sql(tmp_path, "SELECT * FROM events WHERE session_id=? AND event='turn.finish'", (sid,))) == 1
    finally:
        gateway.stop()
