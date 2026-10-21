"""Owned model-default metadata/receipt effects; no model or provider connection."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.caller_auth import client_headers


def test_atomic_model_cas_receipt_reopen_aba_and_admitted_snapshot(tmp_path):
    store=GatewaySessionStore(tmp_path/'gateway.sqlite3')
    store.ensure_session('owned',metadata={'agent_id':'native:owned','preserve':'original'})
    def save(oid,model,revision):
        return store.save_model_choice('owned',{'model':model,'provider':'owned'},operation_id=oid,expected_revision=revision,actor='owner:webui',requested_model=model)
    first=save('owned-model-first','first',0)
    assert first['ok'] and first['result']['model_choice_revision']==1
    admitted=store.admit_request('owned','Owned harmless fixture',request_id='owned-frozen')
    snapshot=store.get_request('owned-frozen')['execution']
    assert snapshot['model']=='first'
    second=save('owned-model-second','second',1)
    assert second['ok'] and store.get_request('owned-frozen')['execution']==snapshot
    stale=save('owned-model-stale','stale',1)
    assert stale['ok'] is False and stale['http_status']==409
    assert save('owned-model-first','first',0)==first # Historical receipt; no revert.
    assert store.get_session('owned')['metadata']['model']=='second'
    assert save('owned-model-back','first',2)['ok']
    assert save('owned-model-aba','stale',1)['ok'] is False
    reopened=GatewaySessionStore(store.path)
    assert reopened.control_operation('owned-model-second')['receipt']==second
    assert reopened.get_request('owned-frozen')['execution']==snapshot
    metadata=reopened.get_session('owned')['metadata']
    assert metadata['preserve']=='original' and metadata['agent_id']=='native:owned'
    assert admitted['request_id']=='owned-frozen'
    with pytest.raises(ValueError,match='another command'):save('owned-model-first','different',0)


def test_atomic_metadata_merge_and_concurrent_choice_single_winner(tmp_path):
    store=GatewaySessionStore(tmp_path/'gateway.sqlite3');store.ensure_session('owned')
    def patch(i):store.update_metadata('owned',{'owned_'+str(i):i})
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(patch,range(20)))
    metadata=store.get_session('owned')['metadata']
    assert all(metadata['owned_'+str(i)]==i for i in range(20))
    def save(i):return store.save_model_choice('owned',{'model':str(i),'provider':'owned'},operation_id='owned-race-'+str(i),expected_revision=0,actor='owner:webui',requested_model=str(i))['ok']
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(save,[1,2]))==[False,True]
    before=store.get_session('owned')['metadata']['model_choice_revision']
    store.update_metadata('owned',{'model':'legacy','provider':'owned'})
    assert store.get_session('owned')['metadata']['model_choice_revision']==before+1
    store.mark_request_status('missing','completed') # Must not create an admission.
    assert store.list_requests()==[]


@pytest.mark.asyncio
async def test_model_patch_scope_duplicate_before_probe_and_rejection_receipt(tmp_path,monkeypatch):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned',metadata={'agent_id':'native:owned','saved':'keep'})
    calls=[]
    def choice(model):calls.append(model);return {'model':model,'provider':'owned'}
    monkeypatch.setattr(gateway,'_session_model_choice',choice)
    body={'model':'first','expected_model_revision':0,'operation_id':'owned-model-http'}
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        current=await (await http.get('/v1/sessions/owned?view=settings')).json()
        assert current['model_choice_revision']==0 and current['atomic_model_operations'] is True
        response=await http.patch('/v1/sessions/owned',json=body);assert response.status==200
        receipt=await response.json();assert receipt['ok']
        # Lost ACK replay reads receipt before availability, never reverses choice.
        monkeypatch.setattr(gateway,'_session_model_choice',lambda m:(_ for _ in ()).throw(AssertionError('duplicate probed provider')))
        assert await (await http.patch('/v1/sessions/owned',json=body)).json()==receipt
        assert calls==['first']
        assert (await http.patch('/v1/sessions/owned',json={**body,'model':'different'})).status==409
        # Availability failure is settled rejection, not a permanent unknown journal.
        rejected=await http.patch('/v1/sessions/owned',json={'model':'unavailable','expected_model_revision':1,'operation_id':'owned-model-rejected'})
        assert rejected.status==409
        durable=await (await http.get('/v1/control-operations/owned-model-rejected')).json()
        assert durable['receipt']['ok'] is False
        assert (await http.patch('/v1/sessions/owned',headers=client_headers('jaegerd'),json=body)).status==409 # Existing turn-scoped caller; cannot reuse another actor's nonce.
        assert (await http.patch('/v1/sessions/owned',headers={'Authorization':'Bearer owned-invalid-fixture'},json=body)).status==401
        assert (await http.patch('/v1/sessions/owned',headers=client_headers('a2a'),json=body)).status==403
        assert gateway.store.get_session('owned')['metadata']['model']=='first'
        assert gateway.store.get_session('owned')['metadata']['saved']=='keep'
        assert gateway.store.list_requests()==[]


def test_admitted_explicit_model_and_queue_defaults_preserve_generation_contract(tmp_path):
    store=GatewaySessionStore(tmp_path/'gateway.sqlite3');store.ensure_session('owned')
    store.update_metadata('owned',{'model':'first','provider':'owned'})
    queued=store.enqueue_request('owned','Old implicit preference',request_id='owned-queued')
    assert queued['execution']['model']=='first'
    store.update_metadata('owned',{'model':'newer','provider':'owned'})
    revision=store.get_session('owned')['metadata']['model_choice_revision']
    promoted=store.promote_next_queue_item('owned')
    assert promoted['execution']['model']=='first'
    assert store.get_session('owned')['metadata']['model']=='newer'
    assert store.get_session('owned')['metadata']['model_choice_revision']==revision
    store.complete_request('owned-queued',status='completed',result={},assistant_text='fixture')
    first=store.admit_request('owned','Explicit model choice',request_id='owned-explicit',requested={'model':'explicit','provider':'owned'})
    assert first['execution']['model']=='explicit'
    after=store.get_session('owned')['metadata']['model_choice_revision']
    assert after==revision+1
    store.admit_request('owned','Explicit model choice',request_id='owned-explicit',requested={'model':'explicit','provider':'owned'})
    assert store.get_session('owned')['metadata']['model_choice_revision']==after
    rejected=store.save_model_choice('owned',{'model':'stale','provider':'owned'},operation_id='owned-stale-after-admission',expected_revision=revision,actor='owner:webui',requested_model='stale')
    assert rejected['ok'] is False


@pytest.mark.asyncio
async def test_catalog_disappearance_rejects_fresh_admission_but_never_replays_unknown(tmp_path,monkeypatch):
    import asyncio
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned',metadata={'model':'chosen','provider':'owned'})
    available=[];probes=[];executed=[]
    def inventory():probes.append(True);return {'providers':[{'id':'owned','configured':True,'reachable':True,'models':list(available)}]}
    monkeypatch.setattr('jaeger_ai.core.runtime.truth.provider_model_inventory',inventory)
    async def execute(*args,**kwargs):executed.append(kwargs['request_id'])
    monkeypatch.setattr(gateway,'_execute_turn',execute)
    body={'text':'Owned fixture question','request_id':'owned-catalog-change'}
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        response=await http.post('/v1/sessions/owned/turns',json=body)
        assert response.status==400 and 'unavailable' in (await response.json())['error']
        assert gateway.store.get_request(body['request_id']) is None and executed==[]
        available.append({'id':'chosen'})
        response=await http.post('/v1/sessions/owned/turns',json=body);assert response.status==200
        await asyncio.sleep(.02);assert executed==[body['request_id']]
        snapshot=gateway.store.get_request(body['request_id'])['execution']
        gateway.store.mark_request_status(body['request_id'],'execution_unknown')
        available.clear();before=len(probes)
        response=await http.post('/v1/sessions/owned/turns',json=body)
        wire=await response.json();assert wire['replayed'] is True and wire['status']=='execution_unknown'
        await asyncio.sleep(.02)
        assert executed==[body['request_id']] and len(probes)==before
        assert gateway.store.get_request(body['request_id'])['execution']==snapshot


@pytest.mark.asyncio
async def test_actual_provider_model_or_unknown_is_persisted_without_claiming_requested_identity(tmp_path,monkeypatch):
    import asyncio,json
    from types import SimpleNamespace
    from jaeger_ai.core.entity.runtime import EntityRuntime,PreparedTurn
    from jaeger_ai.core.entity.events import JaegerEvent
    runtime=SimpleNamespace(layout=None,executive_selector=None,current_state=SimpleNamespace(active_goals=[]),identity=SimpleNamespace(entity_id='owned',display_name='Owned'),
        prepare_turn=lambda text,*,session_id,**kw:PreparedTurn(text,JaegerEvent.human_message(text,session_id=session_id),text,session_id),finish_turn=lambda *a:None)
    monkeypatch.setattr(EntityRuntime,'get_singleton',classmethod(lambda cls,*a,**kw:runtime))
    monkeypatch.setenv('OLLAMA_API_KEY','owned-fixture-key')
    monkeypatch.setattr('jaeger_ai.core.runtime.truth.provider_model_inventory',lambda:{'providers':[{'id':'owned','configured':True,'reachable':True,'models':[{'id':'configured'}]}]})
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned',metadata={'model':'configured','provider':'owned','execution_mode':'text_only'})
    monkeypatch.setattr(gateway,'_resolve_session_agent',lambda sid:None)
    reported=['provider-actual']
    class Response:
        status=200
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def text(self):return json.dumps({'message':{'content':'Owned fixture answer'},**({'model':reported[0]} if reported else {})})
    class Session:
        def __init__(self,*a,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        def post(self,*a,**kw):return Response()
    monkeypatch.setattr('jaeger_ai.core.gateway.server.ClientSession',Session)
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        for i,value in enumerate(('provider-actual',None,'owned-fixture-key')):
            reported[:]=[value] if value else []
            rid='owned-model-receipt-'+str(i)
            response=await http.post('/v1/sessions/owned/turns',json={'text':'A fixture question','request_id':rid})
            assert response.status==200,await response.text()
            for _ in range(100):
                row=gateway.store.get_request(rid)
                if row['status'] not in {'admitted','running'}:break
                await asyncio.sleep(.02)
            assert row['status']=='completed'
            expected=value if value=='provider-actual' else None
            assert row['result']['actual_model']==expected
            assert row['result']['model_identity_scope']==('provider_reported' if expected else 'unknown')
            identity=next(p for p in gateway.store.get_session('owned')['messages'][-1]['parts'] if p['type']=='model_identity')
            assert identity['actual_model']==expected
            assert 'owned-fixture-key' not in json.dumps(identity)


def test_pending_model_cancellation_blocks_late_commit_and_never_undoes_success(tmp_path):
    store=GatewaySessionStore(tmp_path/'gateway.sqlite3');store.ensure_session('owned',metadata={'model':'original','provider':'owned'})
    command={'operation_id':'owned-cancel-model','expected_revision':0,'actor':'owner:webui','requested_model':'new'}
    cancelled=store.cancel_model_choice('owned',**command)
    assert cancelled['result']['cancelled'] is True
    assert store.save_model_choice('owned',{'model':'new','provider':'owned'},**command)==cancelled
    assert store.get_session('owned')['metadata']['model']=='original'
    command={**command,'operation_id':'owned-committed-model'}
    saved=store.save_model_choice('owned',{'model':'new','provider':'owned'},**command)
    assert store.cancel_model_choice('owned',**command)==saved
    assert store.get_session('owned')['metadata']['model']=='new'
    assert store.list_requests()==[]


@pytest.mark.asyncio
async def test_model_validation_race_cannot_admit_a_stale_snapshot(tmp_path,monkeypatch):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned',metadata={'model':'original','provider':'owned'})
    def inventory():
        gateway.store.update_metadata('owned',{'model':'newer','provider':'owned'})
        return {'providers':[{'id':'owned','reachable':True,'configured':True,'models':[{'id':'original'},{'id':'newer'}]}]}
    monkeypatch.setattr('jaeger_ai.core.runtime.truth.provider_model_inventory',inventory)
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        response=await http.post('/v1/sessions/owned/turns',json={'text':'Owned race fixture','request_id':'owned-validation-race'})
        assert response.status==409 and 'changed during validation' in (await response.json())['error']
        assert gateway.store.get_request('owned-validation-race') is None
        assert gateway.store.get_session('owned')['metadata']['model']=='newer'
