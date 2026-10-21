"""Actual existing local PDF render/parser boundary, owned synthetic bytes only."""
import base64
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

from jaeger_ai.core.gateway.pdf_preview import _output, pdf

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


def owned_pdf():
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Count 2 /Kids [3 0 R 4 0 R] >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for text in ('Owned PDF page one','Owned PDF page two'):
        stream=f'BT /F1 16 Tf 20 100 Td ({text}) Tj ET'.encode()
        objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    data=b'%PDF-1.4\n';offsets=[0]
    for index,obj in enumerate(objects,1):offsets.append(len(data));data+=str(index).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref=len(data);data+=b'xref\n0 8\n0000000000 65535 f \n'
    data+=b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    return data+b'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'


@pytest.mark.skipif(not all(shutil.which(n) for n in ('pdfinfo','pdftoppm','pdftotext')),reason='Existing local Poppler required; not installed by tests')
def test_real_static_pdf_pages_and_literal_text():
    raw=owned_pdf();first=pdf(raw,'application/pdf','owned.pdf');second=pdf(raw,'application/pdf','owned.pdf',page=2)
    assert first['format']=='pdf' and first['page_count']==2 and first['page']==1 and first['page_limit']==20
    assert 'Owned PDF page one' in first['text'] and 'Owned PDF page two' not in first['text']
    assert 'Owned PDF page two' in second['text'] and first['image_base64']!=second['image_base64']
    assert base64.b64decode(first['image_base64']).startswith(b'\x89PNG\r\n\x1a\n')
    assert 0<first['width']<=1280 and 0<first['height']<=1280
    assert 'data_base64' not in first and 'pdf_base64' not in first
    with pytest.raises(ValueError):pdf(raw,'application/pdf','owned.pdf',page=3)


def test_unavailable_pdf_tools_and_bad_inputs_never_install_or_launch(monkeypatch):
    monkeypatch.setattr(shutil,'which',lambda _:None)
    result=pdf(owned_pdf(),'application/pdf','owned.pdf');assert result['format']=='unsupported' and 'No installation attempted' in result['notice']
    for page in (0,21,True):
        with pytest.raises(ValueError):pdf(owned_pdf(),'application/pdf','owned.pdf',page=page)
    with pytest.raises(ValueError):pdf(b'<script>untrusted</script>','application/pdf','owned.pdf')
    with pytest.raises(ValueError):pdf(owned_pdf(),'text/html','owned.pdf')


def test_local_parser_byte_limit_and_timeout_reap_only_owned_children(tmp_path):
    marker=tmp_path/'owned-child.pid'
    code=f'import os;from pathlib import Path;Path({str(marker)!r}).write_text(str(os.getpid()));print("x"*1000000)'
    with pytest.raises(ValueError,match='output exceeds bound'):_output(sys.executable,['-c',code],b'',limit=32,deadline=time.monotonic()+3)
    with pytest.raises(ProcessLookupError):os.kill(int(marker.read_text()),0)
    code=f'import os,time;from pathlib import Path;Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(30)'
    with pytest.raises(TimeoutError):_output(sys.executable,['-c',code],b'',limit=32,deadline=time.monotonic()+0.4)
    with pytest.raises(ProcessLookupError):os.kill(int(marker.read_text()),0)



def test_deadline_cleans_descendant_after_parent_exit_without_signalling_other_group(tmp_path):
    marker=tmp_path/'descendant.pid'
    control=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True)
    child=None
    def observe(pid, *, allow_missing=False):
        observed=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True,timeout=2,check=False)
        assert not observed.stderr.strip(), observed.stderr
        assert observed.returncode in ({0,1} if allow_missing else {0}), observed
        status=observed.stdout.strip()
        if observed.returncode==0:assert status and len(status.splitlines())==1, observed
        else:assert allow_missing and not status, observed
        return status
    # The child inherits stdout and its parent's new process group. The parent
    # exits immediately; only the child keeps the parser pipe open.
    code=("import os,subprocess,sys;from pathlib import Path;"
          "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
          f"Path({str(marker)!r}).write_text(str(p.pid));os._exit(0)")
    try:
        assert not observe(control.pid).startswith('Z')
        with pytest.raises(TimeoutError):
            _output(sys.executable,['-c',code],b'',limit=32,deadline=time.monotonic()+0.8)
        child=int(marker.read_text())
        # A killed orphan can remain a zombie briefly until init reaps it.
        # ps status distinguishes that from a surviving sleeping descendant.
        end=time.monotonic()+3
        while time.monotonic()<end:
            status=observe(child,allow_missing=True)
            if not status or status.startswith('Z'):break
            time.sleep(0.02)
        assert not status or status.startswith('Z'), status
        assert not observe(control.pid).startswith('Z')
        assert control.poll() is None
    finally:
        if child is None and marker.exists():child=int(marker.read_text())
        if child is not None:
            try:os.kill(child,signal.SIGKILL)
            except ProcessLookupError:pass
        control.kill();control.wait()


