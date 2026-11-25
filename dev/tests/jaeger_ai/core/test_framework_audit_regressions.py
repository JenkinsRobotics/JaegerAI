"""Independent regressions from the November hard-task audit.

Provider doubles verify transport/path contracts, not generation quality.
"""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_agent import tools
from jaeger_agent.core.workspace import project_scope
from jaeger_ai.core.instance.instance import InstanceLayout


@pytest.fixture
def layout(tmp_path):
    value = InstanceLayout(root=tmp_path / 'instance')
    value.ensure_dirs()
    tools.bind(value)
    with project_scope(None):
        yield value


def test_image_generation_delivers_to_admitted_absolute_path(layout, tmp_path, monkeypatch):
    from PIL import Image
    from jaeger_agent.tools import vision
    source = tmp_path / 'source.png'
    Image.new('RGB', (24, 24), 'red').save(source)
    monkeypatch.setattr(vision, '_run_grok_imagine', lambda *a, **k: {
        'generated': True, 'source_file': str(source), 'backend': 'grok',
        'model_id': 'test', 'elapsed_s': 0.1})
    project = tmp_path / 'project'
    project.mkdir()
    with project_scope(project):
        target = project / 'out' / 'image.png'
        result = vision.generate_image('red square', out_path=str(target), backend='grok')
        assert result['generated'] and Path(result['absolute_path']) == target
        assert target.read_bytes() == source.read_bytes()
        denied = vision.generate_image('red square', out_path=str(tmp_path / 'escape.png'))
        assert not denied['generated']
        assert not (tmp_path / 'escape.png').exists()


@pytest.mark.parametrize('status,category', [(402, 'provider_billing_required'), (401, 'provider_authentication'), (500, 'provider_error')])
def test_grok_process_failure_is_not_hidden_by_log_files(layout, tmp_path, monkeypatch, status, category):
    from jaeger_agent.tools import vision
    monkeypatch.setattr(vision, '_grok_cli_path', lambda: Path('/fake/grok'))
    monkeypatch.setattr(vision, '_grok_oauth_available', lambda: True)
    monkeypatch.setattr(vision, '_grok_child_env', lambda: {})
    monkeypatch.setattr(vision.tempfile, 'mkdtemp', lambda **k: str(tmp_path))
    def launch(*a, **k):
        k['stderr'].write(f'API error status {status}; private-token-never-return'.encode())
        return SimpleNamespace(wait=lambda **k: 1, returncode=1)
    monkeypatch.setattr(vision.subprocess, 'Popen', launch)
    result = vision.generate_image('test', backend='grok')
    assert not result['generated'] and result['error_type'] == category
    assert 'private-token' not in str(result)


@pytest.mark.parametrize('override,expected', [('', 8192), ('4096', 4096), ('invalid', 8192)])
def test_local_vision_has_bounded_context(monkeypatch, override, expected):
    from jaeger_ai.core.models import local_vision
    monkeypatch.setenv('JAEGER_VISION_CTX', override)
    monkeypatch.setattr(local_vision, '_ollama_base', lambda: 'http://vision.invalid')
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"message":{"content":"red square"}}'
    def open_request(req, **kwargs):
        requests.append(json.loads(req.data))
        return Response()
    monkeypatch.setattr(local_vision.urllib.request, 'urlopen', open_request)
    assert local_vision.describe(b'image', model='test')['ok']
    assert requests[0]['options']['num_ctx'] == expected


def test_web_fetch_retains_superseded_claims(monkeypatch):
    import requests
    from jaeger_agent.tools import web
    body = b'<html><p><s>Large transactions do not work.</s></p><p>Since version 3.11 they do.</p></html>'
    response = SimpleNamespace(raise_for_status=lambda: None,
        iter_content=lambda **k: [body], headers={'Content-Type': 'text/html'},
        encoding='utf-8', close=lambda: None)
    monkeypatch.setattr(requests, 'get', lambda *a, **k: response)
    monkeypatch.setattr(web, '_ollama_web_fetch', lambda *a: pytest.fail('must preserve origin formatting'))
    result = web.web_fetch('https://example.test/docs')
    assert result['ok']
    assert '[DELETED/SUPERSEDED: Large transactions do not work. ]' in result['text']
    assert 'Since version 3.11 they do.' in result['text']


