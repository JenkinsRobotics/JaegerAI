from types import SimpleNamespace
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jaeger_ai.core.runtime.dispatcher import DispatcherStore, context_note, session_policy
from jaeger_ai.core.sessions import SessionStore


def test_dispatcher_binding_and_focus_policy_survive_restart(tmp_path):
    layout = SimpleNamespace(memory_dir=tmp_path)
    store = DispatcherStore(layout)
    assert store.bind_dispatcher('primary') == 'primary'
    assert store.bind_dispatcher('another-tab') == 'primary'
    assert store.route('primary', 'hello') == 'dispatcher'
    assert store.route('task', 'Refactor the parser') == 'focus:task'
    restarted = DispatcherStore(layout)
    assert restarted.route('task', 'follow up') == 'focus:task'
    policy = session_policy(layout, 'focus:task')
    assert policy['goal'] == 'Refactor the parser'
    assert policy['toolsets'] == ['time', 'math', 'files', 'code']
    assert policy['context'] == 16384
    assert session_policy(layout, 'dispatcher') is None
    with pytest.raises(ValueError):
        session_policy(layout, 'focus:unregistered')


def test_focus_reports_are_durable_idempotent_and_separate_from_history(tmp_path):
    layout = SimpleNamespace(memory_dir=tmp_path)
    store = DispatcherStore(layout)
    native = store.route('task', 'Read the project README')
    store.report('r1', native, 'Read README. First line: JaegerAI.')
    store.report('r1', native, 'duplicate must not replace the original')
    state = DispatcherStore(layout).overview()
    assert len(state['reports']) == 1
    assert state['reports'][0]['summary'] == 'Read README. First line: JaegerAI.'
    from jaeger_agent.background.board import board_for_layout
    cards = board_for_layout(layout).list()
    assert len(cards) == 1 and cards[0].column == 'done'
    assert 'Read README.' in cards[0].result
    assert 'Read README.' in context_note(layout, 'dispatcher')
    assert 'Read README.' not in context_note(layout, native)
    assert store.path.stat().st_mode & 0o077 == 0


def test_dispatcher_history_is_not_removed_by_focus_retention(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    try:
        store.record('dispatcher', 'user', 'Remember our conversation')
        for i in range(5):
            store.record(f'focus:task{i}', 'user', 'task')
        assert store.prune(2) == 3
        assert store.history('dispatcher')[0]['text'] == 'Remember our conversation'
        assert len(store.list_sessions()) == 3
    finally:
        store.close()


def test_board_failure_preserves_report_and_repair_does_not_execute_work(tmp_path):
    layout = SimpleNamespace(memory_dir=tmp_path)
    store = DispatcherStore(layout)
    session = store.route('task', 'Read a file')
    board_path = tmp_path / 'board.json'
    board_path.write_text('{broken')
    store.report('durable-result', session, 'File was read')
    assert board_path.read_text() == '{broken'
    assert store.overview()['pending_board_reports'] == 1
    assert store.overview()['reports'][0]['summary'] == 'File was read'
    assert store.repair_projections()['errors']
    # Simulate restoring the board from backup. Repair only projects the
    # already-saved result; no model, tool, or native runner is involved.
    board_path.write_text('{"cards":[]}')
    assert store.repair_projections() == {'repaired': ['durable-result'], 'errors': {}}
    assert store.overview()['pending_board_reports'] == 0
    assert store.repair_projections() == {'repaired': [], 'errors': {}}


def test_concurrent_report_projection_creates_one_card(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from jaeger_agent.background.board import board_for_layout
    layout = SimpleNamespace(memory_dir=tmp_path)
    session = DispatcherStore(layout).route('task', 'Read a file')
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: DispatcherStore(layout).report('same-run', session, 'result'), range(12)))
    assert len(board_for_layout(layout).list()) == 1


def test_cancelled_focus_reports_preserve_partial_output(tmp_path):
    from jaeger_agent.background.board import board_for_layout
    layout = SimpleNamespace(memory_dir=tmp_path)
    store = DispatcherStore(layout)
    session = store.route('task', 'Inspect files')
    store.report('cancelled-run', session, 'Read the first file.', cancelled=True)
    report = store.overview()['reports'][0]
    assert report['status'] == 'cancelled'
    assert 'Read the first file.' in report['summary']
    assert board_for_layout(layout).list()[0].column == 'blocked'


def test_sidecar_denies_missing_credentials_before_backend_access(tmp_path, monkeypatch):
    from jaeger_ai.features.hermes_webui import dispatcher_sidecar as sidecar
    token = tmp_path / 'sidecar.token'
    monkeypatch.setattr(sidecar, 'token_file', lambda: token)
    monkeypatch.setattr(sidecar, 'backend', lambda: pytest.fail('Backend must not be reached'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), sidecar.Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base + '/health') as response:
            assert json.load(response)['owner'] == 'jaeger'
        with pytest.raises(HTTPError) as exc:
            urlopen(base + '/memory')
        assert exc.value.code == 503
        token.write_text('private-token')
        with pytest.raises(HTTPError) as exc:
            urlopen(base + '/memory')
        assert exc.value.code == 401
        with pytest.raises(HTTPError) as exc:
            urlopen(Request(base + '/arbitrary-route', headers={'X-Hermes-Sidecar-Token': 'private-token'}))
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
