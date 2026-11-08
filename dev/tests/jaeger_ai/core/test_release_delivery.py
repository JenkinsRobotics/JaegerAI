"""Release failures must reject incomplete artifacts and retain recoverable state."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inspector_rejects_plain_text_empty_and_corrupt_archives(tmp_path):
    inspector = load('release_inspector', 'dev/scripts/inspect_release_artifacts.py')
    text = tmp_path / 'release.txt'; text.write_text('not an archive')
    assert inspector.inspect(text)
    empty = tmp_path / 'empty.zip'
    with zipfile.ZipFile(empty, 'w'): pass
    assert inspector.inspect(empty)
    corrupt = tmp_path / 'bad.whl'; corrupt.write_bytes(b'not zip')
    assert inspector.inspect(corrupt)


def test_inspector_rejects_missing_ui_and_dependency_contract(tmp_path):
    inspector = load('release_inspector', 'dev/scripts/inspect_release_artifacts.py')
    wheel = tmp_path / 'jaeger_ai-1.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('jaeger_ai-1.0.dist-info/METADATA', 'Name: jaeger-ai\nVersion: 1.0\n')
    errors = inspector.inspect(wheel)
    assert any('shared-ui/index.html' in error for error in errors)
    assert any('dependency: jaeger_agent' in error for error in errors)
    assert any('compiled shared UI' in error for error in errors)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'runtime.sqlite3', 'node_modules/pkg/index.js'])
def test_inspector_rejects_unsafe_members(tmp_path, name):
    inspector = load('release_inspector', 'dev/scripts/inspect_release_artifacts.py')
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as stream: stream.writestr(name, 'unsafe')
    assert any('unsafe member' in error for error in inspector.inspect(archive))


def test_rollback_can_retry_failed_dependency_restore(tmp_path, monkeypatch):
    from jaeger_ai.cli.verbs import update_verb as update
    monkeypatch.setattr(update, "_preflight_update", lambda home: 0)
    home = tmp_path / 'product'
    prev = home / '.update-prev'
    (prev / 'jaeger_ai').mkdir(parents=True)
    (prev / 'jaeger_ai/version.txt').write_text('old')
    (home / 'jaeger_ai').mkdir()
    (home / 'jaeger_ai/version.txt').write_text('new')
    monkeypatch.setattr(update, '_reinstall_deps', lambda _: 37)
    monkeypatch.setattr(update, '_rebuild_mac_shell', lambda _: 0)
    assert update._do_rollback(home) == 37
    assert (prev / 'jaeger_ai/version.txt').read_text() == 'old'
    assert (home / 'jaeger_ai/version.txt').read_text() == 'old'
    monkeypatch.setattr(update, '_reinstall_deps', lambda _: 0)
    assert update._do_rollback(home) == 0
    assert not prev.exists()
    assert (home / 'jaeger_ai/version.txt').read_text() == 'old'


def test_rollback_retains_recovery_when_app_build_fails(tmp_path, monkeypatch):
    from jaeger_ai.cli.verbs import update_verb as update
    monkeypatch.setattr(update, "_preflight_update", lambda home: 0)
    (tmp_path / '.update-prev').mkdir()
    (tmp_path / '.update-prev/fixture').write_text('saved')
    monkeypatch.setattr(update, '_reinstall_deps', lambda _: 0)
    monkeypatch.setattr(update, '_rebuild_mac_shell', lambda _: 9)
    assert update._do_rollback(tmp_path) == 9
    assert (tmp_path / '.update-prev/fixture').read_text() == 'saved'


def test_test_stack_refuses_existing_state_without_removing_it(tmp_path):
    stack = load('test_stack', 'scripts/test-stack.py')
    sentinel = tmp_path / 'keep'; sentinel.write_text('operator work')
    with pytest.raises(ValueError, match='new and empty'):
        stack.run(tmp_path, tmp_path)
    assert sentinel.read_text() == 'operator work'


def test_write_guard_blocks_real_file_sqlite_and_rename_writes(tmp_path):
    # Audit hooks cannot be unregistered: install in a child so pytest can
    # still remove its own disposable fixture afterward.
    program = '''
from pathlib import Path
import sqlite3, sys
sys.path.insert(0, sys.argv[1])
from dev.tests.fixtures.live_write_guard import install
root = Path(sys.argv[2]); root.mkdir()
outside = root.parent / 'outside'; outside.write_text('safe')
install((root,))
for action in (lambda: (root/'file').write_text('bad'),
               lambda: sqlite3.connect(root/'db.sqlite3'),
               lambda: outside.rename(root/'renamed')):
    try: action()
    except PermissionError: pass
    else: raise AssertionError('write guard did not block operation')
assert list(root.iterdir()) == []
assert outside.read_text() == 'safe'
'''
    result = subprocess.run([sys.executable, '-B', '-c', program, str(ROOT), str(tmp_path / 'protected')],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_release_workflow_requires_qualification_and_inspects_published_artifacts():
    import yaml
    workflow = yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)
    job = workflow['jobs']['release']
    assert set(job['needs']) == {'qualification', 'feature-qualification'}
    steps = job['steps']
    commands = '\n'.join(step.get('run', '') for step in steps)
    assert 'scripts/install-packages.py --no-install --sdist' in commands
    assert 'inspect_release_artifacts.py "$RUNNER_TEMP/jaeger-dist"' in commands
    assert 'python -m build' not in commands
    assert '|| true' not in commands and 'packaging skipped' not in commands.lower()
    publish = next(step for step in steps if step.get('uses', '').startswith('softprops/action-gh-release'))
    assert '${{ runner.temp }}/jaeger-dist/*' in publish['with']['files']
    assert publish['with']['fail_on_unmatched_files'] == 'true'
    for name in ('ci.yml', 'v013-tests.yml'):
        called = yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)
        assert 'workflow_call' in called['on']


@pytest.mark.parametrize('scenario, succeeds', [('tag', True), ('branch', False), ('wrong-version', False), ('moved-head', False)])
def test_release_tag_validation_rejects_unqualified_identity(tmp_path, scenario, succeeds):
    import os
    import yaml
    workflow = yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)
    command = next(step['run'] for step in workflow['jobs']['release']['steps']
                   if step.get('name', '').startswith('Require an immutable'))
    repo = tmp_path / 'release'; repo.mkdir()
    def git(*args):
        return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
            '-c', 'user.email=fixture@invalid', *args], check=True, capture_output=True, text=True)
    git('init', '-q')
    package = repo / 'jaeger_ai'; package.mkdir()
    (package / '__init__.py').write_text('__version__ = "1.2.3"\n')
    git('add', 'jaeger_ai'); git('commit', '-qm', 'release')
    tag = 'v9.9.9' if scenario == 'wrong-version' else 'v1.2.3'
    git('tag', tag)
    if scenario == 'moved-head':
        (repo / 'extra').write_text('not the qualified commit')
        git('add', 'extra'); git('commit', '-qm', 'later')
    env = dict(os.environ, GITHUB_REF_TYPE='branch' if scenario == 'branch' else 'tag',
               GITHUB_REF_NAME=tag, GITHUB_REF='refs/tags/' + tag)
    result = subprocess.run(['bash', '-e', '-c', command], cwd=repo, env=env, capture_output=True, text=True)
    assert (result.returncode == 0) == succeeds, result.stdout + result.stderr


def test_local_installer_refuses_running_service_before_creating_environment(tmp_path):
    import os
    import socket
    # Own listener only: this never reads or stops the operator's services.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1)
        port = listener.getsockname()[1]
        home = tmp_path / 'home'; home.mkdir()
        venv = tmp_path / 'must-not-be-created'
        env = dict(os.environ, HOME=str(home), PY=sys.executable,
                   JAEGER_VENV=str(venv), JAEGER_GATEWAY_PORT=str(port),
                   JAEGER_STATE_DIR=str(tmp_path / 'state'), JAEGER_HOME=str(tmp_path / 'state'))
        result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--product', '--skip-deps'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'still listening' in result.stderr
    assert not venv.exists()
    assert not (tmp_path / 'state').exists()