def test_web_fetch_hosted_fallback_discloses_formatting_loss(monkeypatch):
    import requests
    from jaeger_agent.tools import web
    def fail(*a, **k): raise requests.ConnectionError('blocked')
    monkeypatch.setattr(requests, 'get', fail)
    monkeypatch.setattr(web, '_ollama_web_fetch', lambda *a: {'ok': True, 'text': 'extracted'})
    result = web.web_fetch('https://example.test/docs')
    assert result['ok'] and 'strike-through' in result['formatting_notice']


def test_broken_venv_is_repaired_without_losing_packages(tmp_path):
    from jaeger_agent.util.venv import ensure_venv, venv_exists, venv_python
    layout = SimpleNamespace(root=tmp_path)
    vdir = tmp_path / 'venv'
    (vdir / 'bin').mkdir(parents=True)
    broken = vdir / 'bin' / 'python'
    broken.write_text('#!/bin/sh\nexit 127\n')
    broken.chmod(0o755)
    # Suppress pip bootstrap in this interpreter-repair test.
    (vdir / 'bin' / 'pip').write_text('preserved')
    (vdir / 'pyvenv.cfg').write_text(f'version = {sys.version_info.major}.{sys.version_info.minor}.0\n')
    marker = vdir / 'lib' / 'installed-package-marker'
    marker.parent.mkdir()
    marker.write_text('retain this package')
    assert not venv_exists(layout)
    ensure_venv(layout)
    assert venv_exists(layout) and venv_python(layout).is_symlink()
    assert marker.read_text() == 'retain this package'
    assert list(vdir.glob('interpreter-backup-*/python'))
    result = subprocess.run([str(venv_python(layout)), '-B', '-c', 'print(6*7)'], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == '42'


def test_venv_minor_upgrade_requires_explicit_migration(tmp_path):
    from jaeger_agent.util.venv import ensure_venv
    vdir = tmp_path / 'venv'
    vdir.mkdir()
    (vdir / 'pyvenv.cfg').write_text('version = 2.7.0\n')
    with pytest.raises(RuntimeError, match='migrate'):
        ensure_venv(SimpleNamespace(root=tmp_path))
    assert (vdir / 'pyvenv.cfg').read_text() == 'version = 2.7.0\n'


def test_oneshot_cli_forwards_before_broken_manifest(tmp_path, monkeypatch):
    from jaeger_ai import main
    import jaeger_ai.contract.legacy_paths as legacy
    root = tmp_path / 'truth'
    root.mkdir()
    (root / 'manifest.json').write_text('{"bound_character":"truth"}')
    monkeypatch.setattr(sys, 'argv', ['jaeger', 'Reply exactly READY'])
    monkeypatch.setattr(legacy, 'legacy_paths_enabled', lambda: False)
    monkeypatch.setattr(main, 'resolve_instance_dir', lambda *a: root)
    seen = []
    monkeypatch.setattr(main, '_forward_oneshot_to_gateway', lambda text, **k: seen.append(text) or 0)
    assert main._main_dispatch() == 0
    assert seen == ['Reply exactly READY']
    assert json.loads((root / 'manifest.json').read_text()) == {'bound_character': 'truth'}


def test_encoded_preview_is_not_classified_as_private_text():
    from jaeger_ai.core.models.request_policy import payload_text, withhold_private_tool_results
    result = {'ok': True, 'preview_base64': '/9j/SSNAAA==',
              'description': 'Three red circles.'}
    text = payload_text(json.dumps(result))
    assert 'Three red circles.' in text and 'SSNAAA' not in text
    message = {'role': 'tool', 'content': json.dumps(result)}
    _, count = withhold_private_tool_results([message])
    assert count == 0
    # Wording is not authority; the producer's structured provenance is.
    result['description'] = '-----BEGIN PRIVATE KEY----- secret -----END PRIVATE KEY-----'
    _, count = withhold_private_tool_results([{'role': 'tool', 'content': json.dumps(result)}])
    assert count == 0
    result['_meta'] = {'local_only': True}
    _, count = withhold_private_tool_results([{'role': 'tool', 'content': result}])
    assert count == 1


def _xlsx(path, cell_type='', value='MISSING'):
    import zipfile
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('_rels/.rels', '<Relationships/>')
        z.writestr('xl/workbook.xml', '<workbook/>')
        z.writestr('xl/worksheets/sheet1.xml',
                   '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   f'<sheetData><row><c r="A1" {cell_type}><f>IFERROR(1,\"MISSING\")</f><v>{value}</v></c></row></sheetData></worksheet>')


def test_office_validator_rejects_wrong_cached_cell_type_and_broken_packages(tmp_path):
    from jaeger_ai.core.entity.verification import artifact_format_error
    path = tmp_path / 'report.xlsx'
    _xlsx(path)
    assert 'nonnumeric cached value' in artifact_format_error(path)
    _xlsx(path, 't="str"')
    assert artifact_format_error(path) is None
    _xlsx(path, value='12.5')
    assert artifact_format_error(path) is None
    path.write_bytes(b'not an Office file')
    assert 'Invalid Office package' in artifact_format_error(path)


def test_owner_rejects_malformed_office_despite_correct_hash(tmp_path):
    import hashlib, time
    from jaeger_ai.core.tasks.owner import GatewayTaskOwner
    path = tmp_path / 'report.xlsx'
    _xlsx(path)
    task = SimpleNamespace(created_at=time.time()-1, goal='Deliver report.xlsx',
                           payload={'execution': {'workspace': str(tmp_path)}})
    receipt = {'ok': True, 'verification_receipts': [{'kind': 'file_sha256', 'path': str(path),
                                                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}
    for payload, result in [({}, {}), ({'artifacts': [str(path)]}, {}), ({}, {'task_completion': receipt})]:
        task.payload.update(payload)
        ok, evidence = GatewayTaskOwner.verify(task, result)
        assert not ok and 'nonnumeric cached value' in evidence
        task.payload.pop('artifacts', None)


def test_format_failure_gets_one_real_correction_then_revalidation(layout, tmp_path):
    from jaeger_ai.core.runtime.autonomous_runner import run_continued_turn
    from jaeger_ai.core.runtime.work_ledger import ledger_scope
    project = tmp_path / 'project'; project.mkdir()
    calls = []
    def turn(prompt):
        calls.append(prompt)
        _xlsx(project / 'report.xlsx', 't="str"' if len(calls)>1 else '')
        return {'text': 'Done.'}
    with project_scope(project), ledger_scope('format-correction'):
        result = run_continued_turn(turn, 'Deliver report.xlsx', max_steps=2)
    assert len(calls) == 2 and 'Independent artifact validation failed' in calls[1]
    assert not result.get('error')


def test_persistently_invalid_artifact_never_reports_success(layout, tmp_path):
    from jaeger_ai.core.runtime.autonomous_runner import run_continued_turn
    from jaeger_ai.core.runtime.work_ledger import ledger_scope
    calls = []
    def turn(prompt):
        calls.append(prompt)
        _xlsx(tmp_path / 'report.xlsx')
        return {'text': 'Done.'}
    with project_scope(tmp_path), ledger_scope('format-failure'):
        result = run_continued_turn(turn, 'Deliver report.xlsx', max_steps=8)
    assert len(calls) == 2
    assert result['status'] == 'failed' and result['halt_reason'] == 'invalid_artifact'


def test_relative_prefix_cannot_escape_admitted_write_root(layout, tmp_path):
    from jaeger_agent.core.workspace import _resolve_write, SandboxError
    project = tmp_path / 'project'; project.mkdir()
    with project_scope(project):
        assert _resolve_write('report.txt') == project / 'report.txt'
        for path in ['workspace/report.txt', 'skills/report.txt', str(layout.workspace_dir / 'report.txt')]:
            with pytest.raises(SandboxError):
                _resolve_write(path)
    # Explicit aliases remain supported when no narrower project was admitted.
    assert _resolve_write('workspace/report.txt') == layout.workspace_dir / 'report.txt'


def test_relative_project_write_preserves_instance_control_protection(layout):
    from jaeger_agent.core.workspace import _resolve_write, SandboxError
    with project_scope(layout.root):
        with pytest.raises(SandboxError, match='protected'):
            _resolve_write('identity.yaml')
def test_reviewer_receives_complete_long_action_and_owner_constraints():
    from jaeger_ai.core.authority.reviewer import reviewer_prompt
    code = '# safe setup\n' * 500 + 'IMPORTANT_FINAL_ACTION'
    request = 'synthetic work ' * 400 + 'DO NOT LEAVE WORKSPACE'
    prompt = reviewer_prompt(user_request=request, tool='terminal', arguments={'command': code})
    assert 'IMPORTANT_FINAL_ACTION' in prompt and 'DO NOT LEAVE WORKSPACE' in prompt


def test_oversized_review_never_sends_a_truncated_action_to_model():
    from jaeger_ai.core.authority.reviewer import review_action, MAX_REVIEW_CHARS
    class MustNotCall:
        @property
        def _loop(self):
            raise AssertionError('Oversized review must ask owner without model approval')
    verdict, reason = review_action(MustNotCall(), user_request='audit', tool='terminal',
                                    arguments={'command': 'x' * MAX_REVIEW_CHARS})
    assert verdict == 'unsure' and 'complete action' in reason


def test_python_traceback_progress_is_not_the_same_semantic_failure():
    from jaeger_loop.backstop import semantic_failure_signature, loop_halt_reason
    header = 'Traceback (most recent call last):\n  File "repair.py", line 1, in <module>\n'
    args = {'command': 'python3 repair.py'}
    first = semantic_failure_signature('terminal', args, {'ok': False, 'stderr': header + 'ImportError: missing etree'})
    second = semantic_failure_signature('terminal', args, {'ok': False, 'stderr': header + "NameError: name M is not defined"})
    assert first != second
    assert loop_halt_reason(2, {}, {first: 1, second: 1}) is None
    assert 'same terminal failure' in loop_halt_reason(2, {}, {second: 2})
    moved_line = header.replace('line 1', 'line 99') + 'ImportError: missing etree'
    assert semantic_failure_signature('terminal', args, {'ok': False, 'stderr': moved_line}) == first


def test_reviewer_uses_bounded_controls_and_cancels_on_timeout():
    import asyncio, threading
    from jaeger_ai.core.authority.reviewer import review_action

    seen = {}
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        class FastGateway:
            _loop = loop
            async def _model_chat(self, prompt, **kwargs):
                seen.update(kwargs)
                return '{"verdict": "approve", "reason": "workspace write matches request"}'

        verdict, reason = review_action(FastGateway(), user_request='save report', tool='terminal', arguments={'command': 'python3 run.py'})
        assert verdict == 'approve' and 'workspace write' in reason
        assert seen['controls'] == {'reasoning_effort': 'low', 'max_tokens': 1024}
        assert seen['interrupt_event'] is not None and not seen['interrupt_event'].is_set()

        cancel_ref = []
        class SlowGateway:
            _loop = loop
            async def _model_chat(self, prompt, **kwargs):
                cancel_ref.append(kwargs['interrupt_event'])
                raise TimeoutError('reviewer timed out')

        v2, r2 = review_action(SlowGateway(), user_request='save report', tool='terminal', arguments={'command': 'python3 run.py'})
        assert v2 == 'unsure' and 'could not complete' in r2
        assert cancel_ref and cancel_ref[0].is_set()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()


def test_view_image_surfaces_model_and_elapsed_on_local_vision_error(layout, tmp_path, monkeypatch):
    from PIL import Image
    from jaeger_agent.tools import vision
    img = tmp_path / 'sample.png'
    Image.new('RGB', (64, 64), 'blue').save(img)
    monkeypatch.setattr(vision, '_local_vision', lambda data, q: {
        'ok': False, 'error': 'local vision failed: TimeoutError: timed out',
        'model': 'qwen3-vl:8b-instruct', 'elapsed_s': 12.34,
    })
    with project_scope(tmp_path):
        res = vision.view_image(str(img), 'describe')
    assert res['description_error'] == 'local vision failed: TimeoutError: timed out'
    assert res['vision_model'] == 'qwen3-vl:8b-instruct'
    assert res['vision_elapsed_s'] == 12.34
