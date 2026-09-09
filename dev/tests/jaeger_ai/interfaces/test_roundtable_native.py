import json
import re
import threading
import time

import pytest

from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import Run, TERMINAL
from jaeger_ai.interfaces.hermes_profile_adapters.roundtable_native import TableService, member_session
from jaeger_ai.interfaces.hermes_profile_adapters.roundtable_policy import MEMBERS, decide, plan, structured
from jaeger_ai.interfaces.hermes_profile_adapters.roundtable_progress import Progress


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.01)
    assert predicate()


def ballot(votes):
    return 'My position.\n```roundtable\n' + json.dumps({'ballot': votes}) + '\n```'


def fake_backends(callback=None):
    def make(member):
        def backend(run, workspace):
            run.dispatch(session_id=run.session, run_id=run.id)
            run.emit('native.state', state='running')
            if callback:
                result = callback(member, run)
                if result is not None:
                    return result
            ids = re.findall(r'"([a-f0-9]{32}:\w+)": "support\|oppose\|abstain"', run.message)
            return ballot({identity: 'support' for identity in ids}) if ids else member + ' answer'
        return backend
    return {member: make(member) for member in MEMBERS}


def finished(service, identity):
    run = service.get(identity)
    wait_for(lambda: not run.worker_active)
    return run


def test_each_native_member_streams_before_finishing_and_has_exactly_one_discussion(tmp_path):
    release = threading.Event()
    def callback(member, run):
        if 'before seeing peers' in run.message:
            run.emit('message.delta', delta=member + ' partial')
            assert release.wait(4)
    service = TableService(tmp_path, fake_backends(callback))
    parent = service.get(service.start('table', 'Question?')['run_id'])
    try:
        wait_for(lambda: len([e for e in parent.events if e['event'] == 'member.message.delta']) == 3)
        assert parent.status not in TERMINAL
        deltas = [e for e in parent.events if e['event'] == 'member.message.delta']
        assert {e['member'] for e in deltas} == set(MEMBERS)
        assert {e['run_id'] for e in deltas} == {parent.id}
        assert len({e['member_run_id'] for e in deltas}) == 3
    finally:
        release.set()
        finished(service, parent.id)
    assert parent.status == 'completed'
    assert '## Round 1 — Everyone Answers' in parent.output
    assert all('### ' + name in parent.output for name in ('Jaeger', 'Hermes', 'OpenClaw'))
    assert '## Round 2 — Discussion' in parent.output
    attempts = service.store.attempts(parent.id)
    assert [a['phase'] for a in attempts].count('discussion') == 3
    assert [a['phase'] for a in attempts].count('synthesis') == 1
    assert service.store.ledger(parent.id)['decision']['consensus']
    assert all(e['run_id'] == parent.id for e in parent.events)


def test_native_member_sessions_survive_new_table_turns_and_store_restart(tmp_path):
    sessions = []
    def callback(member, run):
        sessions.append((member, run.session))
    first = TableService(tmp_path, fake_backends(callback))
    finished(first, first.start('existing-table', '/quick @hermes remember this')['run_id'])
    second = TableService(tmp_path, fake_backends(callback))
    finished(second, second.start('existing-table', '/quick @hermes recall it')['run_id'])
    assert sessions == [('hermes', member_session('existing-table', 'hermes'))] * 2
    from jaeger_ai.interfaces.hermes_profile_adapters.roundtable import _member_session_id
    assert member_session('existing-table', 'jaeger') == _member_session_id('existing-table', 'jaeger')
    assert member_session('existing-table', 'hermes') == 'roundtable-hermes:' + _member_session_id('existing-table', 'hermes')


def test_chair_really_rotates_across_turns_and_service_restart(tmp_path):
    chairs = []
    for _ in range(4):
        service = TableService(tmp_path, fake_backends())
        parent = finished(service, service.start('rotating-table', 'Question?')['run_id'])
        chair = next(a['member'] for a in service.store.attempts(parent.id) if a['phase'] == 'synthesis')
        chairs.append(chair)
        assert service.store.last_chair('rotating-table') == chair
    assert set(chairs[:3]) == set(MEMBERS)
    assert chairs[0] == chairs[3]


