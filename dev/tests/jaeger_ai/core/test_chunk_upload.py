"""Durable byte staging only, real HTTP and existing final attachment producer."""
import base64
import hashlib
import uuid
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.upload_chunks import CHUNK_BYTES


@pytest.mark.asyncio
async def test_resume_duplicate_conflict_finalize_reopen_and_exact_admission(tmp_path):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        sid='owned-chunks';gateway.store.ensure_session(sid);gateway.store.ensure_session('other-chunks')
        base=f'/v1/sessions/{sid}/uploads';data=b'fixture-byte'*30000
        body={'operation_id':uuid.uuid4().hex,'name':'fixture.bin','mime':'application/octet-stream','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        async def start():return await (await http.post(base,json=body)).json()
        state=await start();assert await start()==state
        assert (await http.post(base,json=body,headers=client_headers('jaegerd'))).status==403
        assert gateway.store.list_attachments(sid)==[]
        assert (await http.post(base,json={**body,'name':'different.bin'})).status==409
        assert (await http.get(base+'?operation_id='+body['operation_id'],headers=client_headers('jaegerd'))).status==404
        assert (await http.get(base+'?operation_id='+body['operation_id'],headers=client_headers('a2a'))).status==403
        common={'operation_id':body['operation_id'],'upload_id':state['upload_id']}
        chunk={**common,'offset':0,'data_base64':base64.b64encode(data[:CHUNK_BYTES]).decode()}
        first=await (await http.post(base+'/chunk',json=chunk)).json()
        assert first['received_bytes']==CHUNK_BYTES
        assert await (await http.post(base+'/chunk',json=chunk)).json()==first
        assert (await http.post(base+'/chunk',json={**chunk,'data_base64':base64.b64encode(b'x'*CHUNK_BYTES).decode()})).status==409
        assert (await http.post(base+'/finish',json=common)).status==409
        assert (await http.post(base.replace(sid,'other-chunks')+'/chunk',json=chunk)).status==404
        # Simulate lost chunk ACK/reopen: inspect retained original bytes, do not repeat it.
        gateway.store=GatewaySessionStore(gateway.store.path)
        assert (await (await http.get(base+'?operation_id='+body['operation_id'])).json())['received_bytes']==CHUNK_BYTES
        assert gateway.store.list_attachments(sid)==[]
        with pytest.raises(ValueError,match='Unknown attachment'):gateway.store.admit_request(sid,'never execute',request_id='owned-pending-attachment',requested={'attachment_ids':[state['upload_id']]})
        tail={**common,'offset':CHUNK_BYTES,'data_base64':base64.b64encode(data[CHUNK_BYTES:]).decode()}
        assert (await http.post(base+'/chunk',json=tail)).status==200
        finished=await (await http.post(base+'/finish',json=common)).json()
        assert finished['state']=='complete' and finished['attachment']['sha256']==body['sha256']
        assert await (await http.post(base+'/finish',json=common)).json()==finished
        assert len(gateway.store.list_attachments(sid))==1
        attachment=finished['attachment']
        raw=await (await http.get(f'/v1/sessions/{sid}/files/'+attachment['attachment_id'])).json()
        assert base64.b64decode(raw['data_base64'])==data
        admitted=gateway.store.admit_request(sid,'fixture only, not started',request_id='owned-complete-attachment',requested={'attachment_ids':[attachment['attachment_id']]})
        assert admitted['execution']['attachments'][0]['sha256']==body['sha256']
        # Cancel the owned admission before admitting another; no worker was started.
        gateway.store.complete_request('owned-complete-attachment',status='cancelled',result={'fixture':'cancelled before execution'})
        empty=gateway.store.admit_request(sid,'fixture only',request_id='owned-no-inherited-files')
        assert empty['execution']['attachments']==[]


@pytest.mark.asyncio
async def test_failed_digest_and_symlink_never_register_attachment(tmp_path):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        gateway.store.ensure_session('owned-invalid')
        base='/v1/sessions/owned-invalid/uploads';body={'operation_id':'bad-digest','name':'fixture.bin','mime':'application/octet-stream','size':3,'sha256':'0'*64}
        state=await (await http.post(base,json=body)).json();common={'operation_id':body['operation_id'],'upload_id':state['upload_id']}
        assert (await http.post(base+'/chunk',json={**common,'offset':0,'data_base64':base64.b64encode(b'abc').decode()})).status==200
        assert (await http.post(base+'/finish',json=common)).status==409
        assert gateway.store.list_attachments('owned-invalid')==[]
        folder=gateway._staged_upload_dir('owned-invalid')/('partial-'+state['upload_id'])
        # Owned fixture swap; original synthetic bytes preserved outside the link.
        (folder/'0').rename(folder/'original-fixture-bytes')
        target=tmp_path/'fixture-target';target.write_bytes(b'abc');(folder/'0').symlink_to(target)
        assert (await http.get(base+'?operation_id=bad-digest')).status==409
        assert target.read_bytes()==b'abc' and gateway.store.list_attachments('owned-invalid')==[]
