"""Explicit resource reads and reviewed copy into existing managed Library."""
from __future__ import annotations
import asyncio
import re
from aiohttp import web
from jaeger_ai.contract.knowledge import MANAGED_DOCUMENT_MAX_BYTES
from . import client,resources


def register(gateway):
    async def cached(request):
        registry=client.get_registry()
        try:
            if registry is None:raise ValueError('MCP not loaded')
            return web.json_response(resources.snapshot(registry,request.match_info['id'],request.match_info['snapshot']))
        except ValueError:return web.json_response({'error':'Volatile snapshot unavailable; no provider read was performed'},status=404)
    async def mutate(request):
        action=request.match_info['action'];server_id=request.match_info['id']
        if action not in {'list','read','import'}:raise web.HTTPNotFound()
        try:
            body=await request.json()
            fields={'operation_id','page'} if action=='list' else {'operation_id','resource_id'} if action=='read' else {'operation_id','snapshot_id','expected_digest'}
            if not isinstance(body,dict) or set(body)!=fields:raise ValueError('Unexpected or missing resource fields')
            oid=body['operation_id']
            if not re.fullmatch(r'[a-f0-9]{24}',server_id) or not isinstance(oid,str) or not oid.strip() or len(oid)>128:raise ValueError('Invalid resource/control identity')
            payload={'action':'mcp.resource.'+action,'id':server_id,'body':body}
            fresh=gateway.store.reserve_control_operation(oid,payload) if action=='import' else gateway.store.reserve_scoped_control_operation(oid,payload,'mcp.resource:'+server_id)
            if not fresh:
                receipt=gateway.store.control_operation(oid)['receipt']
                return web.json_response(receipt or {'operation_id':oid,'execution_unknown':True,'error':'Original resource outcome unknown; do not retry'},status=receipt.get('http_status',200) if receipt else 409)
        except (TypeError,ValueError) as exc:return web.json_response({'error':str(exc)},status=400)
        try:
            registry=client.get_registry()
            if registry is None:raise ValueError('MCP is not initialized; no server started')
            if action=='list':
                page=body['page']
                if page is not None and (not isinstance(page,str) or not re.fullmatch(r'[a-f0-9]{32}',page)):raise ValueError('Invalid opaque page handle')
                result={'catalog':await asyncio.to_thread(resources.listing,registry,server_id,page=page)}
            elif action=='read':
                if not isinstance(body['resource_id'],str) or not re.fullmatch(r'[a-f0-9]{32}',body['resource_id']):raise ValueError('Invalid listed resource handle')
                snapshot=await asyncio.to_thread(resources.read,registry,server_id,body['resource_id'],limit=MANAGED_DOCUMENT_MAX_BYTES)
                # Receipts preserve only metadata, never duplicate source text in Gateway DB.
                result={'snapshot':{k:v for k,v in snapshot.items() if k!='text'},'volatile_content':True}
            else:
                if not isinstance(body['snapshot_id'],str) or not isinstance(body['expected_digest'],str):raise ValueError('Reviewed snapshot identity/digest required')
                snapshot=resources.snapshot(registry,server_id,body['snapshot_id'])
                if snapshot['digest']!=body['expected_digest']:raise ValueError('Snapshot changed; review before importing')
                from jaeger_ai.features.knowledge_library.tools import _library
                library=_library()
                try:
                    row=library.create_document(title=snapshot['title'],content=snapshot['text'],command_id=oid,
                        provenance={'kind':'configured_mcp_resource','server_id':server_id,'resource_id':snapshot['resource_id'],'source_text_digest':snapshot['digest'],'observed_at':snapshot['observed_at'],'redacted':snapshot['redacted']})
                    result={'document':{k:row[k] for k in ('id','revision','digest','provenance')}}
                finally:library.close()
            receipt={'ok':True,'operation_id':oid,'http_status':200,'result':result}
        except (ValueError,TypeError,KeyError):receipt={'ok':False,'operation_id':oid,'http_status':409,'error':'Resource unsupported, unavailable, changed or not previously listed/reviewed; no automatic retry'}
        except Exception:return web.json_response({'operation_id':oid,'execution_unknown':True,'error':'Resource operation outcome unknown; inspect original receipt without replay'},status=503)
        gateway.store.finish_control_operation(oid,receipt)
        if receipt['ok'] and action=='import':gateway.event_bus.publish('*','library.document.updated',{'document_id':result['document']['id'],'revision':result['document']['revision']})
        return web.json_response(receipt,status=receipt['http_status'])
    gateway.app.router.add_get('/v1/runtime/mcp/{id}/resources/snapshots/{snapshot}',cached)
    gateway.app.router.add_post('/v1/runtime/mcp/{id}/resources/{action}',mutate)
