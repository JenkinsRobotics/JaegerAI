"""Owner-only controls for already-loaded MCP connections; no credential/config API."""
from __future__ import annotations
import asyncio
import sys
from aiohttp import web


def register(gateway):
    async def mutate(request):
        action = request.match_info['action']
        if action not in {'disconnect', 'reconnect'}:
            raise web.HTTPNotFound()
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'operation_id', 'expected_state'}:
                raise ValueError('operation_id and expected_state required')
            oid = body['operation_id']
            if not isinstance(oid, str) or not oid.strip() or len(oid)>128 or not isinstance(body['expected_state'],str):
                raise ValueError('Invalid control identity')
            cid = request.match_info['id']
            if not gateway.store.reserve_scoped_control_operation(oid, {'action':'mcp.'+action,'id':cid,'body':body}, 'mcp:'+cid):
                receipt = gateway.store.control_operation(oid)['receipt']
                return web.json_response(receipt or {'operation_id':oid,'execution_unknown':True,'error':'Outcome unresolved; do not retry'},status=receipt.get('http_status',200) if receipt else 409)
        except (ValueError,TypeError) as exc:
            return web.json_response({'error':str(exc)},status=400)
        module = sys.modules.get('jaeger_ai.plugins.mcp.client')
        registry = module.get_registry() if module else None
        try:
            if registry is None:
                raise ValueError('MCP is not initialized; this control does not start a bridge')
            result = await asyncio.to_thread(registry.lifecycle,cid,action,body['expected_state'])
            receipt = {'ok':True,'operation_id':oid,'http_status':200,'result':result}
        except ValueError as exc:
            receipt = {'ok':False,'operation_id':oid,'http_status':409,'error':str(exc)}
        except Exception:
            return web.json_response({'operation_id':oid,'execution_unknown':True,'error':'MCP lifecycle outcome unknown; inspect connection without replay'},status=503)
        gateway.store.finish_control_operation(oid,receipt)
        gateway.event_bus.publish('*','mcp.changed',{'id':cid,'action':action,'confirmed':receipt['ok']})
        return web.json_response(receipt,status=receipt['http_status'])
    gateway.app.router.add_post('/v1/runtime/mcp/{id}/{action}',mutate)
