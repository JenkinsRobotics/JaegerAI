"""Playbook-skill discovery metadata — platform filtering, disabled skills,
and the compact prompt-side skill index.

Skills gained discovery metadata: ``platforms`` (with ``macos`` first-class),
``requires_tools`` / ``requires_toolsets`` / ``fallback_for_tools``, and a
config-driven disabled list. ``available_playbooks`` is the agent-facing
view — discovered skills minus those for another OS and those disabled in
config — and ``build_skill_index`` renders a compact index for the prompt.
"""

from __future__ import annotations

from pathlib import Path

from jaeger_os.agent.skill_registry.playbook_skills import (
    PlaybookSkill,
    _current_platform,
    _format_skill_index,
    _normalize_platforms,
    _platform_ok,
    _select_available,
    _str_list,
    available_playbooks,
    build_skill_index,
    discover_playbooks,
)


def _skill(name: str, *, category: str = "general", platforms=None) -> PlaybookSkill:
    return PlaybookSkill(
        name=name,
        category=category,
        description=f"{name} description",
        path=Path(f"/skills/{name}/SKILL.md"),
        platforms=list(platforms or []),
    )


# ── frontmatter coercion ─────────────────────────────────────────────


def test_str_list_accepts_list_and_bare_string():
    assert _str_list({"requires_tools": ["a", "b"]}, "requires_tools") == ["a", "b"]
    assert _str_list({"requires_tools": "solo"}, "requires_tools") == ["solo"]
    assert _str_list({}, "requires_tools") == []
    assert _str_list({"requires_tools": 17}, "requires_tools") == []


def test_normalize_platforms_maps_aliases_to_canonical():
    assert _normalize_platforms(["Mac", "OSX", "darwin"]) == ["macos"]
    assert _normalize_platforms(["win"]) == ["windows"]
    assert _normalize_platforms(["linux", "bogus"]) == ["linux"]


# ── platform filtering ───────────────────────────────────────────────


def test_skill_with_no_platforms_runs_everywhere():
    assert _platform_ok(_skill("anywhere")) is True


def test_skill_is_visible_only_on_a_declared_platform():
    here = _current_platform()
    other = "linux" if here != "linux" else "windows"
    assert _platform_ok(_skill("here", platforms=[here])) is True
    assert _platform_ok(_skill("elsewhere", platforms=[other])) is False


def test_select_available_drops_wrong_platform_and_disabled():
    here = _current_platform()
    other = "linux" if here != "linux" else "windows"
    skills = [
        _skill("keep"),                          # no platforms → kept
        _skill("local", platforms=[here]),       # this OS → kept
        _skill("foreign", platforms=[other]),    # other OS → dropped
        _skill("turned_off"),                    # disabled by config → dropped
    ]
    out = _select_available(skills, disabled={"turned_off"})
    names = {s.name for s in out}
    assert names == {"keep", "local"}


# ── compact skill index ──────────────────────────────────────────────


def test_format_skill_index_groups_by_category():
    skills = [
        _skill("drive-the-mac", category="mac"),
        _skill("take-a-screenshot", category="mac"),
        _skill("inspect-a-codebase", category="code"),
    ]
    index = _format_skill_index(skills)
    assert "- code: inspect-a-codebase" in index
    assert "- mac: drive-the-mac, take-a-screenshot" in index
    assert "skill(" in index  # tells the model how to use one


def test_format_skill_index_is_empty_for_no_skills():
    assert _format_skill_index([]) == ""


# ── integration with the real bundled skills ─────────────────────────


def test_discovery_and_index_run_against_the_real_library():
    """The bundled skill tree must still discover, filter, and index
    cleanly — a smoke test over the production filesystem path."""
    discovered = discover_playbooks()
    assert discovered, "expected the bundled skill library to be non-empty"
    available = available_playbooks()
    # availability is a subset of discovery
    assert len(available) <= len(discovered)
    index = build_skill_index()
    assert isinstance(index, str)
    if available:
        # the always-on block is now a "Capabilities" menu listing skill
        # playbooks alongside tools (was "Skill library — …")
        assert "Skill playbooks" in index
