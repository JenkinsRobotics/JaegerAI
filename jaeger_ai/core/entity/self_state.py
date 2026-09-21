"""Authoritative Compact Current-State Projection (SelfState) for Jaeger.

Core Constraints:
- Truthful continuity: NO hard-coded consciousness or subjective claims.
- The state is grounded strictly in demonstrable runtime facts:
  identity, boot time, active interfaces, active goals, commitments,
  environmental observations, and tool outcomes.
- Models may reason ABOUT this state; models do NOT authoritatively write it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Any

from .identity import EntityIdentity


@dataclass(frozen=True)
class SelfState:
    """The authoritative projection of Jaeger's current operational state."""

    identity: EntityIdentity
    boot_timestamp: float = field(default_factory=time.time)
    last_event_timestamp: float = 0.0
    last_user_interaction_ts: float = 0.0
    current_activity: str = "idle"
    current_focus: str = ""
    active_interfaces: tuple[str, ...] = ("gateway",)
    active_sensors: tuple[str, ...] = ()
    active_goals: tuple[dict[str, Any], ...] = ()
    commitments: tuple[dict[str, Any], ...] = ()
    important_people: tuple[dict[str, Any], ...] = ()
    uncertainty_areas: tuple[str, ...] = ()
    resource_telemetry: dict[str, Any] = field(default_factory=dict)
    recent_insights: tuple[str, ...] = ()
    total_events_processed: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["identity"] = self.identity.to_dict()
        data["active_interfaces"] = list(self.active_interfaces)
        data["active_sensors"] = list(self.active_sensors)
        data["active_goals"] = list(self.active_goals)
        data["commitments"] = list(self.commitments)
        data["important_people"] = list(self.important_people)
        data["uncertainty_areas"] = list(self.uncertainty_areas)
        data["recent_insights"] = list(self.recent_insights)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelfState:
        identity = EntityIdentity.from_dict(data["identity"])
        return cls(
            identity=identity,
            boot_timestamp=float(data.get("boot_timestamp") or time.time()),
            last_event_timestamp=float(data.get("last_event_timestamp") or 0.0),
            last_user_interaction_ts=float(data.get("last_user_interaction_ts") or 0.0),
            current_activity=str(data.get("current_activity") or "idle"),
            current_focus=str(data.get("current_focus") or ""),
            active_interfaces=tuple(str(x) for x in data.get("active_interfaces") or ["gateway"]),
            active_sensors=tuple(str(x) for x in data.get("active_sensors") or []),
            active_goals=tuple(dict(x) for x in data.get("active_goals") or []),
            commitments=tuple(dict(x) for x in data.get("commitments") or []),
            important_people=tuple(dict(x) for x in data.get("important_people") or []),
            uncertainty_areas=tuple(str(x) for x in data.get("uncertainty_areas") or []),
            resource_telemetry=dict(data.get("resource_telemetry") or {}),
            recent_insights=tuple(str(x) for x in data.get("recent_insights") or []),
            total_events_processed=int(data.get("total_events_processed") or 0),
        )

    def to_prompt_context_block(self) -> str:
        """Render a truthful, compact self-state block for inclusion in cognition prompts."""
        lines = [
            f"# Persistent Entity State [{self.identity.display_name}]",
            f"- Entity ID: {self.identity.entity_id}",
            f"- Current Activity: {self.current_activity}",
        ]
        if self.current_focus:
            lines.append(f"- Current Focus: {self.current_focus}")
        if self.active_goals:
            lines.append("- Active Goals:")
            for g in self.active_goals[-5:]:
                desc = g.get("desc") or g.get("description") or g.get("id")
                lines.append(f"  * {desc}")
        if self.commitments:
            lines.append("- Active Commitments:")
            for c in self.commitments[-5:]:
                lines.append(f"  * {c.get('description') or c.get('id')}")
        if self.recent_insights:
            lines.append("- Recent Consolidated Insights:")
            for insight in self.recent_insights[-5:]:
                lines.append(f"  * {insight}")
        return "\n".join(lines)
