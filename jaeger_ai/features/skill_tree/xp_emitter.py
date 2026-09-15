"""XpEmitter — bus integration for the skill-tree registry.

Subscribes to ``/sense/xp_awarded`` and applies the XP grant to the
registered :class:`SkillTreeRegistry`.  Mirrors the registry's
listener callbacks BACK out to the bus as
``/sense/skill_level_up``, ``/sense/skill_unlocked``,
``/sense/skill_mastered`` events so any UI (TUI status bar, Swift
visualisation surface) can observe progression in real time.

Lifecycle::

    emitter = XpEmitter(bus=bus, registry=registry)
    emitter.start()   # subscribes; arms the registry listener
    ...
    emitter.stop()    # unsubscribes; idempotent

The emitter intentionally does NOT publish XP itself — that's the
job of whatever instruments tool dispatches / bench passes /
milestone events.  The standalone module ``xp_award.py`` (TBD)
provides a tiny helper for those callers to fire
:class:`jaeger_os.transport.topics.XpAwarded` events from anywhere in the
codebase without re-implementing the bus wiring.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.transport import topics
from jaeger_os.transport import Bus

from .registry import SkillTreeRegistry


class XpEmitter:
    """Subscribe to /sense/xp_awarded; apply to registry; mirror
    skill-tree state events back onto the bus."""

    def __init__(
        self,
        *,
        bus: Bus,
        registry: SkillTreeRegistry,
        autosave: bool = True,
        node_id: str = "skill_tree",
    ) -> None:
        self.bus = bus
        self.registry = registry
        self.autosave = autosave
        self.node_id = node_id
        self._listener_installed = False
        self._subscribed = False

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        if self._listener_installed:
            return
        self.registry.add_listener(self._on_registry_event)
        self._listener_installed = True
        if not self._subscribed:
            self.bus.subscribe(
                topics.SENSE_XP_AWARDED,
                self._on_xp_event,
            )
            self._subscribed = True

    def stop(self) -> None:
        if self._subscribed:
            try:
                self.bus.unsubscribe(
                    topics.SENSE_XP_AWARDED,
                    self._on_xp_event,
                )
            except Exception:  # noqa: BLE001
                pass
            self._subscribed = False
        # The registry's listener list isn't trivially removable
        # without exposing more API; the listener is a no-op once
        # the emitter is torn down because all paths guard on
        # ``_listener_installed``.
        self._listener_installed = False

    # ── bus → registry ────────────────────────────────────────────

    def _on_xp_event(self, msg: topics.TopicMessage) -> None:
        if not isinstance(msg, topics.XpAwarded):
            return
        try:
            self.registry.award_xp(
                msg.skill_id,
                int(msg.amount),
                reason=msg.reason,
                metadata=dict(msg.metadata or {}),
            )
        except Exception:  # noqa: BLE001
            return
        if self.autosave:
            try:
                self.registry.save()
            except Exception:  # noqa: BLE001
                pass

    # ── registry → bus ────────────────────────────────────────────

    def _on_registry_event(self, event_name: str, payload: dict) -> None:
        """Mirror registry state events out to the bus so any
        subscriber can react in real time."""
        if not self._listener_installed:
            return
        try:
            if event_name == "level_up":
                self.bus.publish(topics.SkillLevelUp(
                    skill_id=str(payload.get("skill_id", "")),
                    new_level=int(payload.get("new_level", 0)),
                    node_id=self.node_id,
                ))
            elif event_name == "unlocked":
                self.bus.publish(topics.SkillUnlocked(
                    skill_id=str(payload.get("skill_id", "")),
                    node_id=self.node_id,
                ))
            elif event_name == "mastered":
                self.bus.publish(topics.SkillMastered(
                    skill_id=str(payload.get("skill_id", "")),
                    node_id=self.node_id,
                ))
            # The "xp_awarded" listener event is intentionally NOT
            # mirrored — we'd echo the message we just consumed.
        except Exception:  # noqa: BLE001
            pass


def award_xp(
    bus: Bus,
    skill_id: str,
    amount: int,
    *,
    reason: str = "",
    metadata: dict | None = None,
    node_id: str = "",
) -> None:
    """Convenience helper for any caller (tool dispatcher, bench
    harness, milestone tracker) to fire an XP grant onto the bus.

    The XpEmitter subscribes to ``/sense/xp_awarded`` and applies
    the grant to the runtime SkillTreeRegistry."""
    try:
        bus.publish(topics.XpAwarded(
            skill_id=skill_id,
            amount=int(amount),
            reason=reason,
            metadata=dict(metadata or {}),
            node_id=node_id,
        ))
    except Exception:  # noqa: BLE001
        pass