def test_failure_isolated_and_retry_only_failed_member_preserves_session(tmp_path):
    calls = []
    fail = {'hermes': True}
    def callback(member, run):
        calls.append((member, run.session))
        if member == 'hermes' and fail['hermes']:
            run.execution_unknown = False  # Explicit native terminal failure.
            raise RuntimeError('native failure')
    service = TableService(tmp_path, fake_backends(callback))
    parent = finished(service, service.start('table', 'Question?')['run_id'])
    assert parent.status == 'completed'  # Orchestration completed with member failures.
    attempts = service.store.attempts(parent.id)
    failed = next(a for a in attempts if a['member'] == 'hermes')
    assert len([a for a in attempts if a['member'] == 'hermes']) == 1
    assert not service.store.ledger(parent.id)['decision']['consensus']
    fail['hermes'] = False
    before = len(calls)
    retry = finished(service, service.retry_member(parent.id, failed['id'])['run_id'])
    assert retry.status == 'completed'
    assert calls[before:] == [('hermes', failed['session'])]
    with pytest.raises(KeyError):
        service.retry_member(retry.id, failed['id'])


def test_unknown_member_cannot_be_replayed_after_observer_restart(tmp_path):
    def callback(member, run):
        raise ConnectionError('lost observer')
    service = TableService(tmp_path, fake_backends(callback))
    parent = finished(service, service.start('table', '/quick @openclaw question')['run_id'])
    assert parent.status == 'failed' and parent.execution_unknown
    attempt = service.store.attempts(parent.id)[0]
    recovered = TableService(tmp_path, fake_backends())
    with pytest.raises(RuntimeError, match='reconciled'):
        recovered.retry_member(parent.id, attempt['id'])
    with pytest.raises(RuntimeError, match='session_busy'):
        recovered.start('table', 'duplicate')


def test_approval_is_member_and_table_scoped(tmp_path):
    received = []
    def callback(member, run):
        received.append(run.request_approval('Harmless test tool', choices=('once', 'deny')))
        return 'done'
    service = TableService(tmp_path, fake_backends(callback))
    a = service.get(service.start('a', '/quick @jaeger test')['run_id'])
    b = service.get(service.start('b', '/quick @hermes test')['run_id'])
    wait_for(lambda: a.snapshot()['pending_approval_ids'] and b.snapshot()['pending_approval_ids'])
    aid, bid = a.snapshot()['pending_approval_ids'][0], b.snapshot()['pending_approval_ids'][0]
    try:
        with pytest.raises(KeyError): b.approve(aid, 'once')
        with pytest.raises(ValueError): a.approve(aid, 'always')
        a.approve(aid, 'once')
        b.approve(bid, 'deny')
        with pytest.raises(KeyError): a.approve(aid, 'once')
    finally:
        a.cancel()
        b.cancel()
        finished(service, a.id)
        finished(service, b.id)
    assert sorted(received) == ['deny', 'once']


def test_stop_one_member_does_not_stop_other_members(tmp_path):
    release = threading.Event()
    def callback(member, run):
        if 'before seeing peers' not in run.message:
            return None
        while not release.is_set() and not run.cancelled.wait(.01):
            pass
        if run.cancelled.is_set():
            run.cancel_confirmed = True
        return member + ' result'
    service = TableService(tmp_path, fake_backends(callback))
    parent = service.get(service.start('table', 'Question?')['run_id'])
    wait_for(lambda: len(parent.children) == 3)
    victim = parent.children['openclaw:answer']
    try:
        assert service.stop_member(parent.id, victim.id)
        wait_for(lambda: victim.status == 'cancelled')
        assert not parent.children['jaeger:answer'].cancelled.is_set()
        assert not parent.children['hermes:answer'].cancelled.is_set()
    finally:
        release.set()
        finished(service, parent.id)


@pytest.mark.parametrize('mode,first_phase,first_count', [('ask', 'answer', 3), ('vote', 'answer', 3),
    ('review', 'proposal', 1), ('collaborate', 'volunteer', 3), ('incident', 'incident', 3)])
def test_modes_use_distinct_workflows_and_persist_ledgers(tmp_path, mode, first_phase, first_count):
    service = TableService(tmp_path, fake_backends())
    parent = finished(service, service.start('table', '/' + mode + ' test')['run_id'])
    attempts = service.store.attempts(parent.id)
    assert len([a for a in attempts if a['phase'] == first_phase]) == first_count
    if mode in {'collaborate', 'incident'}:
        tasks = service.store.ledger(parent.id)['tasks']
        assert len(tasks) == 3
        assert {t['status'] for t in tasks} == {'response_received'}
    assert service.store.turn(parent.id)['decision'] is not None


