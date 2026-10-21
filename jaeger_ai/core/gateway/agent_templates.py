"""Owner-local retained template snapshots through existing registry metadata."""
import hashlib
import json
import re

from aiohttp import web

from jaeger_ai.core.agent_registry.configuration import editable, template_catalog
from jaeger_ai.core.agent_registry.types import AgentRecord


def register(gateway):
    def owner(request):
        caller=request.get('caller')
        if caller is None or 'admin' not in caller.scopes or caller.session_prefix or not request['caller_actor'].startswith('owner:'):
            raise web.HTTPForbidden(text='Existing owner administration scope required')
        return request['caller_actor']
    def key(registry,actor,op):return 'template:'+hashlib.sha256((str(registry.path)+'\0'+actor+'\0'+op).encode()).hexdigest()
    def record(registry,agent_id):
        registry._load()
        raw=registry._data.get('agents',{}).get(agent_id)
        if not isinstance(raw,dict):raise KeyError('Agent not found')
        value=AgentRecord.from_dict(raw)
        if value.id!=agent_id:raise KeyError('Agent not found')
        if not editable(value):raise PermissionError('Protected source definition')
        return value
    def catalog_hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    def original(registry,actor,op):
        identity=key(registry,actor,op);saved=gateway.store.control_operation(identity)
        if saved is None:raise web.HTTPNotFound()
        if saved.get('receipt') is not None:return saved['receipt']
        with gateway.store._immediate() as conn:
            plan=conn.execute('SELECT value FROM schema_meta WHERE key=?',('template-plan:'+identity,)).fetchone()
        if plan:
            try:
                value=json.loads(plan[0]);source=record(registry,value['agent_id'])
                if catalog_hash(template_catalog(source))==value['catalog_hash']:
                    receipt={'operation_id':op,'outcome':'saved','recovered':True,'result':registry.template_state(source)}
                    gateway.store.finish_control_operation(identity,receipt)
                    return receipt
            except (KeyError,ValueError,PermissionError,OSError):pass
        return {'operation_id':op,'outcome':'unknown','error':'Original catalog mutation unresolved; do not replay'}
    async def operation(request):return web.json_response(original(gateway._registry(),owner(request),request.match_info['operation']))
    async def catalog(request):
        actor=owner(request);registry=gateway._registry();agent_id=request.match_info['id']
        if request.method=='GET':
            try:return web.json_response(registry.template_state(record(registry,agent_id)))
            except KeyError:raise web.HTTPNotFound() from None
            except PermissionError:raise web.HTTPForbidden() from None
            except (ValueError,OSError):return web.json_response({'error':'Retained template catalog unavailable; unchanged'},status=409)
        try:
            body=await request.json()
            if not isinstance(body,dict):raise TypeError()
            fields={'operation_id','action','expected_catalog_revision','expected_revision'} if body.get('action')=='save' else {'operation_id','action','expected_catalog_revision','hidden'}
            if set(body)!=fields or body.get('action') not in {'save','visibility'}:raise ValueError()
            op=body['operation_id']
            if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',op):raise ValueError()
            identity=key(registry,actor,op)
            intent={'actor':actor,'agent_id':agent_id,'body':body}
            try:fresh=gateway.store.reserve_scoped_control_operation(identity,intent,'template-source:'+str(registry.path)+':'+agent_id)
            except ValueError:
                if gateway.store.control_operation(identity) is not None:raise
                if gateway.store.reserve_control_operation(identity,intent):
                    gateway.store.finish_control_operation(identity,{'operation_id':op,'outcome':'rejected','error':'Earlier catalog operation unresolved; this intent will never execute'})
                return web.json_response(original(registry,actor,op),status=409)
            if not fresh:return web.json_response(original(registry,actor,op))
        except (ValueError,TypeError):return web.json_response({'error':'Invalid or conflicting catalog intent'},status=409)
        def planned(data,_revision):
            source=AgentRecord.from_dict(data['agents'][agent_id])
            with gateway.store._immediate() as conn:
                conn.execute('INSERT INTO schema_meta(key,value) VALUES(?,?)',('template-plan:'+identity,json.dumps({'agent_id':agent_id,'catalog_hash':catalog_hash(template_catalog(source))})))
        try:
            if body['action']=='save':result=registry.save_template(agent_id,body['expected_revision'],body['expected_catalog_revision'],before_commit=planned)
            else:result=registry.set_template_hidden(agent_id,body['hidden'],body['expected_catalog_revision'],before_commit=planned)
            receipt={'operation_id':op,'outcome':'saved','result':result}
        except (KeyError,ValueError,TypeError,RuntimeError,PermissionError):receipt={'operation_id':op,'outcome':'rejected','error':'Source or catalog changed, protected or invalid; original retained'}
        except Exception:  # noqa: BLE001 - retain original unknown without mutation replay
            return web.json_response({'operation_id':op,'outcome':'unknown','error':'Inspect original catalog result; do not replay'},status=503)
        gateway.store.finish_control_operation(identity,receipt)
        if receipt['outcome']=='saved':gateway.event_bus.publish('*','agent.updated',{'agent_id':agent_id,'template_catalog_revision':result['catalog_revision']})
        return web.json_response(receipt)
    gateway.app.router.add_get('/v1/agents/{id}/templates',catalog)
    gateway.app.router.add_post('/v1/agents/{id}/templates',catalog)
    gateway.app.router.add_get('/v1/agent-template-operations/{operation}',operation)
