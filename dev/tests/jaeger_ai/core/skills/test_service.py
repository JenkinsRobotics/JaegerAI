from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml, load_yaml
from jaeger_ai.core.skills import service


@pytest.fixture
def layout(tmp_path, monkeypatch):
    root = tmp_path / "instance"
    skills = root / "skills"
    skills.mkdir(parents=True)
    config_path = root / "config.yaml"
    dump_yaml(config_path, Config(instance_name="test", model=ModelConfig(model_path="/dev/null")))
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setattr(service._playbook_module(), "_SKILLS_DIR", bundled)
    monkeypatch.setattr(service, "_code_rows", lambda _layout: [])
    return SimpleNamespace(root=root, skills_dir=skills, config_path=config_path), bundled


def _skill(folder, name, description="test skill"):
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def test_list_get_clone_and_remove_skill(layout):
    instance, bundled = layout
    _skill(bundled / "research" / "summarize", "summarize")

    rows = service.list_skills(instance)["skills"]
    assert rows == [{
        "name": "summarize", "description": "test skill", "category": "research",
        "origin": "builtin", "zone": "builtin", "kinds": ["playbook"],
        "disabled": False, "mutable": False,
    }]
    assert service.get_skill(instance, "summarize")["owner"] == "jaeger"

    result = service.clone_skill(instance, "summarize")
    assert result["ok"] is True
    assert (instance.skills_dir / "summarize" / "SKILL.md").is_file()
    assert service.get_skill(instance, "summarize")["mutable"] is True
    assert service.remove_skill(instance, "summarize")["ok"] is True
    assert not (instance.skills_dir / "summarize").exists()


def test_install_updates_content_without_deleting_linked_files(layout):
    instance, _bundled = layout
    original = "---\nname: custom\ndescription: old\n---\nold\n"
    updated = "---\nname: custom\ndescription: new\n---\nnew\n"

    service.install_skill(instance, "custom", original)
    asset = instance.skills_dir / "custom" / "assets" / "keep.txt"
    asset.parent.mkdir()
    asset.write_text("keep", encoding="utf-8")
    service.install_skill(instance, "custom", updated)

    assert asset.read_text(encoding="utf-8") == "keep"
    assert service.get_skill(instance, "custom")["content"] == updated


def test_disable_and_enable_playbook_are_schema_validated(layout):
    instance, bundled = layout
    _skill(bundled / "ops", "deploy")

    disabled = service.set_skill_enabled(instance, "deploy", False)
    assert disabled["enabled"] is False
    assert load_yaml(instance.config_path, Config).skills.disabled_playbooks == ["deploy"]
    assert service.list_skills(instance)["skills"][0]["disabled"] is True

    enabled = service.set_skill_enabled(instance, "deploy", True)
    assert enabled["enabled"] is True
    assert load_yaml(instance.config_path, Config).skills.disabled_playbooks == []


def test_instance_playbook_overrides_builtin_and_archived_is_hidden(layout):
    instance, bundled = layout
    _skill(bundled / "apple" / "apple-notes", "apple-notes", "Manage Apple Notes via memo CLI")
    live = instance.skills_dir / "apple" / "apple-notes"
    live.mkdir(parents=True)
    (live / "SKILL.md").write_text(
        "---\nname: apple-notes\ndescription: Process the Apple Notes inbox.\n---\nmerge\n",
        encoding="utf-8",
    )
    retired = instance.skills_dir / "smart-notes-organizer"
    retired.mkdir()
    (retired / "SKILL.md").write_text(
        "---\nname: smart-notes-organizer\narchived: true\ndescription: old move-all\n---\n",
        encoding="utf-8",
    )

    rows = {row["name"]: row for row in service.list_skills(instance)["skills"]}
    assert rows["apple-notes"]["description"] == "Process the Apple Notes inbox."
    assert rows["apple-notes"]["zone"] == "instance"
    assert rows["apple-notes"]["category"] == "apple"
    assert "smart-notes-organizer" not in rows


def test_rejects_name_traversal_and_bundled_removal(layout):
    instance, bundled = layout
    _skill(bundled / "safe", "safe")

    with pytest.raises(service.SkillServiceError, match="invalid skill name"):
        service.install_skill(instance, "../escape", "x")
    with pytest.raises(service.SkillServiceError, match="bundled skills cannot be removed"):
        service.remove_skill(instance, "safe")


def test_hidden_archive_and_staging_never_reenter_live_catalog_or_lookup(layout,monkeypatch):
    instance,bundled=layout
    _skill(instance.skills_dir/'.archive'/'retired','retired')
    _skill(instance.skills_dir/'.pending'/'staged','staged')
    _skill(instance.skills_dir/'active','active')
    # Both the owner catalog and actual model-facing discovery share the guard.
    pb=service._playbook_module()
    monkeypatch.setattr(pb,'_instance_skills_dir',lambda:instance.skills_dir)
    monkeypatch.setattr(pb,'_CATALOG_PATH',bundled/'missing-catalog.yaml')
    assert [r['name'] for r in service.list_skills(instance)['skills']]==['active']
    assert [s.name for s in pb.discover_playbooks()]==['active']
    for name in ('retired','staged'):
        with pytest.raises(service.SkillServiceError,match='not found'):service.get_skill(instance,name)
    before=pb._discovery_signature([instance.skills_dir])
    (instance.skills_dir/'.archive'/'retired'/'SKILL.md').write_text('untrusted archived edit')
    assert pb._discovery_signature([instance.skills_dir])==before


