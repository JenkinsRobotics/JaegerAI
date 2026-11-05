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
