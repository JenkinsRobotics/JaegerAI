"""Explicit operator resource reads through the existing connected MCP owner.

Opaque listed handles only. No arbitrary URI/config, auto-load, model grant or
external connection initialization. Text snapshots are bounded and volatile.
"""
from __future__ import annotations
import hashlib
import time
import uuid
from contextlib import contextmanager
from jaeger_ai.core.redaction import redact_text
from .client import _redact_known_secrets,_SECRET_NAME
CATALOG_LIMIT=1000
SNAPSHOT_LIMIT=5


@contextmanager
def admitted(registry,server_id):
    with registry._lifecycle_lock:
        name=next((n for n in registry._clients if registry.control_id(n)==server_id),None)
        if name is None:raise ValueError('Loaded server not found')
        client=registry._clients[name]
        if registry._server_states.get(name,'loaded_not_probed')!='loaded_not_probed':raise ValueError('Server outcome/lifecycle requires reconciliation')
        if not getattr(client,'resources_advertised',False):raise ValueError('Connected server does not advertise resources')
        registry._active_calls[name]=registry._active_calls.get(name,0)+1
    try:yield name,client
    finally:
        with registry._lifecycle_lock:registry._active_calls[name]-=1


def safe_text(client,text):
    secrets=set(client.config.headers.values())|{v for k,v in client.config.env.items() if _SECRET_NAME.search(k)}
    return redact_text(_redact_known_secrets(str(text),secrets))


def call(registry,name,client,coroutine):
    try:return registry._submit(coroutine,timeout=client.config.call_timeout_s)
    except Exception:
        with registry._lifecycle_lock:registry._server_states[name]='outcome_unknown'
        raise RuntimeError('Resource request outcome unknown; no retry') from None


def listing(registry,server_id,*,page=None):
    with admitted(registry,server_id) as (name,client):
        with registry._lifecycle_lock:
            cursor=registry._resource_pages.get((name,page)) if page else None
        if page and cursor is None:raise ValueError('Resource page handle expired; explicitly list again')
        result=call(registry,name,client,client.list_resources(cursor))
        offered=list(getattr(result,'resources',[]) or []);rows=[]
        with registry._lifecycle_lock:
            for resource in offered[:CATALOG_LIMIT]:
                uri=str(getattr(resource,'uri',''))
                if not uri or len(uri)>4096:continue
                rid=hashlib.sha256((name+'\0'+uri).encode()).hexdigest()[:32]
                registry._resource_handles[(name,rid)]={'uri':uri,'title':safe_text(client,getattr(resource,'name','Resource'))[:200] or 'Imported resource'}
                rows.append({'id':rid,'title':safe_text(client,getattr(resource,'name','Resource'))[:200],
                    'description':safe_text(client,getattr(resource,'description','') or '')[:1000],
                    'mime':safe_text(client,getattr(resource,'mimeType','') or 'unknown')[:100]})
            while len(registry._resource_handles)>CATALOG_LIMIT:registry._resource_handles.pop(next(iter(registry._resource_handles)))
            next_cursor=getattr(result,'nextCursor',None)
            next_page=uuid.uuid4().hex if next_cursor else None
            if next_page:registry._resource_pages[(name,next_page)]=str(next_cursor)
            while len(registry._resource_pages)>20:registry._resource_pages.pop(next(iter(registry._resource_pages)))
        return {'server_id':server_id,'resources':rows,'next_page':next_page,'truncated':len(offered)>CATALOG_LIMIT,'availability':'advertised_not_proven','no_grants':True}


def read(registry,server_id,resource_id,*,limit):
    with admitted(registry,server_id) as (name,client):
        with registry._lifecycle_lock:entry=registry._resource_handles.get((name,resource_id))
        if entry is None:raise ValueError('Resource handle expired or was not listed by this connection')
        result=call(registry,name,client,client.read_resource(entry['uri']))
        contents=list(getattr(result,'contents',[]) or [])
        if not contents or any(getattr(part,'text',None) is None for part in contents):raise ValueError('Only text resources can be staged; no document created')
        text='\n\n'.join(str(part.text) for part in contents)
        if len(text.encode('utf-8'))>limit:raise ValueError('Resource exceeds managed document byte limit; no document created')
        safe=safe_text(client,text)
        if len(safe.encode('utf-8'))>limit:raise ValueError('Staged text exceeds document limit')
        snapshot={'title':entry['title'],'id':uuid.uuid4().hex,'server_id':server_id,'resource_id':resource_id,'text':safe,
            'digest':hashlib.sha256(safe.encode()).hexdigest(),'redacted':safe!=text,'observed_at':time.time(),
            'source':'configured_mcp_resource','authority':'reference_data_only'}
        with registry._lifecycle_lock:
            registry._resource_snapshots[snapshot['id']]=snapshot
            while len(registry._resource_snapshots)>SNAPSHOT_LIMIT:registry._resource_snapshots.pop(next(iter(registry._resource_snapshots)))
        return snapshot


def snapshot(registry,server_id,snapshot_id):
    with registry._lifecycle_lock:value=registry._resource_snapshots.get(snapshot_id)
    if value is None or value['server_id']!=server_id:raise ValueError('Volatile resource snapshot expired; no automatic read performed')
    return dict(value)
