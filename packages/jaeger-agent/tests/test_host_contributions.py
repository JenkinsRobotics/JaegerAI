"""A host application can extend the agent, and what it adds is equal.

This is the property that makes the module embeddable rather than merely
importable: JaegerAI, Mochi, or a robot chassis contributes tools and
skills, and the agent treats them exactly like the ones it ships. If that
holds, an application is also the natural place to DEVELOP a capability —
build it against a real instance, prove it, and only then decide whether
it belongs in the module.

Three ways in, and all three must be equal:

  1. register a tool           the process-wide registry, read every turn
  2. register a toolset        so it survives a host that scopes
  3. drop a SKILL.md in the    instance skills/ dir, which discovery
     instance                  already merges with the bundled tree

Number 2 did not work before 1.0.7: runtime-registered toolsets lived in
one registry and ``resolve_toolsets`` read another, so naming one raised
``KeyError: unknown toolset``.
"""

from __future__ import annotations

import pytest

from jaeger_agent.schemas.tool_bundles import resolve_toolsets
from jaeger_agent.skill_registry import toolset_scoping


@pytest.fixture()
def app_tool(live_tools):
    """A tool contributed the way a host application would."""
    from jaeger_os.core.tools.tool_registry import register_tool_from_function

    @register_tool_from_function(name="host_contributed_probe", side_effect="read")
    def _probe(what: str = "") -> dict:
        """Contributed by the host application, not by jaeger-agent."""
        return {"ok": True, "what": what}

    return "host_contributed_probe"


class _Stub:
    provider = "stub"
    model = "stub"

    def call(self, *a, **k):
        raise NotImplementedError


def _agent(**kwargs):
    from jaeger_agent.loop.jaeger_agent import JaegerAgent

    return JaegerAgent(adapter=_Stub(), system_prompt="x", **kwargs)


def test_an_unscoped_agent_sees_host_tools(app_tool) -> None:
    """The default path: no toolsets, so the surface IS the registry, and
    the registry is re-read every turn. Nothing distinguishes a host tool
    from a shipped one."""
    assert app_tool in _agent().tool_names()


def test_a_scoped_agent_needs_the_host_to_declare_a_toolset(app_tool) -> None:
    """Scoping filters by NAME against declared bundles, so a tool no
    bundle names is correctly absent. This is not a bug — it is what
    scoping means — but it is the reason the next test matters."""
    agent = _agent(toolsets={"default"}, toolset_resolver=resolve_toolsets)
    assert app_tool not in agent.tool_names()


def test_a_host_registered_toolset_resolves(app_tool) -> None:
    """The gap closed in 1.0.7. A host registers its toolset and can then
    scope to it, exactly as a skill does."""
    toolset_scoping.register_skill_toolset("probeset", [app_tool], "host tools")
    agent = _agent(toolsets={"default", "probeset"}, toolset_resolver=resolve_toolsets)
    assert app_tool in agent.tool_names()


def test_a_host_toolset_appears_in_the_catalogue(app_tool) -> None:
    """``/toolsets`` and the model-facing catalogue must show it too, or
    the model cannot ask for what it cannot see."""
    from jaeger_agent.schemas.tool_bundles import list_toolsets

    toolset_scoping.register_skill_toolset("probeset", [app_tool], "host tools")
    assert "probeset" in list_toolsets()
    assert app_tool in list_toolsets()["probeset"]["tools"]


def test_star_includes_host_toolsets(app_tool) -> None:
    """``"*"`` means every tool in every toolset. It used to mean every
    tool in every STATICALLY DECLARED toolset, which quietly excluded
    everything a host or a skill added."""
    toolset_scoping.register_skill_toolset("probeset", [app_tool], "host tools")
    assert app_tool in resolve_toolsets(["*"])


def test_a_genuinely_unknown_toolset_still_raises() -> None:
    """Falling back to runtime registrations must not turn a typo into
    silence — an unknown name is still an error."""
    with pytest.raises(KeyError):
        resolve_toolsets({"no_such_toolset_anywhere"})


def test_host_can_force_scoping_for_one_agent_without_process_env(
    app_tool, monkeypatch,
) -> None:
    """A context-tight face scopes locally while ordinary agents stay full."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    toolset_scoping.register_toolset("probeset", [app_tool], "host tools")
    toolset_scoping.reset_toolsets()
    scoped = _agent(tool_visibility=toolset_scoping.scoped_tool_visible)
    ordinary = _agent(tool_visibility=toolset_scoping.tool_visible)

    assert app_tool not in scoped.tool_names()
    assert app_tool in ordinary.tool_names()

    toolset_scoping.register_toolset("probeset", [app_tool], "host tools")
    assert toolset_scoping.enable_toolset("probeset") is True
    assert app_tool in scoped.tool_names()


def test_instance_skills_merge_with_bundled_ones(tmp_path, monkeypatch) -> None:
    """The skills half, which already worked: discovery reads the bundled
    tree AND the bound instance's, so a host (or the agent itself) can add
    a playbook without touching the package."""
    from jaeger_agent.skill_registry import playbook_skills as pb

    skill_dir = tmp_path / "skills" / "host-added"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: host-added\ndescription: contributed by the host\n---\n\nDo the thing.\n"
    )
    monkeypatch.setattr(pb, "_instance_skills_dir", lambda: tmp_path / "skills")
    pb._DISCOVERY_CACHE["sig"] = None          # bypass the stat-signature cache

    names = {s.name for s in pb.discover_playbooks()}
    assert "host-added" in names
    assert len(names) > 1, "bundled skills must still be there too"
