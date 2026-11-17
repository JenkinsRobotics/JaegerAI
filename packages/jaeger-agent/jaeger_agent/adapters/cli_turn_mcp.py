"""Loopback MCP server for CLI brains (Grok, Claude, Codex, Gemini, Antigravity).

Industry-standard path: the CLI talks to Jaeger tools as real MCP tools.
Each ``tools/call`` is executed by the same Jaeger tool executor the
agent loop already uses, so permissions, approvals, guardrails, and
events stay in Jaeger. The CLI's own built-in file tools stay off.

A text ``<tool_call>`` catalogue remains the fallback when this server
cannot start or the backend has no MCP client.
"""

from __future__ import annotations

import contextvars
import inspect
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from jaeger_os.core.tools.tool_schema import ToolDef

logger = logging.getLogger(__name__)

MCP_BACKENDS = frozenset({"grok", "claude", "codex", "gemini", "agy"})
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")

# Always on the loopback MCP, even when the model-facing schema is scoped
# or a reused server was started with a narrower set. The system prompt
# names these; Grok looks them up with search_tool / use_tool(jaeger__*).
REQUIRED_CLI_MCP_TOOLS = frozenset({
    "list_skill_dir", "list_skills", "read_file", "write_file", "patch",
    "search_files", "glob", "terminal", "execute_code",
    "web_search", "web_extract", "x_search",
    "list_tools", "load_tools", "describe_tool", "tool_search",
    "memory", "recall", "todo", "clarify", "delegate_task",
    "get_time", "get_weather", "calculate",
    "image_generate", "image_edit",
    "skill_manage", "user_profile",
})

ExecuteTool = Callable[[ToolDef, dict[str, Any]], Any]


def current_autonomy() -> str:
    """Owner approval setting: ask / scoped / auto. Fail closed to scoped."""
    try:
        import os
        from pathlib import Path

        from jaeger_ai.core.runtime.autonomy import current_autonomy as live
        from jaeger_ai.core.runtime.autonomy import effective_autonomy

        state = os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_STATE_DIR")
        if state:
            config = Path(state) / "instances" / "jaeger" / "config.yaml"
            if config.is_file():
                return effective_autonomy(config)
        return live()
    except Exception:  # noqa: BLE001 — never block a turn on status lookup
        return "scoped"


def permission_argv(backend_id: str, autonomy: str) -> list[str]:
    """CLI flags so the binary will invoke Jaeger MCP tools.

    Jaeger remains the approval owner. The CLI must not prompt or auto-deny
    those MCP calls in headless mode. ``auto`` also lifts the CLI's own
    confirmation floor (bypassPermissions / always-approve). Built-in file
    tools stay disabled by ``--tools ""`` elsewhere in the argv.
    """
    mode = (autonomy or "scoped").strip().lower()
    argv: list[str] = []
    if backend_id == "grok":
        argv.extend(["--allow", "MCPTool(jaeger__*)", "--allow", "mcp:jaeger"])
        if mode == "auto":
            argv.extend(["--permission-mode", "bypassPermissions"])
        else:
            argv.extend(["--permission-mode", "dontAsk"])
    elif backend_id == "claude":
        argv.extend(["--allowed-tools", "mcp__jaeger__*"])
        if mode == "auto":
            argv.extend(["--permission-mode", "bypassPermissions"])
        else:
            argv.extend(["--permission-mode", "dontAsk"])
    elif backend_id == "codex":
        # Jaeger owns approval; keep the CLI sandbox. Never pass
        # --dangerously-bypass-approvals-and-sandbox.
        argv.extend(["--ask-for-approval", "never"])
    elif backend_id == "gemini":
        argv.extend(["--skip-trust", "--allowed-mcp-server-names", "jaeger"])
        if mode == "auto":
            argv.extend(["--approval-mode", "yolo"])
    elif backend_id == "agy":
        # Jaeger still owns approvals in the MCP executor. These flags only
        # stop the Antigravity CLI from prompting in a headless turn.
        if "--sandbox" not in argv:
            argv.append("--sandbox")
        if "--dangerously-skip-permissions" not in argv:
            argv.append("--dangerously-skip-permissions")
        if "--mode" not in argv:
            argv.extend(["--mode", "auto"])
    elif backend_id == "hermes":
        if mode == "auto":
            argv.append("--yolo")
    return argv


