"""Team roles: standing specialists carry role skills; runs see only those."""
from __future__ import annotations

from pathlib import Path

from jaeger_ai.core.agent_registry.specialists import (
    LEAD_SKILLS, SHARED_SKILLS, STANDING_SPECIALISTS, agent_skill_names,
    expand_tool_patterns, resolve_skill_cards, scoped_skill_names, specialist_skills,
)
from jaeger_ai.core.agent_registry.types import AgentRecord

TEAM_SKILLS = Path(__file__).resolve().parents[4] / "jaeger_ai/core/agent_registry/team_skills"


def _rec(name, role="specialist", **meta):
    return AgentRecord.from_dict({"id": f"native:{name}", "name": name, "kind": "jaeger_native",
                                  "role": role, "metadata": meta})


def test_team_roles_are_standing_with_skills():
    names = {s["name"] for s in STANDING_SPECIALISTS}
    assert {"reverse-engineer", "builder", "reviewer", "researcher", "designer"} <= names
    re_skills = specialist_skills(_rec("reverse-engineer"))
    assert re_skills == ["reverse-engineer-anything", "jaeger-reverse-engineer"]
    assert specialist_skills(_rec("builder")) == ["jaeger-builder"]
    assert specialist_skills(_rec("jaeger", role="lead")) == list(LEAD_SKILLS)
    for spec in STANDING_SPECIALISTS:
        if spec.get("team_role"):
            assert not spec["keywords"], "team roles are assigned by the lead, never auto-routed"


def test_scoped_skills_are_own_plus_shared_only():
    assert scoped_skill_names(_rec("builder")) == ["jaeger-builder", *SHARED_SKILLS]
    assert scoped_skill_names(_rec("jaeger", role="lead")) is None  # lead keeps the catalog
    assert agent_skill_names(_rec("jaeger", role="lead")) == [*LEAD_SKILLS, *SHARED_SKILLS]
    assert scoped_skill_names(_rec("builder", skills=["custom"])) == ["custom", *SHARED_SKILLS]


def test_tool_globs_expand_against_registry():
    avail = {"mcp__rea__doctor", "mcp__rea__inspect_asar", "read_file", "mcp__x__y"}
    out = expand_tool_patterns(["mcp__rea__*", "read_file", "web_search"], avail)
    assert out == ["mcp__rea__doctor", "mcp__rea__inspect_asar", "read_file", "web_search"]


def test_every_role_skill_folder_resolves():
    names = sorted({n for s in STANDING_SPECIALISTS for n in s.get("skills", ())} | set(LEAD_SKILLS) | set(SHARED_SKILLS))
    names.remove("reverse-engineer-anything")  # installed from the REA source, not the repo
    cards = resolve_skill_cards(names, [TEAM_SKILLS])
    assert all(c["source_path"] and c["description"] for c in cards), cards
    missing = resolve_skill_cards(["nope"], [TEAM_SKILLS])
    assert missing == [{"id": "nope", "name": "nope", "description": "", "source_path": None, "missing": True}]


def test_skill_scope_filters_discovery(tmp_path, monkeypatch):
    from jaeger_agent.skill_registry import playbook_skills as pb

    for name in ("jaeger-builder", "jaeger-reviewer", "jaeger-team-handbook"):
        d = tmp_path / name
        d.mkdir()
        d.joinpath("SKILL.md").write_text((TEAM_SKILLS / name / "SKILL.md").read_text())
    monkeypatch.setattr(pb, "_instance_skills_dir", lambda: tmp_path)
    pb._DISCOVERY_CACHE.update({"sig": None, "result": None})
    with pb.skill_scope(["jaeger-builder", "jaeger-team-handbook"]):
        names = {s.name for s in pb.callable_playbooks()}
        assert names == {"jaeger-builder", "jaeger-team-handbook"}
        assert pb.find_playbook("jaeger-reviewer") is None
        assert pb.find_playbook("jaeger-builder") is not None
    assert pb.find_playbook("jaeger-reviewer") is not None
    assert pb.active_skill_scope() is None


def test_skills_block_lists_only_own_skills(monkeypatch, tmp_path):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    monkeypatch.setattr(JaegerGatewayApp, "_skill_roots", staticmethod(lambda: [TEAM_SKILLS]))
    block = JaegerGatewayApp._skills_block(_rec("builder"))
    assert block.startswith("[Your skills]")
    assert "jaeger-builder:" in block and "jaeger-team-handbook:" in block
    assert "jaeger-reviewer" not in block
