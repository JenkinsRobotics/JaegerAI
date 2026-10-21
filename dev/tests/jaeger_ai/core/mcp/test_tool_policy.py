"""Existing MCP filter owner; local inert definitions, no credentials/network."""
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.mcp import service
from jaeger_ai.plugins.mcp.client import (
    filter_tool_names,
    is_read_only_tool,
    server_config_from_entry,
)


def fixture(layout):
    data={'version':1,'servers':[{'name':'owned','command':'never-run','args':[],'headers':{'Authorization':{'secret_ref':'retained'}},'scope':'existing','enabled':False,'tools':{'include':[],'exclude':['admin_*'],'gated':False,'max':3,'read_only':['read_*'],'private_extension':{'retained':True}}}]}
    (layout.root/'mcp.json').write_text(json.dumps(data));return data


def test_restriction_uses_actual_parser_and_filter_retains_grants_and_other_fields(tmp_path,monkeypatch):
    layout=SimpleNamespace(root=tmp_path);before=fixture(layout)
    monkeypatch.setattr(service,'resolve_server_headers',lambda *a:pytest.fail('No credentials'))
    monkeypatch.setattr(service,'_runtime',lambda *a:pytest.fail('No bridge initialization'))
    prior=service.configuration_revision(layout)
    policy={'include':['read_*','write_one'],'exclude':['admin_*','write_one'],'gated':True}
    result=service.set_tool_policy(layout,'owned',policy,expected_revision=prior)
    after=json.loads((tmp_path/'mcp.json').read_text());expected=json.loads(json.dumps(before));expected['servers'][0]['tools'].update(policy)
    assert after==expected
    config=server_config_from_entry(after['servers'][0],env={},headers={})
    assert filter_tool_names(['read_one','write_one','read_two','admin_secret'],config)==['read_one','read_two']
    assert is_read_only_tool('read_one',config) and not is_read_only_tool('write_one',config)
    assert config.gated and config.max_tools==3 and config.tools_read_only==['read_*']
    assert result['grants_changed'] is False and result['current_connection_unchanged'] is True and not result['connection_attempted']
    restored=service.set_tool_policy(layout,'owned',result['before_policy'],restore_policy=result['after_policy'],expected_revision=result['config_revision'])
    assert restored['kind']=='tool_policy_restore' and json.loads((tmp_path/'mcp.json').read_text())==before


@pytest.mark.parametrize('policy',[{'include':['read_*'],'exclude':[],'gated':True},{'include':['read_*'],'exclude':['admin_*'],'gated':False},{'include':['*'],'exclude':['admin_*'],'gated':True}])
def test_cannot_remove_existing_restrictions_or_widen_include(tmp_path,policy):
    layout=SimpleNamespace(root=tmp_path);data=fixture(layout);data['servers'][0]['tools'].update(include=['read_*'],gated=True)
    path=tmp_path/'mcp.json';path.write_text(json.dumps(data));original=path.read_bytes()
    with pytest.raises(ValueError):service.set_tool_policy(layout,'owned',policy,expected_revision=service.configuration_revision(layout))
    assert path.read_bytes()==original


def test_policy_cas_revalidates_after_plan_and_secret_strings_never_project(tmp_path):
    layout=SimpleNamespace(root=tmp_path);data=fixture(layout);path=tmp_path/'mcp.json'
    new={**data,'different':'retained concurrent edit'}
    with pytest.raises(ValueError,match='current file retained'):
        service.set_tool_policy(layout,'owned',{'include':[],'exclude':['admin_*','write_one'],'gated':True},expected_revision=service.configuration_revision(layout),before_commit=lambda *_:path.write_text(json.dumps(new)))
    assert json.loads(path.read_text())==new
    secret='a-quoted"loaded-value';data['servers'][0]['headers']={'Authorization':secret};data['servers'][0]['tools']['exclude']=[secret]
    path.write_text(json.dumps(data));inventory=service.configured_startup_inventory(layout)
    assert 'tool_policy' not in inventory['servers'][0] and secret not in str(inventory)
    with pytest.raises(ValueError,match='Known secret'):
        service.set_tool_policy(layout,'owned',{'include':[],'exclude':[secret],'gated':True},expected_revision=service.configuration_revision(layout))


def test_real_registry_excludes_filtered_tool_without_connecting_external_sdk(tmp_path,monkeypatch):
    from jaeger_ai.plugins.mcp import client
    layout=SimpleNamespace(root=tmp_path);data=fixture(layout)
    policy={'include':[],'exclude':['admin_*','write_one'],'gated':True}
    service.set_tool_policy(layout,'owned',policy,expected_revision=service.configuration_revision(layout))
    class OwnedLocalSDK:
        def __init__(self,config):self.config=config
        async def connect(self):return [SimpleNamespace(name=name,description='Owned fixture',inputSchema={}) for name in ('read_one','write_one','read_two','admin_one')]
        async def close(self,**kwargs):pass
        async def call(self,name,args):return SimpleNamespace(content=[{'type':'text','text':'Owned local '+name}],isError=False)
    monkeypatch.setattr(client,'_MCPClient',OwnedLocalSDK)
    registry=client.MCPRegistry()
    try:
        row=json.loads((tmp_path/'mcp.json').read_text())['servers'][0]
        specs=registry.add_server(server_config_from_entry(row,env={},headers={}))
        assert {spec.tool_name for spec in specs}=={'read_one','read_two'}
        with pytest.raises(ValueError,match='unknown MCP tool'):registry.call('mcp:owned/write_one',{})
        assert registry._clients['owned'].config.tools_read_only==data['servers'][0]['tools']['read_only']
        assert all(spec.read_only for spec in specs)
    finally:registry.shutdown();registry._loop.close()


def test_configured_auth_status_does_not_read_credential_files_or_probe(tmp_path,monkeypatch):
    layout=SimpleNamespace(root=tmp_path);data=fixture(layout)
    monkeypatch.setattr(service,'resolve_server_headers',lambda *a:pytest.fail('No credential read'))
    monkeypatch.setattr(service,'resolve_server_env',lambda *a:pytest.fail('No credential read'))
    monkeypatch.setattr(service,'_runtime',lambda *a:pytest.fail('No transport'))
    assert service.configured_startup_inventory(layout)['servers'][0]['authentication']=='headers_configured_not_probed'
    data['servers'][0].update(auth='oauth',headers={});(tmp_path/'mcp.json').write_text(json.dumps(data))
    assert service.configured_startup_inventory(layout)['servers'][0]['authentication']=='oauth_configured_not_probed'