def mcp_safe_name(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", (name or "").strip()).strip("_")
    return cleaned or "tool"


def merge_cli_mcp_tools(*groups: list[ToolDef] | None) -> list[ToolDef]:
    """Union turn tools with the required MCP set, required names first.

    Prompt text and ``use_tool`` must see the same catalog. A reused
    loopback server that started on a specialist or slim list otherwise
    drops CORE tools (list_skill_dir, terminal, …) while the override
    still advertises them.
    """
    by_name: dict[str, ToolDef] = {}
    for group in groups:
        for tool in group or []:
            name = getattr(tool, "name", "") or ""
            if name and name not in by_name:
                by_name[name] = tool
    missing = [name for name in REQUIRED_CLI_MCP_TOOLS if name not in by_name]
    if missing:
        try:
            from jaeger_os.core.tools.tool_registry import get_tools
            for tool in get_tools():
                name = getattr(tool, "name", "") or ""
                if name in missing and name not in by_name:
                    by_name[name] = tool
        except Exception:  # noqa: BLE001 — turn still proceeds with what we have
            pass
    required = [by_name[n] for n in sorted(REQUIRED_CLI_MCP_TOOLS) if n in by_name]
    rest = [tool for name, tool in by_name.items() if name not in REQUIRED_CLI_MCP_TOOLS]
    return required + rest


def _handler_for(tool: ToolDef, execute: ExecuteTool, lock: threading.Lock):
    """Build a FastMCP-callable whose signature matches the tool schema."""

    def handler(**kwargs: Any) -> Any:
        with lock:
            result = execute(tool, dict(kwargs))
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str, ensure_ascii=False)
        return "" if result is None else str(result)

    handler.__name__ = mcp_safe_name(tool.name)
    handler.__doc__ = (tool.description or tool.name).strip() or tool.name
    try:
        fields = tool.args_model.model_fields
        params: list[inspect.Parameter] = []
        for field_name, field in fields.items():
            required = bool(getattr(field, "is_required", lambda: True)())
            default = inspect.Parameter.empty
            if not required:
                value = getattr(field, "default", inspect.Parameter.empty)
                if value is inspect.Parameter.empty or type(value).__name__ == "PydanticUndefinedType":
                    default = None
                else:
                    default = value
            annotation = field.annotation if field.annotation is not inspect.Parameter.empty else Any
            params.append(inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            ))
        handler.__signature__ = inspect.Signature(params)
    except Exception:  # noqa: BLE001 — fall back to free-form kwargs
        handler.__signature__ = inspect.Signature([
            inspect.Parameter("kwargs", inspect.Parameter.VAR_KEYWORD, annotation=Any),
        ])
    return handler


