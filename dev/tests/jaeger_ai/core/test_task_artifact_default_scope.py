"""Owner-bound default artifact scope. No provider, daemon, or external effects."""
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.attachment_access import read as read_bytes
from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.artifacts import catalog, read
from jaeger_ai.core.tasks.completion import authoritative_transition
from jaeger_ai.core.tasks.models import TaskState
from jaeger_ai.core.tasks.owner import GatewayTaskOwner
from jaeger_ai.core.tasks.store import SqliteDurableTaskStore


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    store = GatewaySessionStore(tmp_path / 'gateway.sqlite3')
    store.ensure_session('default-origin', workspace='')
    gateway = SimpleNamespace(store=store, event_bus=GatewayEventBus(store=store), UPLOAD_MAX_BYTES=1048576)
    owner = GatewayTaskOwner(gateway)
    gateway.task_owner = owner
    monkeypatch.setattr('jaeger_agent.core.workspace.get_effective_workspace_dir', lambda: workspace)

    async def response(request, row, session):
        from aiohttp import web
        try:
            value = read_bytes(row, staged_root=tmp_path/'unused-upload-root',
                               workspace=session['workspace'], limit=gateway.UPLOAD_MAX_BYTES)
        except (OSError, ValueError):
            return web.json_response({'error': 'Bytes withheld'}, status=409)
        return web.json_response(value)
    gateway._session_file_response = response

    def make(*, pinned=False, explicit=False, receipt_extra=None, kind='file_sha256', named=False):
        execution = {'workspace': str(workspace) if pinned or explicit else ''}
        if pinned:
            # Internal, canonical admission metadata. HTTP cannot supply this key.
            execution['_instance_defaults'] = {'workspace': str(workspace)}
        if explicit:
            with store._immediate() as conn:
                conn.execute('UPDATE sessions SET workspace=? WHERE session_id=?', (str(workspace), 'default-origin'))
        goal = 'Write report.md' if named else 'Deep research: Produce a sourced Markdown report'
        admitted = owner.submit(goal, context={'session_id': 'default-origin', 'source': 'client',
            'execution': execution, 'request_id': 'research-proposal', 'client_submission_id': 'research-proposal'}, proposal=True)
        task = owner.store.get_task(admitted['task_id'])
        report = workspace/'report.md'
        report.write_text('# Report\nSource: local deterministic fixture.\n')
        completion = {'task_completion': {'ok': True, 'verification_receipts': [
            {'kind': kind, 'path': 'report.md', 'sha256': hashlib.sha256(report.read_bytes()).hexdigest(), **(receipt_extra or {})}]}}
        verified, evidence = owner.verify(task, {} if named else completion)
        assert verified
        owner.store.update_task(task.task_id, lambda current: authoritative_transition(current, TaskState.COMPLETED_VERIFIED, evidence=evidence))
        return task.task_id, report, evidence
    return gateway, make, workspace


def request_for(row):
    return SimpleNamespace(match_info={'task_id': row['task_id'], 'artifact_id': row['attachment_id']}, query={})


@pytest.mark.parametrize('mode', ['research-default', 'foreground-pinned-default', 'named-default'])
@pytest.mark.asyncio
async def test_verified_default_report_reopens_after_store_recovery(artifact, mode):
    gateway, make, workspace = artifact
    task_id, report, evidence = make(pinned=mode=='foreground-pinned-default', named=mode=='named-default')
    rows = catalog(gateway, task_id=task_id)
    assert len(rows) == 1, 'Verified report is silently absent from the artifact catalog'
    assert rows[0]['readable'], rows[0]['unavailable_reason']
    assert str(workspace) not in json.dumps(rows)
    assert evidence[0]['kind'] == 'owner_file_sha256'
    assert evidence[0]['owner_artifact_scope']['workspace'] == str(workspace)
    gateway.task_owner.store = SqliteDurableTaskStore(gateway.store.path)
    assert catalog(gateway, task_id=task_id) == rows
    response = await read(gateway, request_for(rows[0]))
    assert response.status == 200
    assert base64.b64decode(json.loads(response.text)['data_base64']) == report.read_bytes()
    assert gateway.store.get_session('default-origin')['workspace'] == ''
    assert gateway.store.list_attachments('default-origin') == []


