"""Skill-tree msgspec schemas.

See ``dev/docs/skills/SKILL_TREE.md`` for the design contract.  These
types ride the bus (e.g. ``XpAwarded`` topic) and persist to
``<instance>/skill_tree.json``.
"""

from __future__ import annotations

import time

import msgspec


# Status strings — kept as a plain enum-shaped class so callers
# can ``SkillStatus.AVAILABLE`` rather than memorise magic strings.
class SkillStatus:
    LOCKED = "locked"
    AVAILABLE = "available"
    ACTIVE = "active"
    MASTERED = "mastered"

    ALL = (LOCKED, AVAILABLE, ACTIVE, MASTERED)


class SkillNode(msgspec.Struct, kw_only=True):
    """One skill in the operator's agent.

    Identity + grouping
    ───────────────────
    ``id``         dotted slug, e.g. ``animation.gif`` or ``voice.tts``
    ``name``       short human-readable name
    ``description`` one-liner the visualisation shows on hover
    ``category``   top-level cluster — ``animation`` | ``voice`` |
                   ``vision`` | ``motor`` | ``light`` | ``core``

    Progression
    ───────────
    ``level``         current operating level (L1 = simplest viable)
    ``max_level``     highest level this skill can climb (1 if the
                      progression happens via UNLOCKING the next skill
                      instead of upgrading this one)
    ``xp``            accumulated experience
    ``xp_to_next_level`` threshold to climb a level within this skill
                      (``None`` if no in-skill level-up — progression
                      goes via unlocking children)
    ``xp_to_mastery`` total XP to flip status to MASTERED — unlocks
                      child skills

    Graph
    ─────
    ``prerequisites``  other skill IDs that must be ``MASTERED`` before
                       this one becomes ``AVAILABLE``
    ``unlocks``        skill IDs this one enables when mastered

    Runtime state
    ─────────────
    ``status``  one of :class:`SkillStatus`
    ``schema_version`` bumps when the schema changes; load/save
                       refuses mismatched versions until migrated
    """

    id: str
    name: str = ""
    description: str = ""
    category: str = ""
    level: int = 1
    max_level: int = 1
    xp: int = 0
    xp_to_next_level: int | None = None
    xp_to_mastery: int = 1000
    prerequisites: tuple[str, ...] = ()
    unlocks: tuple[str, ...] = ()
    status: str = SkillStatus.AVAILABLE
    schema_version: int = 1


class XpAward(msgspec.Struct, kw_only=True):
    """One XP grant event.  Appended to ``<instance>/skill_tree.log``
    (JSONL) for replay + future visualisation; also published on
    ``/sense/xp_awarded`` so any subscriber can react in real time."""

    skill_id: str
    amount: int
    reason: str = ""
    metadata: dict = msgspec.field(default_factory=dict)
    awarded_at_ns: int = msgspec.field(default_factory=time.time_ns)


class SkillTree(msgspec.Struct, kw_only=True):
    """The whole tree for one instance.  Persisted to
    ``<instance>/skill_tree.json``."""

    schema_version: int = 1
    instance_id: str = ""
    skills: dict[str, SkillNode] = msgspec.field(default_factory=dict)
