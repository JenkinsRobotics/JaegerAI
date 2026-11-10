from types import SimpleNamespace
import pytest
from aiohttp import web


def test_cloud_cli_context_never_sizes_local_ollama(monkeypatch):
    from jaeger_ai.core.runtime import stack
    monkeypatch.setattr(stack,'_existing_plist_env',lambda _: {})
    monkeypatch.setattr(stack,'_instance_config',lambda:{'external_model':{'enabled':True,'provider':'cli','model':'grok','ctx':131072}})
    env=stack.operator_env(stack.SERVICE_BY_ID['ollama'])
    assert env['OLLAMA_CONTEXT_LENGTH']=='32768'
    assert env['OLLAMA_MAX_LOADED_MODELS']=='1' and env['OLLAMA_NUM_PARALLEL']=='1'


def test_external_only_doctor_does_not_require_gguf(tmp_path):
    from jaeger_ai.core.runtime.preflight import _check_instance_config
    (tmp_path/'config.yaml').write_text('external_model:\n  enabled: true\n  provider: cli\n  model: grok\n')
    checks=_check_instance_config(SimpleNamespace(root=tmp_path))
    assert not any(c.name.startswith('model.') and not c.ok for c in checks)
    assert next(c for c in checks if c.name=='external_model').unknown


def test_missing_executor_cannot_claim_completion(monkeypatch):
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.entity.cognition_router import ReActHandler
    from jaeger_ai.core.entity.events import JaegerEvent
    monkeypatch.setattr(EntityRuntime,'get_singleton',lambda:SimpleNamespace(layout=None))
    event=JaegerEvent.human_message('Create a file',actor='human:operator',source='test',session_id='s')
    result=ReActHandler().handle(event,None,None,None,None,{'model_runner':lambda _:pytest.fail('No fake model-only completion')})
    assert result['status']=='failed' and result['halt_reason']=='execution_unavailable'
    assert not result['action_taken'] and not result['llm_invoked']


@pytest.mark.asyncio
async def test_delete_closes_browser_before_session_disappears():
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    order=[]
    class Store:
        def active_session_state(self):return {}
        def delete_session(self,sid):order.append('delete');return True
    class Browser:
        async def close_session(self,sid):order.append('close')
    app=SimpleNamespace(store=Store(),browser_runtime=Browser(),event_bus=SimpleNamespace(publish=lambda *a:None))
    response=await JaegerGatewayApp.handle_delete_session(app,SimpleNamespace(match_info={'id':'s'}))
    assert response.status==200 and order==['close','delete']


def test_local_context_is_bounded_without_explicit_service_override(monkeypatch):
    from jaeger_ai.core.runtime import stack
    monkeypatch.setattr(stack,'_existing_plist_env',lambda _: {})
    cfg={'external_model':{'enabled':True,'provider':'ollama','model':'installed:latest','ctx':131072}}
    monkeypatch.setattr(stack,'_instance_config',lambda:cfg)
    assert stack.operator_env(stack.SERVICE_BY_ID['ollama'])['OLLAMA_CONTEXT_LENGTH']=='32768'
    cfg['stack']={'env':{'ollama':{'OLLAMA_CONTEXT_LENGTH':'49152'}}}
    assert stack.operator_env(stack.SERVICE_BY_ID['ollama'])['OLLAMA_CONTEXT_LENGTH']=='49152'