def test_symlink_cannot_alias_retired_skill_back_into_live_catalog(layout,monkeypatch):
    instance,_=layout
    _skill(instance.skills_dir/'.archive'/'retired','retired')
    (instance.skills_dir/'resurrected').symlink_to(instance.skills_dir/'.archive'/'retired',target_is_directory=True)
    pb=service._playbook_module();monkeypatch.setattr(pb,'_instance_skills_dir',lambda:instance.skills_dir)
    assert service.list_skills(instance)['skills']==[]
    assert not pb.active_skill_path(instance.skills_dir,instance.skills_dir/'resurrected'/'SKILL.md')


def test_recoverable_remove_restore_preserves_all_assets_and_refuses_replacement(layout):
    instance,_=layout
    content='---\nname: fixture\ndescription: isolated fixture\n---\nSafe local text\n'
    service.install_skill(instance,'fixture',content,category='owned')
    asset=instance.skills_dir/'owned'/'fixture'/'assets'/'owned.bin';asset.parent.mkdir();asset.write_bytes(b'owned asset')
    mode=asset.stat().st_mode
    removed=service.remove_skill(instance,'fixture')
    assert removed['state']=='removed' and not asset.exists()
    source=instance.skills_dir/'.archive'/removed['archive_name']
    assert (source/'assets'/'owned.bin').read_bytes()==b'owned asset'
    assert service.list_skills(instance)['skills']==[]
    kwargs={k:removed[k] for k in ('archive_name','original_relative','revision')}
    service.install_skill(instance,'fixture',content+'replacement',category='owned')
    with pytest.raises(service.SkillServiceError,match='replacement'):service.restore_skill(instance,'fixture',**kwargs)
    replacement=service.remove_skill(instance,'fixture')
    assert replacement['archive_name']!=removed['archive_name']
    assert service.restore_skill(instance,'fixture',**kwargs)['state']=='restored'
    assert asset.read_bytes()==b'owned asset' and asset.stat().st_mode==mode
    assert service.get_skill(instance,'fixture')['content']==content
    assert service.restore_skill(instance,'fixture',**kwargs)['already_restored']
    assert (instance.skills_dir/'.archive'/replacement['archive_name']/'SKILL.md').read_text()==content+'replacement'


def test_archive_tamper_and_symlink_rejected_without_mutating_live_state(layout):
    instance,_=layout;service.install_skill(instance,'fixture','---\nname: fixture\n---\nowned')
    removed=service.remove_skill(instance,'fixture');kwargs={k:removed[k] for k in ('archive_name','original_relative','revision')}
    source=instance.skills_dir/'.archive'/removed['archive_name'];(source/'SKILL.md').write_text('changed')
    with pytest.raises(service.SkillServiceError,match='changed'):service.restore_skill(instance,'fixture',**kwargs)
    assert not (instance.skills_dir/'fixture').exists()
    with pytest.raises(service.SkillServiceError,match='invalid skill name'):service.restore_skill(instance,'fixture',**{**kwargs,'original_relative':'../outside'})


def test_ambiguous_same_zone_identity_refuses_management_instead_of_wrong_folder(layout):
    instance,_=layout
    _skill(instance.skills_dir/'one'/'fixture','fixture')
    _skill(instance.skills_dir/'two'/'fixture','fixture')
    with pytest.raises(service.SkillServiceError,match='ambiguous'):service.remove_skill(instance,'fixture')
    assert (instance.skills_dir/'one'/'fixture'/'SKILL.md').is_file()
    assert (instance.skills_dir/'two'/'fixture'/'SKILL.md').is_file()


def test_remove_revalidates_reviewed_revision_inside_archive_lock(layout,monkeypatch):
    from contextlib import contextmanager
    from jaeger_agent.skill_improvement import skill_maintenance
    instance,_=layout
    original='---\nname: fixture\n---\noriginal'
    changed='---\nname: fixture\n---\nchanged while waiting for lock'
    service.install_skill(instance,'fixture',original)
    expected=service.skill_revision(instance.skills_dir/'fixture')
    acquire=skill_maintenance.archive_lock
    @contextmanager
    def edit_before_mutation(root):
        with acquire(root) as archive:
            (instance.skills_dir/'fixture'/'SKILL.md').write_text(changed)
            yield archive
    monkeypatch.setattr(skill_maintenance,'archive_lock',edit_before_mutation)
    with pytest.raises(service.SkillServiceError,match='active replacement retained'):
        service.remove_skill(instance,'fixture',expected_revision=expected)
    assert service.get_skill(instance,'fixture')['content']==changed
