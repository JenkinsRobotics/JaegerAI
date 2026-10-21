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
