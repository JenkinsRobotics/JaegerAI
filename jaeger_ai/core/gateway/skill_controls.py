"""Recoverable instance-playbook controls through the existing skill owner."""
import hashlib

from aiohttp import web

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.skills import service


def register(gateway):
    from jaeger_ai.core.redaction import redact_text
    def safe(value):
        if isinstance(value,str):return redact_text(value)
        if isinstance(value,list):return [safe(item) for item in value]
        if isinstance(value,dict):return {k:safe(v) for k,v in value.items()}
        return value
    def layout():return InstanceLayout(root=gateway._instance_root())
    def owner(request):
        spec=request.get('caller')
        if spec is None or 'admin' not in spec.scopes or spec.session_prefix or not request['caller_actor'].startswith('owner:'):
            raise web.HTTPForbidden(text='Existing owner administration scope required')
        return request['caller_actor']
    def key(actor,op):return 'skill-owner:'+hashlib.sha256((actor+'\0'+op).encode()).hexdigest()
    def original(actor,op):
        row=gateway.store.control_operation(key(actor,op))
        if row is None:raise web.HTTPNotFound(text='Original skill operation not retained')
        return row.get('receipt') or {'operation_id':op,'outcome':'unknown','error':'Original operation uncertain; inspect only, never repeat'}

    async def listing(request):
        actor=owner(request);current=layout();rows=[]
        for row in service.list_skills(current)['skills']:
            if 'playbook' not in row['kinds']:continue
            value={**row,'revision':None,'mutable':row['zone']=='instance' and row['kinds']==['playbook']}
            if 'tool' in row['kinds']:value['management_error']='Loaded code skills require the package/runtime lifecycle; this playbook control cannot unload code'
            if value['mutable']:
                try:
                    folder,_,_=service._find_playbook(current,row['name'])
                    value['revision']=service.skill_revision(folder)
                except (ValueError,OSError):value['management_error']='Skill identity/assets require inspection; no mutation available'
            if redact_text(row['name'])!=row['name']:
                value['mutable']=False;value['revision']=None;value['management_error']='Skill identity redacted; management unavailable'
            rows.append(value)
        with gateway.store._get_conn() as conn:
            saved=conn.execute("SELECT receipt_json FROM control_operations WHERE operation_id LIKE 'skill-owner:%' ORDER BY created_at DESC LIMIT 100").fetchall()
        import json
        receipts=[]
        for record in saved:
            if not record[0]:continue
            value=json.loads(record[0])
            if value.get('actor')==actor:receipts.append(value)
        return web.json_response(safe({'skills':rows,'operations':receipts,'scope':'current_instance_playbooks','activation_performed':False}))

    async def read(request):return web.json_response(safe(original(owner(request),request.match_info['operation_id'])))

    async def change(request):
        actor=owner(request);current=layout()
        try:
            body=await request.json()
            if not isinstance(body,dict):raise TypeError('Skill command object required')
            op=body.get('operation_id')
            if not isinstance(op,str) or not 1<=len(op)<=128:raise ValueError('Stable bounded operation required')
            action=body.get('action')
            expected={'operation_id','action','name','expected_revision'} if action=='remove' else {'operation_id','action','restore_from'}
            if action not in {'remove','restore'} or set(body)!=expected:raise ValueError('Exact supported skill command fields required')
            if not gateway.store.reserve_control_operation(key(actor,op),{'actor':actor,'body':body}):return web.json_response(safe(original(actor,op)))
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)
        try:
            if action=='remove':
                catalog=next((r for r in service.list_skills(current)['skills'] if r['name']==body['name']),None)
                if catalog is None or catalog['kinds']!=['playbook']:raise service.SkillServiceError('Code skills require the existing package/runtime lifecycle')
                folder,_,zone=service._find_playbook(current,body['name'])
                if zone!='instance':raise service.SkillServiceError('Bundled skills cannot be removed')
                if service.skill_revision(folder)!=body['expected_revision']:raise service.SkillServiceError('Skill changed since review')
                value=service.remove_skill(current,body['name'],expected_revision=body['expected_revision'])
            else:
                prior=original(actor,body['restore_from'])
                if prior.get('outcome')!='saved' or prior.get('action')!='remove':raise service.SkillServiceError('Known original remove receipt required')
                source=prior['result']
                value=service.restore_skill(current,source['name'],**{k:source[k] for k in ('archive_name','original_relative','revision')})
            receipt={'operation_id':op,'actor':actor,'action':action,'outcome':'saved','result':value,'command':body}
        except (ValueError,TypeError) as exc:
            receipt={'operation_id':op,'actor':actor,'action':action,'outcome':'rejected','error':str(exc),'command':body}
        except Exception:  # noqa: BLE001 - filesystem outcome may be unknown; never repeat a reserved action
            return web.json_response(safe(original(actor,op)))
        gateway.store.finish_control_operation(key(actor,op),receipt)
        return web.json_response(safe(receipt))

    gateway.app.router.add_get('/v1/runtime/skills/managed',listing)
    gateway.app.router.add_post('/v1/runtime/skills/managed/change',change)
    gateway.app.router.add_get('/v1/runtime/skills/managed/operations/{operation_id}',read)
