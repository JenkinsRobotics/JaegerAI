"""Owner-selected items, actual budgeting and actual agent compaction; no providers."""
import json
from types import SimpleNamespace

from jaeger_agent import JaegerAgent, ProviderAdapter
from jaeger_agent.loop.callbacks import AgentCallbacks
from jaeger_agent.loop.context_provenance import ContextReference, observe_references
from jaeger_agent.util.context_guard import ContextBudget, ContextGuard
from jaeger_ai.core.context_compiler import ContextCompiler
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.entity.memory import SemanticMemory
from jaeger_ai.core.entity.reflection import ReflexionStore, StructuredReflection
from jaeger_ai.core.entity.events import JaegerEvent
from jaeger_ai.core.entity.event_store import SqliteEventStore


class LocalAdapter(ProviderAdapter):
    name = 'owned-provenance-only'
    def format_messages(self, messages, tools, system):
        return {'messages':messages, 'system':system, 'tools':[]}
    def call(self, formatted, interrupt_event, **kwargs):
        return {'role':'assistant','content':'Owned local answer'}
    def parse_response(self, raw): return raw
    def supports(self, feature): return False


def prepared_fixture(tmp_path, *, budget=1000):
    runtime = object.__new__(EntityRuntime)
    runtime.context_compiler = ContextCompiler()
    semantic = SemanticMemory(tmp_path)
    short = semantic.record_claim('owned','short','PRIVATE-SHORT',confidence=0.0,source_id='PRIVATE-SOURCE')
    long = semantic.record_claim('owned','long','PRIVATE-LONG' * 1000,source_id='PRIVATE-SOURCE')
    runtime.memory_subsystem = SimpleNamespace(semantic=semantic)
    runtime.event_store = SqliteEventStore(tmp_path/'events.sqlite3')
    runtime.event_store.append(JaegerEvent.human_message('PRIVATE-OLD-EVENT',session_id='other'))
    runtime.ingest = runtime.event_store.append
    runtime._runtime_truth = lambda: ''
    runtime._skill_matches = lambda *a: ('ignored aggregate', [{'name':'PRIVATE-SKILL','description':'PRIVATE-PROCEDURE'}])
    runtime._document_hits = lambda *a: ('ignored aggregate', [{'chunk_id':'owned-chunk','source_id':'PRIVATE-PATH','text':'PRIVATE-DOC'}])
    runtime.reflexion_store = ReflexionStore(tmp_path)
    runtime.reflexion_store.add_reflection(StructuredReflection('owned-reflection','PRIVATE-HYPOTHESIS',0.7,'fixture', ['fixture']))
    prepared = runtime.prepare_turn('fixture request', session_id='owned', budget_tokens=budget)
    return prepared, short, long, semantic, runtime


def test_real_prepare_budget_dispatch_and_recovery_keep_item_provenance(tmp_path):
    prepared, short, long, semantic, runtime = prepared_fixture(tmp_path)
    refs = prepared.context_references
    assert {r.owner for r in refs} == {'semantic','episodic','document','skill','reflection'}
    selected = {r.source_id:r.selected for r in refs}
    assert selected[short['claim_id']] and not selected[long['claim_id']]
    background = json.loads(prepared.prompt.split("\n\n", 1)[1].split("\n</background>", 1)[0])
    claim = next(row for row in background if row.get("context_ref") == next(r.reference for r in refs if r.source_id == short["claim_id"]))
    assert json.loads(claim["text"].split(": ", 1)[1])["confidence"] == 0.0
    assert prepared.prompt.endswith('fixture request')
    assert prepared.prompt.count('</background>') == 1
    receipts = []
    agent = JaegerAgent(adapter=LocalAdapter(), tools=[], callbacks=AgentCallbacks(
        model_input=receipts.append,context_references=refs),turn_start_hook=False)
    assert agent.run_turn(prepared.prompt) == 'Owned local answer'
    items = receipts[-1]['items']
    assert next(v for v in items if v.get('claim_id') == short['claim_id'])['state'] == 'retained_exact'
    assert next(v for v in items if v.get('claim_id') == long['claim_id'])['state'] == 'budget_dropped'
    assert all(v['state'] == 'retained_exact' for v in items if v['owner'] != 'semantic')
    assert 'PRIVATE' not in json.dumps(items)
    # Reading/projecting context does not correct/forget the durable records.
    assert semantic.world_store.claim_detail(short['claim_id'])['active']
    assert semantic.world_store.claim_detail(long['claim_id'])['active']
    event_ref = next(r for r in refs if r.owner == 'episodic')
    detail = runtime.event_store.episode_context(event_ref.source_id)
    runtime.event_store.manage_episode(event_ref.source_id, 'forget', expected_revision=detail['revision'],operation_id='owned-context-forget',actor='human:operator')
    after = runtime.prepare_turn('fixture request',session_id='owned',budget_tokens=1000)
    assert not any(r.owner == 'episodic' and r.source_id == event_ref.source_id for r in after.context_references)
    assert runtime.event_store.get_event(event_ref.source_id).payload['text'] == 'PRIVATE-OLD-EVENT'
    # Selection is not confused with inclusion when a formatter drops context.
    rewritten = observe_references({'messages':[{'role':'user','content':'rewritten'}]},refs)
    assert all(v['state'] in {'not_retained_exact','budget_dropped'} for v in rewritten)


