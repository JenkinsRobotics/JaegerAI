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