class TurnToolMcp:
    """Loopback streamable-HTTP MCP server for one CLI completion."""

    def __init__(self) -> None:
        self.url: str | None = None
        self.token: str | None = None
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self._mcp: Any = None
        self._lock = threading.Lock()

    def start(self, tools: list[ToolDef], execute: ExecuteTool) -> str:
        """Serve ``tools`` on 127.0.0.1 and return the MCP URL."""
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings

        token = secrets.token_urlsafe(32)
        lock = self._lock
        mcp = FastMCP(
            "jaeger",
            host="127.0.0.1",
            port=0,
            streamable_http_path="/mcp",
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
                allowed_origins=[
                    "http://127.0.0.1:*",
                    "http://localhost:*",
                    "http://[::1]:*",
                ],
            ),
        )
        seen: set[str] = set()
        for tool in tools:
            name = mcp_safe_name(tool.name)
            if name in seen:
                continue
            seen.add(name)
            fn = _handler_for(tool, execute, lock)
            mcp.add_tool(fn, name=name, description=fn.__doc__)
            try:
                registered = mcp._tool_manager.get_tool(name)
                registered.parameters = tool.to_anthropic_schema().get("input_schema") or registered.parameters
            except Exception:  # noqa: BLE001 — inferred signature is enough
                pass

        from jaeger_ai.interfaces.mcp_server import RequireBearer

        app = RequireBearer(mcp.streamable_http_app(), token)
        import socket
        import uvicorn

        # Reserve a loopback port so we don't have to race uvicorn's port=0.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            holder.bind(("127.0.0.1", 0))
            port = holder.getsockname()[1]

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
        server = uvicorn.Server(config)
        failed: list[BaseException] = []

        def _run() -> None:
            try:
                server.run()
            except BaseException as exc:  # noqa: BLE001
                failed.append(exc)

        thread = threading.Thread(target=_run, name="jaeger-cli-turn-mcp", daemon=True)
        thread.start()
        deadline = time.time() + 5.0
        while time.time() < deadline and not failed:
            if getattr(server, "started", False):
                self._server = server
                self._thread = thread
                self._mcp = mcp
                self.token = token
                self.url = f"http://127.0.0.1:{int(port)}/mcp"
                return self.url
            time.sleep(0.02)
        if failed:
            raise RuntimeError(f"turn MCP failed to start: {failed[0]!r}")
        raise RuntimeError("turn MCP did not become ready")

    def sync_tools(self, tools: list[ToolDef], execute: ExecuteTool) -> None:
        """Add or drop MCP tools so a reused server matches this turn's set."""
        mcp = self._mcp
        if mcp is None:
            return
        manager = getattr(mcp, "_tool_manager", None)
        have = set(getattr(manager, "_tools", {}) or {})
        want: set[str] = set()
        for tool in tools:
            name = mcp_safe_name(tool.name)
            if not name or name in want:
                continue
            want.add(name)
            if name in have:
                continue
            fn = _handler_for(tool, execute, self._lock)
            mcp.add_tool(fn, name=name, description=fn.__doc__)
            try:
                registered = manager.get_tool(name)
                registered.parameters = tool.to_anthropic_schema().get("input_schema") or registered.parameters
            except Exception:  # noqa: BLE001 — inferred signature is enough
                pass
        # Never drop tools the prompt / use_tool must be able to call.
        protected = {mcp_safe_name(n) for n in REQUIRED_CLI_MCP_TOOLS}
        for name in have - want:
            if name in protected:
                continue
            try:
                mcp.remove_tool(name)
            except Exception:  # noqa: BLE001 — stale name must not fail the turn
                pass

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._mcp = None
        self.url = None
        self.token = None

    def write_grok_config(self, folder: str) -> None:
        """Project-scoped Grok MCP config (loaded when cwd is this folder)."""
        from pathlib import Path

        if not self.url or not self.token:
            raise RuntimeError("turn MCP is not running")
        grok_dir = Path(folder) / ".grok"
        grok_dir.mkdir(parents=True, exist_ok=True)
        # Token lives only in this 0600 file next to the prompt, same as
        # the existing prompt.txt privacy rule. Never log it.
        body = (
            # Project-only: enable a Jaeger leader socket without writing
            # the operator's ~/.grok/config.toml.
            "[cli]\n"
            "use_leader = true\n"
            "\n"
            "[mcp_servers.jaeger]\n"
            f'url = "{self.url}"\n'
            f'headers = {{ Authorization = "Bearer {self.token}" }}\n'
        )
        path = grok_dir / "config.toml"
        path.write_text(body, encoding="utf-8")
        path.chmod(0o600)

    def write_claude_config(self, folder: str) -> str:
        """Claude ``--mcp-config`` JSON. Returns the file path."""
        from pathlib import Path

        if not self.url or not self.token:
            raise RuntimeError("turn MCP is not running")
        path = Path(folder) / "mcp.json"
        payload = {
            "mcpServers": {
                "jaeger": {
                    "type": "http",
                    "url": self.url,
                    "headers": {"Authorization": f"Bearer {self.token}"},
                }
            }
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        path.chmod(0o600)
        return str(path)

    def write_gemini_config(self, folder: str) -> None:
        """Project-scoped Gemini settings (loaded from cwd ``.gemini/settings.json``)."""
        from pathlib import Path

        if not self.url or not self.token:
            raise RuntimeError("turn MCP is not running")
        target = Path(folder) / ".gemini"
        target.mkdir(parents=True, exist_ok=True)
        payload = {
            "mcp": {"allowed": ["jaeger"]},
            "mcpServers": {
                "jaeger": {
                    "httpUrl": self.url,
                    "headers": {"Authorization": f"Bearer {self.token}"},
                    "trust": True,
                }
            },
        }
        path = target / "settings.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        path.chmod(0o600)

    def write_agy_config(self, folder: str) -> str:
        """Project-scoped Antigravity MCP settings (do not touch the user home).

        Returns the ``.gemini/antigravity-cli/settings.json`` path so a turn
        that runs in the session worktree can pass ``--settings`` instead of
        writing this file into the owner's project.
        """
        from pathlib import Path

        if not self.url or not self.token:
            raise RuntimeError("turn MCP is not running")
        payload = {
            "mcpServers": {
                "jaeger": {
                    "httpUrl": self.url,
                    "headers": {"Authorization": f"Bearer {self.token}"},
                    "trust": True,
                }
            }
        }
        written = ""
        for relative in (".gemini/antigravity-cli", ".gemini"):
            target = Path(folder) / relative
            target.mkdir(parents=True, exist_ok=True)
            path = target / "settings.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            path.chmod(0o600)
            if not written:
                written = str(path)
        return written

    def write_hermes_config(self, folder: str) -> str:
        """Sidecar Hermes MCP config. Returns the file path for HERMES_CONFIG_PATH."""
        from pathlib import Path

        if not self.url or not self.token:
            raise RuntimeError("turn MCP is not running")
        path = Path(folder) / "hermes-jaeger.yaml"
        body = (
            "mcp_servers:\n"
            "  jaeger:\n"
            f'    url: "{self.url}"\n'
            "    headers:\n"
            f'      Authorization: "Bearer {self.token}"\n'
        )
        path.write_text(body, encoding="utf-8")
        path.chmod(0o600)
        return str(path)

    def codex_argv(self) -> list[str]:
        """Codex ``-c`` overrides that point at this turn's MCP server."""
        if not self.url or not self.token:
            raise RuntimeError("turn MCP is not running")
        return [
            "-c", f"mcp_servers.jaeger.url={self.url}",
            "-c", "mcp_servers.jaeger.bearer_token_env_var=JAEGER_TURN_MCP_TOKEN",
        ]



import os
from pathlib import Path as _Path

_POOL_LOCK = threading.Lock()
_POOL: dict[str, "TurnToolMcp"] = {}
_STABLE_ROOT = _Path.home() / ".cache" / "jaeger" / "cli-workdir"
GROK_LEADER_SOCKET = _Path.home() / ".grok" / "leader-jaeger.sock"


class _ExecuteHolder:
    """Mutable execute + tool map so a reused MCP server tracks the live turn."""

    def __init__(self) -> None:
        self.execute: ExecuteTool | None = None
        self.context: contextvars.Context | None = None
        self.tools: dict[str, ToolDef] = {}
        self.lock = threading.Lock()
        # Turns currently driving this server. A second concurrent turn must
        # not overwrite execute/context/tools (it hijacked the first turn's
        # grant and catalog: "Tool is outside this request scope", "Tool
        # 'get_events' not listed"), so it gets a dedicated server instead.
        self.active = 0

    def __call__(self, tool: ToolDef, args: dict[str, Any]) -> Any:
        fn = self.execute
        if fn is None:
            raise RuntimeError("CLI MCP executor is not attached to a turn")
        # Prefer the currently registered tool of this name so a refreshed
        # schema/handler still hits the live approval/session closure.
        live = self.tools.get(getattr(tool, "name", "")) or tool
        # FastMCP handles tools on worker threads that do not inherit the
        # turn's ContextVar state. Native tool execution uses copy_context();
        # without the same wrap here, get_project_root() falls back to the
        # instance workspace and use_policy approvals never reach the card.
        ctx = self.context
        result = ctx.run(fn, live, args) if ctx is not None else fn(live, args)
        # CLI backends are cloud models: a private tool output is withheld here
        # instead of reaching the model (and failing the turn's next step).
        try:
            from jaeger_ai.core.models.request_policy import withhold_private_result
            return withhold_private_result(result)
        except ImportError:
            return result


def stable_cli_workdir(backend_id: str) -> str:
    """Persistent per-backend folder for MCP config and private prompt files.

    The CLI process may run in the session's resolved cwd or Agent worktree
    instead; this directory still holds tokens and config so they are not
    written into the owner's project.
    """
    folder = _STABLE_ROOT / (backend_id or "cli")
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    return str(folder)


def cli_session_cwd() -> str | None:
    """Session folder or Agent-mode worktree this turn is scoped to, if any."""
    try:
        from jaeger_agent.core.workspace import get_project_root
        root = get_project_root()
    except Exception:  # noqa: BLE001 — absence means the stable config dir
        return None
    if root is None:
        return None
    path = os.path.realpath(str(root))
    return path if os.path.isdir(path) else None


_GROK_EXCLUDE = "/.grok"
_GROK_OVERLAY_MARK_START = "# begin-jaeger-turn-mcp"
_GROK_OVERLAY_MARK_END = "# end-jaeger-turn-mcp"


def _git_info_exclude(work_cwd: str) -> _Path | None:
    """``info/exclude`` for this working tree, or None if it is not a git repo."""
    import subprocess
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=work_cwd, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    path = _Path(raw)
    if not path.is_absolute():
        path = _Path(work_cwd) / path
    return path


def _add_git_exclude(work_cwd: str, line: str) -> bool:
    """Append ``line`` to info/exclude. Returns True if this call wrote it."""
    path = _git_info_exclude(work_cwd)
    if path is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if line in existing.splitlines():
        return False
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + prefix + line + "\n", encoding="utf-8")
    return True


