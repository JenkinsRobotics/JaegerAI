"""No live bridge or native model is contacted by these contract tests."""
from contextlib import contextmanager
import json
import pytest

from jaeger_ai.features.webui.adapter.bridge_client import BridgeClient


@pytest.mark.parametrize('flag', [True, False])
def test_bridge_client_does_not_discard_execution_uncertainty(monkeypatch, flag):
    @contextmanager
    def connection(self):
        yield None, iter([json.dumps({'type': 'reply', 'text': 'result', 'execution_unknown': flag})])
    monkeypatch.setattr(BridgeClient, '_connection', connection)
    monkeypatch.setattr(BridgeClient, '_ready', staticmethod(lambda _: {}))
    monkeypatch.setattr(BridgeClient, '_write', staticmethod(lambda *args: None))
    assert BridgeClient('jaeger').turn('hi', 'session')['execution_unknown'] is flag


def test_recovery_query_has_bounded_handshake_and_response_wait(monkeypatch):
    waits, requests = [], []
    class Socket:
        def settimeout(self, value): waits.append(value)
    def response():
        yield json.dumps({'type': 'result', 'id': requests[0]['id'], 'ok': True, 'data': {'status': 'unknown'}})
    @contextmanager
    def connection(self):
        yield Socket(), response()
    def ready(_):
        assert waits == [10]
        return {}
    monkeypatch.setattr(BridgeClient, '_connection', connection)
    monkeypatch.setattr(BridgeClient, '_ready', staticmethod(ready))
    monkeypatch.setattr(BridgeClient, '_write', staticmethod(lambda rx, frame: requests.append(frame)))
    result = BridgeClient('jaeger').query('turn_status', {'turn_id': 'original'}, timeout_s=10)
    assert result == {'status': 'unknown'}
    assert requests[0]['op'] == 'query'  # Observation only, never send/replay.


def test_bridge_client_preserves_structured_halt(monkeypatch):
    @contextmanager
    def connection(self):
        yield None, iter([json.dumps({'type': 'reply', 'text': 'stopped',
            'halt_reason': 'repeated failures', 'halt_code': 'repeated_tool_failure'})])
    monkeypatch.setattr(BridgeClient, '_connection', connection)
    monkeypatch.setattr(BridgeClient, '_ready', staticmethod(lambda _: {}))
    monkeypatch.setattr(BridgeClient, '_write', staticmethod(lambda *args: None))
    reply = BridgeClient('jaeger').turn('task', 'dispatcher')
    assert reply['halt_reason'] == 'repeated failures'
    assert reply['halt_code'] == 'repeated_tool_failure'


def test_bridge_forwards_empty_tool_grant_instead_of_omitting_it(monkeypatch):
    frames = []
    @contextmanager
    def connection(self):
        yield None, iter([json.dumps({'type': 'reply', 'text': 'done'})])
    monkeypatch.setattr(BridgeClient, '_connection', connection)
    monkeypatch.setattr(BridgeClient, '_ready', staticmethod(lambda _: {}))
    monkeypatch.setattr(BridgeClient, '_write', staticmethod(lambda rx, frame: frames.append(frame)))
    BridgeClient('jaeger').turn('task', 'specialist:test', turn_id='receipt', allowed_tools=[])
    assert frames[0]['allowed_tools'] == [] and frames[0]['turn_id'] == 'receipt'