@pytest.mark.asyncio
@pytest.mark.skipif(not all(shutil.which(n) for n in ('pdfinfo','pdftoppm')),reason='Existing local Poppler required')
async def test_real_registered_pdf_preview_digest_page_scope_and_changed_bytes(gw):
    app,http=gw;app.store.ensure_session('owned-pdf');app.store.ensure_session('other-pdf');raw=owned_pdf()
    uploaded=await (await http.post('/v1/sessions/owned-pdf/attachments/upload',json={'name':'owned.pdf','mime':'application/pdf','data_base64':base64.b64encode(raw).decode()})).json()
    path='/v1/sessions/owned-pdf/files/'+uploaded['attachment_id']+'?view=preview&page=2'
    response=await http.get(path);assert response.status==200
    value=await response.json();assert value['sha256']==hashlib.sha256(raw).hexdigest() and value['preview']['page']==2
    assert 'data_base64' not in value and 'Owned PDF page two' in value['preview']['text']
    assert (await http.get(path.replace('owned-pdf','other-pdf'))).status==404
    row=app.store.list_attachments('owned-pdf')[0]
    from pathlib import Path
    Path(row['safe_path']).write_bytes(b'changed')
    assert (await http.get(path)).status==409


def test_ambiguous_pdf_metadata_cannot_fabricate_page_count(monkeypatch):
    from jaeger_ai.core.gateway import pdf_preview
    monkeypatch.setattr(pdf_preview.shutil,'which',lambda name:'/owned/'+name)
    calls=[]
    def output(*a,**k):calls.append(a[0]);return b'Title: owned\nPages: 9999\nPages: 2\n'
    monkeypatch.setattr(pdf_preview,'_output',output)
    with pytest.raises(ValueError,match='page is unavailable'):pdf(owned_pdf(),'application/pdf','owned.pdf')
    assert calls==['/owned/pdfinfo']


@pytest.mark.asyncio
async def test_repeated_pdf_requests_share_one_owned_renderer_and_keep_source_scope(gw,monkeypatch):
    import asyncio
    import threading

    from jaeger_ai.core.gateway import pdf_preview
    app,http=gw;app.store.ensure_session('owned-repeated-pdf');raw=owned_pdf()
    uploaded=await (await http.post('/v1/sessions/owned-repeated-pdf/attachments/upload',json={'name':'owned.pdf','mime':'application/pdf','data_base64':base64.b64encode(raw).decode()})).json()
    other=await (await http.post('/v1/sessions/owned-repeated-pdf/attachments/upload',json={'name':'other.pdf','mime':'application/pdf','data_base64':base64.b64encode(raw).decode()})).json()
    app.store.append_message('owned-repeated-pdf','user','Retain this transcript')
    seen=app.store.agents_seen()
    started,release=threading.Event(),threading.Event();calls=[]
    def render(*a,**k):
        calls.append(1);started.set()
        if not release.wait(3):raise TimeoutError('Owned fixture gate')
        return {'format':'unsupported','notice':'Owned deterministic renderer receipt'}
    monkeypatch.setattr(pdf_preview,'pdf',render)
    path='/v1/sessions/owned-repeated-pdf/files/'+uploaded['attachment_id']+'?view=preview'
    first=asyncio.create_task(http.get(path))
    try:
        assert await asyncio.to_thread(started.wait,2)
        second=asyncio.create_task(http.get(path))
        busy=await (await http.get(path.replace(uploaded['attachment_id'],other['attachment_id']))).json()
        assert 'no additional renderer' in busy['preview']['notice']
        release.set()
        left,right=await asyncio.gather(first,second)
        assert await left.json()==await right.json() and calls==[1]
        assert (await (await http.get(path)).json())['preview']['notice']=='Owned deterministic renderer receipt'
        assert calls==[1] and len(app.store.list_messages('owned-repeated-pdf')['messages'])==1
        assert app.store.agents_seen()==seen
    finally:release.set();await first
