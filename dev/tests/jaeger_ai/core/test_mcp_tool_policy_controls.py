"""Owner HTTP filtering, exact prior-receipt restore and lost-ACK recovery."""
import json

import pytest

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.mcp import service

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.mark.asyncio
async def test_policy_recovery_restores_only_exact_owned_baseline_and_no_live_connection(gw,tmp_path,monkeypatch):
    app,http=gw;root=tmp_path/'owned-policy';root.mkdir();monkeypatch.setattr(app,'_instance_root',lambda:root)
    data={'version':1,'servers':[{'name':'owned','command':'never-run','enabled':False,'tools':{'include':[],'exclude':[],'read_only':['read_one'],'gated':True},'headers':{'Authorization':{'secret_ref':'retained-owned-ref'}}}]}
    (root/'mcp.json').write_text(json.dumps(data));path='/v1/runtime/mcp/configuration'
    listing=await (await http.get(path)).json();revision=listing['config_revision']
    policy={'include':[],'exclude':['write_one'],'gated':True}
    body={'operation_id':'owned-tool-policy','action':'policy','name':'owned','expected_revision':revision,'policy':policy}
    assert (await http.post(path+'/change',json=body,headers=client_headers('a2a'))).status==403
    assert (await http.post(path+'/change',json=body,headers=client_headers('jaegerd'))).status==403
    mutate=service.set_tool_policy
    def lost(*a,**k):mutate(*a,**k);raise OSError('Lost ACK')
    monkeypatch.setattr(service,'set_tool_policy',lost)
    assert (await http.post(path+'/change',json=body)).status==503
    monkeypatch.setattr(service,'set_tool_policy',lambda *a,**k:pytest.fail('Original cannot replay'))
    result=await (await http.get(path+'/operations/'+body['operation_id'])).json()
    assert result['outcome']=='saved' and result['kind']=='tool_policy_restriction' and result['before_policy']['exclude']==[] and result['recovered']
    assert await (await http.post(path+'/change',json=body)).json()==result
    listing=await (await http.get(path)).json();assert listing['restore_operation']==body['operation_id']
    monkeypatch.setattr(service,'set_tool_policy',mutate)
    restore={'operation_id':'owned-policy-restore','action':'restore_policy','expected_revision':result['config_revision'],'restore_from':body['operation_id']}
    restored=await (await http.post(path+'/change',json=restore)).json()
    assert restored['outcome']=='saved' and restored['kind']=='tool_policy_restore'
    assert json.loads((root/'mcp.json').read_text())==data and not restored['connection_attempted']
    assert 'restore_operation' not in await (await http.get(path)).json()
    repeat={**restore,'operation_id':'owned-stale-restore'}
    assert (await (await http.post(path+'/change',json=repeat)).json())['outcome']=='rejected'
    assert json.loads((root/'mcp.json').read_text())==data
