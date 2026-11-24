"""Durable multi-step workflow tools backed by standalone ``jaeger-workflows``.

Lets the agent persist long multi-turn jobs (4-account inbox cleanup, folder
organization batches, YouTube video production pipelines) in SQLite so progress
survives turn limits, approvals, and restarts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import get_layout


def _engine():
    from jaeger_workflows import WorkflowEngine

    layout = get_layout()
    if layout is not None and getattr(layout, "root", None):
        db = Path(layout.root) / "workflows.sqlite3"
    else:
        db = Path.home() / ".jaeger" / "workflows.sqlite3"
    return WorkflowEngine(db)


@register_tool_from_function(name="workflow_create", side_effect="write")
def workflow_create(
    name: str,
    steps: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a durable SQLite-checkpointed multi-step workflow so long tasks
    can resume cleanly across turns and approval gates.

    Each item in ``steps`` is ``{"id": str, "name": str, "depends_on": [str],
    "requires_approval": bool, "idempotent": bool}``."""
    try:
        run = _engine().create_run(name=name, steps=steps, context=context)
        return {"ok": True, **run.to_dict()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@register_tool_from_function(name="workflow_checkpoint", side_effect="write")
def workflow_checkpoint(
    run_id: str,
    step_id: str,
    status: str = "completed",
    output: Any = None,
    error: str = "",
) -> dict[str, Any]:
    """Persist a step's result (completed / failed / skipped / waiting_approval)
    into a durable workflow run so subsequent turns pick up where this one left off."""
    try:
        run = _engine().checkpoint_step(
            run_id=run_id, step_id=step_id, status=status, output=output, error=error,
        )
        return {"ok": True, **run.summary()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@register_tool_from_function(name="workflow_status", side_effect="read")
def workflow_status(run_id: str = "", limit: int = 10) -> dict[str, Any]:
    """Inspect a durable workflow run (or list recent runs when ``run_id`` is empty)."""
    try:
        eng = _engine()
        if run_id.strip():
            run = eng.get_run(run_id.strip())
            if run is None:
                return {"ok": False, "error": f"workflow run not found: {run_id!r}"}
            return {"ok": True, **run.to_dict()}
        runs = eng.list_runs(limit=limit)
        return {"ok": True, "runs": [r.summary() for r in runs], "count": len(runs)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


__all__ = ["workflow_create", "workflow_checkpoint", "workflow_status"]
