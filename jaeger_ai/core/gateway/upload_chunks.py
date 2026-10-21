"""Resumable immutable byte staging within existing attachment/Gateway owners.

Manifest in existing schema_meta, partial bytes under existing attachment root.
No request/model execution, new database/service, background worker or deletion.
Only final verified bytes enter the existing attachment registration route.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import uuid
import stat
from pathlib import Path
from aiohttp import web

CHUNK_BYTES=256*1024


def _key(session,actor,operation):
    if not isinstance(operation,str) or not 1<=len(operation)<=200:raise ValueError('A stable upload operation is required')
    return 'attachment-upload:'+hashlib.sha256(json.dumps([session,actor,operation]).encode()).hexdigest()


def _manifest(gateway,session,actor,operation):
    with gateway.store._get_conn() as conn:
        row=conn.execute('SELECT value FROM schema_meta WHERE key=?',(_key(session,actor,operation),)).fetchone()
    if row is None:raise KeyError('Upload not retained in this conversation/caller scope')
    return json.loads(row[0])


def _folder(gateway,manifest):
    return gateway._staged_upload_dir(manifest['session_id'])/('partial-'+manifest['upload_id'])


def _read_chunk(folder, offset):
    if folder.is_symlink():raise ValueError('Partial upload directory changed; original retained')
    fd=os.open(folder/str(offset),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>CHUNK_BYTES:raise ValueError('Partial chunk is not a bounded regular file')
        return stream.read(CHUNK_BYTES+1)


def _complete(gateway,manifest):
    for row in gateway.store.list_attachments(manifest['session_id']):
        if (row.get('metadata') or {}).get('idempotency_key')=='chunks:'+manifest['upload_id']:
            if row['sha256']!=manifest['sha256'] or row['size_bytes']!=manifest['size']:
                raise ValueError('Staged attachment conflicts with original upload; original partial bytes retained')
            return gateway._upload_view(row)


def _status(gateway,manifest):
    attachment=_complete(gateway,manifest)
    folder=_folder(gateway,manifest)
    offset=manifest['size'] if attachment else 0
    # Fixed offsets and bounded reads: crash after a durable chunk but before
    # its HTTP ACK is discoverable without appending/replaying that chunk.
    while offset<manifest['size']:
        try:data=_read_chunk(folder,offset)
        except FileNotFoundError:break
        if len(data)!=min(CHUNK_BYTES,manifest['size']-offset):raise ValueError('Partial upload chunk changed; original retained')
        offset+=len(data)
    return {**{k:v for k,v in manifest.items() if k!='actor'},'state':'complete' if attachment else 'pending',
            'received_bytes':manifest['size'] if attachment else offset,'chunk_bytes':CHUNK_BYTES,'attachment':attachment}


def register(gateway):
    async def begin(request):
        sid=request.match_info['id'];actor=request['caller_actor']
        if not gateway.store.get_session(sid):return web.json_response({'error':'Session not found'},status=404)
        try:
            body=await request.json()
            if not isinstance(body,dict) or set(body)!={'operation_id','name','mime','size','sha256'}:raise ValueError('Exact upload descriptor required')
            if type(body['size']) is not int or not 1<=body['size']<=gateway.UPLOAD_MAX_BYTES:raise ValueError('Upload size exceeds existing attachment limit')
            if not isinstance(body['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',body['sha256']):raise ValueError('Original file digest required')
            if not isinstance(body['name'],str) or not 1<=len(body['name'])<=1024 or not isinstance(body['mime'],str) or len(body['mime'])>200:raise ValueError('Bounded file name and MIME required')
            key=_key(sid,actor,body['operation_id'])
            with gateway.store._immediate() as conn:
                row=conn.execute('SELECT value FROM schema_meta WHERE key=?',(key,)).fetchone()
                if row:
                    manifest=json.loads(row[0])
                    if any(manifest[k]!=v for k,v in body.items()):raise ValueError('Upload operation belongs to different file bytes or metadata')
                else:
                    manifest={**body,'session_id':sid,'actor':actor,'upload_id':uuid.uuid4().hex}
                    conn.execute('INSERT INTO schema_meta VALUES (?,?)',(key,json.dumps(manifest)))
            return web.json_response(_status(gateway,manifest))
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)

    async def status(request):
        try:
            return web.json_response(_status(gateway,_manifest(gateway,request.match_info['id'],request['caller_actor'],request.query.get('operation_id'))))
        except KeyError:return web.json_response({'error':'Upload not retained in this scope; outcome unknown, do not assume absent admission'},status=404)
        except (ValueError,TypeError,OSError) as exc:return web.json_response({'error':str(exc)},status=409)

    async def change(request):
        try:
            body=await request.json();action=request.match_info['action']
            expected={'operation_id','upload_id'}|({'offset','data_base64'} if action=='chunk' else set())
            if action not in {'chunk','finish'} or not isinstance(body,dict) or set(body)!=expected:raise ValueError('Exact upload chunk/finish fields required')
            manifest=_manifest(gateway,request.match_info['id'],request['caller_actor'],body['operation_id'])
            if body['upload_id']!=manifest['upload_id']:raise ValueError('Upload identity mismatch')
            current=_status(gateway,manifest)
            if action=='chunk':
                if current['attachment']:raise ValueError('Upload already complete; inspect final attachment, no chunk rewritten')
                offset=body['offset']
                if type(offset) is not int or offset<0 or offset%CHUNK_BYTES or offset>=manifest['size'] or offset>current['received_bytes']:raise ValueError('Upload offset does not follow retained chunks')
                if not isinstance(body['data_base64'],str) or len(body['data_base64'])>(CHUNK_BYTES*4//3+8):raise ValueError('Chunk exceeds supported bound')
                data=base64.b64decode(body['data_base64'],validate=True)
                if len(data)!=min(CHUNK_BYTES,manifest['size']-offset):raise ValueError('Chunk size does not match original descriptor')
                folder=_folder(gateway,manifest);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                path=folder/str(offset)
                if path.exists():
                    old=_read_chunk(folder,offset)
                    if old!=data:raise ValueError('Chunk identity already contains different bytes; original retained')
                else:
                    temp=folder/('pending-'+uuid.uuid4().hex)
                    try:
                        with temp.open('xb') as stream:os.chmod(temp,0o600);stream.write(data);stream.flush();os.fsync(stream.fileno())
                        try:os.link(temp,path) # Never overwrite an acknowledged chunk.
                        except FileExistsError:
                            if _read_chunk(folder,offset)!=data:raise ValueError('Concurrent chunk has different bytes; original retained')
                        fd=os.open(folder,os.O_RDONLY)
                        try:os.fsync(fd)
                        finally:os.close(fd)
                    finally:
                        if temp.exists():temp.unlink() # Only this operation's temporary duplicate, not retained chunks.
                return web.json_response(_status(gateway,manifest))
            if current['attachment']:return web.json_response(current)
            if current['received_bytes']!=manifest['size']:raise ValueError('Upload incomplete; retain and resume original chunks')
            data=bytearray()
            folder=_folder(gateway,manifest)
            for offset in range(0,manifest['size'],CHUNK_BYTES):
                data.extend(_read_chunk(folder,offset))
            if len(data)!=manifest['size'] or hashlib.sha256(data).hexdigest()!=manifest['sha256']:raise ValueError('Final upload digest mismatch; no attachment registered, partial bytes retained')
            # Reuse the one established staging/registration producer. Its same
            # idempotency key recovers a crash after registration, before ACK.
            class FinalRequest:
                match_info={'id':manifest['session_id']}
                headers={'Idempotency-Key':'chunks:'+manifest['upload_id']}
                content_type='application/json'
                content_length=None
                content=None
            payload=json.dumps({'name':manifest['name'],'mime':manifest['mime'],'data_base64':base64.b64encode(data).decode()}).encode()
            class Content:
                async def read(self,n):return payload[:n]
            final=FinalRequest();final.content=Content()
            response=await gateway.handle_upload_attachment(final)
            if response.status!=201:raise ValueError('Final upload registration not confirmed; inspect original status')
            result=_status(gateway,manifest)
            if not result['attachment']:raise ValueError('Final attachment not confirmed; inspect original upload')
            return web.json_response(result)
        except KeyError:return web.json_response({'error':'Upload not retained in this scope'},status=404)
        except (ValueError,TypeError,OSError) as exc:return web.json_response({'error':str(exc)},status=409)
    gateway.app.router.add_post('/v1/sessions/{id}/uploads',begin)
    gateway.app.router.add_get('/v1/sessions/{id}/uploads',status)
    gateway.app.router.add_post('/v1/sessions/{id}/uploads/{action}',change)
