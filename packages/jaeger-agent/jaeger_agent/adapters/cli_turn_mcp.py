"""Loopback MCP server for CLI brains (Grok, Claude, Codex, Gemini, Antigravity).

Industry-standard path: the CLI talks to Jaeger tools as real MCP tools.
Each ``tools/call`` is executed by the same Jaeger tool executor the
agent loop already uses, so permissions, approvals, guardrails, and
events stay in Jaeger. The CLI's own built-in file tools stay off.

A text ``<tool_call>`` catalogue remains the fallback when this server
cannot start or the backend has no MCP client.
"""

from __future__ import annotations

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
        argv.extend(["--allow", "MCPTool(jaeger__*)"])
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
        if "--sandbox" not in argv:
            argv.append("--sandbox")
    elif backend_id == "hermes":
        if mode == "auto":
            argv.append("--yolo")
    return argv


def mcp_safe_name(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", (name or "").strip()).strip("_")
    return cleaned or "tool"


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

    def start(self, tools: list[ToolDef], execute: ExecuteTool) -> str:
        """Serve ``tools`` on 127.0.0.1 and return the MCP URL."""
        from mcp.server.fastmcp import FastMCP
        from mcp.server.transport_security import TransportSecuritySettings

        token = secrets.token_urlsafe(32)
        lock = threading.Lock()
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
                self.token = token
                self.url = f"http://127.0.0.1:{int(port)}/mcp"
                return self.url
            time.sleep(0.02)
        if failed:
            raise RuntimeError(f"turn MCP failed to start: {failed[0]!r}")
        raise RuntimeError("turn MCP did not become ready")

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            server.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
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

    def write_agy_config(self, folder: str) -> None:
        """Project-scoped Antigravity MCP settings (do not touch the user home)."""
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
        for relative in (".gemini/antigravity-cli", ".gemini"):
            target = Path(folder) / relative
            target.mkdir(parents=True, exist_ok=True)
            path = target / "settings.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            path.chmod(0o600)

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
        self.tools: dict[str, ToolDef] = {}
        self.lock = threading.Lock()

    def __call__(self, tool: ToolDef, args: dict[str, Any]) -> Any:
        fn = self.execute
        if fn is None:
            raise RuntimeError("CLI MCP executor is not attached to a turn")
        # Prefer the currently registered tool of this name so a refreshed
        # schema/handler still hits the live approval/session closure.
        live = self.tools.get(getattr(tool, "name", "")) or tool
        return fn(live, args)


def stable_cli_workdir(backend_id: str) -> str:
    """Persistent per-backend cwd so MCP config can be reused across turns."""
    folder = _STABLE_ROOT / (backend_id or "cli")
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    return str(folder)


def acquire_cli_mcp(backend_id: str, tools: list[ToolDef], execute: ExecuteTool) -> TurnToolMcp:
    """Reuse a process-global MCP server; refresh the execute closure every turn."""
    with _POOL_LOCK:
        server = _POOL.get(backend_id)
        if server is None or not server.url:
            server = TurnToolMcp()
            holder = _ExecuteHolder()
            holder.execute = execute
            holder.tools = {t.name: t for t in tools}
            server._holder = holder  # type: ignore[attr-defined]
            server.start(tools, holder)
            _POOL[backend_id] = server
        else:
            holder = getattr(server, "_holder", None)
            if holder is None:
                holder = _ExecuteHolder()
                server._holder = holder  # type: ignore[attr-defined]
            holder.execute = execute
            holder.tools = {t.name: t for t in tools}
        return server


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
) -> tuple[list[str], dict[str, str], TurnToolMcp | None, bool]:
    """Start a turn MCP (when possible) and return argv, extra env, server, text_fallback.

    ``text_fallback`` is True when the caller should still inject the Hermes
    text protocol into the prompt.
    """
    if backend_id not in MCP_BACKENDS or not tools or execute is None:
        return argv, {}, None, bool(tools)
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
        # Load the project MCP config in the stable cwd without writing the
        # owner's trusted_folders.toml or ~/.grok/config.toml.
        extra_env["GROK_FOLDER_TRUST"] = "0"
        extra_env["GROK_LEADER_SOCKET"] = str(GROK_LEADER_SOCKET)
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
            server.write_agy_config(folder)
        else:
            return argv, {}, None, True
    elif backend_id == "hermes":
        if folder:
            config_path = server.write_hermes_config(folder)
            extra_env["HERMES_CONFIG_PATH"] = config_path
            extra_env["HERMES_CONFIG"] = config_path
        else:
            return argv, {}, None, True
    return child, extra_env, server, False
