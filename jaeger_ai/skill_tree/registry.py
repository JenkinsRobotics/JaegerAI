"""Skill-tree runtime registry.

Holds the in-memory ``SkillTree`` for the active instance.  Tools
+ nodes call :meth:`award_xp` to grant XP; the registry runs the
state-machine (level up, unlock cascade, mastery) and persists
changes to ``<instance>/skill_tree.json``.

Designed for evolvability per the operator's standing rule:
``schema_version`` lets us migrate state forward.  Persistence is
via msgspec.json so the on-disk format is human-readable +
visualisation-friendly.

Bus integration lives in a separate module (``xp_emitter``) so
this registry stays usable in tests + offline tooling without a
live Bus.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import msgspec

from .schema import (
    SkillNode,
    SkillStatus,
    SkillTree,
    XpAward,
)


class SkillTreeRegistry:
    """Per-instance skill tree state + behaviour.

    Construct via :meth:`load` or :meth:`for_instance`; the latter
    looks at the operator's layout to find or create the persisted
    JSON.  All mutations are thread-safe via a re-entrant lock —
    tools / nodes can call ``award_xp`` from any thread.
    """

    def __init__(self, tree: SkillTree, *, persist_path: Path | None = None,
                 log_path: Path | None = None) -> None:
        self._tree = tree
        self._persist_path = persist_path
        self._log_path = log_path
        self._lock = threading.RLock()
        # Subscribers — populated by the runtime when wiring the bus.
        # Signature: (event_name, payload_dict) -> None.  Examples:
        #   ("xp_awarded",   {"skill_id": "animation.gif", "amount": 2, ...})
        #   ("level_up",     {"skill_id": "...", "new_level": 2})
        #   ("unlocked",     {"skill_id": "..."})
        #   ("mastered",     {"skill_id": "..."})
        self._listeners: list[Any] = []

    # ── construction ────────────────────────────────────────────

    @classmethod
    def load(cls, persist_path: Path | None = None,
             log_path: Path | None = None) -> "SkillTreeRegistry":
        """Load from disk; if file is missing, start with an empty
        tree.  Atomic write back via :meth:`save`."""
        if persist_path is not None and persist_path.exists():
            data = persist_path.read_bytes()
            try:
                tree = msgspec.json.decode(data, type=SkillTree)
            except Exception:
                # Corrupted state — fall back to empty rather than
                # crashing the boot.  Operator gets a fresh tree;
                # the on-disk file is renamed for forensic review.
                bad = persist_path.with_suffix(".json.bad")
                persist_path.rename(bad)
                tree = SkillTree()
        else:
            tree = SkillTree()
        return cls(tree, persist_path=persist_path, log_path=log_path)

    @classmethod
    def for_instance(cls, layout: Any) -> "SkillTreeRegistry":
        """Convenience: derive the standard paths from a JROS
        InstanceLayout and load."""
        root = Path(layout.root)
        persist = root / "skill_tree.json"
        log = root / "skill_tree.log"
        return cls.load(persist_path=persist, log_path=log)

    # ── access ──────────────────────────────────────────────────

    @property
    def tree(self) -> SkillTree:
        return self._tree

    def get(self, skill_id: str) -> SkillNode | None:
        with self._lock:
            return self._tree.skills.get(skill_id)

    def all(self) -> tuple[SkillNode, ...]:
        with self._lock:
            return tuple(self._tree.skills.values())

    def categories(self) -> tuple[str, ...]:
        with self._lock:
            seen: list[str] = []
            for s in self._tree.skills.values():
                if s.category and s.category not in seen:
                    seen.append(s.category)
            return tuple(seen)

    # ── mutation ────────────────────────────────────────────────

    def register(self, node: SkillNode) -> SkillNode:
        """Register or replace a skill.  Preserves XP + level + status
        if the skill already exists (we only refresh metadata)."""
        with self._lock:
            existing = self._tree.skills.get(node.id)
            if existing is not None:
                merged = SkillNode(
                    id=existing.id,
                    name=node.name or existing.name,
                    description=node.description or existing.description,
                    category=node.category or existing.category,
                    level=existing.level,
                    max_level=node.max_level or existing.max_level,
                    xp=existing.xp,
                    xp_to_next_level=node.xp_to_next_level if node.xp_to_next_level is not None else existing.xp_to_next_level,
                    xp_to_mastery=node.xp_to_mastery or existing.xp_to_mastery,
                    prerequisites=node.prerequisites or existing.prerequisites,
                    unlocks=node.unlocks or existing.unlocks,
                    status=existing.status,
                    schema_version=node.schema_version or existing.schema_version,
                )
                self._tree.skills[node.id] = merged
                return merged
            # If the skill has prereqs, default to LOCKED — the
            # reconciler then promotes to AVAILABLE when all prereqs
            # are mastered.  Without this default, a fresh skill with
            # unmet prereqs would be incorrectly AVAILABLE.
            if node.prerequisites and node.status == SkillStatus.AVAILABLE:
                node = msgspec.structs.replace(
                    node, status=SkillStatus.LOCKED,
                )
            self._tree.skills[node.id] = node
            # Re-evaluate status from prerequisites after each addition.
            self._reconcile_status(node.id)
            return node

    def award_xp(self, skill_id: str, amount: int, *,
                 reason: str = "", metadata: dict | None = None,
                 ) -> XpAward | None:
        """Grant XP to a skill.  Cascades level-up / unlock / mastery.

        Returns the :class:`XpAward` event (so callers can publish it
        on the bus); ``None`` if the skill doesn't exist."""
        if amount <= 0:
            return None
        with self._lock:
            node = self._tree.skills.get(skill_id)
            if node is None:
                return None
            event = XpAward(
                skill_id=skill_id, amount=amount, reason=reason,
                metadata=dict(metadata or {}),
            )
            # Mutate in-place via a fresh SkillNode (msgspec.Struct is
            # immutable by default but we control reassignment).
            new_xp = node.xp + amount
            self._tree.skills[skill_id] = msgspec.structs.replace(
                node, xp=new_xp,
                status=SkillStatus.ACTIVE if node.status == SkillStatus.AVAILABLE
                       else node.status,
            )
            self._notify("xp_awarded", {
                "skill_id": skill_id, "amount": amount, "reason": reason,
            })
            self._maybe_level_up(skill_id)
            self._maybe_master(skill_id)
            self._append_log(event)
            return event

    # ── persistence ─────────────────────────────────────────────

    def save(self) -> None:
        """Atomic JSON write of the current tree."""
        if self._persist_path is None:
            return
        with self._lock:
            payload = msgspec.json.encode(self._tree)
        tmp = self._persist_path.with_suffix(".json.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(payload)
        tmp.replace(self._persist_path)

    def _append_log(self, event: XpAward) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            line = msgspec.json.encode(event) + b"\n"
            with open(self._log_path, "ab") as f:
                f.write(line)
        except Exception:
            # Logging must never break the skill-tree update path.
            pass

    # ── listeners (the bus subscribes here when wired) ──────────

    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def _notify(self, event_name: str, payload: dict) -> None:
        for cb in self._listeners:
            try:
                cb(event_name, payload)
            except Exception:
                pass  # listeners must not break state updates

    # ── state machine ──────────────────────────────────────────

    def _maybe_level_up(self, skill_id: str) -> None:
        """If the skill has crossed its in-skill level-up threshold,
        bump level.

        Threshold model: ``xp_to_next_level * level`` is the
        CUMULATIVE XP required to reach the next level.  So at L1
        with threshold=50, you need xp>=50 to reach L2.  At L2 with
        threshold=50, you need xp>=100 cumulative to reach L3.  A
        single huge award can cascade through multiple levels if the
        XP supports it, capped at ``max_level``."""
        node = self._tree.skills.get(skill_id)
        if node is None or node.xp_to_next_level is None:
            return
        while (node.level < node.max_level
               and node.xp >= node.xp_to_next_level * node.level):
            node = msgspec.structs.replace(node, level=node.level + 1)
            self._tree.skills[skill_id] = node
            self._notify("level_up", {
                "skill_id": skill_id, "new_level": node.level,
            })

    def _maybe_master(self, skill_id: str) -> None:
        """If XP crosses mastery threshold, flip status + cascade
        prerequisites to children."""
        node = self._tree.skills.get(skill_id)
        if node is None:
            return
        if node.status == SkillStatus.MASTERED:
            return
        if node.xp < node.xp_to_mastery:
            return
        # Master this skill.
        self._tree.skills[skill_id] = msgspec.structs.replace(
            node, status=SkillStatus.MASTERED,
        )
        self._notify("mastered", {"skill_id": skill_id})
        # Cascade — re-evaluate children that listed this as a prereq.
        for child_id in node.unlocks:
            self._reconcile_status(child_id)

    def _reconcile_status(self, skill_id: str) -> None:
        """Re-evaluate a skill's status based on its prerequisites.

        ``locked`` → ``available`` when all prereqs are ``mastered``.
        Doesn't touch ``active`` / ``mastered`` skills — once they're
        engaged, prereq changes don't revoke them."""
        node = self._tree.skills.get(skill_id)
        if node is None:
            return
        if node.status in (SkillStatus.ACTIVE, SkillStatus.MASTERED):
            return
        prereqs_satisfied = all(
            self._tree.skills.get(pid) is not None
            and self._tree.skills[pid].status == SkillStatus.MASTERED
            for pid in node.prerequisites
        )
        if prereqs_satisfied and node.status == SkillStatus.LOCKED:
            self._tree.skills[skill_id] = msgspec.structs.replace(
                node, status=SkillStatus.AVAILABLE,
            )
            self._notify("unlocked", {"skill_id": skill_id})
