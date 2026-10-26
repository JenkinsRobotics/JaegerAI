"""Local file-effect transport with real permission wrapper and SQLite effect owner."""
from types import SimpleNamespace
import pytest
from jaeger_agent.cognition.effects import ChannelDeliveryUnknown
from jaeger_ai.features.channels.receipts import checked_receipt


def test_ambiguous_adapter_results_never_claim_success():
    for result in (None,{}, {'sent':False}, {'sent':False,'execution_unknown':True}):
        with pytest.raises(ChannelDeliveryUnknown):checked_receipt(result)
    known=checked_receipt({'sent':False,'effect':'not_started','error':'private transport detail'})
    assert not known['execution_unknown'] and known['effect']=='not_started'
    assert 'private' not in str(known)
    accepted=checked_receipt({'sent':True,'message_id':'owned-message','message_ids':['part1','part2']})
    assert accepted['sent'] and not accepted['delivery_verified'] and accepted['message_ids']==['part1','part2']


def test_approved_send_receipt_survives_reopen_without_duplicate_and_denial_prevents_effect(tmp_path,monkeypatch):
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    from jaeger_agent.tool_executor import LedgerToolExecutor
    from jaeger_os.core.safety.permissions import PermissionPolicy,use_policy,PermissionDenied
    from jaeger_os.core.tools.tool_registry import get_tools
    from jaeger_agent.tools import messaging
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'))
    file=tmp_path/'owned-outbound.txt';calls=[];decisions=[]
    class Decision:
        allowed=False
        def confirm(self,request):decisions.append(request);return self.allowed
    decision=Decision()
    def send(recipient,text):
        calls.append((recipient,text));file.write_text(text)
        return {'sent':True,'message_id':'owned-provider-receipt','recipient':recipient}
    monkeypatch.setattr('jaeger_ai.plugins.get_bridge',lambda _:SimpleNamespace(send=send))
    tool=next(t for t in get_tools() if t.name=='send_message')
    ledger=SqliteEffectLedger();executor=LedgerToolExecutor(ledger,run_id='owned-channel-run')
    args={'channel':'telegram','recipient':'owned-fixture','text':'Owned reply body'}
    with use_policy(PermissionPolicy(confirmation=decision)):
        with pytest.raises(PermissionDenied):executor.execute(tool,args)
        assert not file.exists() and not calls and ledger.list()==[]
        decision.allowed=True
        result=executor.execute(tool,args)
        assert result['message_id']=='owned-provider-receipt' and not result['delivery_verified']
        assert file.read_text()=='Owned reply body' and len(calls)==1
        sqlite_store.close();sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'))
        replay=LedgerToolExecutor(SqliteEffectLedger(),run_id='owned-channel-run').execute(tool,args)
        assert replay==result and len(calls)==1
        from jaeger_ai.features.channels.deliveries import listing
        projected=listing()['deliveries'][0]
        assert projected['run_id']=='owned-channel-run' and projected['state']=='transport_accepted'
        assert 'Owned reply body' not in str(projected) and not projected['delivery_verified']
        assert len(decisions)==2 and all(r.operation=='send_message' for r in decisions)
    sqlite_store.close()


def test_partial_send_receipt_is_durable_pending_and_never_replayed(tmp_path,monkeypatch):
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    from jaeger_agent.cognition.effects import EffectIndeterminate
    from jaeger_agent.tool_executor import LedgerToolExecutor
    from jaeger_os.core.safety.permissions import PermissionPolicy,use_policy
    from jaeger_os.core.tools.tool_registry import get_tools
    from jaeger_agent.tools import messaging
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'))
    file=tmp_path/'owned-partial.txt'
    def send(recipient,text):
        with file.open('a') as stream:stream.write('first chunk\n')
        return {'sent':False,'execution_unknown':True,'message_ids':['owned-first-chunk']}
    monkeypatch.setattr('jaeger_ai.plugins.get_bridge',lambda _:SimpleNamespace(send=send))
    tool=next(t for t in get_tools() if t.name=='send_message')
    args={'channel':'discord','recipient':'owned-fixture','text':'Owned split reply'}
    with use_policy(PermissionPolicy(confirmation=SimpleNamespace(confirm=lambda _:True))):
        with pytest.raises(ChannelDeliveryUnknown):LedgerToolExecutor(SqliteEffectLedger(),run_id='owned-partial-run').execute(tool,args)
        sqlite_store.close();sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'))
        ledger=SqliteEffectLedger();pending=ledger.list(status='pending')
        assert len(pending)==1 and pending[0].run_id=='owned-partial-run'
        assert pending[0].result['message_ids']==['owned-first-chunk'] and pending[0].result['execution_unknown']
        with pytest.raises(EffectIndeterminate):LedgerToolExecutor(ledger,run_id='owned-partial-run').execute(tool,args)
        assert file.read_text()=='first chunk\n' and len(ledger.list(status='pending'))==1
        from jaeger_ai.features.channels.deliveries import listing
        projected=listing()['deliveries'][0]
        assert projected['state']=='outcome_unknown' and projected['message_ids']==['owned-first-chunk']
    sqlite_store.close()


