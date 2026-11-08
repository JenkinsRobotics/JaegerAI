"""Task Stop propagates through qualified handoffs without provider execution."""
import pytest
pytest_plugins = ('dev.tests.jaeger_ai.core.test_sessions_contract',)

@pytest.mark.asyncio
@pytest.mark.parametrize('later_attempt', [False, True])
async def test_task_stop_closes_owned_pending_handoff(gw, later_attempt):
    app, http = gw
    sid = app._ensure_agent_home('native:everyday')[0]
    tid = app.task_owner.submit('Synthetic parent', context={'source':'client',
        'session_id': sid, 'execution': {'caller':'owner:webui'}})['task_id']
    child_sid = 'task:' + tid
    rid = tid + ':0'
    app.store.admit_request(child_sid, 'Synthetic parent', request_id=rid,
        requested={'caller':'owner:webui'})
    response = await http.post('/v1/agents/native:builder/handoff', json={
        'task':'owned pending child', 'request_id':'pending-child',
        'parent_request_id':rid, 'session_id':child_sid, 'require_approval':True})
    assert response.status in (200,202), await response.text()
    child = await response.json()
    if later_attempt:
        app.store.complete_request(rid, status='completed', result={'halt_reason': 'yielded'})
        app.task_owner.store.update_task(tid, lambda task: task.payload.update(attempt=1))
        # No current request yet: the previous attempt still owns its child.
    assert await app.task_owner.cancel(tid)
    assert app.store.get_handoff(child['id'])['status'] == 'cancelled'

    approval = app.store.get_approval(child['approval_id'])
    assert approval['status'] == 'resolved'
    assert approval['decision'] == 'cancelled'


@pytest.mark.asyncio
@pytest.mark.parametrize(('later_attempt', 'dispatch_blocker'), [
    (False, None), (True, None), (True, 'disabled'),
    (True, 'removed'), (True, 'revoked_webhook'),
])
async def test_task_cannot_report_cancelled_until_owned_child_is_terminal(
        gw, later_attempt, dispatch_blocker, monkeypatch):
    from jaeger_ai.contract.handoffs import child_request_id
    from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session

    app, http = gw
    sid = app._ensure_agent_home('native:everyday')[0]
    tid = app.task_owner.submit('Synthetic parent with child', context={'source': 'client',
        'session_id': sid, 'execution': {'caller': 'owner:webui'}})['task_id']
    root_sid, root_rid = 'task:' + tid, tid + ':0'
    app.store.admit_request(root_sid, 'Synthetic parent', request_id=root_rid,
        requested={'caller': 'owner:webui'})
    response = await http.post('/v1/agents/native:builder/handoff', json={
        'task': 'owned live child', 'request_id': 'live-child',
        'parent_request_id': root_rid, 'session_id': root_sid, 'require_approval': True})
    assert response.status in (200, 202), await response.text()
    handoff = await response.json()
    child_sid = specialist_session(handoff['to_agent_id'], handoff['request_id'])
    child_rid = child_request_id(handoff['request_id'])
    app.store.ensure_session(child_sid, metadata={'handoff_id': handoff['id'],
        'agent_id': handoff['to_agent_id'], 'parent_session_id': root_sid})
    app.store.admit_request(child_sid, 'synthetic child', request_id=child_rid,
        requested={'caller': 'owner:webui', 'is_subordinate': True})
    if later_attempt:
        app.store.complete_request(root_rid, status='completed', result={'halt_reason': 'yielded'})
        app.task_owner.store.update_task(tid, lambda task: task.payload.update(attempt=1))
    response = await http.post('/v1/tasks/' + tid + '/cancel', json={})
    assert response.status == 200
    assert app._cancellations.is_cancelled(child_rid)
    assert app.store.get_handoff(handoff['id'])['metadata']['cancel_requested']
    app.store.complete_request(root_rid, status='cancelled', result={})
    await app.task_owner._execute(tid)
    task = app.task_owner.store.get_task(tid)
    assert task.state.value == 'paused'
    assert 'child' in task.error
    assert task.payload['cancellation_children'][0]['cancellation_confirmed'] is False
    app.store.complete_request(child_rid, status='cancelled', result={})
    if dispatch_blocker in {'disabled', 'removed'}:
        from types import SimpleNamespace
        agent = SimpleNamespace(disabled=True) if dispatch_blocker == 'disabled' else None
        monkeypatch.setattr(app, '_registry', lambda: SimpleNamespace(get_agent=lambda _: agent))
    elif dispatch_blocker == 'revoked_webhook':
        app.task_owner.store.update_task(tid, lambda task:
            task.provenance.update(webhook_subscription_id='revoked-test-subscription'))
        monkeypatch.setattr('jaeger_ai.features.webhooks.owner.execution_allowed', lambda *a, **k: False)
    monkeypatch.setattr(app, '_start_admitted_turn', lambda *a: pytest.fail('Cancellation must not redispatch'))
    if later_attempt:
        import asyncio
        await app.task_owner.tick()
        assert tid in app.task_owner._active
        await asyncio.gather(*list(app.task_owner._active.values()))
    else:
        await app.task_owner._execute(tid)
    assert app.task_owner.store.get_task(tid).state.value == 'cancelled'
    if later_attempt:
        assert app.store.get_request(tid + ':1') is None
