import io
import json

import pytest

from jaeger_ai.interfaces.hermes_profile_adapters import hermes_native, roundtable
from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import Run, Runs

RID = 'run_' + 'a' * 32


def wire(monkeypatch, events):
    calls = []
    monkeypatch.setattr(hermes_native, 'connection', lambda: ('http://native', 'private-key'))
    def open_request(req, **kwargs):
        calls.append(req)
        if req.full_url.endswith('/v1/runs'):
            return io.BytesIO(json.dumps({'run_id': RID}).encode())
        return io.BytesIO(b''.join(b'data: ' + json.dumps({'run_id': RID, **event}).encode() + b'\n\n' for event in events))
    monkeypatch.setattr(hermes_native, 'urlopen', open_request)
    return calls


def test_native_hermes_streams_tool_and_text_with_pinned_controls(monkeypatch, tmp_path):
    calls = wire(monkeypatch, [{'event': 'tool.started', 'tool': 'read'},
                               {'event': 'message.delta', 'delta': 'answer'},
                               {'event': 'run.completed'}])
    run = Run(tmp_path, 'session', 'question')
    assert hermes_native.hermes_turn(run) == 'answer'
    assert run.native == {'session_id': 'session', 'run_id': RID}
    assert not run.execution_unknown
    assert any(e['event'] == 'tool.started' for e in run.events)
    run.cancel_native()
    assert calls[-1].full_url == f'http://native/v1/runs/{RID}/stop'
    assert all(req.get_header('Authorization') == 'Bearer private-key' for req in calls)


@pytest.mark.parametrize('event', [None, {'event': 'message.delta', 'delta': 'partial'},
                                 {'event': 'run.completed', 'run_id': 'wrong-run'}])
def test_hermes_missing_or_wrong_terminal_is_unknown_not_success(monkeypatch, tmp_path, event):
    wire(monkeypatch, [] if event is None else [event])
    run = Run(tmp_path, 'session', 'question')
    with pytest.raises(RuntimeError): hermes_native.hermes_turn(run)
    assert run.execution_unknown


def test_roundtable_native_hermes_reuses_owned_session_without_cli(monkeypatch, tmp_path):
    seen = []
    def backend(run, workspace):
        seen.append(run.session)
        return f'answer {len(seen)}'
    runs = Runs(tmp_path, backend)
    monkeypatch.setattr(roundtable, '_native_hermes_runs', lambda: runs)
    monkeypatch.setenv('ROUNDTABLE_HERMES_NATIVE', '1')
    monkeypatch.setattr(roundtable, '_chat_hermes_cli', lambda *a: pytest.fail('No CLI replay'))
    assert roundtable.chat_hermes('first', 'a' * 32) == 'answer 1'
    assert roundtable.chat_hermes('second', 'a' * 32) == 'answer 2'
    assert seen == ['roundtable-hermes:' + 'a' * 32] * 2


def test_legacy_roundtable_denies_unpresentable_approval_and_reports_failure(monkeypatch, tmp_path):
    choices = []
    def backend(run, workspace):
        choices.append(run.request_approval('tool request'))
        return 'Tool was denied'
    monkeypatch.setenv('ROUNDTABLE_HERMES_NATIVE', '1')
    runs = Runs(tmp_path, backend)
    monkeypatch.setattr(roundtable, '_native_hermes_runs', lambda: runs)
    answer = roundtable.chat_hermes('test', 'a' * 32)
    assert choices == ['deny']
    assert answer.error_category == 'approval_required'
    assert roundtable._is_failed_answer(answer)