def test_model_text_cannot_promote_itself_to_verified_evidence(tmp_path):
    def callback(member, run):
        return '[Verified] I inspected everything. Everyone agrees.'
    service = TableService(tmp_path, fake_backends(callback))
    parent = finished(service, service.start('table', 'Question?')['run_id'])
    ledger = service.store.ledger(parent.id)
    assert not ledger['evidence']
    assert not ledger['decision']['consensus']
    assert all(p['evidence_status'] == 'reported' for p in ledger['decision']['proposals'])


def test_progressing_turns_have_no_default_total_deadline_and_heartbeats_do_not_count():
    now = [0.]
    progress = Progress(clock=lambda: now[0])
    progress.observe({'event': 'native.state', 'state': 'running'})
    for second in (80, 160, 240, 320):
        now[0] = second
        progress.observe({'event': 'message.delta', 'delta': 'more'})
        assert progress.expired() is None
    now[0] = 441
    progress.observe({'event': 'heartbeat'})
    assert progress.expired() == 'idle_timeout'


@pytest.mark.parametrize('event,expected', [({'event': 'tool.started'}, 'tool_timeout'),
    ({'event': 'approval.request'}, 'approval_timeout'), ({'event': 'heartbeat'}, 'queue_timeout')])
def test_wait_states_have_separate_budgets(event, expected):
    now = [0.]
    progress = Progress({'queue': 3, 'tool': 4, 'approval': 5}, clock=lambda: now[0])
    progress.observe(event)
    now[0] = {'queue_timeout': 3, 'tool_timeout': 4, 'approval_timeout': 5}[expected]
    assert progress.expired() == expected


def test_ballots_require_explicit_agreement_and_keep_minorities():
    proposals = [{'id': 'p', 'owner': 'jaeger', 'text': 'proposal'}]
    discussion = {'jaeger': ballot({'p': 'support'}), 'hermes': ballot({'p': 'support'}),
                  'openclaw': ballot({'p': 'oppose'})}
    result = decide(MEMBERS, proposals, discussion)
    assert not result['consensus']
    assert result['proposals'][0]['outcome'] == 'majority'
    assert result['proposals'][0]['votes']['oppose'] == ['openclaw']
    discussion['openclaw'] = 'I agree with everyone.'
    assert decide(MEMBERS, proposals, discussion)['proposals'][0]['votes']['missing'] == ['openclaw']
    assert not structured(ballot({'p': 'support'}) + '\n' + ballot({'p': 'oppose'}))


def test_selection_and_muting_are_enforced_and_workspace_is_not_ignored(tmp_path):
    selected = plan('/quick @hermes test', {'members': ['hermes', 'openclaw'], 'muted': ['openclaw']})
    assert selected['participants'] == ['hermes']
    with pytest.raises(ValueError, match='muted'):
        plan('@openclaw test', {'muted': ['openclaw']})
    with pytest.raises(ValueError, match='Unknown'):
        plan('/imaginary test')
    service = TableService(tmp_path, fake_backends())
    with pytest.raises(ValueError, match='workspace'):
        service.start('table', 'hello', workspace='/workspace')


def test_no_global_consensus_when_another_proposal_has_dissent_or_is_truncated():
    proposals = [{'id': 'a', 'owner': 'jaeger', 'text': 'one'}, {'id': 'b', 'owner': 'hermes', 'text': 'two'}]
    discussion = {m: ballot({'a': 'support', 'b': 'oppose' if m == 'openclaw' else 'support'}) for m in MEMBERS}
    decision = decide(MEMBERS, proposals, discussion)
    assert decision['agreed_proposal_ids'] == ['a'] and not decision['consensus']
    assert decision['open_questions'] == [{'proposal_id': 'b', 'reason': 'majority'}]
    proposals[0]['truncated'] = True
    assert decide(MEMBERS, proposals, discussion)['agreed_proposal_ids'] == []


def test_volunteers_receive_unique_task_ownership_and_invalid_metadata_is_not_authority():
    from jaeger_ai.interfaces.hermes_profile_adapters.roundtable_policy import assign_owners
    offers = {'jaeger': '```roundtable\n{"volunteer_for":["review"]}\n```',
              'hermes': '```roundtable\n{"volunteer_for":["analysis"]}\n```',
              'openclaw': '```roundtable\n{"volunteer_for":null}\n```'}
    assignments = assign_owners(offers, list(MEMBERS))
    assert {a['task']: a['owner'] for a in assignments} == {
        'analysis': 'hermes', 'implementation': 'openclaw', 'review': 'jaeger'}
    # A fallback cannot steal the owner who volunteered for a later task.
    assert len({a['owner'] for a in assignments}) == 3
    assert assignments[1]['assignment_source'] == 'orchestrator'