def _remove_git_exclude_line(work_cwd: str, line: str) -> None:
    path = _git_info_exclude(work_cwd)
    if path is None or not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [row for row in lines if row != line]
    if kept != lines:
        body = "\n".join(kept)
        path.write_text(body + ("\n" if body else ""), encoding="utf-8")


def _strip_overlay(body: str) -> str:
    start, end = _GROK_OVERLAY_MARK_START, _GROK_OVERLAY_MARK_END
    if start not in body or end not in body:
        return body
    pre, rest = body.split(start, 1)
    _, post = rest.split(end, 1)
    if post.strip():
        return pre.rstrip() + "\n" + post.lstrip("\n")
    return pre.rstrip() + ("\n" if pre.strip() else "")


def stage_session_cli_config(backend_id: str, work_cwd: str | None, folder: str | None):
    """Make a session worktree see the stable Grok MCP config, then undo it.

    Headless ``grok`` reads project MCP from ``--cwd/.grok/config.toml``, not
    from the process cwd, and has no --mcp-config flag. A symlink (or a
    marked overlay in an existing project config) plus a git exclude keeps
    the token out of ``git add`` / Undo / Apply. The returned callable
    always removes what this function added.
    """
    if backend_id != "grok" or not work_cwd or not folder:
        return lambda: None
    if os.path.realpath(work_cwd) == os.path.realpath(folder):
        return lambda: None
    src = _Path(folder) / ".grok"
    dest = _Path(work_cwd) / ".grok"
    if not src.is_dir():
        return lambda: None

    added_exclude = _add_git_exclude(work_cwd, _GROK_EXCLUDE)
    cleanups: list = []

    def cleanup() -> None:
        for fn in reversed(cleanups):
            try:
                fn()
            except OSError:
                pass
        if added_exclude:
            try:
                _remove_git_exclude_line(work_cwd, _GROK_EXCLUDE)
            except OSError:
                pass

    if dest.is_symlink() or not dest.exists():
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        dest.symlink_to(src)
        cleanups.append(lambda: dest.unlink(missing_ok=True) if dest.is_symlink() else None)
        return cleanup

    # Owner already has a project .grok/. Temporarily overlay our MCP block.
    cfg = dest / "config.toml"
    original = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    source_cfg = src / "config.toml"
    incoming = source_cfg.read_text(encoding="utf-8") if source_cfg.is_file() else ""
    stripped = _strip_overlay(original)
    overlay = (
        (stripped + ("\n" if stripped and not stripped.endswith("\n") else ""))
        + _GROK_OVERLAY_MARK_START + "\n"
        + incoming.rstrip() + "\n"
        + _GROK_OVERLAY_MARK_END + "\n"
    )
    if not cfg.exists():
        def _remove_cfg() -> None:
            try:
                cfg.unlink()
            except OSError:
                pass
        cleanups.append(_remove_cfg)
    else:
        def _restore() -> None:
            try:
                cfg.write_text(original, encoding="utf-8")
                cfg.chmod(0o600)
            except OSError:
                pass
        cleanups.append(_restore)
    cfg.write_text(overlay, encoding="utf-8")
    cfg.chmod(0o600)
    return cleanup


