"""Skill tree — XP-driven progression for every node + skill.

Foundation module per the operator-locked architectural pattern
(see ``dev/docs/skills/SKILL_TREE.md``).  Every node + skill is a
:class:`SkillNode` in a DAG; tool dispatches award XP via the
bus; level-ups + mastery cascade through the graph as
prerequisites get satisfied.

The schemas are msgspec.Struct so they ride the bus cheaply.
The registry persists per-instance state to
``<instance>/skill_tree.json`` and appends an audit log to
``<instance>/skill_tree.log``.

Public surface:

    from jaeger_os.skill_tree import (
        SkillNode, SkillTree, XpAward,
        SkillTreeRegistry,
    )

    registry = SkillTreeRegistry.load(layout)
    registry.award_xp("animation.gif", 2, reason="tool_call_success")
    registry.save()

The bus integration (``XpEmitter``) is wired separately by the
runtime so the registry stays usable in tests + the bench harness
without a live bus.
"""

from .schema import (
    SkillNode,
    SkillTree,
    XpAward,
    SkillStatus,
)
from .registry import SkillTreeRegistry
from .seed import default_catalog, seed_default_tree
from .xp_emitter import XpEmitter, award_xp

__all__ = [
    "SkillNode",
    "SkillTree",
    "XpAward",
    "SkillStatus",
    "SkillTreeRegistry",
    "XpEmitter",
    "award_xp",
    "default_catalog",
    "seed_default_tree",
]
