"""Owned instance playbooks, no user skills, scripts or external activation."""
import pytest

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml
from jaeger_ai.core.skills import service

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.mark.asyncio
async def test_owned_remove_restore_receipts_cas_assets_and_scope(gw,tmp_path,monkeypatch):
    app,http=gw;layout=InstanceLayout(root=tmp_path/'owned-skill-instance');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'bundled';bundled.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:layout.root)
    monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled)
    monkeypatch.setattr(service,'_code_rows',lambda _:[])
    content='---\nname: fixture\n---\nSafe owned text'
    service.install_skill(layout,'fixture',content)
    (layout.skills_dir/'fixture'/'asset.txt').write_text('preserve owned asset')
    path='/v1/runtime/skills/managed';listing=await (await http.get(path)).json()
    row=listing['skills'][0];assert row['name']=='fixture' and row['revision']
    assert (await http.get(path,headers=client_headers('jaegerd'))).status==403
    assert (await http.get(path,headers=client_headers('a2a'))).status==403
    body={'operation_id':'owned-remove','action':'remove','name':'fixture','expected_revision':row['revision']}
    stale={**body,'operation_id':'owned-stale','expected_revision':'stale'}
    assert (await (await http.post(path+'/change',json=stale)).json())['outcome']=='rejected'
    assert service.get_skill(layout,'fixture')['content']==content
    removed=await (await http.post(path+'/change',json=body)).json()
    assert removed['outcome']=='saved' and removed['result']['state']=='removed'
    assert await (await http.get(path+'/operations/owned-remove')).json()==removed
    assert await (await http.post(path+'/change',json=body)).json()==removed
    assert not (layout.skills_dir/'fixture').exists()
    assert (await (await http.get(path)).json())['skills']==[]
    restored=await (await http.post(path+'/change',json={'operation_id':'owned-restore','action':'restore','restore_from':'owned-remove'})).json()
    assert restored['outcome']=='saved' and restored['result']['state']=='restored'
    assert (layout.skills_dir/'fixture'/'asset.txt').read_text()=='preserve owned asset'
    assert (await http.post(path+'/change',json=body,headers=client_headers('jaegerd'))).status==403
    assert service.get_skill(layout,'fixture')['content']==content
    assert len((await (await http.get(path)).json())['operations'])==3


@pytest.mark.asyncio
async def test_code_playbook_cannot_claim_hot_unload_and_unknown_command_never_replays(gw,tmp_path,monkeypatch):
    import hashlib
    app,http=gw;layout=InstanceLayout(root=tmp_path/'owned-dual');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'empty-bundled';bundled.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:layout.root)
    monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled)
    monkeypatch.setattr(service,'_code_rows',lambda _:[{'name':'fixture','description':'owned code','category':'general','origin':'instance','zone':'instance','version':'1','kinds':['tool'],'disabled':False,'mutable':True}])
    service.install_skill(layout,'fixture','---\nname: fixture\n---\nowned code companion')
    path='/v1/runtime/skills/managed';row=(await (await http.get(path)).json())['skills'][0]
    assert not row['mutable'] and row['revision'] is None and 'cannot unload' in row['management_error']
    body={'operation_id':'owned-code-remove','action':'remove','name':'fixture','expected_revision':service.skill_revision(layout.skills_dir/'fixture')}
    rejected=await (await http.post(path+'/change',json=body)).json()
    assert rejected['outcome']=='rejected' and rejected['command']==body
    assert (layout.skills_dir/'fixture'/'SKILL.md').is_file()
    unknown={**body,'operation_id':'owned-uncertain'};actor='owner:webui'
    oid='skill-owner:'+hashlib.sha256((actor+'\0'+unknown['operation_id']).encode()).hexdigest()
    app.store.reserve_control_operation(oid,{'actor':actor,'body':unknown})
    monkeypatch.setattr(service,'remove_skill',lambda *a,**k:pytest.fail('Reserved operation cannot execute again'))
    assert (await (await http.post(path+'/change',json=unknown)).json())['outcome']=='unknown'
    assert (await (await http.get(path+'/operations/owned-uncertain')).json())['outcome']=='unknown'


@pytest.mark.asyncio
async def test_intervening_edit_is_rejected_by_owner_and_active_replacement_survives(gw,tmp_path,monkeypatch):
    app,http=gw;layout=InstanceLayout(root=tmp_path/'owned-race');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'empty-race';bundled.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:layout.root)
    monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled)
    monkeypatch.setattr(service,'_code_rows',lambda _:[])
    first='---\nname: fixture\n---\nreviewed original'
    replacement='---\nname: fixture\n---\nnew unreviewed replacement'
    service.install_skill(layout,'fixture',first)
    path='/v1/runtime/skills/managed';row=(await (await http.get(path)).json())['skills'][0]
    original_remove=service.remove_skill
    def edit_after_gateway_review(current,name,**kwargs):
        service.install_skill(current,name,replacement)
        return original_remove(current,name,**kwargs)
    monkeypatch.setattr(service,'remove_skill',edit_after_gateway_review)
    body={'operation_id':'owned-racing-remove','action':'remove','name':'fixture','expected_revision':row['revision']}
    result=await (await http.post(path+'/change',json=body)).json()
    assert result['outcome']=='rejected' and 'changed since review' in result['error']
    assert service.get_skill(layout,'fixture')['content']==replacement
    assert not [p for p in (layout.skills_dir/'.archive').iterdir() if not p.name.startswith('.')]
    monkeypatch.setattr(service,'remove_skill',lambda *a,**k:pytest.fail('Rejected original command must never execute later'))
    assert await (await http.post(path+'/change',json=body)).json()==result
    assert await (await http.get(path+'/operations/owned-racing-remove')).json()==result