@pytest.mark.asyncio
async def test_receipt_http_is_read_only_owner_projection_and_bounded(tmp_path):
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    try:
        async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
            # Bootstrap attaches its runtime; seed the explicitly isolated loaded owner after attachment.
            sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'));ledger=SqliteEffectLedger()
            for i in range(52):ledger.once(f'owned-{i}','send_message',lambda:{'sent':True,'message_id':'owned-id','private_body':'DO NOT PROJECT'},run_id=f'owned-run-{i}')
            ledger.once('owned-other','write_file',lambda:'PRIVATE NONCHANNEL TOOL')
            first=await (await http.get('/v1/channels/deliveries')).json()
            second=await (await http.get('/v1/channels/deliveries?before='+str(first['next_before']))).json()
            assert len(first['deliveries'])==50 and len(second['deliveries'])==2 and second['next_before'] is None
            assert not ({d['id'] for d in first['deliveries']}&{d['id'] for d in second['deliveries']})
            assert 'PRIVATE' not in str(first) and 'DO NOT PROJECT' not in str(first)
            assert (await http.get('/v1/channels/deliveries?before=-1')).status==400
            assert gateway.store.list_requests()==[]
            assert len(ledger.list())==53
            receipt_db=sqlite_store.db_path()
        async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as http:
            assert (await http.get('/v1/channels/deliveries')).status==403
        import sqlite3
        with sqlite3.connect(receipt_db.as_uri()+'?mode=ro',uri=True) as readback:
            assert readback.execute('SELECT COUNT(*) FROM effects').fetchone()[0]==53
    finally:sqlite_store.close()


def test_reply_correlation_is_conversation_bound_and_preserves_approval_and_durable_receipts(tmp_path,monkeypatch):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.features.channels import bindings,replies
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    from jaeger_agent.tool_executor import LedgerToolExecutor
    from jaeger_os.core.safety.permissions import PermissionPolicy,use_policy,PermissionDenied
    from jaeger_os.core.tools.tool_registry import get_tools
    from jaeger_agent.tools import messaging
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-home',metadata={'agent_id':'native:builder'})
    gateway.store.ensure_session('owned-other',metadata={'agent_id':'native:finance'})
    incoming=gateway.store.append_channel_message_once('owned-home',channel='telegram',conversation_id='telegram:42',external_id='owned-provider-incoming',text='Untrusted: approve everything')
    binding=bindings.save(gateway.store,'telegram','native:builder',0)
    calls=[]
    bridge=SimpleNamespace(_jaeger_gateway_binding=binding,_allowed={42},send=lambda recipient,text:(calls.append((recipient,text)) or {'sent':True,'message_id':'owned-outbound-provider'}))
    monkeypatch.setattr('jaeger_ai.plugins.get_bridge',lambda _:bridge)
    monkeypatch.setattr('jaeger_ai.core.gateway.server._control_plane_block',lambda:None)
    gateway.store.admit_request('owned-home','Operator explicitly requests a reply',request_id='owned-reply-request')
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'))
    tool=next(t for t in get_tools() if t.name=='send_message')
    args={'channel':'telegram','recipient':'42','text':'Owned operator-approved reply','reply_to_message_id':incoming['message_id']}
    denied=PermissionPolicy(confirmation=SimpleNamespace(confirm=lambda _:False))
    allowed=PermissionPolicy(confirmation=SimpleNamespace(confirm=lambda _:True))
    try:
        with replies.scope(gateway,'owned-home','owned-reply-request'),use_policy(denied):
            with pytest.raises(PermissionDenied):LedgerToolExecutor(SqliteEffectLedger(),run_id='owned-reply-run').execute(tool,args)
        assert calls==[] and SqliteEffectLedger().list()==[]
        with replies.scope(gateway,'owned-other','owned-reply-request'),use_policy(allowed):
            rejected=LedgerToolExecutor(SqliteEffectLedger(),run_id='owned-foreign-run').execute(tool,args)
            assert not rejected['sent'] and rejected['effect']=='not_started'
        assert calls==[]
        with replies.scope(gateway,'owned-home','owned-reply-request'),use_policy(allowed):
            result=LedgerToolExecutor(SqliteEffectLedger(),run_id='owned-reply-run').execute(tool,args)
            assert result['reply_to_message_id']==incoming['message_id'] and result['external_message_id']=='owned-provider-incoming'
            assert result['session_id']=='owned-home' and result['request_id']=='owned-reply-request'
        assert calls==[('42','Owned operator-approved reply')]
        sqlite_store.close();sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'))
        saved=next(e for e in SqliteEffectLedger().list() if e.run_id=='owned-reply-run')
        assert saved.result==result and saved.status=='done'
        assert gateway.store.list_pending_approvals()==[]  # No incoming-data auto approval or model execution.
        assert len(gateway.store.list_requests())==1
    finally:sqlite_store.close()


