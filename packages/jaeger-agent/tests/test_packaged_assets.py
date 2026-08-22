"""Assets the package ships must be findable FROM the package.

The 0.11 move broke three of these at once and none of them raised.
``CORE_SKILLS_DIR``, ``playbook_skills._SKILLS_DIR`` and
``plugins._PLUGINS_ROOT`` were all written as walks up from
``__file__`` to a location that was correct in ``jaeger_ai/agent/…`` and
pointed at nothing after the move. The scan functions treat a missing
directory as an empty one, so the agent came up reporting **zero
skills** and carried on. Only the benchmark noticed, three categories
later.

A missing directory is not an empty directory. These check the paths
resolve and are populated, so the next relocation fails here instead of
in a routing score nobody reads until Friday.
"""

from __future__ import annotations

import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).parents[1] / "jaeger_agent"


def test_core_skills_dir_resolves_inside_the_package() -> None:
    from jaeger_agent.skill_registry.skill_loader import CORE_SKILLS_DIR

    assert CORE_SKILLS_DIR.is_dir(), f"skills dir missing: {CORE_SKILLS_DIR}"
    assert PACKAGE in CORE_SKILLS_DIR.parents or CORE_SKILLS_DIR.parent == PACKAGE, (
        "skills must ship INSIDE the package — a path reaching outside it is "
        "how the module ends up depending on a host directory layout"
    )
    assert len(list(CORE_SKILLS_DIR.iterdir())) > 10


def test_playbook_and_loader_agree_on_where_skills_live() -> None:
    """Two constants, one directory. They drifted apart once already."""
    from jaeger_agent.skill_registry.playbook_skills import _SKILLS_DIR
    from jaeger_agent.skill_registry.skill_loader import CORE_SKILLS_DIR

    assert _SKILLS_DIR == CORE_SKILLS_DIR


def test_the_shipped_skill_corpus_is_present() -> None:
    """The number that silently collapsed to zero.

    Counts skill FOLDERS, not what ``_scan_zone`` returns — that one
    yields only the handful which register tools (computer_use,
    macos_computer). The ~107 that matter here provide a *recipe* loaded
    through ``use_skill``, and they are the ones the move lost.
    """
    from jaeger_agent.skill_registry.skill_loader import CORE_SKILLS_DIR

    manifests = list(CORE_SKILLS_DIR.rglob("SKILL.md")) + list(
        CORE_SKILLS_DIR.rglob("manifest.yaml")
    )
    assert len(manifests) > 50, f"only {len(manifests)} skills shipped"


@pytest.mark.parametrize(
    "relative",
    [
        "prompts/three_laws.md",
        "prompts/framework_agent.md",
        "prompts/agent_system_prompt.md",
        "background/thinking_runner.yaml",
        "module.yaml",
    ],
)
def test_non_python_assets_ship_with_the_code(relative: str) -> None:
    """setuptools only auto-includes .py for a found package. Every one of
    these is read at runtime by a module beside it."""
    assert (PACKAGE / relative).is_file(), f"missing packaged asset: {relative}"