@pytest.mark.parametrize('change', ['default-root', 'explicit-project', 'deleted-session', 'missing-runtime', 'symlink', 'changed-bytes'])
@pytest.mark.asyncio
async def test_saved_default_artifact_never_expands_current_scope(artifact, tmp_path, monkeypatch, change):
    gateway, make, workspace = artifact
    task_id, report, _ = make()
    original = catalog(gateway, task_id=task_id)[0]
    other = tmp_path/'other'
    other.mkdir()
    (other/'report.md').write_bytes(report.read_bytes())
    if change == 'default-root':
        monkeypatch.setattr('jaeger_agent.core.workspace.get_effective_workspace_dir', lambda: other)
    elif change == 'explicit-project':
        with gateway.store._immediate() as conn:
            conn.execute('UPDATE sessions SET workspace=? WHERE session_id=?', (str(workspace), 'default-origin'))
    elif change == 'deleted-session':
        monkeypatch.setattr(gateway.store, 'get_session', lambda _: None)
    elif change == 'missing-runtime':
        def missing(): raise RuntimeError('No instance bound')
        monkeypatch.setattr('jaeger_agent.core.workspace.get_effective_workspace_dir', missing)
    elif change == 'symlink':
        report.unlink()
        report.symlink_to(other/'report.md')
    else:
        report.write_bytes(b'changed')
    current = catalog(gateway, task_id=task_id)[0]
    assert current['attachment_id'] == original['attachment_id']
    if change != 'changed-bytes':
        assert not current['readable']
    assert (await read(gateway, request_for(original))).status == 409


def test_worker_scope_is_discarded_and_owner_scope_is_reissued(artifact, tmp_path):
    gateway, make, workspace = artifact
    _, _, evidence = make(receipt_extra={'owner_artifact_scope': {'version': 1, 'mode': 'instance', 'workspace': str(tmp_path)}})
    assert evidence[0]['owner_artifact_scope']['workspace'] == str(workspace)
    assert evidence[0]['path'] == str(workspace/'report.md')


def test_legacy_worker_scope_cannot_grant_default_access(artifact):
    gateway, make, workspace = artifact
    task_id, _, evidence = make()
    # Old worker receipts could preserve arbitrary keys. Their kind is not an
    # owner-reissued receipt, so a fabricated scope cannot create a file grant.
    evidence[0]['kind'] = 'file_sha256'
    gateway.task_owner.store.update_task(task_id, lambda task: task.payload.update(verification=evidence))
    assert catalog(gateway, task_id=task_id) == []


@pytest.mark.asyncio
async def test_explicit_project_receipts_retain_existing_access_rules(artifact):
    gateway, make, _ = artifact
    task_id, _, evidence = make(explicit=True)
    assert 'owner_artifact_scope' not in evidence[0]
    row = catalog(gateway, task_id=task_id)[0]
    assert row['readable']
    assert (await read(gateway, request_for(row))).status == 200
    with gateway.store._immediate() as conn:
        conn.execute('UPDATE sessions SET workspace=? WHERE session_id=?', ('', 'default-origin'))
    assert (await read(gateway, request_for(row))).status == 409


@pytest.mark.parametrize('status,halt,kind,expected', [
    ('completed', '', 'owner_file_sha256', TaskState.FAILED),
    ('failed', '', 'file_sha256', TaskState.FAILED),
    ('cancelled', '', 'file_sha256', TaskState.CANCELLED),
    ('completed', 'yielded', 'file_sha256', TaskState.FAILED),
    ('completed', 'blocked', 'file_sha256', TaskState.BLOCKED),
    ('completed', 'needs_owner', 'file_sha256', TaskState.NEEDS_OWNER),
    ('execution_unknown', '', 'file_sha256', TaskState.PAUSED),
])
def test_untrusted_worker_receipts_and_nonclean_outcomes_cannot_publish_artifacts(artifact, status, halt, kind, expected):
    gateway, _, workspace = artifact
    owner = gateway.task_owner
    owner.admit_turn_card({'task_id': 'worker-claim', 'session_id': 'default-origin',
        'goal': 'Research a topic'}, execution={'workspace': ''})
    report = workspace/'result.md'
    report.write_text('Partial or forged worker result')
    forged = {'kind': kind, 'path': str(report), 'sha256': hashlib.sha256(report.read_bytes()).hexdigest(),
              'owner_artifact_scope': {'version': 1, 'mode': 'instance', 'workspace': str(workspace)}}
    task, receipt = owner.close_turn('worker-claim', {'text': 'done', 'halt_reason': halt,
        'task_completion': {'ok': True, 'verification_receipts': [forged]},
        'verification': [forged], 'state': 'completed_verified'}, status=status)
    assert task.state == expected
    assert receipt.verification == 'unverified'
    assert catalog(gateway, task_id=task.task_id) == []