@pytest.mark.asyncio
async def test_filesystem_receipt_crash_recovers_observed_remove_restore_without_reexecution(gw,tmp_path,monkeypatch):
    app,http=gw;layout=InstanceLayout(root=tmp_path/'owned-recovery');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'empty-recovery';bundled.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:layout.root)
    monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled)
    monkeypatch.setattr(service,'_code_rows',lambda _:[])
    service.install_skill(layout,'fixture','---\nname: fixture\n---\nowned durable bytes')
    path='/v1/runtime/skills/managed';revision=(await (await http.get(path)).json())['skills'][0]['revision']
    finish=app.store.finish_control_operation
    def crash(*a,**k):raise OSError('owned fixture crash after move before receipt')
    monkeypatch.setattr(app.store,'finish_control_operation',crash)
    body={'operation_id':'owned-crash-remove','action':'remove','name':'fixture','expected_revision':revision}
    assert (await http.post(path+'/change',json=body)).status==500
    assert not (layout.skills_dir/'fixture').exists()
    monkeypatch.setattr(app.store,'finish_control_operation',finish)
    monkeypatch.setattr(service,'remove_skill',lambda *a,**k:pytest.fail('Recovery must not repeat filesystem mutation'))
    recovered=await (await http.get(path+'/operations/owned-crash-remove')).json()
    assert recovered['outcome']=='saved' and recovered['recovered'] and recovered['result']['state']=='removed'
    assert await (await http.post(path+'/change',json=body)).json()==recovered
    monkeypatch.setattr(app.store,'finish_control_operation',crash)
    restore={'operation_id':'owned-crash-restore','action':'restore','restore_from':'owned-crash-remove'}
    assert (await http.post(path+'/change',json=restore)).status==500
    assert (layout.skills_dir/'fixture'/'SKILL.md').read_text().endswith('owned durable bytes')
    monkeypatch.setattr(app.store,'finish_control_operation',finish)
    monkeypatch.setattr(service,'restore_skill',lambda *a,**k:pytest.fail('Recovery must not repeat restoration'))
    restored=await (await http.get(path+'/operations/owned-crash-restore')).json()
    assert restored['outcome']=='saved' and restored['recovered'] and restored['result']['state']=='restored'
    assert await (await http.post(path+'/change',json=restore)).json()==restored


@pytest.mark.asyncio
async def test_planned_but_unproven_move_stays_unknown_and_blocks_fresh_resource_commands(gw,tmp_path,monkeypatch):
    app,http=gw;layout=InstanceLayout(root=tmp_path/'owned-unproven');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'empty-unproven';bundled.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:layout.root)
    monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled)
    monkeypatch.setattr(service,'_code_rows',lambda _:[])
    content='---\nname: fixture\n---\nuntouched original';service.install_skill(layout,'fixture',content)
    path='/v1/runtime/skills/managed';revision=(await (await http.get(path)).json())['skills'][0]['revision']
    original=service.remove_skill;calls=[]
    def interrupt(current,name,**kwargs):
        calls.append(name);planned=kwargs['before_move']
        def before_move(proposal):planned(proposal);raise OSError('owned fixture interruption before atomic move')
        kwargs['before_move']=before_move
        return original(current,name,**kwargs)
    monkeypatch.setattr(service,'remove_skill',interrupt)
    body={'operation_id':'owned-unproven-remove','action':'remove','name':'fixture','expected_revision':revision}
    value=await (await http.post(path+'/change',json=body)).json()
    assert value['outcome']=='unknown'
    assert (await (await http.get(path+'/operations/owned-unproven-remove')).json())['outcome']=='unknown'
    newer={**body,'operation_id':'owned-fresh-must-not-repeat'}
    rejected=await (await http.post(path+'/change',json=newer)).json()
    assert rejected['outcome']=='rejected' and rejected['command']==newer
    assert await (await http.post(path+'/change',json=newer)).json()==rejected
    assert calls==['fixture'] and service.get_skill(layout,'fixture')['content']==content
    assert await (await http.post(path+'/change',json=body)).json()==value
    assert calls==['fixture']


