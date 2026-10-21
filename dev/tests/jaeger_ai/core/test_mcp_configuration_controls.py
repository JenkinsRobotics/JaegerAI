"""Owner-only local MCP setup and original-operation recovery."""
import pytest

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.mcp import service

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.mark.asyncio
async def test_local_disabled_setup_owner_scope_recovery_no_replay(gw,tmp_path,monkeypatch):
    app,http=gw;root=tmp_path/'owned-mcp';root.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:root)
    path='/v1/runtime/mcp/configuration'
    assert (await http.get(path,headers=client_headers('jaegerd'))).status==403
    assert (await http.get(path,headers=client_headers('a2a'))).status==403
    initial=await (await http.get(path)).json();assert initial['config_revision']=='missing'
    body={'operation_id':'owned-mcp-stage','action':'stage','expected_revision':'missing','definition':{'name':'owned','command':'echo','args':['fixture']}}
    save=service.stage_disabled_server
    def lost_ack(*a,**k):save(*a,**k);raise RuntimeError('lost ack')
    monkeypatch.setattr(service,'stage_disabled_server',lost_ack)
    assert (await http.post(path+'/change',json=body)).status==503
    monkeypatch.setattr(service,'stage_disabled_server',lambda *a,**k:pytest.fail('Never replay'))
    receipt=await (await http.get(path+'/operations/'+body['operation_id'])).json()
    assert receipt['outcome']=='saved' and receipt['recovered'] and not receipt['connection_attempted']
    assert await (await http.post(path+'/change',json=body)).json()==receipt
    listing=await (await http.get(path)).json()
    assert listing['servers'][0]['startup_enabled'] is False
    startup={'operation_id':'owned-mcp-startup','action':'startup','expected_revision':listing['config_revision'],'name':'owned','enabled':True}
    assert (await (await http.post(path+'/change',json=startup)).json())['outcome']=='saved'
    stale={**startup,'operation_id':'owned-mcp-stale','enabled':False}
    assert (await (await http.post(path+'/change',json=stale)).json())['outcome']=='rejected'
    assert (await (await http.get(path)).json())['servers'][0]['startup_enabled'] is True


@pytest.mark.asyncio
async def test_divergent_lost_result_stays_unknown_and_blocks_fresh_intent(gw,tmp_path,monkeypatch):
    app,http=gw;root=tmp_path/'owned-mcp-diverged';root.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:root)
    path='/v1/runtime/mcp/configuration'
    body={'operation_id':'owned-mcp-uncertain','action':'stage','expected_revision':'missing','definition':{'name':'owned','url':'https://example.invalid/mcp'}}
    assert (await http.post(path+'/change',json=body,headers=client_headers('jaegerd'))).status==403
    save=service.stage_disabled_server;calls=[]
    def divergent_ack(*a,**k):
        calls.append(1);save(*a,**k)
        (root/'mcp.json').write_text('{"version":1,"servers":[]}')
        raise RuntimeError('unknown after edit')
    monkeypatch.setattr(service,'stage_disabled_server',divergent_ack)
    assert (await http.post(path+'/change',json=body)).status==503
    assert (await (await http.get(path+'/operations/'+body['operation_id'])).json())['outcome']=='unknown'
    assert (await (await http.post(path+'/change',json=body)).json())['outcome']=='unknown'
    assert (await http.post(path+'/change',json={**body,'operation_id':'owned-mcp-fresh'})).status==409
    assert calls==[1]
    assert (root/'mcp.json').read_text()=='{"version":1,"servers":[]}'