def acquire_cli_mcp(backend_id: str, tools: list[ToolDef], execute: ExecuteTool) -> TurnToolMcp:
    """Reuse a process-global MCP server; refresh the execute closure every turn."""
    # Capture on the turn thread (already under project_scope / use_policy).
    turn_ctx = contextvars.copy_context()
    with _POOL_LOCK:
        server = _POOL.get(backend_id)
        if server is None or not server.url:
            server = TurnToolMcp()
            holder = _ExecuteHolder()
            holder.execute = execute
            holder.context = turn_ctx
            holder.tools = {t.name: t for t in tools}
            server._holder = holder  # type: ignore[attr-defined]
            server.start(tools, holder)
            _POOL[backend_id] = server
        elif getattr(getattr(server, "_holder", None), "active", 0) > 0:
            # Pooled server is mid-turn: give this turn its own server,
            # stopped by release_cli_mcp when the turn ends.
            server = TurnToolMcp()
            holder = _ExecuteHolder()
            holder.execute = execute
            holder.context = turn_ctx
            holder.tools = {t.name: t for t in tools}
            server._holder = holder  # type: ignore[attr-defined]
            server._dedicated = True  # type: ignore[attr-defined]
            server.start(tools, holder)
        else:
            holder = getattr(server, "_holder", None)
            if holder is None:
                holder = _ExecuteHolder()
                server._holder = holder  # type: ignore[attr-defined]
            holder.execute = execute
            holder.context = turn_ctx
            holder.tools = {t.name: t for t in tools}
            # Warmup used to start this server with zero tools; later turns
            # only refreshed the holder, so Grok's tools/list stayed empty.
            server.sync_tools(tools, holder)
        holder = getattr(server, "_holder", None)
        if holder is not None:
            holder.active += 1
        return server


