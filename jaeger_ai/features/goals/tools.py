"""Agent-facing goal tools.

Importing this module registers the ``goal_*`` / ``project_status`` /
``task_spawn`` tools into the jaeger-os tool registry (same import-registers
pattern as :mod:`jaeger_ai.features.missions.tools`). They are classified
under the ``goals`` toolset in
``jaeger_agent.skill_registry.toolset_scoping``.
"""

from __future__ import annotations

from typing import Any

from jaeger_agent.cognition.commitments import CommitmentError
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .service import GoalService


def _service() -> GoalService:
    return GoalService(SqliteCommitmentStore())


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="goals",
    operation="goal_create",
    summary="create a durable operator goal, optionally under a project, with a tool bundle cap",
)
def goal_create(
    title: str,
    objective: str = "",
    project: str | None = None,
    tool_bundle: str | None = None,
    success_criteria: str = "",
) -> dict:
    """Create a durable operator goal. ``tool_bundle`` (e.g. "robotics.build")
    caps which tools agents working on this goal may reach — it never grants
    tools. Dispatch the work with task_spawn, delegate_task, or the Kanban
    tools."""
    try:
        return {"ok": True, **_service().create(
            title,
            objective=objective,
            project=project,
            tool_bundle=tool_bundle,
            success_criteria=success_criteria,
        )}
    except (CommitmentError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
def goal_list(state: str = "") -> dict:
    """List durable operator goals, their projects, tasks, and lifecycle state."""
    return {"ok": True, "goals": _service().list(state=state or None)}


@register_tool_from_function(side_effect="read")
def goal_status(goal_id: str) -> dict:
    """Show one operator goal: objective, tool bundle, success criteria, and open tasks."""
    try:
        return {"ok": True, **_service().describe(goal_id)}
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="goals",
    operation="goal_update",
    summary="edit or transition a durable operator goal",
)
def goal_update(
    goal_id: str,
    title: str | None = None,
    objective: str | None = None,
    tool_bundle: str | None = None,
    success_criteria: str | None = None,
    state: str | None = None,
) -> dict:
    """Edit a goal in place (title/objective/tool_bundle/success_criteria)
    and/or transition its lifecycle state. Pass tool_bundle="" to clear the
    bundle cap."""
    try:
        service = _service()
        if any(v is not None for v in (title, objective, tool_bundle, success_criteria)):
            service.update(
                goal_id,
                title=title,
                objective=objective,
                tool_bundle=tool_bundle,
                success_criteria=success_criteria,
            )
        if state is not None:
            return {"ok": True, "commitment": service.transition(goal_id, state)}
        return {"ok": True, **service.describe(goal_id)}
    except (CommitmentError, KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
def project_status(project_id: str) -> dict:
    """Roll-up for one project: its goals, open tasks, and tool bundles."""
    try:
        return {"ok": True, **_service().project_status(project_id)}
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="goals",
    operation="task_spawn",
    summary="spawn a durable background task bound to an operator goal",
)
def task_spawn(
    goal_id: str,
    task_goal: str,
    owning_agent: str = "jaeger",
) -> dict:
    """Spawn a durable background task bound to a goal so its work runs off
    the chat turn. Returns the durable task record."""
    try:
        service = _service()
        goal = service.describe(goal_id)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        from jaeger_ai.core.tasks.unified import UnifiedScheduler
        scheduler = UnifiedScheduler()
        task = scheduler.submit(
            task_goal,
            context={
                "goal_id": goal_id,
                "goal_title": goal["goal"].get("title", ""),
                "tool_bundle": goal["goal"].get("payload", {}).get("tool_bundle"),
            },
            owning_agent=owning_agent,
        )
        # Record the spawn as a child commitment so the goal shows its work.
        service.commitments.create(
            f"task: {task_goal}",
            kind="task",
            payload={"task_id": task.task_id, "state": task.state.value
                     if hasattr(task.state, "value") else str(task.state)},
            parent_id=goal_id,
        )
        return {"ok": True, "task_id": task.task_id, "goal": goal["goal"]}
    except Exception as exc:  # noqa: BLE001 — scheduler may be unbound in tests
        return {"ok": False, "error": f"task spawn failed: {exc}"}
