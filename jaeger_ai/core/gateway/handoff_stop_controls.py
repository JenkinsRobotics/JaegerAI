"""Explicit owner leaf Stop, durable command receipt, existing scopes only."""
from aiohttp import web

from jaeger_ai.core.gateway.handoff_cancellation import (
    cancel_one,
    status,
    unconfirmed_ids,
)
from jaeger_ai.core.gateway.handoff_controls import command_key


def register(gateway):
    def owner(request):
        caller=request.get('caller')
        if caller is None or 'admin' not in caller.scopes or caller.session_prefix:
            raise web.HTTPForbidden(text='Owner administration scope required')
        # Existing local owner callers share administration; untrusted callers
        # never enter here. No new grants, actor rewrite or tool authority.
        if not str(request['caller_actor']).startswith('owner:'):
            raise web.HTTPForbidden(text='Owner caller required')

    def owned(request):
        owner(request)
        row=gateway.store.get_handoff(request.match_info['id'])
        if row is None:raise web.HTTPNotFound(text='Handoff not retained')
        return row

    async def listing(request):
        owner(request)
        rows=gateway.store.list_handoffs(limit=100)
        return web.json_response({'handoffs':[{'handoff_id':row['id'],'request_id':row['request_id'],'task':row['task'],'from_agent_id':row['from_agent_id'],'to_agent_id':row['to_agent_id'],'current':status(gateway,row)} for row in rows],'limit':100})

    def receipt(row,op,actor):
        saved=gateway.store.control_operation(command_key('handoff_stop',row['id'],op,actor))
        if saved is None:raise web.HTTPNotFound(text='Original Stop command not retained')
        value=saved.get('receipt')
        if value is not None:
            value=dict(value)
            # Preserve original descendant references while refreshing current
            # receipt truth; a parent finishing never settles its descendants.
            def refresh(previous):
                retained=gateway.store.get_handoff(previous['handoff_id'])
                current=status(gateway,retained) if retained else previous
                if previous.get('outcome')=='blocked':current=previous
                return {**current,'descendants':[refresh(child) for child in previous.get('descendants',[])]}
            value['current']=refresh(value['current'])
            value['unconfirmed_task_ids']=unconfirmed_ids([value['current']])
            return value
        # Monotonic intent is proof of admission, never proof that effects ended.
        meta=row.get('metadata') or {}
        accepted=meta.get('cancel_requested') and meta.get('cancel_operation_id')==op
        current=status(gateway,row)
        return {'handoff_id':row['id'],'operation_id':op,'request_id':row['request_id'],'outcome':'accepted' if accepted else 'unknown','current':current,'unconfirmed_task_ids':unconfirmed_ids([current]),'error':None if accepted else 'Original Stop outcome unknown; inspect only, nothing replayed'}

    async def state(request):
        row=owned(request)
        return web.json_response({'handoff_id':row['id'],'request_id':row['request_id'],'current':status(gateway,row)})

    async def read(request):
        row=owned(request)
        return web.json_response(receipt(row,request.match_info['operation_id'],request['caller_actor']))

    async def submit(request):
        row=owned(request);actor=request['caller_actor']
        try:
            body=await request.json()
            if not isinstance(body,dict) or set(body)!={'operation_id','request_id'}:raise ValueError('Exact Stop identity fields required')
            op=body['operation_id']
            if not isinstance(op,str) or not 1<=len(op)<=128:raise ValueError('Bounded operation identity required')
            if body['request_id']!=row['request_id']:raise ValueError('Handoff request identity changed')
            oid=command_key('handoff_stop',row['id'],op,actor)
            if not gateway.store.reserve_control_operation(oid,{'scope':'handoff_stop','resource':row['id'],'actor':actor,'body':body}):
                return web.json_response(receipt(row,op,actor))
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)
        try:
            result=await cancel_one(gateway,row['id'],operation_id=op,request_context=request)
            value={'handoff_id':row['id'],'request_id':row['request_id'],'operation_id':op,'outcome':'accepted','current':result,'unconfirmed_task_ids':unconfirmed_ids([result])}
            gateway.store.finish_control_operation(oid,value)
            return web.json_response(value)
        except Exception:  # noqa: BLE001 - post-reservation uncertainty never repeats the executor
            return web.json_response(receipt(gateway.store.get_handoff(row['id']) or row,op,actor))

    gateway.app.router.add_get('/v1/handoff-controls',listing)
    gateway.app.router.add_get('/v1/handoffs/{id}/stop-state',state)
    gateway.app.router.add_post('/v1/handoffs/{id}/stop-commands',submit)
    gateway.app.router.add_get('/v1/handoffs/{id}/stop-commands/{operation_id}',read)
