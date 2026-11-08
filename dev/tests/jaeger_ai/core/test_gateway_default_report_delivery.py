"""Owned HTTP default report journey; only the provider boundary is scripted."""
import base64
import hashlib
import json
import sqlite3
import time
from urllib.error import HTTPError
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway, auth

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_default_report_delivery_survives_restart_and_denies_scope_drift(tmp_path):
    gateway = OwnedGateway(tmp_path)
    sid = 'default-report-parent'
    content = b'DURABLE-VERIFIED-CONTENT'
    digest = hashlib.sha256(content).hexdigest()
    body = {'session_id': sid, 'goal': 'CONTRACT-DURABLE: produce and verify the report'}
    approved_ids = []
    try:
        gateway.start()
        identity = gateway.identity
        gateway.request('/v1/sessions', {'session_id': sid, 'profile': 'jaeger'})
        assert not gateway.request('/v1/sessions/' + sid)[1]['workspace']
        _, admitted = gateway.request('/v1/tasks', body)
        tid = admitted['task_id']
        assert admitted['status'] == 'queued'
        task = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            for approval in gateway.request('/v1/approvals')[1]['approvals']:
                # Fail before approval on any unrelated action or caller scope.
                assert not approved_ids, approval
                assert approval['kind'] == 'tool_confirm'
                assert approval['session_id'] == 'task:' + tid
                assert approval['request_id'] == tid + ':0'
                metadata = approval['metadata']
                assert metadata['tool'] == 'files.write_file'
                assert metadata['target'] == ('path="workspace/durable-report.txt"\n'
                                              'content="DURABLE-VERIFIED-CONTENT"')
                assert metadata['origin'] == {
                    'task_id': tid, 'child_session_id': 'task:' + tid,
                    'agent_id': 'native:jaeger', 'parent_session_id': sid}
                assert 'once' in approval['options']
                gateway.request('/v1/approvals/' + approval['approval_id'],
                                {'approved': True, 'decision': 'once'})
                approved_ids.append(approval['approval_id'])
            response = gateway.request('/v1/tasks/' + tid)[1]
            task = response.get('task', response)
            if task['state'] in {'completed_verified', 'failed', 'cancelled', 'needs_owner', 'blocked'}:
                break
            time.sleep(0.05)
        assert task and task['state'] == 'completed_verified', (task, (tmp_path / 'gateway.log').read_text()[-15000:])
        assert len(approved_ids) == 1
        assert gateway.request('/v1/approvals')[1]['approvals'] == []
        # A default task now freezes the effective root without converting
        # instance-path semantics into an explicitly selected project.
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        from jaeger_ai.core.runtime.execution_defaults import default_route_fingerprint, execution_project_root
        root = tmp_path / 'instances/contract/workspace'
        config = load_yaml(tmp_path / 'instances/contract/config.yaml', Config)
        execution = task['payload']['execution']
        assert task['payload']['background_admission_version'] == 1
        assert execution['workspace'] == str(root.resolve())
        assert execution['model'] == config.external_model.model == 'contract-model'
        assert execution['provider'] == config.external_model.provider == 'openai'
        assert execution['interaction_tier'] == config.automation.interaction_tier
        assert execution['_instance_defaults'] == {
            'workspace': str(root.resolve()), 'route_fingerprint': default_route_fingerprint(config)}
        assert execution_project_root(execution, SimpleNamespace(workspace_dir=root)) is None
        assert task['payload']['background_authority']['execution'] == execution
        assert not gateway.request('/v1/sessions/' + sid)[1]['workspace']
        assert task['payload'].get('attempt', 0) == 0
        receipt = gateway.request('/v1/requests/' + tid + ':0')[1]
        assert receipt['status'] == 'completed' and not receipt['result'].get('halt_reason')
        for key in ('workspace', 'model', 'provider', 'interaction_tier', '_instance_defaults'):
            assert receipt['execution'][key] == execution[key]
        assert task['payload']['background_admissions'][tid + ':0']['execution'] == receipt['execution']
        completion = receipt['result']['task_completion']
        assert completion['ok'] is True
        assert any(r.get('kind') == 'file_sha256' and r.get('sha256') == digest
                   for r in completion['verification_receipts'])
        def tool_events():
            # Read-only evidence only: never insert task/receipt/terminal state.
            with sqlite3.connect(f'file:{tmp_path / "gateway_sessions.sqlite3"}?mode=ro', uri=True) as conn:
                return [(name, json.loads(data)) for name, data in conn.execute(
                    "SELECT event, data_json FROM events WHERE event LIKE 'tool.%' ORDER BY rowid")]

        events = tool_events()
        assert all(data.get('request_id') == tid + ':0' and
                   data.get('session_id') == 'task:' + tid for _, data in events)
        assert len(events) == 10
        started = [data for name, data in events if name == 'tool.started']
        completed = [data for name, data in events if name == 'tool.completed']
        assert len(started) == len(completed) == 5
        assert [d['call_id'] for d in started] == [d['call_id'] for d in completed]
        assert len({d['call_id'] for d in started}) == 5
        assert all(d['success'] is True and d['ok'] is True for d in completed)
        assert not any(name == 'tool.failed' for name, _ in events)
        assert [data['tool'] for name, data in events if name == 'tool.completed'] == [
            'work_ledger', 'write_file', 'read_file', 'work_ledger', 'complete_task']
        assert (root / 'durable-report.txt').read_bytes() == content
        file_stat = (root / 'durable-report.txt').stat()
        verified = task['payload']['verification']
        assert any(r.get('kind') == 'owner_file_sha256' and r.get('sha256') == digest
                   and r.get('owner_artifact_scope', {}).get('workspace') == str(root)
                   for r in verified)
        catalog_url = '/v1/library/artifacts?task_id=' + tid
        first = gateway.request(catalog_url)[1]
        assert len(first['artifacts']) == 1, first
        ref = first['artifacts'][0]
        assert ref['readable'] and ref['sha256'] == digest and ref['session_id'] == sid
        assert 'safe_path' not in ref and str(root) not in json.dumps(first)
        url = '/v1/library/artifacts/' + tid + '/' + ref['attachment_id']

        def check_bytes():
            downloaded = gateway.request(url)[1]
            assert base64.b64decode(downloaded['data_base64']) == content
            assert downloaded['sha256'] == digest

        check_bytes()
        for endpoint in (catalog_url, url):
            for headers, code in [({}, 401), ({'Authorization': 'Bearer invalid-owned-test'}, 401),
                                  (auth('a2a'), 403)]:
                with pytest.raises(HTTPError) as denied:
                    urlopen(Request(gateway.url + endpoint, headers=headers), timeout=5)
                assert denied.value.code == code
        before = (tmp_path / 'provider-calls.jsonl').read_text()
        requests_before = (tmp_path / 'provider-requests.jsonl').read_text()
        assert len(before.splitlines()) == 6
        requests = [json.loads(line) for line in requests_before.splitlines()]
        assert len(requests) == 6 and all(r['request_id'] == tid + ':0' for r in requests)

        def assert_no_reexecution():
            assert (tmp_path / 'provider-calls.jsonl').read_text() == before
            assert (tmp_path / 'provider-requests.jsonl').read_text() == requests_before
            assert tool_events() == events
            after_stat = (root / 'durable-report.txt').stat()
            assert (after_stat.st_ino, after_stat.st_mtime_ns, after_stat.st_size) == (
                file_stat.st_ino, file_stat.st_mtime_ns, file_stat.st_size)
            assert gateway.request('/v1/approvals')[1]['approvals'] == []
            assert gateway.request('/v1/requests/' + tid + ':0')[1] == receipt
            assert gateway.request('/v1/tasks/' + tid)[1]['payload']['execution'] == execution

        assert_no_reexecution()
        gateway.stop()
        assert gateway.process.poll() is not None
        gateway.start()
        assert gateway.identity == identity
        assert gateway.request(catalog_url)[1] == first
        check_bytes()
        replay = gateway.request('/v1/tasks', body)[1]
        assert replay['replayed'] and replay['task_id'] == tid
        session = gateway.request('/v1/sessions/' + sid)[1]
        assert not session['workspace']
        assert len([m for m in session['messages'] if m['role'] == 'assistant']) == 1
        assert not gateway.request('/v1/sessions/' + sid + '/attachments')[1]['attachments']
        assert_no_reexecution()
        # Rebind only this stopped fixture's default root by moving its owned
        # directory intact. Same bytes, different resolved root: no new grant.
        gateway.stop()
        assert gateway.process.poll() is not None
        moved = root.with_name('retained-default-workspace')
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
        gateway.start()
        assert gateway.identity == identity
        drifted = gateway.request(catalog_url)[1]['artifacts']
        assert drifted == []  # Saved path no longer fits the rebound root.
        assert (root / 'durable-report.txt').read_bytes() == content
        with pytest.raises(HTTPError) as denied:
            gateway.request(url)
        assert denied.value.code == 404
        assert_no_reexecution()
    finally:
        gateway.stop()
        assert gateway.process is None or gateway.process.poll() is not None
