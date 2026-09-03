"""Agent-facing mission tools."""

from __future__ import annotations

from typing import Any

from jaeger_agent.cognition.commitments import CommitmentError
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .service import MissionService


def _service() -> MissionService:
    return MissionService(SqliteCommitmentStore())


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="missions",
    operation="mission_create",
    summary="create a durable mission, goals, and plan steps",
)
def mission_create(
    title: str,
    goals: list[dict[str, Any] | str],
    metadata: dict[str, Any] | None = None,
) -> dict:
    """Create a durable mission with nested goals and optional ``steps`` per
    goal. This records the plan; dispatch its work through delegate_task or
    the Kanban tools."""
    try:
        return {"ok": True, **_service().create(title, goals, metadata=metadata)}
    except (CommitmentError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
def mission_list(state: str = "") -> dict:
    """List durable missions, their goals, plan steps, and lifecycle state."""
    return {"ok": True, "missions": _service().list(state=state or None)}


@register_tool_from_function(side_effect="read")
def mission_status(mission_id: str) -> dict:
    """Show one durable mission with its nested goals and plan steps."""
    try:
        return {"ok": True, **_service().describe(mission_id)}
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="missions",
    operation="mission_transition",
    summary="change durable mission or goal state",
)
def mission_transition(commitment_id: str, state: str) -> dict:
    """Move a mission, goal, or plan step through its deterministic lifecycle.
    A mission cannot complete while any child goal remains open."""
    try:
        return {"ok": True, "commitment": _service().transition(commitment_id, state)}
    except (CommitmentError, KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
