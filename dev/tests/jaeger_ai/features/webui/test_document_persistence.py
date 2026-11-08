"""Document CAS is serialized across threads and independently spawned writers."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import threading
import time

import pytest

SOURCE = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/unified_api.py'


def load_api():
    spec = importlib.util.spec_from_file_location('_document_api', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_HOME', str(tmp_path))
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path))
    return load_api()


def save_result(api, doc, text):
    try:
        return ('saved', api.save_doc(doc['id'], {'body': text, 'expected_updated_at': doc['updated_at']}))
    except api.ApiError as error:
        return ('error', error.status)


def test_thread_writers_have_one_exact_winner(api, monkeypatch):
    doc = api.save_doc(None, {'body': 'original'})
    original = api.get_doc
    # Hold a stale snapshot long enough for genuinely overlapping requests.
    def slow_read(did):
        value = original(did)
        time.sleep(.03)
        return value
    monkeypatch.setattr(api, 'get_doc', slow_read)
    start = threading.Barrier(8)
    def writer(index):
        start.wait(5)
        return save_result(api, doc, str(index))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(writer, range(8)))
    winners = [value for status, value in results if status == 'saved']
    assert len(winners) == 1
    assert [value for status, value in results if status == 'error'] == [409] * 7
    assert original(doc['id']) == winners[0]


def test_spawned_writers_and_restart_read(api, tmp_path):
    doc = api.save_doc(None, {'body': 'original'})
    script = """
import importlib.util, json, pathlib, sys, time
spec = importlib.util.spec_from_file_location('_api', sys.argv[1])
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
doc = json.loads(sys.argv[2])
original = api.get_doc
def slow_read(did):
    value = original(did)
    time.sleep(.2)
    return value
api.get_doc = slow_read
pathlib.Path(sys.argv[3] + '.ready').touch()
while not pathlib.Path(sys.argv[3]).exists(): time.sleep(.01)
try:
    result = ('saved', api.save_doc(doc['id'], {'body': sys.argv[4], 'expected_updated_at': doc['updated_at']}))
except api.ApiError as error:
    result = ('error', error.status)
print(json.dumps(result))
"""
    gates = [tmp_path / f'start-{i}' for i in range(4)]
    workers = [subprocess.Popen([sys.executable, '-c', script, str(SOURCE), json.dumps(doc), str(gate), str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i, gate in enumerate(gates)]
    try:
        deadline = time.monotonic() + 15
        while not all(Path(str(gate) + '.ready').exists() for gate in gates):
            assert time.monotonic() < deadline
            time.sleep(.01)
        for gate in gates:
            gate.touch()
        outcomes = []
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=15)
            assert worker.returncode == 0, stderr
            outcomes.append(json.loads(stdout))
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate()
    winners = [value for status, value in outcomes if status == 'saved']
    assert len(winners) == 1
    assert [value for status, value in outcomes if status == 'error'] == [409] * 3
    read_script = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('_api', sys.argv[1])
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
print(json.dumps(api.get_doc(sys.argv[2])))
"""
    restarted = subprocess.run([sys.executable, '-c', read_script, str(SOURCE), doc['id']], check=True, capture_output=True, text=True, timeout=15)
    assert json.loads(restarted.stdout) == winners[0]
    assert json.loads((api._docs() / (doc['id'] + '.json')).read_text()) == winners[0]


@pytest.mark.parametrize('clock', [100.0, 50.0])
def test_clock_regression_still_invalidates_previous_revision(api, monkeypatch, clock):
    monkeypatch.setattr(api.time, 'time', lambda: 100.0)
    doc = api.save_doc(None, {'body': 'original'})
    monkeypatch.setattr(api.time, 'time', lambda: clock)
    saved = api.save_doc(doc['id'], {'body': 'changed', 'expected_updated_at': doc['updated_at']})
    assert saved['updated_at'] > doc['updated_at']
    assert save_result(api, doc, 'stale') == ('error', 409)
    assert api.get_doc(doc['id']) == saved


@pytest.mark.parametrize('revision', [float('nan'), float('inf'), -float('inf'), 'NaN', 'oops', {}, [], True, None])
def test_invalid_revision_rejected_without_write(api, revision):
    doc = api.save_doc(None, {'body': 'original'})
    with pytest.raises(api.ApiError) as error:
        api.save_doc(doc['id'], {'body': 'invalid', 'expected_updated_at': revision})
    assert error.value.status == 400
    assert api.get_doc(doc['id']) == doc


