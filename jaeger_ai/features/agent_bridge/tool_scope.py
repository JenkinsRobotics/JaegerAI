"""Host-bound bridge goal confinement around the ordinary tool executor.

No model argument enables this scope. The Gateway derives it from its durable
admission record. Unsupported tools fail closed, including every MCP tool.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

# These existing native file tools have explicit, bounded path arguments.
PATH_ARGUMENTS = {
    "read_file": ("path",),
    "write_file": ("path",),
    "append_file": ("path",),
    "patch": ("path",),
    "delete_file": ("path",),
    "copy_file": ("src", "dst"),
    "move_file": ("src", "dst"),
}
TEAM_TOOLS = {"call_agent", "run_team", "get_agent_result"}
_scope = ContextVar("agent_bridge_goal_scope", default=None)


def supported_tools():
    # Registration and dispatch remain owned by the lead's canonical catalog.
    from jaeger_agent.tools import files  # noqa: F401 — register native tools
    from jaeger_os.core.tools.tool_registry import get_tools

    return sorted(
        tool.name
        for tool in get_tools()
        if (
            tool.name in PATH_ARGUMENTS
            and tool.fn.__module__ == "jaeger_agent.tools.files"
        )
        or (
            tool.name in TEAM_TOOLS
            and tool.fn.__module__ == "jaeger_agent.tools.call_agent"
        )
    )


@contextmanager
def goal_scope(gateway, session_id, request_id, execution):
    """Bind only a durable bridge admission matching the actual caller/session."""
    from .delegation import checked_execution, origin

    binding = origin(gateway, session_id, request_id)
    if binding is None:
        yield
        return
    actor, root = checked_execution(gateway, binding)
    if actor != (execution or {}).get("caller") or root != (execution or {}).get(
        "workspace"
    ):
        raise PermissionError("Bridge goal caller/workspace mismatch")
    token = _scope.set((actor, root, gateway, binding, session_id, request_id))
    from jaeger_agent.core.workspace import path_guard

    try:
        with path_guard(confined_path):
            yield
    finally:
        _scope.reset(token)


def confined_path(raw):
    """Recheck at actual native I/O, after permission decorators have asked."""
    from jaeger_agent.tool_executor import active_caller_identity

    from .service import enabled

    scope = _scope.get()
    if scope is None:
        return raw
    enabled()
    actor, folder, gateway, binding, *_ = scope
    from .delegation import checked_execution

    checked_execution(gateway, binding)
    if actor != active_caller_identity():
        raise PermissionError("Bridge goal caller mismatch")
    root = Path(folder).resolve(strict=True)
    if root != Path(folder):
        raise PermissionError("Workspace changed after admission")
    if not isinstance(raw, str) or not raw or raw.startswith("~"):
        raise PermissionError("Explicit workspace path required")
    path = Path(raw)
    target = (path if path.is_absolute() else root / path).resolve()
    if not target.is_relative_to(root) or target == root:
        raise PermissionError("Path is outside the bridge goal workspace")
    if target.exists() and not target.is_file():
        raise PermissionError("Only regular file resources are supported")
    return str(target)


def confined_arguments(tool, arguments):
    """Run before authority and again after approval/hook argument changes."""
    if _scope.get() is None:
        return dict(arguments)
    if tool.name not in supported_tools():
        raise PermissionError("Tool is outside the bridge goal grant")
    args = dict(arguments)
    if tool.name in TEAM_TOOLS:
        _actor, _, gateway, binding, _session_id, request_id = _scope.get()
        from .delegation import checked_execution

        checked_execution(gateway, binding)
        if tool.name == "get_agent_result":
            handoff = gateway.store.get_handoff(args.get("handoff_id")) or {}
            if (handoff.get("metadata") or {}).get("bridge_origin") != binding:
                raise PermissionError("Handoff belongs to another goal")
        elif tool.name == "call_agent":
            args.update(
                parent_run_id=request_id,
                from_agent_id="native:jaeger",
                require_approval=True,
            )
            # task_scope supplies session_id; the REST handler independently
            # checks it against the durable parent, workspace and actor.
            if args.get("project_id"):
                raise PermissionError(
                    "Bridge handoff cannot select an unrelated project"
                )
        elif args.get("project_id"):
            raise PermissionError("Bridge handoff cannot select an unrelated project")
        return args
    for name in PATH_ARGUMENTS[tool.name]:
        args[name] = confined_path(args.get(name))
    return args


# A goal scope can only ever exist inside this module (goal_scope() opens it),
# so registering here at import keeps confinement exactly as live as the
# lazy-import check it replaces — no executor sees confinement without the
# module that owns the scope being loaded.
from jaeger_agent.tool_executor import register_goal_confinement

register_goal_confinement(confined_arguments)
