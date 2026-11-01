"""Terminal input -> real Gateway/agent/forms; only provider transport is scripted."""
import threading
import time

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway
from jaeger_ai.core.gateway.caller_auth import TOKEN_DIR_ENV, ensure_tokens
from jaeger_ai.core.gateway.client import GatewayTurnClient
from jaeger_ai.interfaces.tui.app import JaegerTUI

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


@pytest.mark.parametrize('answer', ['staging', None], ids=['answer', 'stop'])
def test_terminal_question_settles_original_gateway_turn(tmp_path, monkeypatch, answer):
    monkeypatch.setenv(TOKEN_DIR_ENV, str(tmp_path / 'tokens'))
    ensure_tokens()
    owned = OwnedGateway(tmp_path)
    worker = None
    tui = JaegerTUI(skip_model=True)
    tui._gateway_cancel_event = threading.Event()
    try:
        owned.start()
        client = GatewayTurnClient(owned.url, caller='cli')
        client.ensure_session(tui.session_id, title='TUI clarification contract', source='tui')
        result = {}

        def run():
            try:
                result.update(tui._execute_client_turn(client, 'CONTRACT-CLARIFY'))
            except Exception as exc:
                result['failure'] = repr(exc)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        deadline = time.monotonic() + 20
        while tui._pending_confirm is None and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert tui._pending_confirm is not None, result
        assert tui._pending_confirm['kind'] == 'clarify'
        if answer is None:
            assert tui._dispatch_slash('/stop') is False
        else:
            assert tui._resolve_pending_confirm(answer) is True
        worker.join(timeout=20)
        assert not worker.is_alive(), 'Original turn did not settle'
        assert 'failure' not in result, result
        forms = owned.request(f'/v1/sessions/{tui.session_id}/clarify?include_resolved=true')[1]['forms']
        assert len(forms) == 1
        if answer is None:
            assert result['cancelled'] is True
            assert forms[0]['answer'] is None
        else:
            assert result['text'] == 'CLARIFICATION-ANSWER-RECEIVED'
            assert result['error'] is None
            assert forms[0]['status'] == 'answered'
            assert forms[0]['answer'] == answer
        detail = owned.request(f'/v1/sessions/{tui.session_id}')[1]
        assert len([m for m in detail['messages'] if m['role'] == 'user']) == 1
    finally:
        tui._gateway_cancel_event.set()
        if tui._pending_confirm is not None:
            tui._pending_confirm['event'].set()
        if worker is not None:
            worker.join(timeout=3)
        owned.stop()


def test_shutdown_while_question_waits_releases_worker_without_answer(tmp_path, monkeypatch):
    """/quit (REPL shutdown) while a clarify form waits: the pending box is
    released with NO answer, the gateway cancel fires, and the worker thread
    unwinds — the TUI never fabricates an answer and never submits a second
    turn to unblock itself."""
    monkeypatch.setenv(TOKEN_DIR_ENV, str(tmp_path / 'tokens'))
    ensure_tokens()
    owned = OwnedGateway(tmp_path)
    tui = JaegerTUI(skip_model=True)
    tui._gateway_cancel_event = threading.Event()
    worker = None
    try:
        owned.start()
        client = GatewayTurnClient(owned.url, caller='cli')
        client.ensure_session(tui.session_id, title='TUI shutdown contract', source='tui')
        answers = []
        monkeypatch.setattr(client, 'answer_clarify', lambda *a: answers.append(a))
        result = {}

        def run():
            try:
                result.update(tui._execute_client_turn(client, 'CONTRACT-CLARIFY'))
            except Exception as exc:
                result['failure'] = repr(exc)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        deadline = time.monotonic() + 20
        while tui._pending_confirm is None and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert tui._pending_confirm is not None, result
        box = tui._pending_confirm
        # Simulate the REPL's _shutdown() path: cancel + release, no answer.
        tui._gateway_cancel_event.set()
        box['event'].set()
        worker.join(timeout=20)
        assert not worker.is_alive(), 'Worker hung after shutdown release'
        assert 'failure' not in result, result
        assert answers == [], 'Shutdown must never answer the form'
        assert result.get('cancelled') is True or result.get('execution_unknown') is True, result
        forms = owned.request(f'/v1/sessions/{tui.session_id}/clarify?include_resolved=true')[1]['forms']
        # The Gateway marks the form cancelled when the turn is cancelled —
        # the invariant is that it was never ANSWERED.
        assert len(forms) == 1 and forms[0]['status'] != 'answered' and forms[0]['answer'] is None
        detail = owned.request(f'/v1/sessions/{tui.session_id}')[1]
        assert len([m for m in detail['messages'] if m['role'] == 'user']) == 1
    finally:
        tui._gateway_cancel_event.set()
        if tui._pending_confirm is not None:
            tui._pending_confirm['event'].set()
        if worker is not None:
            worker.join(timeout=3)
        owned.stop()


def test_unknown_outcome_reported_without_replay(tmp_path, monkeypatch):
    """When the gateway reports execution_unknown, the TUI surfaces it
    truthfully and does NOT resubmit the turn (no duplicate user message)."""
    from jaeger_ai.core.gateway.client import TurnResult

    tui = JaegerTUI(skip_model=True)
    tui._gateway_cancel_event = threading.Event()
    client = GatewayTurnClient()
    submitted = []

    def stream(session, text, *, request_id, on_event):
        submitted.append((session, text, request_id))
        return TurnResult(request_id, 'execution_unknown', '')

    monkeypatch.setattr(client, 'stream_turn', stream)
    result = tui._execute_client_turn(client, 'do work')
    assert result['execution_unknown'] is True
    assert result['cancelled'] is False
    assert len(submitted) == 1, 'Unknown outcome must not trigger a replay turn'
