"""Existing configuration producer: fresh field patches, revision fences, modes."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from jaeger_ai.core.instance.atomic_files import file_revision, mutate_yaml
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import (
    Config,
    ModelConfig,
    dump_yaml,
    load_yaml,
)
from jaeger_ai.core.settings.catalog import set_value
from jaeger_ai.core.skills import service


def test_parallel_field_patches_keep_both_settings_and_existing_file_mode(tmp_path):
    layout=InstanceLayout(root=tmp_path/'owned-config');layout.root.mkdir()
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    layout.config_path.chmod(0o640);gate=threading.Barrier(2)
    def one():
        gate.wait()
        def change(cfg):cfg.skills.disabled_playbooks=['owned-skill'];return cfg
        mutate_yaml(layout.config_path,Config,change)
    def other():
        gate.wait()
        set_value(layout,'model.ctx',16384)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(one),pool.submit(other)]
        for future in futures:future.result(timeout=5)
    cfg=load_yaml(layout.config_path,Config)
    assert cfg.skills.disabled_playbooks==['owned-skill'] and cfg.model.ctx==16384
    assert layout.config_path.stat().st_mode&0o777==0o640
    assert not list(layout.root.glob('*.tmp'))


def test_stale_revision_and_noncooperating_edit_during_plan_preserve_replacement(tmp_path):
    path=tmp_path/'config.yaml';dump_yaml(path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    old=file_revision(path)
    def change(cfg):cfg.skills.disabled_playbooks=['owned-skill'];return cfg
    mutate_yaml(path,Config,change)
    before=path.read_bytes()
    with pytest.raises(ValueError,match='changed'):mutate_yaml(path,Config,change,expected_revision=old)
    assert path.read_bytes()==before
    replacement=before+b'\n# independent fixture edit\n'
    with pytest.raises(ValueError,match='changed before commit'):
        mutate_yaml(path,Config,lambda cfg:Config.model_validate({**cfg.model_dump(),'skills':{**cfg.skills.model_dump(),'disabled_playbooks':[]}}),before_commit=lambda *_:path.write_bytes(replacement))
    assert path.read_bytes()==replacement


def test_existing_skill_policy_owner_preserves_unrelated_configuration_and_expected_revision(tmp_path,monkeypatch):
    root=tmp_path/'owned-policy';root.mkdir();layout=InstanceLayout(root=root)
    dump_yaml(layout.config_path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    bundled=tmp_path/'bundled';bundled.mkdir();monkeypatch.setattr(service._playbook_module(),'_SKILLS_DIR',bundled);monkeypatch.setattr(service,'_code_rows',lambda _:[])
    service.install_skill(layout,'fixture','---\nname: fixture\n---\nSafe owned text')
    before=load_yaml(layout.config_path,Config).model_dump();revision=file_revision(layout.config_path)
    result=service.set_skill_enabled(layout,'fixture',False,expected_revision=revision)
    assert result['enabled'] is False and load_yaml(layout.config_path,Config).model_dump()=={**before,'skills':{**before['skills'],'disabled_playbooks':['fixture']}}
    with pytest.raises(ValueError,match='changed'):service.set_skill_enabled(layout,'fixture',True,expected_revision=revision)
    assert load_yaml(layout.config_path,Config).skills.disabled_playbooks==['fixture']


def test_strict_config_refuses_unknown_fields_without_rewriting_user_document(tmp_path):
    import yaml
    path=tmp_path/'owned-config.yaml';dump_yaml(path,Config(instance_name='owned',model=ModelConfig(model_path='/dev/null')))
    data=yaml.safe_load(path.read_text());data['future_owner']={'owned_note':'preserve'};data['skills']['future_metadata']={'fixture':True}
    path.write_text(yaml.safe_dump(data,sort_keys=False));before=path.read_bytes()
    def change(cfg):cfg.skills.disabled_playbooks=['owned-skill'];return cfg
    with pytest.raises(ValueError,match='Extra inputs are not permitted'):mutate_yaml(path,Config,change)
    assert path.read_bytes()==before


def test_generic_permissive_document_patch_retains_unrelated_original_fields(tmp_path):
    import yaml
    from pydantic import BaseModel
    class Section(BaseModel):
        value:int=1
    class Document(BaseModel):
        section:Section
    path=tmp_path/'owned-document.yaml';data={'section':{'value':1,'existing_note':'preserve'},'unmodeled':{'fixture':True}}
    path.write_text(yaml.safe_dump(data))
    def change(document):document.section.value=2;return document
    mutate_yaml(path,Document,change)
    assert yaml.safe_load(path.read_text())=={'section':{'value':2,'existing_note':'preserve'},'unmodeled':{'fixture':True}}
