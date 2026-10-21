"""Append-only memory controls and authenticated owner routes; owned stores only."""
import json
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.entity.event_store import SqliteEventStore
from jaeger_ai.core.entity.events import JaegerEvent
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.entity.ownership import EntityRuntimeMode
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers


def test_append_only_correction_exclusion_restore_durable_receipts_and_aba(tmp_path):
    owner=SqliteEventStore(tmp_path/'events.sqlite3')
    event=owner.append(JaegerEvent.human_message('Owned original',session_id='other'))
    original=event.to_dict()
    def change(action,oid,text=None):
        return owner.manage_episode(event.event_id,action,operation_id=oid,expected_revision=owner.episode_context(event.event_id)['revision'],actor='human:operator',text=text)
    before=owner.episode_context(event.event_id)['revision']
    receipt=change('annotate','owned-note','Owned correction; data, not authority')
    assert receipt['ok'] and owner.get_event(event.event_id).to_dict()==original
    projected=owner.project_recall([event])
    assert projected[0].payload['operator_correction']=='Owned correction; data, not authority'
    change('forget','owned-forget')
    assert owner.project_recall([event])==[]
    change('restore','owned-restore')
    assert owner.project_recall([event])[0].payload['operator_correction'].startswith('Owned correction')
    assert owner.episode_context(event.event_id)['revision']!=before
    with pytest.raises(ValueError,match='changed'):
        owner.manage_episode(event.event_id,'forget',operation_id='owned-stale',expected_revision=before,actor='human:operator')
    reopened=SqliteEventStore(owner.path)
    assert reopened.episode_operation('owned-note')==receipt
    assert reopened.get_event(event.event_id).to_dict()==original
    assert len(reopened.episode_context_page()['episodes'])==1 # policy records are not conversation turns
    with owner._get_conn() as conn:
        command=json.loads(conn.execute("SELECT payload_json FROM entity_events WHERE idempotency_key='memory:episode:owned-note'").fetchone()[0])['command']
    assert reopened.manage_episode(command.pop('event_id'),command.pop('action'),operation_id='owned-note',**command)==receipt
    with pytest.raises(ValueError,match='different command'):
        reopened.manage_episode(event.event_id,'forget',operation_id='owned-note',expected_revision=before,actor='human:operator')


def test_episode_search_paging_literal_query_and_atomic_cas(tmp_path):
    owner=SqliteEventStore(tmp_path/'events.sqlite3')
    for i in range(32):owner.append(JaegerEvent.human_message('Owned literal_% '+str(i),session_id='owned'))
    page=owner.episode_context_page('literal_%')
    assert len(page['episodes'])==30 and page['next_before']
    older=owner.episode_context_page('literal_%',before=page['next_before'])
    assert len(older['episodes'])==2 and older['next_before'] is None
    assert not set(x['event_id'] for x in page['episodes']) & set(x['event_id'] for x in older['episodes'])
    row=page['episodes'][0]
    def race(i):
        try:return owner.manage_episode(row['event_id'],'annotate',operation_id='owned-race-'+str(i),expected_revision=row['revision'],actor='human:operator',text=str(i))['ok']
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(race,[1,2]))==[False,True]
    system=owner.append(JaegerEvent.typed('tool.completed',{'text':'protected'},actor='system:tool',source='fixture'))
    with pytest.raises(ValueError,match='not found'):owner.episode_context(system.event_id)
    assert owner.episode_context_page("' OR 1=1 --")['episodes']==[]


@pytest.mark.asyncio
async def test_episode_routes_scope_residency_stop_and_receipt_recovery(tmp_path,monkeypatch):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    owner=SqliteEventStore(tmp_path/'events.sqlite3')
    event=owner.append(JaegerEvent.human_message('Owned HTTP memory',session_id='owned'))
    runtime=SimpleNamespace(mode=EntityRuntimeMode.OWNER,is_resident=True,event_store=owner)
    monkeypatch.setattr(EntityRuntime,'_instance',runtime)
    base='/v1/runtime/memory/episodes/'+event.event_id
    body={'operation_id':'owned-http-note','expected_revision':owner.episode_context(event.event_id)['revision'],'text':'Owned HTTP correction'}
    async with TestClient(TestServer(gateway.app),headers=client_headers('jaegerd')) as http:
        assert (await http.get(base)).status==200
        assert not (await (await http.get(base)).json())['editable']
        assert (await http.post(base+'/annotate',json=body)).status==403
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as http:
        assert (await http.get('/v1/runtime/memory/episodes')).status==403
        assert (await http.post(base+'/annotate',json=body)).status==403
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        runtime.is_resident=False
        assert (await http.post(base+'/annotate',json=body)).status==400
        runtime.is_resident=True
        response=await http.post(base+'/annotate',json=body)
        assert response.status==200,await response.text()
        receipt=await response.json()
        assert receipt['ok'] and owner.get_event(event.event_id).payload['text']=='Owned HTTP memory'
        with gateway.store._get_conn() as conn:conn.execute('UPDATE control_operations SET receipt_json=NULL,status=? WHERE operation_id=?',('reserved',body['operation_id']))
        assert (await (await http.get('/v1/runtime/memory/episode-operations/'+body['operation_id'])).json())['receipt']==receipt
        assert await (await http.post(base+'/annotate',json=body)).json()==receipt
        stopped={**body,'operation_id':'owned-stop-check','expected_revision':owner.episode_context(event.event_id)['revision']}
        monkeypatch.setattr('jaeger_ai.core.gateway.server._control_plane_block',lambda:'owned fixture Stop')
        assert (await http.post(base+'/annotate',json=stopped)).status==409
        assert owner.episode_operation(stopped['operation_id']) is None
        rejection=(await (await http.get('/v1/runtime/memory/episode-operations/'+stopped['operation_id'])).json())['receipt']
        assert rejection['ok'] is False and rejection['operation_id']==stopped['operation_id'] and 'guard' in rejection['error']
        assert gateway.store.list_requests()==[]
