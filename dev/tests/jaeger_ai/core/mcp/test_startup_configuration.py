"""Local configuration only: no SDK, credentials, execution or real MCP data."""
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.mcp import service


def test_stage_disabled_then_startup_cas_preserves_credentials_and_grants(tmp_path,monkeypatch):
    layout=SimpleNamespace(root=tmp_path)
    monkeypatch.setattr(service,'_migrate_inline_secrets',lambda *a:pytest.fail('No migration'))
    monkeypatch.setattr(service,'_runtime',lambda *a:pytest.fail('No transport'))
    result=service.stage_disabled_server(layout,{'name':'owned','url':'https://example.invalid/mcp'},expected_revision='missing')
    path=tmp_path/'mcp.json';data=json.loads(path.read_text())
    assert result['connection_attempted'] is False and data['servers'][0]['enabled'] is False
    assert data['servers'][0]['tools']=={'gated':True,'read_only':[]}
    data['servers'][0].update(headers={'Authorization':{'secret_ref':'existing-owned-ref'}},scope={'existing':'retained'})
    path.write_text(json.dumps(data));before=service.configuration_revision(layout)
    changed=service.set_startup_enabled(layout,'owned',True,expected_revision=before)
    data['servers'][0]['enabled']=True
    assert json.loads(path.read_text())==data
    assert changed['current_connection_unchanged'] and not changed['credentials_changed'] and not changed['grants_changed']
    with pytest.raises(ValueError,match='changed'):
        service.set_startup_enabled(layout,'owned',False,expected_revision=before)
    assert json.loads(path.read_text())==data
    inventory=service.configured_startup_inventory(layout)
    assert inventory['servers']==[{'name':'owned','startup_enabled':True,'transport':'http','status':'not_probed'}]
    assert 'existing-owned-ref' not in json.dumps(inventory)


def test_plan_window_edit_retained_and_disabled_creation_no_overwrite(tmp_path):
    layout=SimpleNamespace(root=tmp_path);path=tmp_path/'mcp.json'
    replacement={'version':1,'servers':[{'name':'other','enabled':False}]}
    def edit(_data,_revision):path.write_text(json.dumps(replacement))
    with pytest.raises(ValueError,match='current file retained'):
        service.stage_disabled_server(layout,{'name':'owned','command':'echo','args':['safe']},expected_revision='missing',before_commit=edit)
    assert json.loads(path.read_text())==replacement
    with pytest.raises(ValueError,match='already exists'):
        service.stage_disabled_server(layout,{'name':'other','command':'echo','args':[]},expected_revision=service.configuration_revision(layout))
    assert json.loads(path.read_text())==replacement


@pytest.mark.parametrize('definition',[{'name':'x','url':'https://example.invalid/?token=x'},{'name':'x','command':'echo','args':['--token=secret']},{'name':'x','url':'https://example.invalid','env':{}}])
def test_setup_refuses_credential_fields_and_embedded_options(tmp_path,definition):
    with pytest.raises(ValueError):service.stage_disabled_server(SimpleNamespace(root=tmp_path),definition,expected_revision='missing')
    assert not (tmp_path/'mcp.json').exists()


def test_disabled_definition_skipped_before_credential_or_transport_boundary(tmp_path,monkeypatch):
    from jaeger_ai.plugins.mcp import client
    layout=SimpleNamespace(root=tmp_path)
    service.stage_disabled_server(layout,{'name':'owned','command':'never-run','args':[]},expected_revision='missing')
    class InertRegistry:
        def add_server(self,*a):pytest.fail('Disabled definition cannot start')
    monkeypatch.setattr(client,'_GLOBAL_REGISTRY',None)
    monkeypatch.setattr(client,'MCPRegistry',InertRegistry)
    monkeypatch.setattr(service,'resolve_server_env',lambda *a:pytest.fail('No credential resolution'))
    result=client.init_from_config(tmp_path/'mcp.json',layout=layout)
    assert isinstance(result,InertRegistry)


def test_catalog_cannot_echo_known_inline_secret_as_name(tmp_path):
    layout=SimpleNamespace(root=tmp_path)
    data={'servers':[{'name':'known-loaded-value','headers':{'Authorization':'known-loaded-value'},'enabled':False}]}
    (tmp_path/'mcp.json').write_text(json.dumps(data))
    assert service.configured_startup_inventory(layout)['servers']==[]
    with pytest.raises(ValueError,match='credential content'):
        service.stage_disabled_server(layout,{'name':'other','command':'echo','args':['known-loaded-value']},expected_revision=service.configuration_revision(layout))
