"""Provider preference transactions preserve winning writes and private documents."""
import importlib.util
import json
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/cli_providers.py'


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_HOME', str(tmp_path))
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path / 'operator'))
    spec = importlib.util.spec_from_file_location('_transaction_cli', API)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'HOME', tmp_path)
    monkeypatch.setattr(module, 'detect', lambda: [{'id': 'codex'}])
    return module


def saved(cli, raw=b'{"codex":{"enabled":true,"models":["old"]},"future":[1]}'):
    path = cli._state_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return path


def test_stale_snapshot_rejected_and_successful_inner_update_retained(cli, monkeypatch):
    path = saved(cli)
    entered = False
    # Both old text and new exact-byte readers use this same race boundary.
    text_read, bytes_read = Path.read_text, Path.read_bytes
    def interleave(original, self, *args, **kwargs):
        nonlocal entered
        raw = original(self, *args, **kwargs)
        if self == path and not entered:
            entered = True
            cli.update('codex', {'models': ['new']})
        return raw
    monkeypatch.setattr(Path, 'read_text', lambda self, *a, **k: interleave(text_read, self, *a, **k))
    monkeypatch.setattr(Path, 'read_bytes', lambda self, *a, **k: interleave(bytes_read, self, *a, **k))
    with pytest.raises(ValueError, match='changed|busy'):
        cli.update('codex', {'enabled': False})
    assert json.loads(path.read_bytes()) == {'codex': {'enabled': True, 'models': ['new']}, 'future': [1]}


def test_each_write_uses_its_own_temp_and_keeps_historical_temp_and_mode(cli, monkeypatch):
    path = saved(cli)
    path.chmod(0o640)
    historical = path.with_suffix('.tmp')
    historical.write_text('retain historical bytes')
    sources = []
    replace = cli.os.replace
    def observe(src, dst):
        sources.append(Path(src))
        return replace(src, dst)
    monkeypatch.setattr(cli.os, 'replace', observe)
    cli.update('codex', {'enabled': False})
    cli.update('codex', {'models': ['new']})
    assert len(set(sources)) == 2
    assert historical not in sources
    assert historical.read_text() == 'retain historical bytes'
    assert path.stat().st_mode & 0o777 == 0o640
    assert all(not source.exists() for source in sources)
    assert json.loads(path.read_bytes()) == {'codex': {'enabled': False, 'models': ['new']}, 'future': [1]}


@pytest.mark.parametrize('raw', [b'\xef\xbb\xbf{}', '{}'.encode('utf-16'), '{}'.encode('utf-32'), b'\xff'])
def test_exact_snapshot_keeps_strict_utf8_without_bom(cli, raw):
    path = saved(cli, raw)
    with pytest.raises(ValueError, match='could not be read'):
        cli.update('codex', {'enabled': False})
    assert path.read_bytes() == raw


@pytest.mark.parametrize('existing', [True, False])
def test_two_writers_have_one_winner_and_explicit_conflict(cli, monkeypatch, existing):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    path = saved(cli) if existing else cli._state_path()
    barrier = threading.Barrier(2)
    readers = set()
    reader_lock = threading.Lock()
    read = Path.read_bytes
    def synchronized(self):
        if self != path:
            return read(self)
        with reader_lock:
            first = threading.get_ident() not in readers
            readers.add(threading.get_ident())
        if not first:
            return read(self)
        try:
            raw = read(self)
        except FileNotFoundError:
            barrier.wait(timeout=5)
            raise
        barrier.wait(timeout=5)
        return raw
    monkeypatch.setattr(Path, 'read_bytes', synchronized)
    def change(body):
        try:
            cli.update('codex', body)
            return 'saved', body
        except ValueError as exc:
            return str(exc), body
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(change, {'enabled': False}), pool.submit(change, {'models': ['new']})]
        results = [f.result(timeout=10) for f in futures]
    winners = [body for outcome, body in results if outcome == 'saved']
    assert len(winners) == 1
    assert sum('changed or writer is busy' in outcome for outcome, _ in results) == 1
    expected = {'codex': {'enabled': True, 'models': ['old']}, 'future': [1]} if existing else {'codex': {}}
    expected['codex'].update(winners[0])
    assert json.loads(read(path)) == expected
    assert not list(path.parent.glob('.cli.json-*.tmp'))


def test_late_external_edit_is_retained_and_unique_temp_cleaned(cli, monkeypatch):
    from jaeger_ai.core.instance import atomic_files
    path = saved(cli)
    replacement = b'{"future":"external exact bytes"}'
    write = atomic_files._write_unlocked
    def interleave(target, payload, **kwargs):
        target.write_bytes(replacement)
        return write(target, payload, **kwargs)
    monkeypatch.setattr(atomic_files, '_write_unlocked', interleave)
    with pytest.raises(ValueError, match='changed or writer is busy'):
        cli.update('codex', {'enabled': False})
    assert path.read_bytes() == replacement
    assert not list(path.parent.glob('.cli.json-*.tmp'))


@pytest.mark.parametrize('stage', ['replace', 'directory_fsync', 'detect'])
def test_api_reports_sanitized_failed_or_uncertain_save(cli, monkeypatch, stage):
    from urllib.parse import urlparse
    from jaeger_ai.core.instance import atomic_files
    path = saved(cli)
    before = path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError('synthetic-private-error-detail')
    if stage == 'replace':
        monkeypatch.setattr(cli.os, 'replace', fail)
    elif stage == 'directory_fsync':
        fsync = cli.os.fsync
        calls = 0
        def sync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                fail()
            return fsync(fd)
        monkeypatch.setattr(cli.os, 'fsync', sync)
    else:
        monkeypatch.setattr(cli, 'detect', fail)
    spec = importlib.util.spec_from_file_location('_transaction_api', API.with_name('unified_api.py'))
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    monkeypatch.setattr(api, '_cli', lambda: cli)
    responses = []
    assert api.route(None, urlparse('/v1/providers/cli/codex'), 'PUT',
                     lambda _: {'enabled': False},
                     lambda _, data, **kw: responses.append((data, kw)))
    assert len(responses) == 1 and responses[0][1] == {'status': 400}
    error = responses[0][0]['error']
    assert 'synthetic-private' not in error and 'no changes saved' not in error
    assert 'refresh' in error or 'reload' in error
    if stage == 'replace':
        assert path.read_bytes() == before
    else:
        assert json.loads(path.read_bytes())['codex']['enabled'] is False
    assert not list(path.parent.glob('.cli.json-*.tmp'))
