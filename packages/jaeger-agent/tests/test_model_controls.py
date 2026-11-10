"""Wire contracts: controls, reasoning continuation, cancellation, and budgets."""
import json
import threading
import time
from types import SimpleNamespace as NS

import pytest
from jaeger_agent.adapters.anthropic import AnthropicAdapter
from jaeger_agent.adapters.openai import OpenAIAdapter
from jaeger_agent.adapters.cli_stream import stream_delta
from jaeger_agent.loop.interrupt import CallProgress, StaleCallTimeout, AgentInterrupted, interruptible_call
from jaeger_agent.loop.runtime_bridge import build_jaeger_agent, _adapter_for_client


def test_first_token_grace_ends_at_first_progress_and_cancel_is_immediate():
    progress, release = CallProgress(), threading.Event()
    def generate():
        time.sleep(.04)  # exceeds stale interval, inside cold-start grace
        progress.touch()
        release.wait(1)
    try:
        with pytest.raises(StaleCallTimeout):
            interruptible_call(generate, threading.Event(), stale_timeout=.025,
                first_progress_timeout_s=.4, progress=progress, poll_interval=.005,
                on_abandon=release.set, join_on_abandon=.1)
        assert progress.first is not None
    finally:
        release.set()
    cancelled = threading.Event(); cancelled.set()
    with pytest.raises(AgentInterrupted):
        interruptible_call(lambda: pytest.fail('cancelled worker started'), cancelled,
                           first_progress_timeout_s=600)


def test_modern_openai_controls_reach_wire_without_callbacks():
    captured = []
    sdk = NS(chat=NS(completions=NS(create=lambda **kw: captured.append(kw) or {})))
    a = OpenAIAdapter(model='gpt-5', max_tokens=2048, reasoning_effort='xhigh',
        verbosity='low', temperature=None, top_p=None, stream_transport=False, client=sdk)
    a.call(a.format_messages([], [], ''), threading.Event(), first_progress_timeout_s=45,
           on_reasoning=lambda _: None)
    wire = captured[0]
    assert wire['max_completion_tokens'] == 2048 and 'max_tokens' not in wire
    assert wire['reasoning_effort'] == 'xhigh' and wire['verbosity'] == 'low'
    assert not {'temperature','top_p','first_progress_timeout_s','on_reasoning'} & wire.keys()


def test_anthropic_stream_and_signed_reasoning_survive_tool_continuation():
    wire, thoughts, texts = [], [], []
    final = NS(content=[NS(type='thinking',thinking='Checking the result',signature='opaque'),
        NS(type='tool_use',id='call1',name='lookup',input={'id': 7})],usage=None, stop_reason='tool_use')
    class Stream:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def __iter__(self):
            yield NS(type='content_block_delta',delta=NS(type='thinking_delta',thinking='Checking the result'))
            yield NS(type='content_block_delta',delta=NS(type='text_delta',text='Looking it up.'))
        def get_final_message(self): return final
    def stream(**kw): wire.append(kw); return Stream()
    a = AnthropicAdapter(model='claude-sonnet-4-6',reasoning_effort='high',max_tokens=4096,
                          client=NS(messages=NS(stream=stream)))
    raw = a.call(a.format_messages([],[],''),threading.Event(), on_reasoning=thoughts.append,on_delta=texts.append)
    assert thoughts == ['Checking the result'] and texts == ['Looking it up.']
    assert wire[0]['thinking'] == {'type':'adaptive'}
    assert wire[0]['output_config'] == {'effort':'high'}
    assert 'on_reasoning' not in wire[0]
    message=a.parse_response(raw)
    messages=[message,{'role':'tool','tool_call_id':'call1','content':'found'}]
    resumed=a.format_messages(messages,[], '')
    assert resumed['messages'][0]['content'][0]['signature']=='opaque'
    assert resumed['messages'][1]['content'][0]['tool_use_id']=='call1'
    other=AnthropicAdapter(model='different-model').format_messages(messages,[], '')
    assert all(b['type']!='thinking' for b in other['messages'][0]['content'])


def test_native_thinking_budget_validated_against_output_budget():
    a=AnthropicAdapter(max_tokens=1024,thinking_budget_tokens=1024)
    with pytest.raises(ValueError,match='smaller than max_tokens'): a.format_messages([],[], '')


def test_output_reserve_matches_local_wire_limit():
    ext=NS(provider='ollama',model='qwen2.5:3b',timeout_s=60,base_url='http://localhost:11434/v1',
           max_tokens=8192,ctx=4096)
    client=NS(ext=ext,_api_key='',num_ctx=4096)
    agent=build_jaeger_agent(client,tools=[],ctx_window=131072,completion_reserve=8192)
    assert agent.context_guard.budget.ctx_window==4096
    assert agent.context_guard.budget.reserve_for_completion==2048
    assert agent.adapter.max_tokens==2048 if hasattr(agent,'adapter') else agent.primary_adapter.max_tokens==2048


@pytest.mark.parametrize('effort',['minimal','low','medium','high','xhigh','max','none'])
def test_factory_preserves_explicit_reasoning_effort(effort):
    from jaeger_ai.core.instance.schemas import ExternalModelConfig
    cfg=ExternalModelConfig(provider='openai',model='gpt-5',reasoning_effort=effort)
    adapter=_adapter_for_client(NS(ext=cfg,_api_key='test'))
    assert adapter.format_messages([],[], '')['reasoning_effort']==effort


def test_cli_stream_separates_reasoning_and_never_replays_summary():
    row={'type':'stream_event','event':{'type':'content_block_delta','delta':{
        'type':'thinking_delta','thinking':'Checking'}}}
    encoded=json.dumps(row).encode()
    assert stream_delta(encoded,'thinking')=='Checking' and stream_delta(encoded)==''
    row['parent_tool_use_id']='child'
    assert stream_delta(json.dumps(row).encode(),'thinking')==''
    assert stream_delta(b'{"type":"result","result":"Checking"}','thinking')==''


def test_explicit_small_cloud_context_is_not_replaced_by_model_estimate(monkeypatch):
    import jaeger_ai.main as main
    monkeypatch.setitem(main._pipeline, 'client', None)
    ext=NS(provider='openai',model='gpt-5',ctx=4096)
    assert main._external_serving_ctx(ext,NS(ctx=8192),4096)==4096


def test_local_explicit_context_overrides_metadata_and_rejects_oversize(monkeypatch):
    from jaeger_ai.core.models import ollama_context as oc
    monkeypatch.setattr(oc,'probe_ollama_context',lambda *a,**kw:(32768,'model_info'))
    kwargs=dict(provider='ollama',model='local',base_url='http://localhost:11434/v1')
    assert oc.resolve_serving_context(**kwargs,configured_ctx=4096)==(4096,'configured')
    with pytest.raises(ValueError,match='exceeds model maximum'):
        oc.resolve_serving_context(**kwargs,configured_ctx=65536)
