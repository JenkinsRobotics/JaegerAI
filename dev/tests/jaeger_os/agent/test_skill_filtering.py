"""Playbook skill filtering by tool availability.

The frontmatter's ``requires_tools`` was parsed but advisory; now passing
the active tool set hides skills whose required tools are absent — without
changing the default (no tools given = no filtering, back-compat)."""

from __future__ import annotations

import dataclasses

from jaeger_os.agent.skill_registry.playbook_skills import (
    PlaybookSkill,
    _select_available,
)


def _mk(name: str, requires_tools: list[str]) -> PlaybookSkill:
    required = {
        f.name: ("" if f.type is str else [])
        for f in dataclasses.fields(PlaybookSkill)
        if f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING
    }
    required.update(name=name, category="c", requires_tools=requires_tools)
    return PlaybookSkill(**required)


def test_no_tools_given_does_not_filter():
    skills = [_mk("a", ["web_search"]), _mk("b", []), _mk("d", ["absent"])]
    assert {s.name for s in _select_available(skills, set())} == {"a", "b", "d"}


def test_filters_skills_whose_required_tools_are_absent():
    skills = [_mk("a", ["web_search"]), _mk("b", []), _mk("d", ["absent"])]
    got = _select_available(skills, set(), available_tools={"web_search"})
    assert {s.name for s in got} == {"a", "b"}   # "d" hidden (needs "absent")
