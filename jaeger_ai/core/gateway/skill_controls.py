"""Recoverable instance-playbook controls through the existing skill owner."""
import hashlib
import json
from pathlib import Path

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
    def command(body):
        if body.get('action')!='save':return body
        content=body['content'].encode('utf-8')
        return {**{k:v for k,v in body.items() if k!='content'},'content_sha256':hashlib.sha256(content).hexdigest(),'content_bytes':len(content)}
    def root_id():return hashlib.sha256(str(layout().root).encode()).hexdigest()
    def save_plan(actor,body,source):
        proposal={'actor':actor,'command':command(body),'source':source,'root':root_id()}
        with gateway.store._immediate() as conn:
            conn.execute('INSERT INTO schema_meta(key,value) VALUES(?,?)',('skill-plan:'+key(actor,body['operation_id']),json.dumps(proposal)))
    def original(actor,op):
        row=gateway.store.control_operation(key(actor,op))
        if row is None:raise web.HTTPNotFound(text='Original skill operation not retained')
        if row.get('receipt') is not None:return row['receipt']
        # SQLite plan precedes the atomic filesystem move under the same skill
        # lock. Recovery observes exact retained identities, never renames again.
        with gateway.store._get_conn() as conn:
            retained=conn.execute('SELECT value FROM schema_meta WHERE key=?',('skill-plan:'+key(actor,op),)).fetchone()
            fingerprint=conn.execute('SELECT fingerprint FROM control_operations WHERE operation_id=?',(key(actor,op),)).fetchone()
        if retained:
            try:
                from jaeger_agent.skill_improvement.skill_maintenance import (
                    archive_lock,
                )

                from jaeger_ai.core.gateway.session_store import input_fingerprint
                plan=json.loads(retained['value']);body=plan['command'];source=plan['source']
                valid=(plan['actor']==actor and body['operation_id']==op and plan['root']==root_id()
                    and fingerprint['fingerprint']==input_fingerprint(json.dumps({'actor':actor,'body':body},sort_keys=True)))
                if valid:
                    current=layout();relative=service.managed_relative(source['original_relative']);name=service.archive_identity(source['archive_name']) if source.get('archive_name') else None
                    if not service._playbook_module().active_skill_path(current.skills_dir,current.skills_dir/relative):raise ValueError('Unqualified origin')
                    with archive_lock(current.skills_dir) as archive:
                        active=current.skills_dir/relative;removed=archive/name if name else None
                        proof=False
                        if body['action']=='remove' and removed is not None:proof=(not active.exists() and not active.is_symlink() and removed.is_dir() and not removed.is_symlink() and service.skill_revision(removed)==source['revision']==body['expected_revision'] and source['name']==body['name'])
                        if body['action']=='restore' and removed is not None:proof=(not removed.exists() and not removed.is_symlink() and active.is_dir() and service.skill_revision(active)==source['revision'])
                        if body['action']=='save':
                            expected_path=service.managed_relative(str(Path(body['category'])/body['name']) if body['category'] else body['name'])
                            proof=(relative==expected_path and source['name']==body['name'] and source['previous_revision']==body['expected_revision'] and active.is_dir() and service.skill_revision(active)==source['revision'] and (body['expected_revision']=='missing' and removed is None or removed is not None and service.skill_revision(removed)==body['expected_revision']))
                        if proof:
                            value={'ok':True,'owner':'jaeger','name':source['name'],'state':'removed' if body['action']=='remove' else source['state'] if body['action']=='save' else 'restored','restart_required':False,'revision':source['revision']}
                            if body['action'] in {'remove','save'}:value.update(archive_name=name,original_relative=str(relative))
                            if body['action']=='save':value.update(previous_revision=source['previous_revision'],publisher_verified=False,execution_authorized=False)
                            receipt={'operation_id':op,'actor':actor,'command':body,'action':body['action'],'outcome':'saved','result':value,'recovered':True}
                            gateway.store.finish_control_operation(key(actor,op),receipt)
                            return receipt
            except (ValueError,TypeError,KeyError,OSError):pass # Inspection failure preserves uncertainty and original files.
        return {'operation_id':op,'outcome':'unknown','error':'Original operation uncertain; inspect only, never repeat'}

    async def listing(request):
        actor=owner(request);current=layout();rows=[]
        for row in service.list_skills(current)['skills']:
            if 'playbook' not in row['kinds']:continue
            value={**row,'revision':None,'mutable':row['zone']=='instance' and row['kinds']==['playbook']}
            if 'tool' in row['kinds']:value['management_error']='Loaded code skills require the package/runtime lifecycle; this playbook control cannot unload code'
            if value['mutable']:
                try:
                    folder,_,_=service._find_playbook(current,row['name'])
                    service.managed_relative(str(folder.relative_to(current.skills_dir)))
                    value['revision']=service.skill_revision(folder)
                except (ValueError,OSError):value['management_error']='Skill identity/assets require inspection; no mutation available'
            if redact_text(row['name'])!=row['name']:
                value['mutable']=False;value['revision']=None;value['management_error']='Skill identity redacted; management unavailable'
            rows.append(value)
        with gateway.store._get_conn() as conn:
            saved=conn.execute("SELECT receipt_json FROM control_operations WHERE operation_id LIKE 'skill-owner:%' ORDER BY created_at DESC LIMIT 100").fetchall()
        receipts=[]
        for record in saved:
            if not record[0]:continue
            value=json.loads(record[0])
            if value.get('actor')==actor:receipts.append(value)
        return web.json_response(safe({'skills':rows,'operations':receipts,'scope':'current_instance_playbooks','activation_performed':False}))

    async def review(request):
        owner(request)
        try:
            body=await request.json()
            if not isinstance(body,dict) or set(body)!={'name','content','category','expected_revision'}:raise ValueError('Exact review fields required')
            return web.json_response(safe(service.review_playbook(layout(),**body)))
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)

    async def content(request):
        owner(request)
        try:
            current=layout();name=request.query.get('name','');folder,_,zone=service._find_playbook(current,name)
            if zone!='instance':raise ValueError('Only existing instance playbooks can be edited here')
            relative=service.managed_relative(str(folder.relative_to(current.skills_dir)))
            files=service._skill_files(folder);text=files['SKILL.md'][0].decode('utf-8');redacted=redact_text(text)
            return web.json_response({'name':name,'category':str(relative.parent) if len(relative.parts)>1 else '', 'content':redacted,'content_redacted':redacted!=text,'revision':service._files_revision(files)})
        except (ValueError,KeyError,OSError) as exc:return web.json_response({'error':str(exc)},status=409)

    async def read(request):return web.json_response(safe(original(owner(request),request.match_info['operation_id'])))

    async def change(request):
        actor=owner(request);current=layout()
        try:
            body=await request.json()
            if not isinstance(body,dict):raise TypeError('Skill command object required')
            op=body.get('operation_id')
            if not isinstance(op,str) or not 1<=len(op)<=128:raise ValueError('Stable bounded operation required')
            action=body.get('action')
            expected=({'operation_id','action','name','expected_revision'} if action=='remove' else {'operation_id','action','name','category','content','expected_revision','review_digest'} if action=='save' else {'operation_id','action','restore_from'})
            if action not in {'remove','restore','save'} or set(body)!=expected:raise ValueError('Exact supported skill command fields required')
            if action=='save' and not isinstance(body['content'],str):raise TypeError('UTF-8 Markdown text required')
            resource=body.get('name')
            if action=='restore':
                prior=original(actor,body['restore_from'])
                if prior.get('outcome')!='saved' or not (prior.get('action')=='remove' or prior.get('action')=='save' and prior.get('result',{}).get('state')=='updated'):raise ValueError('Known original removable/restorable version receipt required')
                resource=prior['result']['name']
            if not isinstance(resource,str):raise TypeError('Canonical skill identity required')
            try:
                fresh=gateway.store.reserve_scoped_control_operation(key(actor,op),{'actor':actor,'body':command(body)},'skill-owner:'+root_id()+':'+resource)
            except ValueError as exc:
                if gateway.store.control_operation(key(actor,op)) is not None:raise
                # A different outstanding operation blocks this new intent.
                # Retain its rejection without replacing the resource pointer;
                # it must never become executable after the earlier one settles.
                if gateway.store.reserve_control_operation(key(actor,op),{'actor':actor,'body':command(body)}):
                    gateway.store.finish_control_operation(key(actor,op),{'operation_id':op,'actor':actor,'action':action,'command':command(body),'outcome':'rejected','error':str(exc)})
                return web.json_response(safe(original(actor,op)))
            if not fresh:return web.json_response(safe(original(actor,op)))
        except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)
        try:
            if action=='remove':
                catalog=next((r for r in service.list_skills(current)['skills'] if r['name']==body['name']),None)
                if catalog is None or catalog['kinds']!=['playbook']:raise service.SkillServiceError('Code skills require the existing package/runtime lifecycle')
                folder,_,zone=service._find_playbook(current,body['name'])
                if zone!='instance':raise service.SkillServiceError('Bundled skills cannot be removed')
                if service.skill_revision(folder)!=body['expected_revision']:raise service.SkillServiceError('Skill changed since review')
                value=service.remove_skill(current,body['name'],expected_revision=body['expected_revision'],before_move=lambda source:save_plan(actor,body,source))
            elif action=='save':
                if not isinstance(body['content'],str):raise TypeError('UTF-8 Markdown text required')
                if hashlib.sha256(body['content'].encode('utf-8')).hexdigest()!=body['review_digest']:raise ValueError('Reviewed content digest changed')
                value=service.save_playbook(current,body['name'],body['content'],body['category'],body['expected_revision'],before_save=lambda proposal:save_plan(actor,body,proposal))
            else:
                prior=original(actor,body['restore_from'])
                if prior.get('outcome')!='saved' or not (prior.get('action')=='remove' or prior.get('action')=='save' and prior.get('result',{}).get('state')=='updated'):raise service.SkillServiceError('Known original removable/restorable version receipt required')
                source=prior['result']
                value=service.restore_skill(current,source['name'],archive_name=source['archive_name'],original_relative=source['original_relative'],revision=source['previous_revision'] if prior['action']=='save' else source['revision'],before_move=lambda proposal:save_plan(actor,body,proposal))
            receipt={'operation_id':op,'actor':actor,'action':action,'outcome':'saved','result':value,'command':command(body)}
        except (ValueError,TypeError) as exc:
            receipt={'operation_id':op,'actor':actor,'action':action,'outcome':'rejected','error':str(exc),'command':command(body)}
        except Exception:  # noqa: BLE001 - filesystem outcome may be unknown; never repeat a reserved action
            return web.json_response(safe(original(actor,op)))
        gateway.store.finish_control_operation(key(actor,op),receipt)
        return web.json_response(safe(receipt))

    gateway.app.router.add_get('/v1/runtime/skills/managed',listing)
    gateway.app.router.add_post('/v1/runtime/skills/managed/review',review)
    gateway.app.router.add_get('/v1/runtime/skills/managed/content',content)
    gateway.app.router.add_post('/v1/runtime/skills/managed/change',change)
    gateway.app.router.add_get('/v1/runtime/skills/managed/operations/{operation_id}',read)
