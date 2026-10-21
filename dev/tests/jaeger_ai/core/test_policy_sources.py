"""Policy-source observations do not evaluate hooks or change authority."""
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.authority.status import snapshot
from jaeger_ai.core.instance.instance import InstanceLayout

pytest_plugins = ('dev.tests.jaeger_ai.core.test_sessions_contract',)


def test_missing_source_read_never_initializes_instance(tmp_path):
    root = tmp_path/'never-created'
    value = snapshot(InstanceLayout(root=root))
    assert value['commissioning_state'] == 'not_configured'
    assert value['persistent_skill_grants']['state'] == 'not_configured'
    assert value['action_authorized'] is False and value['hook_execution_performed'] is False
    assert not root.exists()
    assert snapshot(None)['state'] == 'runtime_not_bound'


def test_existing_sources_project_closed_fields_without_leaking_paths_or_grants(tmp_path, monkeypatch):
    from jaeger_ai.core.runtime import autonomy
    monkeypatch.setattr(autonomy, '_state', {'mode':'scoped', 'explicit':False})
    layout = InstanceLayout(root=tmp_path)
    layout.config_path.write_text('automation:\n  autonomy: ask\n')
    (tmp_path/'authority_policy.yaml').write_text('filesystem:\n  read: true\n  write: false\n  approved_roots: ["/private/fixture-path"]\nshell:\n  risk_mode: deny\nemail:\n  send: false\nsecret: fixture-secret-do-not-return\n')
    (tmp_path/'permissions.json').write_text(json.dumps({'granted_skills':['fixture-private-skill','fixture-private-skill']}))
    before = {p.name:p.read_bytes() for p in tmp_path.iterdir()}
    value = snapshot(layout)
    by_id = {r['id']:r['value'] for r in value['sources']}
    assert by_id['filesystem.write'] is False and by_id['shell.risk_mode']=='deny'
    assert by_id['autonomy.current']=='ask' and by_id['filesystem.approved_root_count']==1
    assert value['persistent_skill_grants']['count']==1
    encoded = json.dumps(value)
    assert 'fixture-secret' not in encoded and '/private' not in encoded and 'fixture-private-skill' not in encoded
    assert snapshot(layout)['revision'] == value['revision']
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()} == before
    # The actual existing owner still denies the same source rule; observation
    # has not manufactured a higher-priority allow or a usable approval token.
    from jaeger_ai.core.authority.kernel import PolicyKernel, ProposedAction
    action = ProposedAction('write_file', {}, actor='owner:webui', context={'instance_root':str(tmp_path)})
    assert PolicyKernel()._check_commissioning_policy(action, {}).decision.value == 'deny'


def test_corrupt_or_unsafe_source_is_unavailable_without_contents(tmp_path):
    layout = InstanceLayout(root=tmp_path)
    (tmp_path/'authority_policy.yaml').write_text('[invalid-policy]')
    (tmp_path/'permissions.json').write_text('{invalid-private')
    value = snapshot(layout)
    assert value['commissioning_state']=='unavailable' and value['sources']==[]
    assert value['persistent_skill_grants']=={'state':'unavailable','count':None,'scope':'configured_skill_names_only_not_per_call_authority','names_disclosed':False}
    assert 'invalid-private' not in json.dumps(value)


@pytest.mark.asyncio
async def test_authenticated_status_uses_only_bound_runtime_never_initializes_or_mutates(gw, monkeypatch, tmp_path):
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.gateway.caller_auth import client_headers
    _app, http = gw
    monkeypatch.setattr(EntityRuntime, 'get_singleton', lambda *a, **k: pytest.fail('status cannot initialize runtime'))
    monkeypatch.setattr(EntityRuntime, '_instance', None)
    response = await http.get('/v1/runtime/policy-sources')
    assert response.status==200 and (await response.json())['state']=='runtime_not_bound'
    monkeypatch.setattr(EntityRuntime, '_instance', SimpleNamespace(layout=InstanceLayout(root=tmp_path/'bound-only')))
    value = await (await http.get('/v1/runtime/policy-sources')).json()
    assert value['state']=='observed' and not (tmp_path/'bound-only').exists()
    assert (await http.get('/v1/runtime/policy-sources', headers=client_headers('a2a'))).status==403
    assert (await http.get('/v1/runtime/policy-sources', headers=client_headers('jaegerd'))).status==403
    assert (await http.post('/v1/runtime/policy-sources', json={'autonomy':'auto'})).status in {403,405}