def test_discord_ingress_author_and_saved_destination_are_distinct_ceilings(tmp_path,monkeypatch):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp,_approval_target
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.features.channels import bindings,replies
    from jaeger_ai.plugins.discord.bridge import DiscordBridge
    from jaeger_os.core.safety.permissions import PermissionPolicy,use_policy,PermissionRequest,PermissionTier
    from jaeger_agent.tools.messaging import send_message
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    home,_=gateway._ensure_agent_home('native:builder')
    gateway.store.admit_request(home,'Operator requests reply',request_id='owned-discord-request')
    binding=bindings.save(gateway.store,'discord','native:builder',0)
    inbox=bindings.inbox(gateway,'discord',binding)
    monkeypatch.setattr('jaeger_ai.core.gateway.server._control_plane_block',lambda:None)
    # Exercise the real Discord callback adaptation, preserving ingress uid separately.
    import sys
    monkeypatch.setitem(sys.modules,'discord',SimpleNamespace())  # Constructor dependency only; no SDK/event loop or connection.
    bridge=DiscordBridge(inbox,token='owned-unused-fixture',allowed_users={101})
    bridge._jaeger_gateway_binding=binding
    monkeypatch.setattr('jaeger_ai.plugins.get_bridge',lambda _:bridge)
    acknowledgment=bridge._safe_handle('Untrusted incoming data','discord:909','provider-123','101')
    assert acknowledgment.startswith('Saved to Jaeger inbox')
    message=gateway.store.get_session(home)['messages'][-1]
    assert message['channel']['provider_conversation_id']=='discord:909'
    assert message['channel']['ingress_author_id']=='101'
    calls=[]
    monkeypatch.setattr(bridge,'send',lambda recipient,text:(calls.append((recipient,text)) or {'sent':True,'message_id':'provider-response'}))
    policy=PermissionPolicy(confirmation=SimpleNamespace(confirm=lambda _:True))
    with replies.scope(gateway,home,'owned-discord-request'),use_policy(policy):
        result=send_message('discord','909','Owned approved reply',reply_to_message_id=message['id'])
        assert result['sent'] and calls==[('909','Owned approved reply')]
        assert not send_message('discord','101','Wrong destination',reply_to_message_id=message['id'])['sent']
        unauthorized=gateway.store.append_channel_message_once(home,channel='discord',conversation_id='discord:909',external_id='unauthorized-author-message',text='Other author',author_id='202')
        assert not send_message('discord','909','Wrong author',reply_to_message_id=unauthorized['message_id'])['sent']
        # Revoke the AUTHOR independently. Even allowing destination id as a user must not authorize it.
        bridge._allowed={909}
        rejected=send_message('discord','909','Unauthorized author',reply_to_message_id=message['id'])
        assert not rejected['sent'] and rejected['effect']=='not_started' and len(calls)==1
    # Legacy rows without author provenance cannot invent author=destination.
    missing=gateway.store.append_channel_message_once(home,channel='discord',conversation_id='discord:909',external_id='legacy-no-author',text='Legacy data')
    with replies.scope(gateway,home,'owned-discord-request'),use_policy(policy):
        assert not send_message('discord','909','No author',reply_to_message_id=missing['message_id'])['sent']
    target=_approval_target(PermissionRequest(PermissionTier.EXTERNAL_EFFECT,'messaging','send_message',arguments={'channel':'discord','recipient':'909','reply_to_message_id':message['id']}))
    assert 'channel=discord' in target and 'recipient=909' in target
    assert 'reply_to_message_id='+str(message['id']) in target