def test_delete_waits_for_inflight_save_without_resurrection(api, monkeypatch):
    doc = api.save_doc(None, {'body': 'original'})
    read, release = threading.Event(), threading.Event()
    original = api.get_doc
    def delayed_read(did):
        result = original(did)
        if threading.current_thread().name.startswith('saving'):
            read.set()
            assert release.wait(5)
        return result
    monkeypatch.setattr(api, 'get_doc', delayed_read)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='saving') as saves, ThreadPoolExecutor(max_workers=1) as deletes:
        saving = saves.submit(save_result, api, doc, 'changed')
        assert read.wait(5)
        deleting = deletes.submit(api.delete_doc, doc['id'])
        try:
            time.sleep(.1)
            assert not deleting.done(), 'delete bypassed the in-flight save transaction'
        finally:
            release.set()
        assert saving.result(timeout=5)[0] == 'saved'
        assert deleting.result(timeout=5) == {'deleted': doc['id']}
    with pytest.raises(api.ApiError) as error:
        original(doc['id'])
    assert error.value.status == 404
    assert save_result(api, doc, 'resurrect') == ('error', 404)


def test_independent_delete_uses_same_transaction_lock(api, tmp_path):
    from jaeger_ai.core.instance.atomic_files import _file_write_lock

    doc = api.save_doc(None, {'body': 'original'})
    ready = tmp_path / 'deleting'
    script = """
import importlib.util, json, pathlib, sys
spec = importlib.util.spec_from_file_location('_api', sys.argv[1])
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
pathlib.Path(sys.argv[3]).touch()
print(json.dumps(api.delete_doc(sys.argv[2])))
"""
    worker = None
    try:
        with _file_write_lock(api._docs() / (doc['id'] + '.json')):
            worker = subprocess.Popen([sys.executable, '-c', script, str(SOURCE), doc['id'], str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 10
            while not ready.exists():
                assert time.monotonic() < deadline
                time.sleep(.01)
            time.sleep(.2)
            assert worker.poll() is None
            assert api.get_doc(doc['id']) == doc
        stdout, stderr = worker.communicate(timeout=10)
        assert worker.returncode == 0, stderr
        assert json.loads(stdout) == {'deleted': doc['id']}
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.communicate()
    assert save_result(api, doc, 'resurrect') == ('error', 404)


def test_failed_atomic_replace_retains_original(api, monkeypatch):
    import os

    doc = api.save_doc(None, {'body': 'original'})
    path = api._docs() / (doc['id'] + '.json')
    before = path.read_bytes()
    def fail_replace(*args):
        raise OSError('simulated replacement failure')
    monkeypatch.setattr(os, 'replace', fail_replace)
    with pytest.raises(OSError, match='simulated'):
        api.save_doc(doc['id'], {'body': 'replacement'})
    assert path.read_bytes() == before
    assert not list(api._docs().glob('*.tmp'))


def test_revision_bound_delete_preserves_newer_document(api):
    doc = api.save_doc(None, {'body': 'original'})
    newer = api.save_doc(doc['id'], {'body': 'newer'})
    with pytest.raises(api.ApiError) as error:
        api.delete_doc(doc['id'], {'expected_updated_at': doc['updated_at']})
    assert error.value.status == 409
    assert error.value.payload['current'] == newer
    assert api.get_doc(doc['id']) == newer
    assert api.delete_doc(doc['id'], {'expected_updated_at': newer['updated_at']}) == {'deleted': doc['id']}


@pytest.mark.parametrize('revision', [float('nan'), float('inf'), 'bad', {}, True, None])
def test_invalid_delete_revision_retains_document(api, revision):
    doc = api.save_doc(None, {'body': 'original'})
    with pytest.raises(api.ApiError) as error:
        api.delete_doc(doc['id'], {'expected_updated_at': revision})
    assert error.value.status == 400
    assert api.get_doc(doc['id']) == doc


def test_delete_route_reads_revision_body(api, monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import urlparse
    stub = SimpleNamespace(handles=lambda path: False)
    for loader in ('_inbox', '_widgets', '_avatar', '_machine'):
        monkeypatch.setattr(api, loader, lambda: stub)
    doc = api.save_doc(None, {'body': 'original'})
    newer = api.save_doc(doc['id'], {'body': 'newer'})
    replies = []
    assert api.route(None, urlparse('/v1/documents/' + doc['id']), 'DELETE',
                     lambda handler: {'expected_updated_at': doc['updated_at']},
                     lambda handler, payload, status=200: replies.append((status, payload)))
    assert replies == [(409, {'error': 'document changed elsewhere; reload it', 'current': newer})]
    assert api.get_doc(doc['id']) == newer