@pytest.mark.asyncio
async def test_review_import_update_retain_original_version_and_explicit_rollback(gw,tmp_path,monkeypatch):
    import hashlib
    app,http=gw;layout=InstanceLayout(root=tmp_path/'owned-editor');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'empty-editor';bundled.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:layout.root)
    monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled)
    monkeypatch.setattr(service,'_code_rows',lambda _:[])
    path='/v1/runtime/skills/managed';first='---\nname: fixture\n---\nSafe owned original'
    preview={'name':'fixture','content':first,'category':'owned','expected_revision':'missing'}
    review=await (await http.post(path+'/review',json=preview)).json()
    assert review['content_sha256']==hashlib.sha256(first.encode()).hexdigest()
    assert not (layout.skills_dir/'owned'/'fixture').exists()
    command={**preview,'operation_id':'owned-import','action':'save','review_digest':review['content_sha256']}
    created=await (await http.post(path+'/change',json=command)).json()
    assert created['outcome']=='saved' and created['result']['state']=='installed'
    assert 'content' not in created['command'] and created['command']['content_sha256']==review['content_sha256']
    assert await (await http.post(path+'/change',json=command)).json()==created
    asset=layout.skills_dir/'owned'/'fixture'/'asset.txt';asset.write_text('preserve owned asset')
    loaded=await (await http.get(path+'/content?name=fixture')).json()
    assert loaded['name']=='fixture' and loaded['content']==first and not loaded['content_redacted']
    new='---\nname: fixture\n---\nSafe revised owned text'
    update={**command,'operation_id':'owned-update','content':new,'expected_revision':loaded['revision'],'review_digest':hashlib.sha256(new.encode()).hexdigest()}
    changed=await (await http.post(path+'/change',json=update)).json()
    assert changed['outcome']=='saved' and changed['result']['state']=='updated'
    archive=layout.skills_dir/'.archive'/changed['result']['archive_name']
    assert (archive/'SKILL.md').read_text()==first and (archive/'asset.txt').read_text()=='preserve owned asset'
    stale=await (await http.post(path+'/change',json={**update,'operation_id':'owned-stale-update'})).json()
    assert stale['outcome']=='rejected' and asset.read_text()=='preserve owned asset'
    occupied=await (await http.post(path+'/change',json={'action':'restore','restore_from':'owned-update','operation_id':'owned-occupied-rollback'})).json()
    assert occupied['outcome']=='rejected' and service.get_skill(layout,'fixture')['content']==new
    removed=await (await http.post(path+'/change',json={'action':'remove','name':'fixture','expected_revision':changed['result']['revision'],'operation_id':'owned-remove-updated'})).json()
    assert removed['outcome']=='saved'
    restored=await (await http.post(path+'/change',json={'action':'restore','restore_from':'owned-update','operation_id':'owned-version-rollback'})).json()
    assert restored['outcome']=='saved' and restored['result']['revision']==loaded['revision']
    assert asset.read_text()=='preserve owned asset' and service.get_skill(layout,'fixture')['content']==first
    bundle_response=await http.get(path+'/export?name=fixture&revision='+loaded['revision'])
    assert bundle_response.status==200
    bundle=await bundle_response.json()
    assert bundle['target']=='local_file' and not bundle['execution_authorized']
    assert {file['path'] for file in bundle['files']}=={'SKILL.md','.origin','asset.txt'}
    assert (await http.get(path+'/export?name=fixture&revision='+loaded['revision'],headers=client_headers('jaegerd'))).status==403
    assert (await http.post(path+'/review',json=preview,headers=client_headers('jaegerd'))).status==403


@pytest.mark.asyncio
@pytest.mark.parametrize('updating',[False,True])
async def test_saved_markdown_crash_recovery_never_repeats_import_or_update(gw,tmp_path,monkeypatch,updating):
    import hashlib
    app,http=gw;layout=InstanceLayout(root=tmp_path/'owned-save-crash');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'empty-save-crash';bundled.mkdir()
    monkeypatch.setattr(app,'_instance_root',lambda:layout.root)
    monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled)
    monkeypatch.setattr(service,'_code_rows',lambda _:[])
    previous='missing'
    if updating:
        service.install_skill(layout,'fixture','---\nname: fixture\n---\nprevious owned version')
        previous=service.skill_revision(layout.skills_dir/'fixture')
    content='---\nname: fixture\n---\nnew owned saved version'
    body={'action':'save','operation_id':'owned-save-crash','name':'fixture','category':'','content':content,'expected_revision':previous,'review_digest':hashlib.sha256(content.encode()).hexdigest()}
    finish=app.store.finish_control_operation
    def crash(*a,**k):raise OSError('owned fixture lost receipt after saved file')
    monkeypatch.setattr(app.store,'finish_control_operation',crash)
    assert (await http.post('/v1/runtime/skills/managed/change',json=body)).status==500
    assert service.get_skill(layout,'fixture')['content']==content
    monkeypatch.setattr(app.store,'finish_control_operation',finish)
    monkeypatch.setattr(service,'save_playbook',lambda *a,**k:pytest.fail('Original recovery cannot repeat a save'))
    result=await (await http.get('/v1/runtime/skills/managed/operations/owned-save-crash')).json()
    assert result['outcome']=='saved' and result['recovered']
    assert result['result']['state']==('updated' if updating else 'installed')
    assert 'content' not in result['command'] and result['command']['content_sha256']==body['review_digest']
    assert await (await http.post('/v1/runtime/skills/managed/change',json=body)).json()==result