@pytest.mark.asyncio
async def test_task_create_and_edit_cannot_install_worker_verification(artifact):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    gateway, _, workspace = artifact
    gateway._current_tier = lambda: 'work'
    gateway._task_board_fields = lambda body: {}
    gateway._session_agent_id = lambda parent: ''
    forged = [{'kind': 'owner_file_sha256', 'path': str(workspace/'fake.md'), 'sha256': 'a'*64,
               'owner_artifact_scope': {'version': 1, 'mode': 'instance', 'workspace': str(workspace)}}]
    body = {'session_id': 'default-origin', 'goal': 'Research a topic', 'proposal': True,
            'request_id': 'forged-api', 'state': 'completed_verified', 'verification': forged,
            'payload': {'verification': forged}}
    class Request(dict):
        method = 'POST'
        async def json(self): return body
    request = Request()
    response = await JaegerGatewayApp.handle_tasks(gateway, request)
    assert response.status == 201
    task_id = json.loads(response.text)['task_id']
    task = gateway.task_owner.store.get_task(task_id)
    assert task.state == TaskState.PAUSED and not task.payload.get('verification')
    body.update(goal='Revised topic', expected_updated_at=task.updated_at)
    request.match_info = {'id': task_id}
    assert (await JaegerGatewayApp.handle_task_edit(gateway, request)).status == 200
    task = gateway.task_owner.store.get_task(task_id)
    assert task.state == TaskState.PAUSED and not task.payload.get('verification')
    assert catalog(gateway, task_id=task_id) == []
    body['execution'] = {'_instance_defaults': {'workspace': str(workspace)}}
    assert (await JaegerGatewayApp.handle_tasks(gateway, request)).status == 400


@pytest.mark.parametrize('change', ['digest', 'scope', 'outside-path'])
@pytest.mark.asyncio
async def test_inconsistent_saved_owner_receipt_does_not_release_bytes(artifact, tmp_path, change):
    gateway, make, _ = artifact
    task_id, _, evidence = make()
    original = catalog(gateway, task_id=task_id)[0]
    if change == 'digest': evidence[0]['sha256'] = '0'*64
    elif change == 'scope': evidence[0]['owner_artifact_scope']['workspace'] = str(tmp_path/'foreign')
    else: evidence[0]['path'] = str(tmp_path/'foreign'/'result.md')
    gateway.task_owner.store.update_task(task_id, lambda task: task.payload.update(verification=evidence))
    # The old identity cannot redirect; inconsistent replacements are absent or
    # fail byte hashing. Direct arbitrary database rewrite is not an auth API.
    assert (await read(gateway, request_for(original))).status in (404, 409)
    for row in catalog(gateway, task_id=task_id):
        assert (await read(gateway, request_for(row))).status in (404, 409)


@pytest.mark.parametrize('named', [False, True])
def test_receipt_uses_the_same_root_and_path_that_were_checked(tmp_path, monkeypatch, named):
    first, later = tmp_path/'first', tmp_path/'later'
    first.mkdir()
    later.mkdir()
    data = b'Only the first root contains this checked report'
    (first/'report.md').write_bytes(data)
    roots = iter([first, later])
    monkeypatch.setattr('jaeger_agent.core.workspace.get_effective_workspace_dir', lambda: next(roots))
    task = SimpleNamespace(payload={'execution': {'workspace': ''}}, created_at=0,
                           goal='Write report.md' if named else 'Research a topic')
    result = {} if named else {'task_completion': {'ok': True, 'verification_receipts': [
        {'kind': 'file_sha256', 'path': 'report.md', 'sha256': hashlib.sha256(data).hexdigest()}]}}
    verified, evidence = GatewayTaskOwner.verify(task, result)
    assert verified
    assert evidence[0]['path'] == str(first/'report.md')
    assert evidence[0]['owner_artifact_scope']['workspace'] == str(first)
    assert next(roots) == later  # only one scope capture, no post-check resolution


def test_receipt_does_not_reresolve_worker_symlink_after_hashing(tmp_path, monkeypatch):
    from pathlib import Path
    first, later, alias = tmp_path/'checked.md', tmp_path/'unchecked.md', tmp_path/'report.md'
    data = b'Checked target'
    first.write_bytes(data)
    later.write_bytes(b'Different unchecked target')
    alias.symlink_to(first)
    original = Path.read_bytes
    def swap_after_read(path):
        contents = original(path)
        if path == first:
            alias.unlink()
            alias.symlink_to(later)
        return contents
    monkeypatch.setattr(Path, 'read_bytes', swap_after_read)
    monkeypatch.setattr('jaeger_agent.core.workspace.get_effective_workspace_dir', lambda: tmp_path)
    task = SimpleNamespace(payload={'execution': {'workspace': ''}}, created_at=0, goal='Research')
    verified, evidence = GatewayTaskOwner.verify(task, {'task_completion': {'ok': True, 'verification_receipts': [
        {'kind': 'file_sha256', 'path': 'report.md', 'sha256': hashlib.sha256(data).hexdigest()}]}})
    assert verified
    assert alias.resolve() == later
    assert evidence[0]['path'] == str(first)
    assert evidence[0]['sha256'] == hashlib.sha256(data).hexdigest()
