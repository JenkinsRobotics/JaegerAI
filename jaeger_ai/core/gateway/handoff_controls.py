"""Read-only original handoff admission lookup; no continuation or replay."""
from aiohttp import web


def register(gateway):
    async def lookup(request):
        row=gateway.store.get_handoff_by_request(request.match_info['request_id'])
        parent=request.match_info.get('parent')
        valid=bool(row and (row.get('metadata') or {}).get('caller_actor')==request['caller_actor'])
        if parent:valid=valid and (row.get('metadata') or {}).get('reply_to_handoff_id')==parent
        else:valid=valid and row['to_agent_id']==request.match_info['id']
        if not valid:return web.json_response({'error':'Original handoff not retained in this scope; do not resubmit uncertain work'},status=404)
        return web.json_response(row)
    gateway.app.router.add_get('/v1/agents/{id}/handoff-requests/{request_id}',lookup)
    gateway.app.router.add_get('/v1/handoffs/{parent}/replies/{request_id}',lookup)
    register_commands(gateway)


def command_key(kind,resource,request_id,actor):
    import hashlib
    import json
    return 'handoff-command:'+hashlib.sha256(json.dumps([kind,resource,request_id,actor]).encode()).hexdigest()


def register_commands(gateway):
    import json

    from jaeger_ai.core.gateway.session_store import _session_agent, input_fingerprint
    def original(kind,resource,rid,actor):
        saved=gateway.store.control_operation(command_key(kind,resource,rid,actor))
        if saved is None:raise KeyError('Original command not retained')
        receipt=saved.get('receipt')
        if receipt is not None:
            receipt=dict(receipt)
            if receipt['outcome']=='saved':
                current=gateway.store.get_handoff_by_request(rid)
                if current and current['id']==receipt['handoff']['id']:receipt['handoff']=current
            return receipt
        # Admission itself is durable proof after a lost wrapper ACK. Do not
        # repeat the executor when the control reservation remains uncertain.
        row=gateway.store.get_handoff_by_request(rid)
        match=row and (row.get('metadata') or {}).get('caller_actor')==actor
        match=match and ((row.get('metadata') or {}).get('reply_to_handoff_id')==resource if kind=='handoff_reply' else row['to_agent_id']==resource)
        if match:
            body={'task':row['task'],'request_id':rid}
            if kind=='handoff_request':body.update(session_id=row.get('session_id'),from_agent_id=row['from_agent_id'],require_approval=True,model=(row.get('metadata') or {}).get('requested_model'),background=True)
            with gateway.store._get_conn() as conn:
                stored=conn.execute('SELECT fingerprint FROM control_operations WHERE operation_id=?',(command_key(kind,resource,rid,actor),)).fetchone()
            match=bool(stored and stored[0]==input_fingerprint(json.dumps({'scope':kind,'resource':resource,'actor':actor,'body':body},sort_keys=True)))
        return {'scope':kind,'resource_id':resource,'request_id':rid,'outcome':'saved' if match else 'unknown','handoff':row if match else None,'command':body if match else None,'error':None if match else 'Original admission unknown; inspect only, never resubmit'}

    async def read(request):
        kind='handoff_reply' if 'parent' in request.match_info else 'handoff_request'
        resource=request.match_info.get('parent') or request.match_info['id']
        try:return web.json_response(original(kind,resource,request.match_info['request_id'],request['caller_actor']))
        except KeyError:return web.json_response({'error':'Original owner command not retained in this scope'},status=404)

    async def submit(request):
        kind='handoff_reply' if 'parent' in request.match_info else 'handoff_request'
        resource=request.match_info.get('parent') or request.match_info['id'];actor=request['caller_actor']
        try:
            body=await request.json()
            if not isinstance(body,dict):raise TypeError('Command must be an object')
            rid=body.get('request_id')
            if not isinstance(rid,str) or not 1<=len(rid)<=128:raise ValueError('Stable request identity required')
            expected={'task','request_id'} if kind=='handoff_reply' else {'task','request_id','session_id','from_agent_id','require_approval','model','background'}
            if set(body)!=expected:raise ValueError('Exact owner command fields required')
            if isinstance(body.get('task'),str):body['task']=body['task'].strip()
            if isinstance(body.get('model'),str):body['model']=body['model'].strip()
            oid=command_key(kind,resource,rid,actor)
            fresh=gateway.store.reserve_control_operation(oid,{'scope':kind,'resource':resource,'actor':actor,'body':body})
            if not fresh:return web.json_response(original(kind,resource,rid,actor))
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)
        try:
            if not isinstance(body['task'],str) or not 1<=len(body['task'].strip())<=20000:raise ValueError('Bounded task text required')
            if kind=='handoff_request':
                if any(not isinstance(body[k],str) or not 1<=len(body[k])<=256 for k in ('from_agent_id','session_id')):raise ValueError('Canonical origin and conversation required')
                if body['require_approval'] is not True or body['background'] is not True:raise ValueError('Existing approval policy and durable background handoff required')
                target=gateway._registry().get_agent(resource)
                if target is None or target.id!=resource or target.kind.value!='jaeger_native' or target.role.value!='specialist':raise ValueError('An existing canonical native specialist is required')
                origin=gateway._registry().get_agent(body['from_agent_id'])
                session=gateway.store.get_session(body['session_id'])
                if origin is None or origin.id!=body['from_agent_id'] or session is None or _session_agent(session['session_id'],session.get('metadata') or {})!=origin.id:raise ValueError('Origin identity and conversation do not match')
            class CommandRequest(dict):
                can_read_body=True
                def __init__(self, original_request):
                    super().__init__(original_request)
                    self.match_info={'id':resource}
                async def json(self):return body
            nested=CommandRequest(request);nested['_owner_handoff_command']=True
            response=await (gateway.handle_handoff_reply(nested) if kind=='handoff_reply' else gateway.handle_handoff_agent(nested))
            value=json.loads(response.text)
            receipt={'scope':kind,'resource_id':resource,'request_id':rid,'outcome':'saved' if response.status<300 and value.get('id') else 'rejected','handoff':value if response.status<300 and value.get('id') else None,'error':value.get('error')}
            proof=original(kind,resource,rid,actor)
            if proof['outcome']=='saved':receipt=proof
            elif response.status>=500 and value.get('admitted') is not False:return web.json_response(proof)
        except (ValueError,TypeError) as exc:
            proof=original(kind,resource,rid,actor)
            receipt=proof if proof['outcome']=='saved' else {'scope':kind,'resource_id':resource,'request_id':rid,'outcome':'rejected','handoff':None,'error':str(exc)}
        except Exception:  # noqa: BLE001 - unexpected post-admission failure must remain unknown, never replayed
            return web.json_response(original(kind,resource,rid,actor)) # Original reservation retained; no automatic executor replay.
        receipt['command']=body
        gateway.store.finish_control_operation(oid,receipt)
        return web.json_response(receipt)
    gateway.app.router.add_post('/v1/agents/{id}/handoff-commands',submit)
    gateway.app.router.add_get('/v1/agents/{id}/handoff-commands/{request_id}',read)
    gateway.app.router.add_post('/v1/handoffs/{parent}/reply-commands',submit)
    gateway.app.router.add_get('/v1/handoffs/{parent}/reply-commands/{request_id}',read)
