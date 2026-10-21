"""Owner-reviewed inert setup and future-startup policy; never starts MCP."""
import hashlib
import json
import re

from aiohttp import web

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.mcp import service


def register(gateway):
    def owner(request):
        spec=request.get('caller')
        if spec is None or 'admin' not in spec.scopes or spec.session_prefix or not request['caller_actor'].startswith('owner:'):
            raise web.HTTPForbidden(text='Existing owner administration scope required')
        return request['caller_actor']
    def layout():return InstanceLayout(root=gateway._instance_root())
    def identity(actor,op):
        return 'mcp-config:'+hashlib.sha256((str(layout().root)+'\0'+actor+'\0'+op).encode()).hexdigest()
    def observed(actor,op):
        key=identity(actor,op);record=gateway.store.control_operation(key)
        if record is None:raise web.HTTPNotFound()
        if record.get('receipt') is not None:return record['receipt']
        with gateway.store._immediate() as conn:
            row=conn.execute('SELECT value FROM schema_meta WHERE key=?',('mcp-plan:'+key,)).fetchone()
        if row:
            plan=json.loads(row[0])
            if service.configuration_revision(layout())==plan['revision']:
                receipt={'operation_id':op,'outcome':'saved','recovered':True,**plan.get('result',{}),'config_revision':plan['revision'],'connection_attempted':False,'current_connection_unchanged':True}
                gateway.store.finish_control_operation(key,receipt)
                return receipt
        return {'operation_id':op,'outcome':'unknown','error':'Original result unresolved; do not replay'}
    async def listing(request):
        owner(request)
        try:
            value=service.configured_startup_inventory(layout())
            with gateway.store._immediate() as conn:
                latest=conn.execute('SELECT value FROM schema_meta WHERE key=?',('control_scope:mcp-config:'+str(layout().root),)).fetchone()
            if latest:
                row=gateway.store.control_operation(latest[0])
                receipt=row.get('receipt') if row else None
                if receipt and receipt.get('kind')=='tool_policy_restriction' and receipt.get('config_revision')==value['config_revision']:
                    value['restore_operation']=receipt['operation_id']
            return web.json_response(value)
        except (ValueError,OSError):return web.json_response({'error':'Local MCP configuration unavailable; no connection attempted'},status=409)
    async def operation(request):return web.json_response(observed(owner(request),request.match_info['operation']))
    async def change(request):
        actor=owner(request)
        try:
            body=await request.json()
            if not isinstance(body,dict):raise TypeError()
            action=body.get('action')
            fields={'stage':{'operation_id','action','expected_revision','definition'},'startup':{'operation_id','action','expected_revision','name','enabled'},'policy':{'operation_id','action','expected_revision','name','policy'},'restore_policy':{'operation_id','action','expected_revision','restore_from'}}
            if action not in fields or set(body)!=fields[action]:raise ValueError()
            op=body['operation_id']
            if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',op):raise ValueError()
            if not isinstance(body['expected_revision'],str):raise TypeError()
            # Retain intent identity, never duplicate command arguments/transport secrets.
            digest=hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
            key=identity(actor,op)
            intent={'actor':actor,'digest':digest}
            try:fresh=gateway.store.reserve_scoped_control_operation(key,intent,'mcp-config:'+str(layout().root))
            except ValueError:
                if gateway.store.control_operation(key) is not None:raise
                if gateway.store.reserve_control_operation(key,intent):
                    gateway.store.finish_control_operation(key,{'operation_id':op,'outcome':'rejected','error':'Earlier configuration operation unresolved; this intent will never execute'})
                return web.json_response(observed(actor,op),status=409)
            if not fresh:return web.json_response(observed(actor,op))
        except (ValueError,TypeError):return web.json_response({'error':'Invalid or conflicting reviewed MCP intent'},status=409)
        def planned(_data,revision,result=None):
            with gateway.store._immediate() as conn:
                conn.execute('INSERT INTO schema_meta(key,value) VALUES(?,?)',('mcp-plan:'+key,json.dumps({'revision':revision,**({'result':result} if result is not None else {})})))
        try:
            if action=='stage':result=service.stage_disabled_server(layout(),body['definition'],expected_revision=body['expected_revision'],before_commit=planned)
            elif action=='startup':result=service.set_startup_enabled(layout(),body['name'],body['enabled'],expected_revision=body['expected_revision'],before_commit=planned)
            elif action=='policy':result=service.set_tool_policy(layout(),body['name'],body['policy'],expected_revision=body['expected_revision'],before_commit=planned)
            else:
                prior=observed(actor,body['restore_from'])
                if prior.get('outcome')!='saved' or prior.get('kind')!='tool_policy_restriction' or prior.get('config_revision')!=body['expected_revision']:raise ValueError('Exact saved original restriction required')
                result=service.set_tool_policy(layout(),prior['name'],prior['before_policy'],restore_policy=prior['after_policy'],expected_revision=body['expected_revision'],before_commit=planned)
            receipt={'operation_id':op,'outcome':'saved',**result}
        except (ValueError,TypeError,KeyError,web.HTTPNotFound):receipt={'operation_id':op,'outcome':'rejected','error':'Definition invalid, changed or unsupported; current configuration retained'}
        except Exception:  # noqa: BLE001 - durable unknown receipt must never replay
            return web.json_response({'operation_id':op,'outcome':'unknown','error':'Inspect original receipt; do not replay'},status=503)
        gateway.store.finish_control_operation(key,receipt)
        gateway.event_bus.publish('*','mcp.changed',{'configuration_changed':receipt['outcome']=='saved','connection_attempted':False})
        return web.json_response(receipt)
    gateway.app.router.add_get('/v1/runtime/mcp/configuration',listing)
    gateway.app.router.add_get('/v1/runtime/mcp/configuration/operations/{operation}',operation)
    gateway.app.router.add_post('/v1/runtime/mcp/configuration/change',change)
