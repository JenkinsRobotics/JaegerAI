"""``execute_with_tools`` — the model-facing half of the tool bridge.

Kept apart from :mod:`jaeger_ai.core.runtime.code_bridge` so the bridge
mechanics stay importable (and unit-testable) without registering a
tool as a side effect of the import. Importing THIS module registers.

Tier: the same ``WRITE_LOCAL`` gate ``execute_code`` carries. A bridged
script is not more privileged than an unbridged one — every tool it
reaches re-checks its own tier at dispatch, so a script that calls a
hardware tool still meets that tool's gate. What the bridge changes is
the number of inference turns, never the permission surface.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from jaeger_ai.core.runtime.code_bridge import BridgeRefused, run_bridged_script


def _workspace() -> Any:
    """The instance ``skills/`` dir, so a script sees files just written.

    Same contract as ``run_python``: falls back to the process cwd when
    no instance is bound (bench / tests), rather than refusing to run.
    """
    try:
        from jaeger_agent.workspace import _require_layout

        workdir = _require_layout().skills_dir
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir
    except Exception:  # noqa: BLE001 — standalone / unbound
        return None


@register_tool_from_function(name="execute_with_tools")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="code",
               operation="execute_with_tools",
               summary="run a Python script that calls Jaeger tools")
def _t_execute_with_tools(code: str, timeout_s: float = 60.0) -> dict:
    """Run ONE Python script that calls Jaeger's tools in a loop, and
    return only what it prints.

    Use this when a task is the SAME operation over many items —
    read every file in a folder and pull one field, check twenty URLs,
    rename a batch. Doing that as separate tool calls costs one model
    turn per item and puts every intermediate result in your context;
    this does the whole chain in one turn and returns only your output.

    Inside the script, ``import jaeger_tools as jt`` and call any tool
    as a function with keyword arguments::

        import jaeger_tools as jt
        entries = jt.list_skill_dir(path="notes")["entries"]
        for name in entries:
            body = jt.file_read(path=f"notes/{name}")
            if "TODO" in body.get("content", ""):
                print(name)

    A failing tool raises ``jt.ToolError`` — catch it and keep going if
    the batch should survive one bad item. PRINT what you need back:
    stdout is the only thing that returns to you. Runs in the skills/
    workspace. 60s default timeout, 120 tool calls max.

    Not for: a single tool call (just call it), anything needing a
    question answered mid-run, or starting sub-agents.

    Returns {ok, stdout, stderr, tool_calls, tool_call_count,
    elapsed_s}.
    """
    try:
        return run_bridged_script(
            code,
            timeout_s=float(timeout_s or 60.0),
            workspace=_workspace(),
        )
    except BridgeRefused as exc:
        return {"ok": False, "error": str(exc)}


__all__ = ["_t_execute_with_tools"]
