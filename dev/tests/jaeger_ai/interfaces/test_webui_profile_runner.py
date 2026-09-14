from __future__ import annotations

import threading
import time

import pytest

from jaeger_ai.features.webui.adapter.server import RunnerBroker, RunStore, ApprovalBroker
from jaeger_ai.features.webui.adapter.profile_runner import ProfileRunner


class Bridge:
    def __init__(self): self.calls = []
    def command(self, *args): return {}
    def query(self, *args): return []
    def turn(self, text, session, *args, **kwargs):
        self.calls.append(session)
        return {'text': 'Jaeger reply'}


def wait_done(broker, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = broker.store.status(run_id)
        if state['terminal_state']:
            return state
        time.sleep(.01)
    pytest.fail('run did not finish')


@pytest.fixture
def broker(tmp_path):
    bridge = Bridge()
    broker = RunnerBroker(bridge, ApprovalBroker(), RunStore(tmp_path))
    def backend(run, workspace):
        run.execution_unknown = False
        run.dispatch(session_id=run.session, run_id=run.id)
        run.emit('message.delta', delta=run.message + ' reply')
        return run.output
    broker.profiles = ProfileRunner(broker.store, {'hermes': backend, 'openclaw': backend})
    return broker


@pytest.mark.parametrize('profile', ['default', 'hermes', 'openclaw'])
def test_selected_framework_never_calls_jaeger_bridge(broker, profile):
    result = broker.start({'profile': profile, 'message': 'hello', 'session_id': 'browser-' + profile})
    assert wait_done(broker, result['run_id'])['status'] == 'completed'
    assert broker.bridge.calls == []
    state = broker.store.status(result['run_id'])
    assert state['native']['session_id'].startswith('webui-')


def test_follow_up_keeps_full_display_history_and_native_identity(broker):
    ids = []
    for text in ('first', 'second'):
        result = broker.start({'profile': 'openclaw', 'message': text, 'session_id': 'same'})
        ids.append(result['run_id'])
        assert wait_done(broker, ids[-1])['status'] == 'completed'
    events = broker.store.events_after(ids[-1], None)['events']
    done = next(e['payload'] for e in events if e['event'] == 'done')
    assert [m['content'] for m in done['session']['messages']] == ['first', 'first reply', 'second', 'second reply']
    assert broker.store.status(ids[0])['native']['session_id'] == broker.store.status(ids[1])['native']['session_id']
    cursor = events[0]['event_id']
    assert broker.store.events_after(ids[-1], cursor)['events'] == events[1:]


def test_unknown_or_cross_profile_session_is_rejected(broker):
    with pytest.raises(ValueError):
        broker.start({'profile': 'missing', 'message': 'hi', 'session_id': 'x'})
    first = broker.start({'profile': 'hermes', 'message': 'hi', 'session_id': 'x'})
    wait_done(broker, first['run_id'])
    with pytest.raises(ValueError):
        broker.start({'profile': 'jaeger', 'message': 'hi', 'session_id': 'x'})
    assert broker.bridge.calls == []


def test_native_failure_surfaces_without_fallback(broker):
    def fail(run, workspace):
        run.execution_unknown = False
        raise ConnectionError('native offline')
    broker.profiles.backends['hermes'] = fail
    result = broker.start({'profile': 'hermes', 'message': 'hi', 'session_id': 'offline'})
    assert wait_done(broker, result['run_id'])['status'] == 'failed'
    events = broker.store.events_after(result['run_id'], None)['events']
    assert events[-1]['payload']['message'] == 'native offline'
    assert broker.bridge.calls == []


def test_cancel_and_approval_are_scoped_to_accepting_run(broker):
    admitted = threading.Event()
    def backend(run, workspace):
        run.execution_unknown = False
        admitted.set()
        answer = run.request_approval('test approval')
        if run.cancelled.is_set(): run.cancel_confirmed = True
        return answer
    broker.profiles.backends['hermes'] = backend
    first = broker.start({'profile': 'hermes', 'message': 'one', 'session_id': 'one'})
    assert admitted.wait(2)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        aid = broker.store.status(first['run_id']).get('pending_approval_id')
        if aid: break
        time.sleep(.01)
    assert aid
    second = broker.start({'profile': 'openclaw', 'message': 'two', 'session_id': 'two'})
    wait_done(broker, second['run_id'])
    with pytest.raises(KeyError): broker.approve(second['run_id'], aid, 'once')
    assert broker.cancel(first['run_id'])['ok']
    assert wait_done(broker, first['run_id'])['status'] == 'cancelled'
    assert broker.store.status(second['run_id'])['status'] == 'completed'


def test_native_model_selection_is_forwarded_before_dispatch(broker):
    seen = []
    def backend(run, workspace):
        seen.append((run.model, run.provider))
        return 'ok'
    broker.profiles.backends['hermes'] = backend
    result = broker.start({'profile': 'hermes', 'message': 'hi', 'session_id': 'model',
                           'model': '@ollama-cloud:example:cloud', 'provider': 'ollama-cloud'})
    assert wait_done(broker, result['run_id'])['status'] == 'completed'
    assert seen == [('example:cloud', 'ollama')]


def test_restart_recovers_completed_native_receipt_without_dispatch(broker):
    first = broker.start({'profile': 'openclaw', 'message': 'hi', 'session_id': 'restore'})
    wait_done(broker, first['run_id'])
    # Simulate losing the observer before it persisted native completion.
    broker.store.set_state(first['run_id'], status='running', terminal_state=None)
    runner = ProfileRunner(RunStore(broker.store.root), broker.profiles.backends)
    assert runner.store.status(first['run_id'])['status'] == 'completed'
    assert runner.managers['openclaw'].runs == {}
    assert broker.bridge.calls == []


def test_restart_unknown_native_run_fails_visibly_without_retry(broker):
    rid = 'a' * 32
    broker.store.create(run_id=rid, session_id='lost', prompt='hi')
    broker.store.set_state(rid, profile='hermes')
    runner = ProfileRunner(RunStore(broker.store.root), broker.profiles.backends)
    assert runner.store.status(rid)['status'] == 'interrupted'
    assert runner.store.status(rid)['execution_unknown']
    with pytest.raises(ValueError, match='unknown'):
        runner.start({'profile': 'hermes', 'message': 'again', 'session_id': 'lost'})
    assert broker.bridge.calls == []


def test_hermes_native_request_carries_selected_model(tmp_path, monkeypatch):
    import io
    import json
    from jaeger_ai.interfaces.hermes_profile_adapters import hermes_native
    from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import Run
    calls = []
    native_id = 'run_' + 'b' * 32
    def urlopen(request, timeout):
        calls.append(request)
        if request.data:
            return io.BytesIO(json.dumps({'run_id': native_id}).encode())
        return io.BytesIO(('data: ' + json.dumps({'event': 'run.completed', 'run_id': native_id, 'output': 'answer'}) + '\n').encode())
    monkeypatch.setattr(hermes_native, 'connection', lambda: ('http://native.invalid', 'synthetic-key'))
    monkeypatch.setattr(hermes_native, 'urlopen', urlopen)
    run = Run(tmp_path, 'stable-session', 'hello')
    run.model = 'selected-model'; run.provider = 'selected-provider'
    assert hermes_native.hermes_turn(run) == 'answer'
    assert json.loads(calls[0].data) == {'session_id': 'stable-session', 'input': 'hello',
                                       'model': 'selected-model', 'provider': 'selected-provider'}


def test_roundtable_admission_is_durable_before_native_dispatch(broker):
    from jaeger_ai.features.roundtable.service import TableService
    def backend(run, workspace):
        rows = broker.store.records_for_session('table')
        assert rows and rows[0]['profile'] == 'roundtable'
        return 'member answer'
    service = TableService(broker.store.root / 'profiles' / 'roundtable',
                           {member: backend for member in ('hermes', 'openclaw', 'jaeger')})
    broker.profiles.managers['roundtable'] = service
    accepted = broker.start({'profile': 'roundtable', 'session_id': 'table', 'message': '/quick @hermes hello'})
    assert wait_done(broker, accepted['run_id'])['status'] == 'completed'
    assert broker.bridge.calls == []


def test_jaeger_halt_is_not_reported_as_success(broker):
    broker.bridge.turn = lambda *a, **k: {'text': '', 'halt_reason': 'thinking_exhausted'}
    accepted = broker.start({'profile': 'jaeger', 'session_id': 'halt', 'message': 'hi'})
    assert wait_done(broker, accepted['run_id'])['status'] == 'failed'
    assert broker.store.events_after(accepted['run_id'], None)['events'][-1]['event'] == 'apperror'


def test_default_profile_identity_survives_native_dispatch(broker):
    accepted = broker.start({'profile': 'default', 'session_id': 'default-ui', 'message': 'hi'})
    wait_done(broker, accepted['run_id'])
    done = next(e['payload'] for e in broker.store.events_after(accepted['run_id'], None)['events'] if e['event'] == 'done')
    assert done['session']['profile'] == 'default'
    assert broker.store.status(accepted['run_id'])['profile'] == 'hermes'


def test_roundtable_forwards_model_and_keeps_member_context_for_second_turn(broker):
    from jaeger_ai.features.roundtable.service import TableService
    seen = []
    def backend(run, workspace):
        seen.append((run.session, run.model, run.provider))
        return 'remembered answer'
    service = TableService(broker.store.root / 'profiles' / 'roundtable',
                           {member: backend for member in ('hermes', 'openclaw', 'jaeger')})
    broker.profiles.managers['roundtable'] = service
    for prompt in ('/quick @hermes remember', '/quick @hermes recall'):
        accepted = broker.start({'profile': 'roundtable', 'session_id': 'table-model',
            'message': prompt, 'model': '@ollama-cloud:chosen:cloud'})
        assert wait_done(broker, accepted['run_id'])['status'] == 'completed'
    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert seen[0][1:] == ('chosen:cloud', 'ollama')
    done = next(e['payload'] for e in broker.store.events_after(accepted['run_id'], None)['events'] if e['event'] == 'done')
    assert len(done['session']['messages']) == 4
