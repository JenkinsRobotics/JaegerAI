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
_scope = ContextVar("agent_bridge_goal_scope", default=None)


def supported_tools():
    # Registration and dispatch remain owned by the lead's canonical catalog.
    from jaeger_agent.tools import files  # noqa: F401 — register native tools
    from jaeger_os.core.tools.tool_registry import get_tools

    return sorted(
        tool.name
        for tool in get_tools()
        if tool.name in PATH_ARGUMENTS
        and tool.fn.__module__ == "jaeger_agent.tools.files"
    )


@contextmanager
def goal_scope(gateway, session_id, request_id, execution):
    """Bind only a durable bridge admission matching the actual caller/session."""
    with gateway.store._get_conn() as conn:
        row = conn.execute(
            "SELECT caller FROM agent_goals WHERE session=? AND request_id=?",
            (session_id, request_id),
        ).fetchone()
    if row is None:
        yield
        return
    from jaeger_ai.core.gateway.caller_auth import CALLERS

    from .routes import workspace

    caller = CALLERS[row["caller"]]
    if caller.actor != (execution or {}).get("caller"):
        raise PermissionError("Bridge goal caller mismatch")
    root = workspace(caller.name, (execution or {}).get("workspace"))
    token = _scope.set((caller.actor, root))
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
    actor, folder = scope
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
    for name in PATH_ARGUMENTS[tool.name]:
        args[name] = confined_path(args.get(name))
    return args
