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
        assert (await client.get('/v1/notifications?before=-1')).status==400
        assert (await client.get('/v1/notifications?category=not-a-category')).status==400
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


def test_notification_category_paging_and_observed_cursor_are_read_only(tmp_path):
    from jaeger_ai.features.notifications.routes import feed
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-paging',metadata={'agent_id':'native:builder'})
    for i in range(65):gateway.event_bus.publish('owned-paging','approval.request',{'approval_id':f'owned-{i}','prompt':'PRIVATE'})
    gateway.event_bus.publish('owned-paging','turn.unknown',{'request_id':'owned-uncertain','error':'PRIVATE'})
    first=feed(gateway.store,category='approvals')
    second=feed(gateway.store,category='approvals',before=first['next_before'])
    assert len(first['notifications'])==50 and len(second['notifications'])==15
    assert not ({n['event_id'] for n in first['notifications']}&{n['event_id'] for n in second['notifications']})
    assert first['observed_through']==second['observed_through']
    errors=feed(gateway.store,category='errors')
    assert len(errors['notifications'])==1 and errors['notifications'][0]['title']=='Conversation outcome unknown'
    assert 'PRIVATE' not in str(first) and first['preferences']['read_through']==0
    assert gateway.store.list_requests()==[] and gateway.store.list_pending_approvals()==[]
    with pytest.raises(ValueError):feed(gateway.store,category='not-a-category')
    with pytest.raises(ValueError):feed(gateway.store,before=-1)


def test_retained_unread_presence_is_not_a_total_or_false_absence_after_bounded_scan(tmp_path):
    from jaeger_ai.features.notifications.routes import feed
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'presence.db'))
    gateway.store.ensure_session('owned-presence',metadata={'agent_id':'native:builder'})
    assert feed(gateway.store)['retained_unread_presence']=='absent'
    gateway.event_bus.publish('owned-presence','approval.request',{'approval_id':'owned-old'})
    assert feed(gateway.store)['retained_unread_presence']=='present'
    assert feed(gateway.store,category='approvals')['retained_unread_presence']=='unknown'
    # Newer nonterminal task updates are deliberately not notification entries.
    # Capping500 cannot justify saying the older unread approval is absent.
    for index in range(500):gateway.event_bus.publish('owned-presence','task.updated',{'task':{'task_id':f'owned-running-{index}','state':'running'}})
    assert feed(gateway.store)['retained_unread_presence']=='unknown'
    page=feed(gateway.store);assert page['notifications']==[] and page['next_before']
    assert feed(gateway.store,before=page['next_before'])['retained_unread_presence']=='unknown'
    gateway.event_bus.publish('owned-presence','turn.failed',{'request_id':'owned-failed'})
    current=feed(gateway.store);assert current['retained_unread_presence']=='present'
    # Use the owner's existing preference mutation helper, no direct badge store.
    from jaeger_ai.features.notifications.routes import settings,write
    with gateway.store._immediate() as conn:
        value=settings(conn);value['read_through']=current['observed_through'];write(conn,value)
    assert feed(gateway.store)['retained_unread_presence']=='absent'
    gateway.event_bus.publish('owned-presence','approval.request',{'approval_id':'owned-new'})
    assert feed(gateway.store)['retained_unread_presence']=='present'
    with gateway.store._immediate() as conn:
        value=settings(conn);value['enabled']=False;write(conn,value)
    assert feed(gateway.store)['retained_unread_presence']=='absent'
