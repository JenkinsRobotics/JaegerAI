from __future__ import annotations

import yaml

from jaeger_agent.skill_registry import playbook_skills as pb
from jaeger_agent.skill_registry.skill_audit import audit_catalog


def test_distribution_catalog_is_lean_and_complete() -> None:
    discovered = pb.discover_playbooks()
    callable_skills = pb.callable_playbooks()
    prompt_visible = pb.available_playbooks()
    policy = yaml.safe_load(pb._CATALOG_PATH.read_text())
    expected = {name for state in ("core", "optional", "plugin", "explicit") for name in policy[state]}
    assert {s.name for s in discovered} == expected
    assert {s.name for s in callable_skills} == expected
    assert 25 <= len(prompt_visible) <= 45
    assert all(s.lifecycle == "core" for s in prompt_visible)
    assert any(s.lifecycle == "optional" for s in discovered)
    assert any(s.lifecycle == "plugin" for s in discovered)


def test_every_core_skill_meets_the_first_class_entrypoint_contract() -> None:
    """Keep the small-model routing surface concise as the catalog evolves."""
    for skill in pb.available_playbooks():
        lines = len(skill.path.read_text(encoding="utf-8").splitlines())
        assert skill.skill_class == "first-class", skill.name
        assert lines <= 130, (skill.name, lines)


def test_bundled_imported_entrypoints_are_concise() -> None:
    imported = [s for s in pb.discover_playbooks()
                if (s.path.parent / "references" / "imported-guide.md").is_file()]
    assert imported, "bundled imported guides must remain discoverable"
    for skill in imported:
        assert len(skill.path.read_text(encoding="utf-8").splitlines()) <= 130
    # Every explicit-only recipe stays callable without competing in auto-routing.
    explicit = {s.name for s in pb.discover_playbooks() if s.lifecycle == "explicit"}
    assert explicit
    assert explicit <= {s.name for s in pb.callable_playbooks()}
    assert explicit.isdisjoint({s.name for s in pb.available_playbooks()})


def test_audit_reports_catalog_shape() -> None:
    result = audit_catalog(available_tools=set())
    assert result["skill_count"] == len(pb.discover_playbooks())
    assert result["callable_count"] == len(pb.callable_playbooks())
    assert result["prompt_visible_count"] <= 45
    assert result["active_count"] == result["prompt_visible_count"]
    assert "lifecycle_counts" in result
    assert isinstance(result["findings"], list)


def test_default_audit_uses_complete_production_tool_catalog() -> None:
    result = audit_catalog(runtime_complete=True)
    missing = [
        finding for finding in result["findings"]
        if finding["code"] == "missing-required-tools"
    ]
    assert missing == []
