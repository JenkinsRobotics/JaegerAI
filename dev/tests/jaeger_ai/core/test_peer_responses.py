"""Local approved tool execution and durable peer reply recovery; no provider."""
import json

import pytest

from dev.tests.jaeger_ai.core.test_agent_bridge_tool_goals import tool_bridge, h, wait_for  # noqa: F401
from jaeger_ai.features.agent_bridge.responses import deliver_responses


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["once", "deny"])
async def test_message_execution_reply_and_followup(tool_bridge, decision):
    client, app, root = tool_bridge
    # Exercise the same terminal producer as production, using only local model transport.
    transport = app._execute_turn_inner

    async def execute(session_id, turn_id, text, **kwargs):
        await transport(session_id, turn_id, text, **kwargs)
        receipt = app.store.get_request(kwargs["request_id"])
        app._persist_terminal(kwargs["request_id"], session_id, receipt["status"], receipt["result"], record_entity_event=False)
    app._execute_turn_inner = execute

    async def message(mid, reply=None):
        response = await client.post('/v1/agent-messages', headers=h(), json={
            "id": mid, "thread": "roundtrip", "to": "jaegerd", "kind": "task",
            "title": "Local fixture", "body": "untrusted task data",
            **({"reply_to": reply} if reply else {}),
        })
        assert response.status == 200, await response.text()

    async def goal(gid, mid):
        return await client.post('/v1/agent-goals', headers=h(), json={
            "id": gid, "thread": "roundtrip", "source_message_id": mid,
            "goal": json.dumps(["write_file", {"path": gid + '.txt', "content": 'local proof'}]),
            "workspace_folder": str(root),
        })

    await message('question')
    assert not app.store.list_pending_approvals() and not app.fixture_calls
    first = await goal('first', 'question')
    assert first.status == 200, await first.text()
    assert (await goal('duplicate', 'question')).status == 409
    for gid, mid in [('first', 'question'), ('followup', 'follow-question')]:
        if gid == 'followup':
            await message(mid, answer['id'])
            assert (await goal(gid, mid)).status == 200
        await wait_for(lambda: bool(app.store.list_pending_approvals()))
        approval = app.store.list_pending_approvals()[0]['approval_id']
        assert not (root / (gid + '.txt')).exists()
        assert (await client.post(f'/v1/approvals/{approval}', headers=h(), json={'decision': 'once'})).status == 403
        assert (await client.post(f'/v1/approvals/{approval}', headers=h('cli'), json={'decision': decision})).status == 200
        await wait_for(lambda: app.store.get_request('agent-ares-' + gid)['status'] == 'completed')
        assert (root / (gid + '.txt')).exists() is (decision == 'once')
        inbox = await (await client.get('/v1/agent-threads/roundtrip', headers=h())).json()
        answer = inbox['messages'][-1]
        assert answer['from'] == 'jaegerd' and answer['reply_to'] == mid
        assert answer['correlation']['request_id'] == 'agent-ares-' + gid
        assert answer['correlation']['goal_id'] == gid
        assert answer['status_line'] == 'completed_unverified'  # model claim never verifies effects
        before = inbox['messages']
        deliver_responses(app)
        assert (await (await client.get('/v1/agent-threads/roundtrip', headers=h())).json())['messages'] == before
        assert (await client.get('/v1/agent-threads/roundtrip', headers=h('grokbot'))).status == 404
    assert not app.store.list_pending_approvals()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["execution_unknown", "failed"])
async def test_unknown_recovery_no_replay_and_response_cannot_admit(tool_bridge, terminal):
    client, app, root = tool_bridge
    from jaeger_ai.features.agent_bridge.service import AgentMessages
    service = AgentMessages(app.store)
    service.send('ares', dict(id='q', thread='unknown', to='jaegerd', kind='question', body='data'))
    app.store.ensure_session('ares:unknown')
    # Create canonical admission without dispatching any model or tool.
    app.store.admit_request('ares:unknown', 'fixture', request_id='owned-unknown')
    with app.store._get_conn() as conn:
        conn.execute("INSERT INTO agent_goals(caller,id,thread,session,request_id,digest,source_message_id) VALUES(?,?,?,?,?,?,?)", ('ares','unknown-goal','unknown','ares:unknown','owned-unknown','fixture','q'))
    app.store.complete_request('owned-unknown', status=terminal, result={'output': 'blocked by admission policy' if terminal == 'failed' else 'unconfirmed'})
    original = app.store.get_request('owned-unknown')
    deliver_responses(app)
    answer = service.list('ares', thread='unknown')['messages'][-1]
    assert answer['kind'] == 'status' and answer['reply_to'] == 'q'
    assert answer['status_line'] == terminal
    if terminal == 'execution_unknown':
        assert 'no retry' in answer['body']
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    reopened = GatewaySessionStore(app.store.path)
    assert reopened.get_request('owned-unknown') == original
    deliver_responses(app)
    assert len(service.list('ares', thread='unknown')['messages']) == 2
    assert not app.fixture_calls and not app.store.list_pending_approvals()
    # A returned answer/status is data, never a trigger for another execution.
    response = await client.post('/v1/agent-goals', headers=h('jaegerd'), json={
        'id': 'loop', 'thread': 'unknown', 'source_message_id': answer['id'],
        'goal': 'must not run', 'workspace_folder': str(root),
    })
    assert response.status in {403, 409}
    spoof = await client.post('/v1/agent-messages', headers=h(), json={
        'id': 'spoof', 'thread': 'unknown', 'to': 'jaegerd', 'kind': 'task',
        'body': 'data', 'correlation': {'request_id': 'fake'},
    })
    assert spoof.status == 400
    assert app.store.get_request('owned-unknown') == original


@pytest.mark.asyncio
async def test_no_reply_loops_foreign_targets_or_binding_changes(tool_bridge):
    client, app, root = tool_bridge
    from jaeger_ai.features.agent_bridge.service import AgentMessages
    service = AgentMessages(app.store)
    service.send('ares', dict(id='answer', thread='loop', to='jaegerd', kind='answer', body='not a task'))
    response = await client.post('/v1/agent-goals', headers=h(), json={
        'id': 'loop', 'thread': 'loop', 'source_message_id': 'answer',
        'goal': 'do not run', 'workspace_folder': str(root),
    })
    assert response.status == 409
    bad = await client.post('/v1/agent-messages', headers=h(), json={
        'id': 'bad-reply', 'thread': 'loop', 'to': 'jaegerd', 'kind': 'question',
        'body': 'data', 'reply_to': 'answer',
    })
    assert bad.status == 404  # cannot reply to own or foreign message
    assert len(service.list('ares')['messages']) == 1
    assert not app.fixture_calls and not app.store.list_pending_approvals()