def test_native_tool_receipt_is_attributed_without_verifying_arbitrary_prose(tmp_path):
    def callback(member, run):
        run.emit('tool.started', tool='read', args={'path': 'README.md'})
        run.emit('tool.completed', tool='read', status='completed', preview='actual result')
        return 'I also claim something unsupported.'
    service = TableService(tmp_path, fake_backends(callback))
    parent = finished(service, service.start('table', '/quick @jaeger inspect')['run_id'])
    evidence = service.store.ledger(parent.id)['evidence']
    assert len(evidence) == 1
    assert evidence[0]['owner'] == 'jaeger'
    assert evidence[0]['claim_scope'] == 'tool_execution_only'
    assert evidence[0]['result']['preview'] == 'actual result'


def test_member_stall_is_unknown_not_an_outage_and_does_not_rerun(tmp_path):
    release = threading.Event()
    calls = []
    def callback(member, run):
        calls.append(member)
        release.wait(3)
        return 'late result'
    service = TableService(tmp_path, fake_backends(callback))
    try:
        parent = finished(service, service.start('table', '/quick @jaeger test',
                         options={'budgets': {'idle': .05}})['run_id'])
        assert parent.status == 'failed' and parent.execution_unknown
        assert calls == ['jaeger']
        event = next(e for e in parent.events if e['event'] == 'member.stalled')
        assert event['error_category'] == 'idle_timeout'
        assert 'not an outage' in event['message']
    finally:
        release.set()
        for child in parent.children.values():
            wait_for(lambda: not child.worker_active)
    recovered = service.reconcile(parent.id)
    assert recovered['status'] == 'failed' and not recovered['execution_unknown']
    assert calls == ['jaeger']  # Reconcile observed, never replayed.


def test_actual_native_roundtable_http_contract_and_auth(tmp_path, monkeypatch):
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from jaeger_ai.interfaces.hermes_profile_adapters import roundtable, native_runs
    from jaeger_ai.interfaces.hermes_profile_adapters.ingress import ProfileHTTPServer
    service = TableService(tmp_path, fake_backends())
    monkeypatch.setenv('ROUNDTABLE_NATIVE_RUNS', 'true')
    monkeypatch.setattr(native_runs, 'profile_key', lambda _: 'test-only')
    monkeypatch.setattr(roundtable.RoundtableHandler, 'native_runs', lambda _: service)
    server = ProfileHTTPServer(('127.0.0.1', 0), roundtable.RoundtableHandler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    def request(path, body=None, token='test-only'):
        return urlopen(Request(f'http://127.0.0.1:{server.server_port}' + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}), timeout=3)
    try:
        with request('/v1/capabilities') as response:
            capabilities = json.load(response)
        assert capabilities['features']['member_events']
        assert len(capabilities['roundtable']['modes']) == 6
        with request('/v1/runs', {'session_id': 'table', 'input': 'Question?',
                     'roundtable': {'mode': 'quick', 'members': ['hermes']}}) as response:
            identity = json.load(response)['run_id']
        parent = finished(service, identity)
        assert parent.table['participants'] == ['hermes']
        with request(f'/v1/runs/{identity}/events') as response:
            text = response.read().decode()
        assert 'member.message.delta' in text
        assert 'data: [DONE]' in text
        with request(f'/v1/runs/{identity}/ledger') as response:
            ledger = json.load(response)
        assert len(ledger['attempts']) == 1
        with pytest.raises(HTTPError) as error:
            request(f'/v1/runs/{identity}/ledger', token='wrong')
        assert error.value.code == 401
        with pytest.raises(HTTPError) as error:
            request(f'/v1/runs/{identity}/members/{"f" * 32}/stop', {})
        assert error.value.code == 404
        from jaeger_ai.interfaces.hermes_profile_adapters.ingress import BodyReadTimeout
        def timed_out(_):
            raise BodyReadTimeout('Incomplete body')
        monkeypatch.setattr(roundtable.RoundtableHandler, 'read_json_body', timed_out)
        with pytest.raises(HTTPError) as error:
            request(f'/v1/runs/{identity}/members/{ledger["attempts"][0]["id"]}/stop', {})
        assert error.value.code == 408
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