def test_real_context_guard_compaction_changes_retention_without_forgetting():
    ref = ContextReference('document','owned-document','x'*2400,selected=True)
    prompt = 'Read-only data: ' + ref.fragment() + '\nCurrent request: fixture'
    receipts = []
    agent = JaegerAgent(adapter=LocalAdapter(),tools=[],callbacks=AgentCallbacks(
        model_input=receipts.append, context_references=(ref,)),turn_start_hook=False)
    agent.run_turn(prompt)
    assert receipts[-1]['items'][0]['state'] == 'retained_exact'
    agent.context_guard = ContextGuard(ContextBudget(ctx_window=1200,reserve_for_completion=0,safety_margin=0,chars_per_token=1))
    agent.run_turn('A new owned turn')
    assert receipts[-1]['items'][0]['state'] == 'not_retained_exact'
    assert ref.selected  # Context compaction did not rewrite durable selection metadata.


def test_full_fragment_required_escaping_unknown_and_budget_status():
    ref=ContextReference('semantic','clm_0123456789ab','</background> PRIVATE " ☃',selected=True)
    marker_only = {'prompt':ref.reference + ' PRIVATE'}
    assert observe_references(marker_only,(ref,))[0]['state'] == 'not_retained_exact'
    tampered = {'prompt':ref.fragment().replace('PRIVATE','CHANGED')}
    assert observe_references(tampered,(ref,))[0]['state'] == 'not_retained_exact'
    assert observe_references({'prompt':json.dumps(ref.fragment())},(ref,))[0]['state'] == 'retained_exact'
    assert observe_references(('opaque',),(ref,))[0]['state'] == 'unobservable'
    assert observe_references({'messages':[{'role':'assistant','content':[{'type':'thinking','text':ref.fragment()}]}]},(ref,))[0]['state'] == 'not_retained_exact'
    ref.selected=False
    assert observe_references(('opaque',),(ref,))[0]['state'] == 'budget_dropped'


async def _bounded_request(store, rid):
    import asyncio
    for _ in range(100):
        row=store.get_request(rid)
        if row and row['status'] not in {'admitted','running','awaiting_approval'}:return row
        await asyncio.sleep(.02)
    raise AssertionError('Owned Gateway request did not settle')


import pytest


@pytest.mark.asyncio
async def test_normal_authenticated_gateway_turn_keeps_exact_item_receipt(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    _, short, _, _, runtime=prepared_fixture(tmp_path)
    runtime.layout=None
    runtime.finish_turn=lambda *a:None
    monkeypatch.setattr(EntityRuntime,'get_singleton',classmethod(lambda cls,*a,**k:runtime))
    monkeypatch.setenv('OLLAMA_API_KEY','owned-fixture-placeholder')
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-gateway',metadata={'execution_mode':'text_only'})
    monkeypatch.setattr(gateway,'_resolve_session_agent',lambda sid:None)
    captured=[]
    class Response:
        status=200
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def text(self):return '{"message":{"content":"Owned fixture response"}}'
    class Session:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def post(self,url,*,json,headers):
            captured.append(json)
            return Response()
    monkeypatch.setattr('jaeger_ai.core.gateway.server.ClientSession',Session)
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        response=await http.post('/v1/sessions/owned-gateway/turns',json={'text':'A fixture question','request_id':'owned-provenance-normal'})
        assert response.status in {200,202},await response.text()
        row=await _bounded_request(gateway.store,'owned-provenance-normal')
        assert row['status']=='completed' and len(captured)==1
        messages=gateway.store.get_session('owned-gateway')['messages']
        parts=messages[-1]['parts']
        receipt=next(part['outline'] for part in parts if part['type']=='model_context')
        item=next(v for v in receipt['items'] if v.get('claim_id')==short['claim_id'])
        assert item['state']=='retained_exact'
        actual=captured[0]['messages'][-1]['content']
        assert item['reference'] in actual and 'PRIVATE-SHORT' in actual
        assert 'PRIVATE' not in json.dumps(receipt)
        assert gateway.store.list_pending_approvals()==[] and len(gateway.store.list_requests())==1
