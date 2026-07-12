"""0.8.1 item 11 — the messaging-setup SOP skill is real and discoverable.

Pins that ``skills/messaging/messaging_setup/SKILL.md`` parses through the
same v3-frontmatter path every other built-in skill uses (the scheduling
SOP is the precedent this was modeled on) and that every tool it declares
in ``requires_tools`` actually exists in the registry — a skill telling the
model to call a tool that doesn't exist is worse than no skill at all.
"""

from __future__ import annotations


def test_messaging_setup_is_discovered() -> None:
    from jaeger_ai.agent.skill_registry.playbook_skills import discover_playbooks

    playbooks = discover_playbooks()
    matches = [p for p in playbooks if p.name == "messaging_setup"]
    assert len(matches) == 1, "messaging_setup not discovered exactly once"
    skill = matches[0]
    assert skill.category == "messaging"
    assert skill.origin == "builtin"
    assert "discord" in skill.description.lower()


def test_messaging_setup_requires_tools_are_all_registered() -> None:
    from jaeger_ai.agent.skill_registry.playbook_skills import discover_playbooks
    import jaeger_ai.main as m
    from jaeger_os.core.tools import tool_registry as R

    m._register_builtins(object())
    registered = {t.name for t in R.get_tools()}

    skill = next(p for p in discover_playbooks() if p.name == "messaging_setup")
    missing = [t for t in skill.requires_tools if t not in registered]
    assert not missing, f"messaging_setup names tools that don't exist: {missing}"


def test_messaging_category_has_a_description() -> None:
    import pathlib
    import jaeger_ai
    desc = (pathlib.Path(jaeger_ai.__file__).resolve().parent
             / "agent" / "skills" / "messaging" / "DESCRIPTION.md")
    assert desc.is_file()
    assert "description:" in desc.read_text(encoding="utf-8")
