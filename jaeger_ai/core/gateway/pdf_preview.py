"""Bounded static PDF projection from verified bytes, not a PDF execution surface.

Optional existing Poppler binaries only. Fixed arguments, external temporary
workspace, no viewer/JavaScript, bounded output/time and owned child cleanup.
"""
from __future__ import annotations

import base64
import os
import re
import selectors
import shutil
import signal
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from jaeger_ai.contract.file_previews import (
    PDF_MAX_DIMENSION,
    PDF_MAX_DOCUMENT_PAGES,
    PDF_MAX_INPUT_BYTES,
    PDF_MAX_PNG_BYTES,
    PDF_MAX_PREVIEW_PAGES,
    PDF_MAX_TEXT_BYTES,
)

DEADLINE_SECONDS=8


def _output(binary: str, args: list[str], data: bytes, *, limit: int, deadline: float) -> bytes:
    """Drain a fixed local parser with a hard byte/time budget; reap only its group."""
    with tempfile.TemporaryDirectory(prefix='jaeger-pdf-preview-') as folder, tempfile.TemporaryFile(dir=folder) as source:
        source.write(data);source.seek(0)
        env={**os.environ,'XDG_CACHE_HOME':folder}
        process=subprocess.Popen([binary,*args,'-'],stdin=source,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                 cwd=folder,env=env,start_new_session=True)
        try:
            chunks=[];size=0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout,selectors.EVENT_READ)
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('PDF preview deadline exceeded')
                    if not selector.select(remaining):raise TimeoutError('PDF preview deadline exceeded')
                    chunk=os.read(process.stdout.fileno(),min(65536,limit-size+1))
                    if not chunk:break
                    size+=len(chunk)
                    if size>limit:raise ValueError('PDF preview output exceeds bound')
                    chunks.append(chunk)
            if process.wait(timeout=max(0.01,deadline-time.monotonic()))!=0:raise ValueError('PDF parser refused input')
            return b''.join(chunks)
        finally:
            # Do not poll here: polling reaps an exited group leader. Its
            # descendants may still hold stdout open, and retaining the unreaped
            # leader reserves this PID/PGID until the owned group is signalled.
            if process.returncode is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait()
            if process.stdout is not None:process.stdout.close()


def pdf(data: bytes, mime: str, name: str, *, page: int = 1) -> dict:
    if type(page) is not int or not 1<=page<=PDF_MAX_PREVIEW_PAGES:raise ValueError('PDF preview page outside supported bounds')
    if len(data)>PDF_MAX_INPUT_BYTES or not data.startswith(b'%PDF-') or not name.lower().endswith('.pdf') or mime.split(';')[0].strip().lower() not in {'application/pdf','application/octet-stream'}:raise ValueError('Unsupported PDF input')
    binaries={name:shutil.which(name) for name in ('pdfinfo','pdftoppm','pdftotext')}
    if not binaries['pdfinfo'] or not binaries['pdftoppm']:
        return {'format':'unsupported','notice':'Local static PDF preview tools are unavailable. No installation attempted; download verified bytes to use a viewer.'}
    binaries={name:str(Path(path).resolve()) if path else None for name,path in binaries.items()}
    deadline=time.monotonic()+DEADLINE_SECONDS
    info=_output(binaries['pdfinfo'],[],data,limit=64000,deadline=deadline).decode('utf-8',errors='replace')
    counts=re.findall(r'^Pages:[ \t]+([0-9]+)[ \t]*$',info,re.MULTILINE)
    if len(counts)!=1 or not 1<=int(counts[0])<=PDF_MAX_DOCUMENT_PAGES or page>int(counts[0]):raise ValueError('PDF page is unavailable')
    if re.search(r'^Encrypted:\s+yes',info,re.MULTILINE|re.IGNORECASE):raise ValueError('Encrypted PDF preview is unsupported; no password requested')
    png=_output(binaries['pdftoppm'],['-f',str(page),'-l',str(page),'-scale-to',str(PDF_MAX_DIMENSION),'-singlefile','-png'],data,limit=PDF_MAX_PNG_BYTES,deadline=deadline)
    if png[:8]!=b'\x89PNG\r\n\x1a\n' or len(png)<33 or png[12:16]!=b'IHDR':raise ValueError('Invalid static PDF render')
    width,height=struct.unpack('>II',png[16:24])
    if not 0<width<=PDF_MAX_DIMENSION or not 0<height<=PDF_MAX_DIMENSION:raise ValueError('PDF raster exceeds bounds')
    text=''
    if binaries['pdftotext']:
        # Fixed page only; no HTML, links, embedded scripts or active PDF returned.
        text=_output(binaries['pdftotext'],['-f',str(page),'-l',str(page),'-enc','UTF-8','-layout','-q','-'],data,limit=PDF_MAX_TEXT_BYTES,deadline=deadline).decode('utf-8',errors='strict').replace('\x0c','').strip()
        if '\x00' in text:raise ValueError('Invalid PDF text projection')
    return {'format':'pdf','notice':'Static local page image and literal extracted text only; links, scripts, attachments and remote actions are not activated. Scanned pages may have no text. Preview is bounded to the first20 pages; verified original is unchanged.',
            'page':page,'page_count':int(counts[0]),'page_limit':PDF_MAX_PREVIEW_PAGES,'image_base64':base64.b64encode(png).decode('ascii'),
            'width':width,'height':height,'text':text,'limits':{'input_bytes':PDF_MAX_INPUT_BYTES,'image_bytes':PDF_MAX_PNG_BYTES,'text_bytes':PDF_MAX_TEXT_BYTES,'dimension':PDF_MAX_DIMENSION}}
