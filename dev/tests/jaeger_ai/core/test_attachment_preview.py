"""Literal-only spreadsheet parsing over verified attachment scope."""
import base64
import io
import zipfile
import hashlib
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.gateway.attachment_preview import spreadsheet
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers

MIME='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

def workbook(*,evil=False,external=False):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_STORED) as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Fixture" r:id="r1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="'+('https://forbidden.invalid/private' if external else 'worksheets/sheet1.xml')+'"'+(' TargetMode="External"' if external else '')+'/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',('<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///forbidden">]>' if evil else '')+'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="10"><c r="A10" t="inlineStr"><is><t>&lt;script&gt;not executed&lt;/script&gt;</t></is></c><c r="B10"><f>WEBSERVICE("https://forbidden.invalid")</f><v>42</v></c></row></sheetData></worksheet>')
        z.writestr('xl/vbaProject.bin',b'never executed or imported')
    return data.getvalue()


def test_literal_spreadsheet_bounds_and_no_active_content():
    result=spreadsheet(workbook(),MIME,'fixture.xlsx');sheet=result['sheets'][0]
    assert sheet['row_numbers']==[10] and sheet['rows'][0][:2]==['<script>not executed</script>','42']
    assert 'WEBSERVICE' not in str(result) and 'forbidden.invalid' not in str(result)
    assert spreadsheet(workbook(external=True),MIME,'fixture.xlsx')['sheets']==[]
    with pytest.raises(ValueError,match='XML declarations'):spreadsheet(workbook(evil=True),MIME,'fixture.xlsx')
    with pytest.raises(ValueError):spreadsheet(b'not zip',MIME,'fixture.xlsm')
    csv=spreadsheet(('a,b\n'+'=1+1,plain\n'*60).encode(),'text/csv','fixture.csv')
    assert len(csv['sheets'][0]['rows'])==50 and csv['sheets'][0]['rows'][1][0]=='=1+1'


@pytest.mark.asyncio
async def test_preview_uses_real_attachment_digest_scope_and_proxy_contract(tmp_path):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        gateway.store.ensure_session('owned-files');gateway.store.ensure_session('other-files')
        raw=workbook()
        uploaded=await (await http.post('/v1/sessions/owned-files/attachments/upload',json={'name':'fixture.xlsx','mime':MIME,'data_base64':base64.b64encode(raw).decode()})).json()
        path='/v1/sessions/owned-files/files/'+uploaded['attachment_id']+'?view=preview'
        response=await http.get(path);assert response.status==200
        value=await response.json();assert value['sha256']==hashlib.sha256(raw).hexdigest() and value['preview']['sheets'][0]['rows'][0][1]=='42'
        assert 'data_base64' not in value
        assert (await http.get(path.replace('owned-files','other-files'))).status==404
        assert (await http.get(path,headers=client_headers('a2a'))).status==403
        stored=gateway.store.list_attachments('owned-files')[0]
        from pathlib import Path
        Path(stored['safe_path']).write_bytes(b'changed')
        assert (await http.get(path)).status==409
