"""Board CAS contract: real routes, temporary disk and independent interpreters.

No HTTP listener/browser or cross-file crash-atomicity claim is made here.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

import pytest

SOURCE = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/unified_api.py'


def load_api():
    spec = importlib.util.spec_from_file_location('_studio_contract_api', SOURCE)
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    return api


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_HOME', str(tmp_path / 'state'))
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path / 'different-operator-root'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    return load_api()


def note(identifier, **changes):
    return dict(id=identifier, kind='note', text=identifier, x=0, y=0, w=100, h=80, **changes)


def route(api, method='GET', body=None, path='/v1/studio/board'):
    responses = []
    handled = api.route(object(), urlparse(path), method, lambda _: body or {},
                        lambda _, payload, status=200: responses.append((status, payload)))
    assert handled and len(responses) == 1
    return responses[0]


def save(api, base, items):
    return route(api, 'PUT', {'expected_revision': base['revision'], 'items': items})


def board_path(api):
    return api.state_root() / 'studio/board.json'


def test_missing_creation_normalized_receipt_and_legacy_read(api):
    status, base = route(api)
    assert status == 200 and base == {'items': [], 'revision': 'missing'}
    status, committed = save(api, base, [dict(note('a'), x=1.8, text='x' * 4100)])
    assert status == 200 and committed['items'][0]['x'] == 2
    assert len(committed['items'][0]['text']) == 4000
    assert committed['revision'] == hashlib.sha256(board_path(api).read_bytes()).hexdigest()
    assert route(api) == (200, committed)
    raw = json.dumps({'items': [note('legacy')], 'updated_at': 123}).encode()
    board_path(api).write_bytes(raw)
    status, legacy = route(api)
    assert status == 200 and legacy['revision'] == hashlib.sha256(raw).hexdigest()
    assert board_path(api).read_bytes() == raw
    assert save(api, legacy, legacy['items'] + [note('new')])[0] == 200


@pytest.mark.parametrize('token,expected', [(None,400), ('',400), ('garbage',400), (3,400), (False,400), ('A'*64,400), ('0'*64,409), ('missing',409)])
def test_invalid_or_stale_precondition_preserves_bytes(api, token, expected):
    save(api, route(api)[1], [note('existing')])
    before = board_path(api).read_bytes()
    assert route(api, 'PUT', {'items': [], 'expected_revision': token})[0] == expected
    assert board_path(api).read_bytes() == before


def test_old_clients_fail_explicitly_missing_and_existing(api):
    assert route(api, 'PUT', {'items': []})[0] == 428
    assert not board_path(api).exists()
    save(api, route(api)[1], [note('keep')])
    before = board_path(api).read_bytes()
    assert route(api, 'PUT', {'items': []})[0] == 428
    assert board_path(api).read_bytes() == before


def test_ordered_edit_move_resize_remove_reopens(api):
    _, first = save(api, route(api)[1], [note('a'), note('b')])
    _, changed = save(api, first, [dict(note('a'), text='edited', x=123, y=45, w=220, h=110)])
    assert route(api) == (200, changed)
    assert changed['items'] == [dict(note('a'), text='edited', x=123, y=45, w=220, h=110, color='yellow')]


@pytest.mark.parametrize('raw', [b'broken', b'null', b'[]', b'{"items":null}', b'{"items":[null]}', b'{"items":[{"id":"a","kind":"note","x":false,"y":0,"w":1,"h":1}]}'])
def test_corruption_after_valid_load_preserves_board_and_assets(api, raw):
    asset = api.add_asset(b'synthetic', 'image/png', 'fixture', 'imported')
    _, loaded = save(api, route(api)[1], [note('keep')])
    path = board_path(api)
    path.write_bytes(raw)
    index = path.parent / 'assets.json'
    before_index = index.read_bytes()
    assert route(api)[0] == 503
    assert save(api, loaded, [note('stale')])[0] == 503
    assert route(api, 'DELETE', path='/v1/studio/assets/' + asset['id'])[0] == 503
    assert path.read_bytes() == raw and index.read_bytes() == before_index
    assert (path.parent / 'assets' / asset['file']).read_bytes() == b'synthetic'


def test_read_denial_after_load_preserves_bytes_and_asset(api, monkeypatch):
    asset = api.add_asset(b'synthetic', 'image/png', 'fixture', 'imported')
    _, loaded = save(api, route(api)[1], [note('keep')])
    path = board_path(api)
    before = path.read_bytes()
    index = (path.parent / 'assets.json').read_bytes()
    original_bytes, original_text = Path.read_bytes, Path.read_text
    def denied_bytes(p, *a, **kw):
        if p == path: raise PermissionError('injected fixture read denial')
        return original_bytes(p, *a, **kw)
    def denied_text(p, *a, **kw):
        if p == path: raise PermissionError('injected fixture read denial')
        return original_text(p, *a, **kw)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'read_bytes', denied_bytes)
        patch.setattr(Path, 'read_text', denied_text)
        assert route(api)[0] == 503
        assert save(api, loaded, [note('stale')])[0] == 503
        assert route(api, 'DELETE', path='/v1/studio/assets/' + asset['id'])[0] == 503
    assert path.read_bytes() == before
    assert (path.parent / 'assets.json').read_bytes() == index
    assert (path.parent / 'assets' / asset['file']).read_bytes() == b'synthetic'


def test_asset_deletion_reads_current_and_prevents_stale_resurrection(api):
    asset = api.add_asset(b'synthetic', 'image/png', 'fixture', 'imported')
    ref = dict(id='picture', kind='asset', asset_id=asset['id'], x=0, y=0, w=100, h=100)
    _, original = save(api, route(api)[1], [ref])
    _, newer = save(api, original, [ref, note('intervening-note')])
    assert route(api, 'DELETE', path='/v1/studio/assets/' + asset['id'])[0] == 200
    current = route(api)[1]
    assert [i['id'] for i in current['items']] == ['intervening-note']
    before = board_path(api).read_bytes()
    assert save(api, newer, newer['items'])[0] == 409
    assert board_path(api).read_bytes() == before
    assert api.list_assets() == []


CHILD = r'''
import importlib.util,json,sys
from urllib.parse import urlparse
spec=importlib.util.spec_from_file_location('worker_api',sys.argv[1]);api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
print('ready',flush=True)
payload=json.loads(sys.stdin.readline())
responses=[]
api.route(object(),urlparse(payload.get('path','/v1/studio/board')),payload['method'],lambda _:payload.get('body',{}),lambda _,body,status=200:responses.append([status,body]))
print(json.dumps(responses[0]),flush=True)
'''


def child(api, state, operator, home):
    env = dict(os.environ, JAEGER_STATE_HOME=str(state), JAEGER_STATE_DIR=str(operator), HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
    p = subprocess.Popen([sys.executable, '-B', '-c', CHILD, str(SOURCE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    assert p.stdout.readline().strip() == 'ready'
    return p


def collect(p):
    output, error = p.communicate(timeout=15)
    assert p.returncode == 0, error
    return json.loads(output)


def test_independent_process_same_base_contenders_alias_roots_and_reopen(api, tmp_path):
    state = api.state_root()
    route(api)
    alias = tmp_path / 'state-alias'
    alias.symlink_to(state, target_is_directory=True)
    for attempt in range(6):
        base = route(api)[1]
        workers = [child(api, alias if n % 2 else state, tmp_path / f'operator-{n}', tmp_path / f'home-{n}') for n in range(4)]
        for n, p in enumerate(workers):
            body = {'expected_revision': base['revision'], 'items': base['items'] + [note(f'round-{attempt}-writer-{n}')]}
            p.stdin.write(json.dumps({'method': 'PUT', 'body': body}) + '\n'); p.stdin.flush()
        results = [collect(p) for p in workers]
        assert sorted(status for status, _ in results) == [200,409,409,409], results
        winner = next(payload for status,payload in results if status == 200)
        assert route(api) == (200, winner)
        assert not list((state / 'studio').glob('.board.json-*.tmp'))
    p = child(api, alias, tmp_path / 'fresh-operator', tmp_path / 'fresh-home')
    p.stdin.write(json.dumps({'method': 'GET'}) + '\n'); p.stdin.flush()
    assert collect(p) == [200, route(api)[1]]
    assert not (tmp_path / 'different-operator-root' / 'studio/board.json').exists()


def test_deletion_waiting_for_lock_keeps_intervening_commit(api, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import contextlib
    import threading
    asset = api.add_asset(b'synthetic', 'image/png', 'fixture', 'imported')
    ref = dict(id='picture', kind='asset', asset_id=asset['id'], x=0, y=0, w=100, h=100)
    _, base = save(api, route(api)[1], [ref])
    reached, release = threading.Event(), threading.Event()
    original_lock = api._board_lock
    worker_thread = []
    @contextlib.contextmanager
    def timed_lock(path):
        if threading.current_thread() is worker_thread[0]:
            reached.set()
            assert release.wait(5)
        with original_lock(path):
            yield
    def delete():
        worker_thread.append(threading.current_thread())
        return api.delete_asset(asset['id'])
    monkeypatch.setattr(api, '_board_lock', timed_lock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(delete)
        assert reached.wait(5)
        try:
            assert save(api, base, [ref, note('intervening')])[0] == 200
        finally:
            release.set()
        assert future.result(timeout=5) == {'deleted': asset['id']}
    assert [i['id'] for i in route(api)[1]['items']] == ['intervening']


def test_shared_helper_default_root_identity_unchanged(tmp_path, monkeypatch):
    from jaeger_ai.core.instance import instance
    from jaeger_ai.core.instance.atomic_files import _file_write_lock
    default = tmp_path / 'default'
    monkeypatch.setattr(instance, 'operator_state_root', lambda: default)
    target = tmp_path / 'target.json'
    key = hashlib.sha256(str(target.resolve()).encode()).hexdigest() + '.lock'
    with _file_write_lock(target):
        assert (default / 'run/schema-write-locks' / key).is_file()
    custom = tmp_path / 'explicit'
    with _file_write_lock(target, lock_root=custom):
        assert (custom / key).is_file()


def test_generation_prevents_aba_when_clock_is_frozen(api, monkeypatch):
    monkeypatch.setattr(api.time, 'time', lambda: 1)
    _, a = save(api, route(api)[1], [note('a')])
    _, b = save(api, a, [note('b')])
    _, a_again = save(api, b, [note('a')])
    assert a['items'] == a_again['items'] and a['revision'] != a_again['revision']
    before = board_path(api).read_bytes()
    assert save(api, a, [note('stale')])[0] == 409
    assert board_path(api).read_bytes() == before


def test_cross_process_delete_waits_for_shared_board_lock(api, tmp_path):
    import select
    asset = api.add_asset(b'synthetic', 'image/png', 'fixture', 'imported')
    ref = dict(id='picture', kind='asset', asset_id=asset['id'], x=0, y=0, w=100, h=100)
    save(api, route(api)[1], [ref, note('keep')])
    path = board_path(api).resolve()
    before = path.read_bytes()
    p = child(api, api.state_root(), tmp_path / 'other-operator', tmp_path / 'other-home')
    with api._board_lock(path):
        p.stdin.write(json.dumps({'method': 'DELETE', 'path': '/v1/studio/assets/' + asset['id']}) + '\n'); p.stdin.flush()
        assert not select.select([p.stdout], [], [], 0.3)[0]
        assert path.read_bytes() == before
        assert (path.parent / 'assets' / asset['file']).read_bytes() == b'synthetic'
    assert collect(p) == [200, {'deleted': asset['id']}]
    assert [i['id'] for i in route(api)[1]['items']] == ['keep']


def test_failed_board_replace_prevents_asset_side_effects(api, monkeypatch):
    asset = api.add_asset(b'synthetic', 'image/png', 'fixture', 'imported')
    ref = dict(id='picture', kind='asset', asset_id=asset['id'], x=0, y=0, w=100, h=100)
    save(api, route(api)[1], [ref])
    path = board_path(api).resolve()
    board_before = path.read_bytes()
    index = path.parent / 'assets.json'
    index_before = index.read_bytes()
    original = os.replace
    def deny_board_replace(source, destination):
        if Path(destination) == path:
            raise PermissionError('injected board replace denial')
        return original(source, destination)
    monkeypatch.setattr(os, 'replace', deny_board_replace)
    assert route(api, 'DELETE', path='/v1/studio/assets/' + asset['id'])[0] == 503
    assert path.read_bytes() == board_before and index.read_bytes() == index_before
    assert (path.parent / 'assets' / asset['file']).read_bytes() == b'synthetic'


@pytest.mark.parametrize('ids', [[''], ['duplicate', 'duplicate'], ['x' * 64 + 'a', 'x' * 64 + 'b']])
def test_invalid_normalized_ids_rejected_for_save_and_disk(api, ids):
    _, base = save(api, route(api)[1], [note('keep')])
    invalid = [note(identifier) for identifier in ids]
    before = board_path(api).read_bytes()
    assert save(api, base, invalid)[0] == 400
    assert board_path(api).read_bytes() == before
    raw = json.dumps({'items': invalid}).encode()
    board_path(api).write_bytes(raw)
    assert route(api)[0] == 503
    assert save(api, base, [note('stale')])[0] == 503
    assert board_path(api).read_bytes() == raw
