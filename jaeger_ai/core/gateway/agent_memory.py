"""Operator view/edit of the same specialist notes owner used by agent_notes."""
from __future__ import annotations
import asyncio
from aiohttp import web
from jaeger_agent.tools.agent_notes import read_notes,mutate_notes,note_versions


def register(gateway):
    def owner(agent_id):
        record=gateway._registry().get_agent(agent_id)
        if record is None or record.id!=agent_id:raise KeyError('Canonical agent required')
        if record.kind.value!='jaeger_native':raise ValueError('External agent memory is not owned by this Gateway')
        return record,gateway.agent_memory_dir(record)
    def editable(record):
        from .agent_presentation import can_rename
        return record.role.value=='specialist' and can_rename(record.to_dict())
    async def read(request):
        try:
            record,root=owner(request.match_info['id'])
            snapshot=await asyncio.to_thread(read_notes,root)
            return web.json_response({'agent_id':record.id,'editable':editable(record),'loaded_in_specialist_prompt':record.role.value=='specialist',**snapshot,'versions':await asyncio.to_thread(note_versions,root)})
        except KeyError:return web.json_response({'error':'Agent not found'},status=404)
        except (ValueError,OSError):return web.json_response({'error':'Memory ownership/content unavailable; original notes preserved'},status=409)
    async def mutate(request):
        try:
            record,root=owner(request.match_info['id'])
            if not editable(record):return web.json_response({'error':'Only exposed native specialist notes are editable; execution definitions unchanged'},status=403)
            body=await request.json()
            action=body.get('action') if isinstance(body,dict) else None
            fields={'operation_id','expected_revision','action', 'text' if action=='replace' else 'restore_revision'}
            if action not in {'replace','restore'} or set(body)!=fields:raise ValueError('Unsupported notes action/fields')
            oid=body['operation_id']
            if not isinstance(oid,str) or not oid.strip() or len(oid)>128 or not isinstance(body['expected_revision'],str):raise ValueError('Stable operation and current revision required')
            if action=='replace' and not isinstance(body['text'],str):raise ValueError('Notes text required')
            if not gateway.store.reserve_control_operation(oid,{'action':'agent.notes','id':record.id,'body':body}):
                receipt=gateway.store.control_operation(oid)['receipt']
                return web.json_response(receipt or {'operation_id':oid,'execution_unknown':True,'error':'Save outcome unknown; read current notes without replay'},status=receipt.get('http_status',200) if receipt else 409)
        except KeyError:return web.json_response({'error':'Agent not found'},status=404)
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=400)
        try:
            result=await asyncio.to_thread(mutate_notes,root,action,body.get('text',''),expected_revision=body['expected_revision'],restore_revision=body.get('restore_revision'))
            receipt={'ok':True,'operation_id':oid,'http_status':200,'agent_id':record.id,'revision':result['revision'],'chars':result['chars']}
        except ValueError:receipt={'ok':False,'operation_id':oid,'http_status':409,'error':'Notes changed, invalid or unavailable; inspect preserved original and draft'}
        except Exception:return web.json_response({'operation_id':oid,'execution_unknown':True,'error':'Notes save outcome unknown; inspect without replay'},status=503)
        gateway.store.finish_control_operation(oid,receipt)
        if receipt['ok']:gateway.event_bus.publish('*','agent.memory.changed',{'agent_id':record.id,'revision':receipt['revision']})
        return web.json_response(receipt,status=receipt['http_status'])
    gateway.app.router.add_get('/v1/agents/{id}/memory',read)
    gateway.app.router.add_post('/v1/agents/{id}/memory',mutate)
