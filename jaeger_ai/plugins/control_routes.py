"""Installed extension metadata and managed-hook controls; never load plugin code."""
from __future__ import annotations
import asyncio
from aiohttp import web
from . import registry


def register(gateway):
    async def listing(request):
        return web.json_response(await asyncio.to_thread(registry.catalog))
    async def mutate(request):
        identity=request.match_info['id'];action=request.match_info['action']
        if action not in {'pause_hooks','resume_hooks'}:raise web.HTTPNotFound()
        try:
            body=await request.json()
            if not isinstance(body,dict) or set(body)!={'operation_id','expected_state'}:raise ValueError('Stable operation and expected state required')
            oid=body['operation_id']
            if not isinstance(oid,str) or not oid.strip() or len(oid)>128 or not isinstance(body['expected_state'],str):raise ValueError('Invalid control fields')
            if not gateway.store.reserve_scoped_control_operation(oid,{'action':'plugin.'+action,'id':identity,'body':body},'plugin:'+identity):
                receipt=gateway.store.control_operation(oid)['receipt']
                return web.json_response(receipt or {'operation_id':oid,'execution_unknown':True,'error':'Original hook operation unresolved; do not retry'},status=receipt.get('http_status',200) if receipt else 409)
        except (TypeError,ValueError) as exc:return web.json_response({'error':str(exc)},status=400)
        try:
            if action=='resume_hooks':
                from jaeger_ai.core.gateway.server import _control_plane_block
                if _control_plane_block():raise ValueError('Global Stop or live-owner guard prevents resuming hooks')
            result=registry.control_hooks(identity,action,body['expected_state'])
            receipt={'ok':True,'operation_id':oid,'http_status':200,'result':result}
        except ValueError as exc:receipt={'ok':False,'operation_id':oid,'http_status':409,'error':str(exc)}
        except Exception:return web.json_response({'operation_id':oid,'execution_unknown':True,'error':'Hook transition unknown; inspect without replay'},status=503)
        gateway.store.finish_control_operation(oid,receipt)
        gateway.event_bus.publish('*','plugins.changed',{'id':identity,'confirmed':receipt['ok']})
        return web.json_response(receipt,status=receipt['http_status'])
    gateway.app.router.add_get('/v1/runtime/plugins',listing)
    gateway.app.router.add_post('/v1/runtime/plugins/{id}/{action}',mutate)
