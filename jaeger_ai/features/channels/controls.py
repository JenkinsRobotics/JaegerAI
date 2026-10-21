"""Configured channel lifecycle and inbox bindings, without model/permission grants."""
from __future__ import annotations
import asyncio
from aiohttp import web
from . import bindings


def register(gateway):
    async def mutate(request):
        from jaeger_ai import plugins
        from .registry import get_registry
        channel=request.match_info['id'];action=request.match_info['action']
        if channel not in bindings.SUPPORTED or action not in {'bind','connect','disconnect'}:raise web.HTTPNotFound()
        try:
            body=await request.json()
            fields={'operation_id','expected_revision','agent_id'} if action=='bind' else {'operation_id'}
            if not isinstance(body,dict) or set(body)!=fields:raise ValueError('Unsupported channel control fields')
            oid=body['operation_id']
            if not isinstance(oid,str) or not oid.strip() or len(oid)>128:raise ValueError('Stable operation_id required')
            if not gateway.store.reserve_scoped_control_operation(oid,{'action':'channel.'+action,'id':channel,'body':body},'channel:'+channel):
                receipt=gateway.store.control_operation(oid)['receipt']
                return web.json_response(receipt or {'execution_unknown':True,'operation_id':oid,'error':'Channel operation unresolved; do not retry'},status=receipt.get('http_status',200) if receipt else 409)
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=400)
        try:
            bridge=plugins.get_bridge(channel)
            if action=='bind':
                if bridge is not None or get_registry().get(channel) is not None:raise ValueError('Disconnect before changing the inbox bot; current routing is preserved')
                target=gateway._registry().get_agent(body['agent_id']) if isinstance(body['agent_id'],str) else None
                row=target.to_dict() if target else {}
                role=row.get('role');role=getattr(role,'value',role)
                if row.get('id')!=body['agent_id'] or row.get('kind')!='jaeger_native' or role not in {'lead','specialist'} or (row.get('metadata') or {}).get('internal'):raise ValueError('Existing exposed native lead/specialist required')
                result={'binding':bindings.save(gateway.store,channel,target.id,body['expected_revision']),'connection_started':False}
            elif action=='disconnect':
                if bridge is None:raise ValueError('No bridge registered in this Gateway')
                if gateway._running_tasks:raise ValueError('Gateway work is active; transport retained')
                await asyncio.to_thread(bridge.stop)
                thread=getattr(bridge,'_thread',None)
                if thread is not None and thread.is_alive():raise RuntimeError('Transport exit unconfirmed')
                plugins.deregister_bridge(channel,expected=bridge)
                get_registry().unregister(channel,expected_bridge=bridge)
                result={'state':'disconnected','delivery_verified':False}
            else:
                if bridge is not None or get_registry().get(channel) is not None:raise ValueError('Bridge already registered; no handler or routing replaced')
                binding=bindings.read(gateway.store,channel)
                if not binding['agent_id']:raise ValueError('Save an inbox bot before connecting')
                from jaeger_ai.core.instance.instance import InstanceLayout
                layout=InstanceLayout(root=gateway._instance_root())
                spec=plugins._BRIDGE_SPECS[channel]
                raw=plugins.plugin_credential(layout,spec['allow'])
                allowed=plugins._parse_chat_ids(raw) if spec['ints'] else plugins._parse_handles(raw)
                if not allowed:raise ValueError('Existing valid nonempty channel allowlist required; this control cannot create/change it')
                handler=bindings.inbox(gateway,channel,binding)
                started=await asyncio.to_thread(plugins.start_bridge,channel,layout=layout,handler=handler)
                if started.get('execution_unknown'):raise RuntimeError('Transport startup unconfirmed')
                if not started.get('started') or started.get('already_running'):raise ValueError('Configured transport could not start; inspect existing setup. No credential or permission changed.')
                bridge=plugins.get_bridge(channel)
                thread=getattr(bridge,'_thread',None)
                if bridge is None or getattr(bridge,'_handler',None) is not handler or thread is None or not thread.is_alive():raise RuntimeError('Transport identity/readiness unconfirmed')
                from .plugin_adapter import register_plugin_bridge
                register_plugin_bridge(channel,bridge)
                bridge._jaeger_gateway_binding=binding
                result={'state':'registered_not_probed','binding':binding,'delivery_verified':False}
            receipt={'ok':True,'operation_id':oid,'http_status':200,'result':result}
        except (ValueError,TypeError) as exc:receipt={'ok':False,'operation_id':oid,'http_status':409,'error':str(exc)}
        except Exception:return web.json_response({'operation_id':oid,'execution_unknown':True,'error':'Channel lifecycle outcome unknown; inspect without retry'},status=503)
        gateway.store.finish_control_operation(oid,receipt)
        gateway.event_bus.publish('*','channel.changed',{'id':channel,'action':action,'confirmed':receipt['ok']})
        return web.json_response(receipt,status=receipt['http_status'])
    gateway.app.router.add_post('/v1/channels/{id}/{action}',mutate)
