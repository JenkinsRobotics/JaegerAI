"""Regression proofs for provider identity, streaming and final-payload egress."""
from types import SimpleNamespace
import threading
import pytest
from jaeger_ai.core.instance.schemas import Config
from jaeger_ai.core.models.request_policy import ModelPolicyError, ModelRoute, GovernedAdapter, require_egress, select_request_client
from jaeger_ai.core.models.completion import complete

@pytest.fixture
def configured():
    return Config(instance_name='test',model={'model_path':'unused'},external_model={
        'enabled':True,'provider':'cli','model':'grok','base_url':''})

@pytest.fixture
def adapter(monkeypatch):
    class Adapter:
        calls=[]
        vision=True
        def format_messages(self,messages,tools,system):
            return {'messages':[{'role':'system','content':system},*messages]}
        def supports(self,feature):return self.vision or feature!='vision'
        def call(self,payload,interrupt,**kwargs):
            self.calls.append(payload)
            if kwargs.get('on_delta'):kwargs['on_delta']('Hello ');kwargs['on_delta']('there')
            return {'content':'Hello there','model':'reported-model'}
        def parse_response(self,raw):return raw
    result=Adapter()
    monkeypatch.setattr('jaeger_agent.loop.runtime_bridge._adapter_for_client',lambda client:result)
    monkeypatch.setattr('jaeger_ai.core.models.external_model.ExternalModelClient',
        lambda ext,layout:SimpleNamespace(ext=ext,kind='external'))
    return result

@pytest.mark.parametrize('provider,model',[('cli','grok'),('openai','gpt-test'),('anthropic','claude-test')])
def test_selected_pair_is_preserved(configured,adapter,provider,model):
    c=select_request_client(configured,None,model=f'@{provider}:{model}')
    assert (c.ext.provider,c.ext.model)==(provider,model)


def test_typical_chat_stream_and_history_once(configured,adapter):
    deltas=[]
    text=complete(configured,None,'hello',history=[{'role':'user','content':'hello'}],on_delta=deltas.append)
    assert text=='Hello there' and deltas==['Hello ','there']
    assert adapter.calls[0]['messages'].count({'role':'user','content':'hello'})==1

@pytest.mark.parametrize('text,history',[
    ('Describe this confidential image',[]),
    ('Summarize the previous message',[{'role':'user','content':'my password is synthetic-test-only'}]),
])
def test_private_payload_never_calls_cloud(configured,adapter,text,history):
    with pytest.raises(ModelPolicyError):complete(configured,None,text,history=history)
    assert not adapter.calls


def test_image_does_not_change_provider(configured,adapter,tmp_path):
    img=tmp_path/'test.png';img.write_bytes(b'synthetic')
    routes=[]
    complete(configured,None,'Describe this',model='gpt-test',provider='openai',
        attachments=[{'safe_path':str(img),'mime_type':'image/png'}],on_route=routes.append)
    assert routes[0]['provider']=='openai' and routes[0]['model']=='gpt-test'
    assert adapter.calls[0]['messages'][-1]['content'][1]['type']=='image_url'
    adapter.vision=False
    with pytest.raises(ModelPolicyError,match='provider was not changed'):
        complete(configured,None,'Describe this',attachments=[{'safe_path':str(img),'mime_type':'image/png'}])
    assert len(adapter.calls)==1


def test_local_only_and_tool_result_boundary(configured,adapter):
    cloud=ModelRoute('cli','grok','',False)
    guarded=GovernedAdapter(adapter,cloud)
    with pytest.raises(ModelPolicyError):guarded.call({'messages':[{'role':'tool','content':'confidential record'}]},threading.Event())
    with pytest.raises(ModelPolicyError):complete(configured,None,'hello',local_only=True)
    local=ModelRoute('ollama','small:latest','http://localhost:11434/v1',True)
    require_egress(local,'confidential record',local_only=True)
    assert not adapter.calls


def test_cancel_prevents_dispatch(configured,adapter):
    from jaeger_agent.loop.interrupt import AgentInterrupted
    interrupt=threading.Event();interrupt.set()
    with pytest.raises(AgentInterrupted):complete(configured,None,'hello',interrupt_event=interrupt)
    assert not adapter.calls


def test_security_discussion_does_not_select_gemma():
    from jaeger_ai.core.models.router import classify
    assert classify('Explain password managers')[0]=='public'
    assert classify('my password is example')[0]=='private'