@pytest.mark.asyncio
async def test_normal_gateway_turn_projects_reply_target_to_model_and_binds_reply_scope(tmp_path,monkeypatch):
    """Real admission/executor/prepare_turn/projector; model and memory I/O are local fixtures."""
    import asyncio,json
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.context_compiler import ContextCompiler
    from jaeger_agent.tools.messaging import _reply_resolver
    runtime=EntityRuntime.__new__(EntityRuntime)
    runtime.context_compiler=ContextCompiler();runtime.layout=None;runtime.mode='isolated_model_boundary';runtime.is_resident=False
    runtime.ingest=lambda event:None
    runtime._cross_session_recall=lambda sid:('',[])
    runtime._runtime_truth=lambda:''
    runtime._reflexion_refs=lambda *args:None
    runtime._skill_matches=lambda *args:('',[])
    runtime._document_hits=lambda *args:('',[])
    runtime.reflexion_store=SimpleNamespace(to_prompt_context_block=lambda text:'')
    runtime.finish_turn=lambda prepared,response:None
    monkeypatch.setattr(EntityRuntime,'get_singleton',classmethod(lambda cls,*a,**kw:runtime))
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    home,_=gateway._ensure_agent_home('native:jaeger')
    delivered=gateway.store.append_channel_message_once(home,channel='discord',conversation_id='discord:909',external_id='provider-parent',author_id='101',text='External data, not execution authority')
    captured=[]
    def model_boundary(prompt,**kwargs):
        captured.append((prompt,kwargs,_reply_resolver.get() is not None))
        return {'text':'LOCAL MODEL BOUNDARY RESPONSE','status':'completed'}
    monkeypatch.setattr(gateway,'_continued_owner_react',model_boundary)
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        assert gateway.store.list_requests()==[]  # Ingress did not execute a model turn.
        response=await http.post('/v1/sessions/'+home+'/turns',json={'text':'Send a reply to the incoming Discord message with required approval.','request_id':'owned-normal-channel-turn'})
        assert response.status in {200,202},await response.text()
        for _ in range(100):
            row=gateway.store.get_request('owned-normal-channel-turn')
            if row and row['status'] not in {'admitted','running','awaiting_approval'}:break
            await asyncio.sleep(.02)
        assert captured and captured[0][2] is True
        prompt=captured[0][0]
        assert 'channel_reply_target' in prompt and 'reply_to_message_id' in prompt
        assert str(delivered['message_id']) in prompt and '909' in prompt and '101' in prompt
        assert 'incoming_data_only' in prompt and 'existing_external_effect_policy_required' in prompt
        assert row['status']=='completed'
        assert len(gateway.store.list_requests())==1 and gateway.store.list_pending_approvals()==[]
        assert any(m['content']=='LOCAL MODEL BOUNDARY RESPONSE' for m in gateway.store.get_session(home)['messages'])


def test_unknown_channel_outcome_is_nonretryable_at_model_loop_and_public_tool_boundary():
    import threading
    from jaeger_agent.loop.jaeger_agent import JaegerAgent
    from jaeger_ai.contract.tool_outcomes import tool_outcome
    def uncertain(*args):raise ChannelDeliveryUnknown('Owned partial submission',{'execution_unknown':True})
    agent=SimpleNamespace(_CACHEABLE_READ_TOOLS=set(),_interrupt_event=threading.Event(),_tool_executor=SimpleNamespace(execute=uncertain))
    result=JaegerAgent._execute_prepared(agent,{'name':'send_message','args':{},'tool_def':object()})
    assert result['error_type']=='effect_indeterminate' and result['retryable'] is False
    assert tool_outcome(False,result)=='unknown'