def release_cli_mcp(server: TurnToolMcp | None) -> None:
    """End this turn's claim on ``server``; stop it if it was dedicated."""
    if server is None:
        return
    with _POOL_LOCK:
        holder = getattr(server, "_holder", None)
        if holder is not None and holder.active > 0:
            holder.active -= 1
        dedicated = bool(getattr(server, "_dedicated", False))
    if dedicated:
        try:
            server.stop()
        except Exception:  # noqa: BLE001 — a stuck loopback server must not fail the turn
            logger.warning("dedicated turn MCP did not stop cleanly", exc_info=True)


def grok_leader_argv() -> list[str]:
    """Jaeger-specific leader socket; never touches the user's default socket."""
    GROK_LEADER_SOCKET.parent.mkdir(parents=True, exist_ok=True)
    return ["--leader-socket", str(GROK_LEADER_SOCKET)]


def attach_cli_mcp(
    backend_id: str,
    argv: list[str],
    folder: str | None,
    tools: list[ToolDef],
    execute: ExecuteTool | None,
    work_cwd: str | None = None,
) -> tuple[list[str], dict[str, str], TurnToolMcp | None, bool]:
    """Start a turn MCP (when possible) and return argv, extra env, server, text_fallback.

    ``text_fallback`` is True when the caller should still inject the Hermes
    text protocol into the prompt.

    ``folder`` is the stable config directory (tokens, MCP config). ``work_cwd``
    is the session folder or Agent worktree the CLI should treat as cwd.
    Config is never written into ``work_cwd``.
    """
    if backend_id not in MCP_BACKENDS or not tools or execute is None:
        return argv, {}, None, bool(tools)
    tools = merge_cli_mcp_tools(tools)
    try:
        server = acquire_cli_mcp(backend_id, tools, execute)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLI native MCP unavailable (%s); using text tool protocol", type(exc).__name__)
        return argv, {}, None, True

    child = list(argv)
    extra_env: dict[str, str] = {}
    autonomy = current_autonomy()
    child.extend(permission_argv(backend_id, autonomy))
    if backend_id == "grok":
        if folder:
            server.write_grok_config(folder)
        # Load the project MCP config without writing the owner's
        # trusted_folders.toml or ~/.grok/config.toml. Headless `grok` has
        # no --plugin-dir / --mcp-config, so a worktree turn stages a
        # temporary .grok link (see stage_session_cli_config).
        extra_env["GROK_FOLDER_TRUST"] = "0"
        extra_env["GROK_LEADER_SOCKET"] = str(GROK_LEADER_SOCKET)
        # X search / code interpreter are backend tools. --disable-web-search
        # does not turn them off; a list-files turn spun on x_keyword_search.
        extra_env["GROK_BACKEND_SEARCH"] = "0"
        # Do not import ~/.claude.json MCP (jaeger-local on :8792 failed auth
        # and is not this turn's loopback server).
        extra_env["GROK_CLAUDE_MCPS_ENABLED"] = "0"
        extra_env["GROK_CURSOR_MCPS_ENABLED"] = "0"
        extra_env["GROK_CLAUDE_SKILLS_ENABLED"] = "0"
        extra_env["GROK_CURSOR_SKILLS_ENABLED"] = "0"
        extra_env["GROK_CLAUDE_AGENTS_ENABLED"] = "0"
        extra_env["GROK_CURSOR_AGENTS_ENABLED"] = "0"
        extra_env["GROK_CLAUDE_RULES_ENABLED"] = "0"
        extra_env["GROK_CURSOR_RULES_ENABLED"] = "0"
        extra_env["GROK_CLAUDE_HOOKS_ENABLED"] = "0"
        extra_env["GROK_CURSOR_HOOKS_ENABLED"] = "0"
        for flag in grok_leader_argv():
            if flag not in child:
                child.append(flag)
    elif backend_id == "claude":
        if folder:
            config_path = server.write_claude_config(folder)
            child.extend(["--mcp-config", config_path, "--strict-mcp-config"])
        else:
            return argv, {}, None, True
    elif backend_id == "codex":
        child.extend(server.codex_argv())
        extra_env["JAEGER_TURN_MCP_TOKEN"] = server.token or ""
    elif backend_id == "gemini":
        if folder:
            server.write_gemini_config(folder)
        else:
            return argv, {}, None, True
        # Headless trusted-folder (Gemini CLI exit 55).
        extra_env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    elif backend_id == "agy":
        if folder:
            settings = server.write_agy_config(folder)
        else:
            return argv, {}, None, True
        # Process cwd may be the session worktree, which has no .gemini/
        # settings. --settings is session-only and is never written there.
        distinct_work = bool(
            work_cwd and folder
            and os.path.realpath(work_cwd) != os.path.realpath(folder)
        )
        if distinct_work:
            child.extend(["--settings", settings])
            if "--add-dir" not in child:
                child.extend(["--add-dir", work_cwd])
    elif backend_id == "hermes":
        if folder:
            config_path = server.write_hermes_config(folder)
            extra_env["HERMES_CONFIG_PATH"] = config_path
            extra_env["HERMES_CONFIG"] = config_path
        else:
            return argv, {}, None, True
    return child, extra_env, server, False
