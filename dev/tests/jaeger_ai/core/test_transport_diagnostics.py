"""Bounded metadata-only diagnostics; no raw traffic or business-state mutation."""
import json
import uuid
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.diagnostics.transport import TransportDiagnostics,MAX_EVENTS
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers


def test_capture_expiry_duplicate_counters_bounds_and_restart_do_not_extend_consent():
    clock=[10.];owner=TransportDiagnostics(clock=lambda:clock[0],wall=lambda:1000+clock[0])
    oid=uuid.uuid4().hex
    started=owner.start(oid,30);cid=started['capture']['id'];eid=uuid.uuid4().hex
    owner.report(cid,eid,'malformed_json',session_id='PRIVATE-SESSION')
    owner.report(cid,eid,'malformed_json',session_id='PRIVATE-SESSION')
    snap=owner.snapshot()
    assert snap['capture']['occurrences']==2 and snap['capture']['unique_receipts']==1
    assert snap['events'][0]['occurrences']==2 and 'PRIVATE' not in json.dumps(snap)
    for _ in range(MAX_EVENTS):owner.report(cid,uuid.uuid4().hex,'transport_idle')
    assert len(owner.snapshot()['events'])==MAX_EVENTS and owner.snapshot()['capture']['overflow_occurrences']==1
    clock[0]=41
    expired=owner.snapshot();assert expired['capture']['state']=='expired'
    with pytest.raises(ValueError,match='inactive or expired'):owner.report(cid,eid,'malformed_json',session_id='PRIVATE-SESSION')
    assert owner.start(oid,30)['capture']['expires_at']==started['capture']['expires_at']
    assert owner.snapshot()['capture']['state']=='expired' # Repeated start does not reopen.
    restarted=TransportDiagnostics()
    assert restarted.snapshot()['capture'] is None and restarted.boot_id!=owner.boot_id


@pytest.mark.asyncio
async def test_real_capture_routes_reject_raw_fields_scope_and_export_only_safe_metadata(tmp_path):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        # Admission after startup: startup legitimately reconciles preexisting admissions.
        gateway.store.ensure_session('owned');gateway.store.admit_request('owned','PRIVATE-PROMPT',request_id='owned-request')
        before=gateway.store.get_request('owned-request')
        events_before=gateway.store.replay_events('*',0)['events']
        base='/v1/runtime/diagnostics/capture'
        assert (await (await http.get(base)).json())['capture'] is None
        started=await (await http.post(base+'/start',json={'operation_id':uuid.uuid4().hex,'duration_seconds':60})).json()
        cid=started['capture']['id'];eid=uuid.uuid4().hex
        body={'capture_id':cid,'event_id':eid,'code':'malformed_json','session_id':'owned','request_id':'owned-request'}
        assert (await http.post(base+'/report',json=body)).status==200
        assert (await http.post(base+'/report',json=body)).status==200
        assert (await http.post(base+'/report',json={**body,'raw_frame':'Authorization: Bearer PRIVATE-TOKEN'})).status==409
        assert (await http.post(base+'/report',json={**body,'code':'PRIVATE-TOKEN'})).status==409
        assert (await http.post(base+'/report',json={**body,'request_id':'foreign'})).status==409
        assert (await http.post(base+'/report',headers=client_headers('jaegerd'),json=body)).status==403
        assert (await http.get(base,headers=client_headers('a2a'))).status==403
        exported=await (await http.get('/v1/runtime/diagnostics/export')).json()
        assert exported['capture']['occurrences']==2 and exported['capture']['unique_receipts']==1
        encoded=json.dumps(exported)
        assert all(value not in encoded for value in ('PRIVATE','Authorization','owned-request','owned'))
        assert len(exported['events'])==1 and exported['events'][0]['stage']=='parser'
        assert gateway.store.get_request('owned-request')==before
        stopped=await (await http.post(base+'/stop',json={'capture_id':cid})).json()
        assert stopped['capture']['state']=='stopped'
        assert (await http.post(base+'/report',json=body)).status==409
        assert gateway.store.replay_events('*',0)['events']==events_before
