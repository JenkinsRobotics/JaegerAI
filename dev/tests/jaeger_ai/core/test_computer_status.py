"""Local execution-host status without hardware, permission or external probes."""
import pytest

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.mark.asyncio
async def test_computer_inventory_is_current_gateway_only_and_never_grants_input_or_provider_access(gw):
    from jaeger_ai.core.gateway.caller_auth import client_headers
    app,http=gw;app.store.ensure_session('owned-computer-context');before=app.store.list_messages('owned-computer-context')
    response=await http.get('/v1/runtime/computers');assert response.status==200
    value=await response.json();assert value['scope']=='gateway_process_only'
    assert value['computers'][0]['id']=='gateway-local' and value['computers'][0]['os_permissions']=='not_inferred_from_gateway'
    assert value['computers'][0]['input_authorization']=='per_admitted_turn_and_existing_policy'
    assert not any(value['actions'].values()) and not value['hosted']['allocation_supported']
    assert not {'hostname','serial','addresses','credentials'} & value['computers'][0].keys()
    assert (await http.get('/v1/runtime/computers',headers=client_headers('a2a'))).status==403
    assert app.store.list_messages('owned-computer-context')==before


def test_global_capability_metadata_never_substitutes_for_connection_or_turn_authority(monkeypatch):
    from jaeger_ai.core.runtime import truth
    monkeypatch.setattr(truth,'framework_inventory',list)
    monkeypatch.setattr(truth,'provider_model_inventory',lambda root:{'providers':[],'active':{}})
    monkeypatch.setattr(truth,'_audio_truth',lambda:{'supported':False,'scope':'owned fixture'})
    value=truth.capability_snapshot()
    assert value['shell']['authorized'] is None and value['filesystem']['authorized'] is None
    assert value['remote_access']['available'] is None and value['remote_access']['authorized'] is None
    assert value['remote_access']['configured'] is None
