"""Skill ↔ tool-registry integrity — the phantom-tool-name guard.

The #1 skill bug (dev/docs/skill_standard.md rule 4) is a SKILL.md that
names a tool which isn't actually registered: the model then hallucinates
the call. It has happened twice by the same mechanism — a tool rename or
removal sweep that missed the skills tree (`delegate_task` stripped as
"fake" 2026-07-03; the removed `kanban` umbrella lingering in three
skills' requires_tools). This test makes the class impossible to ship.

The authoritative name set is built the way the review said it must be:
the static registry PLUS the build-time registrations in ``main.py`` and
the two tool-providing skill modules (a bare ``import jaeger_os.agent.tools``
misses those — that's exactly how the delegate_task incident happened).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SKILLS_DIR = REPO / "jaeger_os" / "agent" / "skills"

# Tool-providing modules whose registrations happen at agent-build /
# skill-load time rather than module import.
_BUILD_TIME_SOURCES = (
    REPO / "jaeger_os" / "main.py",
    REPO / "jaeger_os" / "agent" / "skills" / "computer_use_v1" / "computer_use.py",
    REPO / "jaeger_os" / "agent" / "skills" / "macos_computer_v1" / "macos_computer.py",
)


def _decorated_tool_names(src: str) -> set[str]:
    """Tool names registered in ``src`` — explicit ``name="..."`` kwargs
    plus bare-decorator functions (the def name is the tool name). Scans
    a few lines past each decorator so stacked/multi-line decorators
    (``@requires_tier(...)`` spanning lines) don't hide the def."""
    names = set(re.findall(
        r'register_tool_from_function\(\s*name="(\w+)"', src))
    lines = src.splitlines()
    for i, ln in enumerate(lines):
        bare_reg = ("@register_tool_from_function" in ln and "name=" not in ln)
        tool_plain = "@agent.tool_plain" in ln or "@host.tool_plain" in ln
        if not (bare_reg or tool_plain):
            continue
        for j in range(i + 1, min(i + 10, len(lines))):
            m = re.match(r"\s*def (\w+)\(", lines[j])
            if m:
                names.add(m.group(1))
                break
    return names


@pytest.fixture(scope="module")
def registry_names() -> set[str]:
    import jaeger_os.agent.tools  # noqa: F401 — triggers module-level registration
    from jaeger_os.agent.schemas.tool_registry import get_tools
    names = {t.name for t in get_tools()}
    for path in _BUILD_TIME_SOURCES:
        names |= _decorated_tool_names(path.read_text(encoding="utf-8"))
    return names


def _requires_tools(skill_md: Path) -> list[str]:
    text = skill_md.read_text(errors="ignore")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return []
    rt = re.search(r"requires_tools:\s*\[(.*?)\]", m.group(1), re.DOTALL)
    if not rt:
        return []
    return [t.strip().strip("'\"") for t in rt.group(1).split(",") if t.strip()]


def test_every_requires_tools_entry_is_a_real_tool(registry_names):
    """Every tool a skill DECLARES must exist in the full-boot registry."""
    offenders: list[str] = []
    for md in sorted(SKILLS_DIR.rglob("SKILL.md")):
        for tool in _requires_tools(md):
            if tool not in registry_names:
                offenders.append(f"{md.parent.name}: {tool!r}")
    assert not offenders, (
        "SKILL.md requires_tools naming unregistered tools (the model will "
        "hallucinate these calls — fix the skill or register the tool):\n  "
        + "\n  ".join(offenders)
    )


def test_registry_extraction_sees_build_time_tools(registry_names):
    """Sanity: the extraction must include the classes of tool the naive
    bare-import approach missed — otherwise this guard guards nothing."""
    for probe in ("delegate_task", "clarify",          # main.py build-time
                  "computer_open_app", "computer_do",  # skill-module tools
                  "board_add", "list_skills", "reflect"):  # module-level
        assert probe in registry_names, f"extraction lost {probe!r}"
