from __future__ import annotations

from jaeger_agent.skill_registry import playbook_skills as pb
from jaeger_agent.skill_registry.skill_audit import audit_catalog


def test_distribution_catalog_is_lean_and_complete() -> None:
    discovered = pb.discover_playbooks()
    active = pb.available_playbooks()
    assert len(discovered) >= 100
    assert 25 <= len(active) <= 45
    assert all(s.lifecycle == "core" for s in active)
    assert any(s.lifecycle == "optional" for s in discovered)
    assert any(s.lifecycle == "plugin" for s in discovered)


def test_every_core_skill_meets_the_first_class_entrypoint_contract() -> None:
    """Keep the small-model routing surface concise as the catalog evolves."""
    for skill in pb.available_playbooks():
        lines = len(skill.path.read_text(encoding="utf-8").splitlines())
        assert skill.skill_class == "first-class", skill.name
        assert lines <= 130, (skill.name, lines)


def test_migrated_large_entrypoints_are_concise() -> None:
    migrated = {
        "audiocraft-audio-generation", "claude-code", "claude-design",
        "comfyui", "dspy", "evaluating-llms-harness", "github-code-review",
        "github-repo-management", "humanizer", "llm-wiki",
        "p5js", "segment-anything-model", "weights-and-biases", "xurl",
        "github-pr-workflow", "github-issues",
    }
    by_name = {s.name: s for s in pb.discover_playbooks()}
    for name in migrated:
        skill = by_name[name]
        assert len(skill.path.read_text(encoding="utf-8").splitlines()) <= 130
        assert (skill.path.parent / "references" / "imported-guide.md").is_file()

    # The red-team import is preserved on disk but quarantined from both
    # automatic and explicit discovery because its bundled attack scripts trip
    # the safety guard.
    assert pb.find_playbook("godmode") is None


def test_audit_reports_catalog_shape() -> None:
    result = audit_catalog(available_tools=set())
    assert result["skill_count"] >= 100
    assert result["active_count"] <= 45
    assert "lifecycle_counts" in result
    assert isinstance(result["findings"], list)


def test_default_audit_uses_complete_production_tool_catalog() -> None:
    result = audit_catalog(runtime_complete=True)
    missing = [
        finding for finding in result["findings"]
        if finding["code"] == "missing-required-tools"
    ]
    assert missing == []