def test_cli_tool_descriptions_do_not_trigger_private_data_fallback(monkeypatch):
    from jaeger_agent.adapters.cli_backend import CliBackendAdapter
    from jaeger_ai.core.models.router import classify
    adapter = CliBackendAdapter(backend_id="grok")
    calls = []
    monkeypatch.setattr(adapter, "call", lambda payload, interrupt, **kw: calls.append(payload))
    guarded = GovernedAdapter(adapter, ModelRoute("cli", "grok", "", False))
    from jaeger_os.core.tools.tool_schema import ToolDef
    from pydantic import BaseModel
    class EmptyArgs(BaseModel):
        pass
    tools = [ToolDef(name="inspect_keys", description="Inspect private keys only when authorized",
                     args_model=EmptyArgs, fn=lambda: None, side_effect="read")]
    formatted = guarded.format_messages([{"role": "user", "content": "Say hello"}], tools, "Be helpful")
    assert classify(formatted["prompt"])[0] == "private"  # flattened schemas caused the regression
    guarded.call(formatted, threading.Event())
    assert len(calls) == 1
    with pytest.raises(ModelPolicyError):
        guarded.format_messages([{"role": "tool", "content": "confidential user record"}], tools, "Be helpful")
    # Mutation after formatting cannot reuse the earlier policy decision.
    formatted["prompt"] += "\nmy password is synthetic-only"
    with pytest.raises(ModelPolicyError):
        guarded.call(formatted, threading.Event())
    assert len(calls) == 1


def test_explicit_cloud_alias_never_becomes_a_local_route(configured, adapter):
    from jaeger_ai.core.models.request_policy import route_for
    client=select_request_client(configured,None,model="@ollama-cloud:hosted-model")
    assert client.ext.base_url == "http://localhost:11434/v1"
    assert client.ext.provider == "ollama"
    assert client.selected_lane == "ollama-cloud"
    assert not route_for(client).local


def test_fallback_uses_admitted_config_and_own_credentials(configured, monkeypatch):
    from jaeger_ai.core.instance.schemas import FallbackModel
    from jaeger_agent.loop.runtime_bridge import _fallback_adapters_for
    configured.external_model.fallback=[FallbackModel(provider="openai",model="gpt-test")]
    seen=[]
    def build(ext,layout):
        seen.append(ext)
        return SimpleNamespace(ext=ext)
    monkeypatch.setattr('jaeger_ai.core.models.external_model.ExternalModelClient',build)
    monkeypatch.setattr('jaeger_agent.loop.runtime_bridge._adapter_for_client',lambda c:c)
    _fallback_adapters_for(SimpleNamespace(ext=configured.external_model,layout=None,_api_key="primary-secret"))
    assert seen[0].provider=="openai" and seen[0].api_key_credential=="openai_api_key"
    assert seen[0].base_url=="https://api.openai.com/v1" and seen[0].api_key_env==""


def test_unconfigured_identity_never_loads_weights(tmp_path,monkeypatch):
    from jaeger_ai.core.entity.runtime import EntityRuntime,load_instance_config_or_default
    from jaeger_ai.core.instance.instance import InstanceLayout
    config=load_instance_config_or_default(InstanceLayout(root=tmp_path))
    monkeypatch.setattr('jaeger_ai.core.models.model_resolver.resolve_model_path',lambda *a,**k:pytest.fail('Must not resolve or download'))
    with pytest.raises(ModelPolicyError,match="Choose and connect"):
        EntityRuntime.local_model_client(SimpleNamespace(),config)


def test_local_only_history_cannot_be_unmarked_by_next_turn(tmp_path):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    store=GatewaySessionStore(tmp_path/'history.sqlite3')
    first=store.admit_request('local','hello',request_id='one',requested={'options':{'local_only':True}})
    store.complete_request('one',status='completed',result={},assistant_text='hello')
    second=store.admit_request('local','summarize',request_id='two',requested={'options':{'local_only':False}})
    assert second['execution']['options']['local_only'] is True
    assert store.session_local_only('local') and not store.session_local_only('other')


def test_loopback_cloud_proxy_is_not_evidence_of_local_inference(configured,adapter):
    from jaeger_ai.core.models.request_policy import route_for
    configured.external_model.provider='openai'
    configured.external_model.model='gpt-test'
    configured.external_model.base_url='http://localhost:1234/v1'
    assert not route_for(select_request_client(configured,None)).local


def test_model_only_lane_streams_reasoning_once(configured,adapter):
    events=[]
    def call(payload, interrupt, **kwargs):
        kwargs['on_reasoning']('Checking')
        kwargs['on_delta']('Answer')
        return {'role':'assistant','content':'Answer','reasoning':'Checking'}
    adapter.call=call
    assert complete(configured,None,'question',on_reasoning=lambda t:events.append(('reasoning',t)),
        on_delta=lambda t:events.append(('text',t)))=='Answer'
    assert events==[('reasoning','Checking'),('text','Answer')]


def test_model_switch_resets_incompatible_controls(configured,adapter):
    configured.external_model.reasoning_effort='xhigh'
    configured.external_model.ctx=131072
    configured.external_model.temperature=1.3
    c=select_request_client(configured,None,model='@ollama:qwen2.5:3b')
    assert c.ext.ctx==0 and c.ext.reasoning_effort=='auto' and c.ext.temperature is None
    assert configured.external_model.ctx==131072
