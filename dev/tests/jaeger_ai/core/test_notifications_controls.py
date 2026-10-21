"""Durable metadata-only notification projection; no OS/external delivery."""
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers


@pytest.mark.asyncio
async def test_notifications_privacy_preferences_read_cursor_and_scopes(tmp_path):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-note',metadata={'agent_id':'native:builder'})
    gateway.event_bus.publish('owned-note','approval.request',{'approval_id':'owned-approval','prompt':'PRIVATE BODY MUST NOT LEAK'})
    gateway.event_bus.publish('owned-note','task.updated',{'task':{'task_id':'owned-task','state':'failed','goal':'PRIVATE GOAL','error':'PRIVATE ERROR'}})
    gateway.event_bus.publish('owned-note','task.updated',{'task':{'task_id':'owned-task','state':'failed','goal':'PRIVATE GOAL'}})
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as client:
        response=await client.get('/v1/notifications');assert response.status==200
        data=await response.json()
        assert len(data['notifications'])==2 and all(n['unread'] for n in data['notifications'])
        assert 'PRIVATE' not in str(data) and data['privacy']=='metadata_only_no_message_preview'
        cursor=max(n['event_id'] for n in data['notifications'])
        assert (await client.patch('/v1/notifications',json={'read_through':cursor})).status==200
        assert not any(n['unread'] for n in (await (await client.get('/v1/notifications')).json())['notifications'])
        assert (await client.patch('/v1/notifications',json={'read_through':cursor+1000})).status==400
        saved=await client.patch('/v1/notifications',json={'expected_revision':0,'enabled':False,'muted_agent_ids':['native:builder']})
        assert saved.status==200 and (await saved.json())['preferences']['revision']==1
        assert (await client.patch('/v1/notifications',json={'expected_revision':0,'enabled':True,'muted_agent_ids':[]})).status==409
        assert (await client.patch('/v1/notifications',json={'expected_revision':1,'enabled':True,'muted_agent_ids':['does-not-exist']})).status==400
        result=await (await client.get('/v1/notifications')).json()
        assert result['preferences']['read_through']==cursor and result['notifications']==[]
        assert gateway.store.list_requests()==[] and gateway.store.list_pending_approvals()==[]
    reopened=GatewaySessionStore(gateway.store.path)
    from jaeger_ai.features.notifications.routes import feed
    assert feed(reopened)['preferences']==result['preferences']
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/notifications')).status==403
        assert (await client.patch('/v1/notifications',json={'read_through':0})).status==403


def test_notifications_follow_actual_terminal_and_handoff_producers(tmp_path):
    from jaeger_ai.features.notifications.routes import feed, NOTIFICATION_EVENTS
    from jaeger_ai.core.gateway.event_bus import EVENT_TYPES
    assert set(NOTIFICATION_EVENTS) <= EVENT_TYPES
    assert {'notifications.changed','mcp.changed'} <= EVENT_TYPES
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-origin',metadata={'agent_id':'native:builder'})
    gateway.store.admit_request('owned-origin','Private failed prompt',request_id='owned-failed')
    gateway.store.complete_request('owned-failed',status='failed',result={'error':'PRIVATE failure details'})
    gateway.store.admit_request('owned-origin','Private uncertain prompt',request_id='owned-unknown')
    gateway.store.complete_request('owned-unknown',status='execution_unknown',result={'error':'PRIVATE uncertain effect'})
    record=gateway.store.save_handoff({'id':'owned-handoff','request_id':'owned-child','from_agent_id':'native:builder','to_agent_id':'native:jaeger','parent_run_id':'owned-failed','session_id':'owned-origin','task':'PRIVATE handoff task','status':'completed','require_approval':False,'result':{'summary':'PRIVATE result'},'metadata':{}})
    gateway._publish_handoff('agent.handoff.finished',record)
    result=feed(gateway.store)
    titles={n['title'] for n in result['notifications']}
    assert {'Conversation failed','Conversation outcome unknown','Delegated work status changed'} <= titles
    assert 'PRIVATE' not in str(result)
    delegated=[n for n in result['notifications'] if n['title']=='Delegated work status changed']
    assert len(delegated)==1 and delegated[0]['session_id']=='owned-origin' and delegated[0]['status']=='completed'
    assert gateway.store.get_request('owned-unknown')['status']=='execution_unknown'
