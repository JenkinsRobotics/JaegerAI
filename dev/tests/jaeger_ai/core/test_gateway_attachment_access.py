"""Verified attachment bytes under the existing session owner, no model execution."""
import base64
import hashlib
import pytest
from aiohttp.test_utils import TestClient, TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers


@pytest.mark.asyncio
async def test_file_reads_exact_registered_bytes_and_refuses_changed_foreign_or_escaped_files(tmp_path):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    gateway.store.ensure_session('owned-files', workspace=str(tmp_path/'workspace'))
    gateway.store.ensure_session('other-files')
    stage=gateway._staged_upload_dir('owned-files')/'owned-attachment';stage.mkdir(parents=True)
    file=stage/'safe.txt';file.write_bytes(b'Owned fixture bytes')
    row=gateway.store.add_attachment('owned-files',{'attachment_id':'owned-attachment','safe_path':str(file),'size_bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'provenance':'upload_staged','original_filename':'safe.txt','mime_type':'text/plain'})
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as client:
        listing=await (await client.get('/v1/sessions/owned-files/files')).json()
        assert listing['session_id']=='owned-files' and listing['files'][0]['readable']
        assert 'safe_path' not in listing['files'][0]
        response=await client.get('/v1/sessions/owned-files/files/owned-attachment')
        assert response.status==200
        data=await response.json()
        assert base64.b64decode(data['data_base64'])==b'Owned fixture bytes'
        assert data['sha256']==row['sha256'] and data['session_id']=='owned-files'
        assert (await client.get('/v1/sessions/other-files/files/owned-attachment')).status==404
        file.write_bytes(b'Changed fixture now')
        assert (await client.get('/v1/sessions/owned-files/files/owned-attachment')).status==409
        file.unlink();outside=tmp_path/'outside.txt';outside.write_bytes(b'Owned fixture bytes');file.symlink_to(outside)
        assert (await client.get('/v1/sessions/owned-files/files/owned-attachment')).status==409
        assert gateway.store.list_requests()==[]
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/sessions/owned-files/files/owned-attachment')).status==403


def test_workspace_attachment_read_and_legacy_missing_digest_are_explicit(tmp_path):
    from jaeger_ai.core.gateway.attachment_access import read,resolve
    root=tmp_path/'workspace';root.mkdir();file=root/'report.txt';file.write_bytes(b'local report')
    row={'attachment_id':'owned-report','safe_path':str(file),'size_bytes':12,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'provenance':'remote_upload'}
    assert base64.b64decode(read(row,staged_root=tmp_path/'stage',workspace=str(root),limit=100)['data_base64'])==b'local report'
    with pytest.raises(ValueError,match='originating workspace'):
        resolve(row,staged_root=tmp_path/'stage',workspace='')
    with pytest.raises(ValueError,match='immutable digest'):
        resolve({**row,'sha256':None},staged_root=tmp_path/'stage',workspace=str(root))
    with pytest.raises(ValueError,match='size'):
        read(row,staged_root=tmp_path/'stage',workspace=str(root),limit=1)
