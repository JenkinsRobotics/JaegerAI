"""JaegerAI as an MCP server — let editors/clients (Claude Code, Cursor, Zed)
drive the agent as a tool. The other half of MCP: JaegerAI is already an MCP
*client* (``plugins/mcp``); this exposes JaegerAI *to* MCP.

``jaeger mcp`` is opt-in stdio: the MCP client spawns this process and it
boots the agent in-process. ``jaeger mcp --http`` is streamable-http on
127.0.0.1:8792/mcp and attaches to the already-running instance bridge —
it does not boot a second model.

Run: ``jaeger mcp`` or ``jaeger mcp --http``.
"""

from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import sys
from typing import Any, Callable

# Turn fn: (client, message, session_key=...) -> {"text": str, "error": str|None}
TurnFn = Callable[..., dict]

MCP_HTTP_HOST = "127.0.0.1"
MCP_HTTP_PORT = 8792
MCP_HTTP_PATH = "/mcp"


def _run_chat(run_turn: TurnFn, client: Any, message: str) -> str:
    """Drive one turn for the ``chat`` MCP tool. Agent/tool/model output is
    forced to stderr so it never corrupts the MCP JSON-RPC stdout stream."""
    with contextlib.redirect_stdout(sys.stderr):
        out = run_turn(client, message, session_key="mcp")
    if out.get("error"):
        return f"(agent error: {out['error']})"
    return out.get("text") or ""


def _bridge_chat(bridge: Any, message: str) -> str:
    out = bridge.turn(message, session="mcp")
    if isinstance(out, dict) and out.get("error"):
        return f"(agent error: {out['error']})"
    if isinstance(out, dict):
        return out.get("text") or ""
    return str(out or "")


def _json_args(raw: str) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("args_json must be a JSON object")
    return parsed


def _tool_names(payload: Any) -> list[str]:
    names: list[str] = []
    if isinstance(payload, dict):
        items = payload.get("tools") or payload.get("items") or payload.get("data") or []
        if not items and "name" in payload:
            items = [payload]
    else:
        items = payload or []
    if isinstance(items, dict):
        items = list(items.values())
    for item in items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("id")
            if name:
                names.append(str(name))
    return names


def build_server(client: Any, instance: str, model: str | None,
                 run_turn: TurnFn | None = None, bridge: Any | None = None,
                 host: str = MCP_HTTP_HOST, port: int = MCP_HTTP_PORT) -> Any:
    """Build the FastMCP server exposing JaegerAI.

    ``run_turn`` defaults to the real ``run_for_voice`` (stdio / in-process).
    When ``bridge`` is provided (HTTP mode), tools call the live BridgeClient
    and do not boot a second model.
    """
    from mcp.server.fastmcp import FastMCP

    if run_turn is None and bridge is None:
        from jaeger_ai.main import run_for_voice as run_turn  # noqa: PLW0127

    mcp = FastMCP(
        "jaeger",
        host=host,
        port=port,
        streamable_http_path=MCP_HTTP_PATH,
    )

    @mcp.tool()
    def chat(message: str) -> str:
        """Send a message to the local JaegerAI agent and return its reply.

        The agent has its own tools, memory, and skills; this drives a full
        turn (it may take a while for a complex request)."""
        if bridge is not None:
            return _bridge_chat(bridge, message)
        return _run_chat(run_turn, client, message)

    @mcp.tool()
    def agent_info() -> dict:
        """Return the JaegerAI agent's instance name and loaded model."""
        info: dict[str, Any] = {"instance": instance, "model": model or "unknown"}
        if bridge is not None:
            try:
                ident = bridge.query("identity")
                if isinstance(ident, dict):
                    info.update({k: ident[k] for k in ("name", "model", "instance") if k in ident})
            except Exception as exc:  # noqa: BLE001
                info["bridge_error"] = str(exc)
            info.setdefault("model", model or "unknown")
            info["instance"] = instance
        return info

    if bridge is not None:
        @mcp.tool()
        def bridge_health() -> dict:
            """Health of the live Jaeger instance bridge (no model boot)."""
            return dict(bridge.health())

        @mcp.tool()
        def bridge_query(what: str, args_json: str = "{}") -> Any:
            """Run a bridge query against the live instance (list/config/identity/...)."""
            return bridge.query(what, _json_args(args_json))

        @mcp.tool()
        def bridge_command(command: str, args_json: str = "{}") -> Any:
            """Run a bridge command against the live instance."""
            return bridge.command(command, _json_args(args_json))

        @mcp.tool()
        def list_delegates() -> dict:
            """Cheap delegate catalog: filter live list_tools for delegate_* names."""
            try:
                payload = bridge.query("list_tools")
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc), "delegates": []}
            names = _tool_names(payload)
            delegates = [name for name in names if "delegate" in name.lower()]
            return {"ok": True, "delegates": delegates, "tools": names}

    return mcp


