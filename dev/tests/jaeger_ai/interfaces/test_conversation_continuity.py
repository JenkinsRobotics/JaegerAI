"""Cross-client admission and durable transcript/control invariants."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time
import uuid

import pytest

from jaeger_ai.core.runtime.dispatcher import DispatcherStore
from jaeger_ai.core.sessions import SessionStore
from jaeger_ai.interfaces.hermes_profile_adapters.conversation import Conversation
from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import Runs, Run


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Native worker did not reach expected state')


def test_history_identity_survives_reopen_and_does_not_merge_focus(tmp_path):
    path = tmp_path / 'sessions.db'
    history = SessionStore(path)
    history.record('dispatcher', 'user', 'from browser')
    history.record('focus:one', 'user', 'separate')
    history.record('dispatcher', 'assistant', 'answer')
    first = history.conversation_snapshot('dispatcher')
    history.close()
    reopened = SessionStore(path)
    assert reopened.conversation_snapshot('dispatcher') == first
    reopened.record('dispatcher', 'user', 'from desktop')
    last = reopened.conversation_snapshot('dispatcher')
    assert last['messages'][:2] == first['messages']
    assert last['revision'] != first['revision']
    assert len({m['id'] for m in last['messages']}) == 3
    reopened.close()


def test_concurrent_client_retry_executes_once_and_survives_restart(tmp_path):
    release = threading.Event()
    calls = []
    def backend(run, workspace):
        calls.append(run.id)
        release.wait(3)
        return 'done'
    store = DispatcherStore(SimpleNamespace(memory_dir=tmp_path / 'memory'))
    runs = Runs(tmp_path / 'runs', backend)
    conversation = Conversation(store, runs, lambda: {'messages': [], 'revision': '0'})
    body = {'request_id': uuid.uuid4().hex, 'input': 'one task'}
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: conversation.start(body), range(4)))
        assert {r['run_id'] for r in results} == {body['request_id']}
        assert calls == [body['request_id']]
        with pytest.raises(ValueError, match='different input'):
            conversation.start({**body, 'input': 'different task'})
        with pytest.raises(RuntimeError):
            conversation.start({**body, 'request_id': uuid.uuid4().hex})
    finally:
        release.set()
    wait_for(lambda: runs.get(body['request_id']).status == 'completed')
    reopened = Conversation(store, Runs(tmp_path / 'runs', backend), lambda: {'messages': [], 'revision': '0'})
    assert reopened.start(body)['status'] == 'completed'
    assert calls == [body['request_id']]


def test_other_client_can_observe_partial_and_answer_same_approval(tmp_path):
    def backend(run, workspace):
        run.emit('message.delta', delta='working')
        answer = run.request_approval('Read a bounded file?', choices=('once', 'deny'))
        return answer
    store = DispatcherStore(SimpleNamespace(memory_dir=tmp_path / 'memory'))
    store.bind_dispatcher('browser-session')
    runs = Runs(tmp_path / 'runs', backend)
    desktop = Conversation(store, runs, lambda: {'messages': [], 'revision': '0'})
    browser = Conversation(store, runs, lambda: {'messages': [], 'revision': '0'})
    admitted = desktop.start({'request_id': uuid.uuid4().hex, 'input': 'read'})
    wait_for(lambda: bool(browser.snapshot()['run']['approvals']))
    snapshot = browser.snapshot()['run']
    assert snapshot['run_id'] == admitted['run_id'] and snapshot['output'] == 'working'
    browser.control('approval', {'run_id': admitted['run_id'], 'approval_id': snapshot['approvals'][0]['approval_id'], 'choice': 'deny'})
    wait_for(lambda: runs.get(admitted['run_id']).status == 'completed')
    assert desktop.snapshot()['run']['output'] == 'deny'
    assert not desktop.snapshot()['run']['active']


def test_controls_cannot_target_focus_and_cancel_requires_native_confirmation(tmp_path):
    release = threading.Event()
    def backend(run, workspace):
        release.wait(3)
        if run.cancelled.is_set():
            run.cancel_confirmed = True
        return 'finished'
    store = DispatcherStore(SimpleNamespace(memory_dir=tmp_path / 'memory'))
    runs = Runs(tmp_path / 'runs', backend)
    conversation = Conversation(store, runs, lambda: {'messages': [], 'revision': '0'})
    focus = runs.start('focus', 'separate')
    own = conversation.start({'request_id': uuid.uuid4().hex, 'input': 'task'})
    try:
        with pytest.raises(KeyError):
            conversation.control('cancel', {'run_id': focus['run_id']})
        cancelled = conversation.control('cancel', {'run_id': own['run_id']})
        assert cancelled['status'] == 'cancelling'
        assert not cancelled['cancellation_confirmed']
        assert cancelled['active']
    finally:
        release.set()
    wait_for(lambda: runs.get(own['run_id']).status == 'cancelled')
    assert conversation.snapshot()['run']['cancellation_confirmed']


def test_restart_marks_unknown_execution_and_never_replays(tmp_path):
    root = tmp_path / 'runs'
    root.mkdir()
    orphan = Run(root, 'dispatcher', 'already dispatched')
    orphan.execution_unknown = True
    orphan.persist()
    calls = []
    runs = Runs(root, lambda run, workspace: calls.append(run.id))
    store = DispatcherStore(SimpleNamespace(memory_dir=tmp_path / 'memory'))
    observer = Conversation(store, runs, lambda: {'messages': [], 'revision': '0'})
    snapshot = observer.snapshot()['run']
    assert snapshot['status'] == 'interrupted'
    assert snapshot['needs_reconciliation'] and snapshot['active']
    assert calls == []
    with pytest.raises(RuntimeError, match='reconcile'):
        observer.control('cancel', {'run_id': orphan.id})


def test_first_approval_answer_wins_across_clients(tmp_path):
    run = Run(tmp_path, 'dispatcher', 'task')
    run.pending['approval'] = {'choices': ['once', 'deny'], 'answer': None}
    run.approve('approval', 'deny')
    with pytest.raises(KeyError, match='no longer active'):
        run.approve('approval', 'once')
    assert run.pending['approval']['answer'] == 'deny'
    assert Conversation.receipt(run)['pending_approval_ids'] == []