def resolve_mcp_token(explicit: str | None = None) -> str | None:
    """Optional bearer for HTTP MCP. Env wins; never prints the value."""
    if explicit is not None:
        value = explicit.strip()
        return value or None
    env = os.environ.get("JAEGER_MCP_TOKEN", "").strip()
    if env:
        return env
    try:
        from jaeger_ai.features.gateway.constants import mcp_token_path

        path = mcp_token_path()
        if os.environ.get("JAEGER_MCP_REQUIRE_TOKEN", "").strip() in {"1", "true", "yes"}:
            if path.exists():
                return path.read_text(encoding="utf-8").strip() or None
    except Exception:  # noqa: BLE001
        return None
    return None


def _tokens_match(got: bytes, expected: bytes) -> bool:
    if len(got) != len(expected):
        hmac.compare_digest(expected, expected)
        return False
    return hmac.compare_digest(got, expected)


class RequireBearer:
    """ASGI wrapper: reject HTTP requests missing the configured bearer token."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token.encode("utf-8")

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin1").lower(): value
            for key, value in scope.get("headers") or []
        }
        auth = headers.get("authorization", b"")
        expected = b"Bearer " + self.token
        if not _tokens_match(auth, expected):
            body = b'{"error":"unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="jaeger-mcp"'),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def http_app(server: Any, token: str | None = None) -> Any:
    """Starlette streamable-HTTP app, optionally wrapped with bearer auth."""
    app = server.streamable_http_app()
    if token:
        return RequireBearer(app, token)
    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jaeger mcp",
        description=(
            "Expose JaegerAI over MCP. Default is stdio (in-process boot). "
            "`--http` serves streamable-http on 127.0.0.1:8792/mcp attached to "
            "the live bridge (no second model)."
        ),
    )
    parser.add_argument("--http", action="store_true", help="Streamable HTTP on 127.0.0.1:8792/mcp")
    parser.add_argument("--host", default=MCP_HTTP_HOST)
    parser.add_argument("--port", type=int, default=MCP_HTTP_PORT)
    parser.add_argument("--instance", default=None, help="Instance name")
    parser.add_argument("instance_name", nargs="?", default=None, help="Instance name (stdio positional)")
    return parser.parse_args([] if argv is None else argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    instance = args.instance or args.instance_name

    if args.http:
        from jaeger_ai.core.instance.instance import default_instance_name
        from jaeger_ai.interfaces.hermes_webui_adapter.bridge_client import BridgeClient

        instance = instance or default_instance_name()
        bridge = BridgeClient(instance=instance)
        health = bridge.health()
        if not health.get("ok"):
            print(
                f"[jaeger-mcp] live bridge is not available for {instance}: "
                f"{health.get('error') or 'unknown error'}",
                file=sys.stderr,
            )
            return 1
        model = None
        try:
            ident = bridge.query("identity")
            if isinstance(ident, dict):
                model = ident.get("model")
        except Exception:  # noqa: BLE001
            model = None
        server = build_server(None, instance, model, bridge=bridge, host=args.host, port=args.port)
        token = resolve_mcp_token()
        import uvicorn

        uvicorn.run(http_app(server, token), host=args.host, port=args.port)
        return 0

    from jaeger_ai.core.instance.instance import default_instance_name
    from jaeger_ai.interfaces.bridge import _model_name
    from jaeger_ai.main import boot_for_tui

    instance = instance or default_instance_name()

    # Boot the agent with all noise on stderr; MCP owns stdout.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            boot = boot_for_tui(instance_name=instance)
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger-mcp] boot failed: {exc}", file=sys.stderr)
            return 1

    server = build_server(boot.client, instance, _model_name(boot))
    try:
        server.run()              # stdio transport; blocks until the client closes
    finally:
        cleanup = getattr(boot, "cleanup", None)
        if callable(cleanup):
            with contextlib.suppress(Exception):
                cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
