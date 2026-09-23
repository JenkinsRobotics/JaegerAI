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
import functools
import anyio
from typing import Any, Callable

from jaeger_ai.contract.ports import (
    A2A_URL,
    LOOPBACK,
    MCP_HTTP_URL,
    MCP_HTTP_PATH,
    MCP_HTTP_PORT,
)

# Turn fn: (client, message, session_key=...) -> {"text": str, "error": str|None}
TurnFn = Callable[..., dict]

MCP_HTTP_HOST = LOOPBACK


def _off_event_loop(fn):
    """Keep the MCP transport responsive while synchronous bridge work waits."""
    @functools.wraps(fn)
    async def invoke(*args, **kwargs):
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
    return invoke


def _run_chat(
    run_turn: TurnFn,
    client: Any,
    message: str,
    session_key: str = "mcp",
    request_id: str = "",
    is_subordinate: bool = False,
) -> str:
    """Drive one turn for the ``chat`` MCP tool. Agent/tool/model output is
    forced to stderr so it never corrupts the MCP JSON-RPC stdout stream."""
    with contextlib.redirect_stdout(sys.stderr):
        kwargs: dict[str, Any] = {"session_key": session_key or "mcp"}
        if request_id:
            kwargs["request_id"] = request_id
        if is_subordinate:
            kwargs["is_subordinate"] = is_subordinate
        try:
            out = run_turn(client, message, **kwargs)
        except TypeError:
            out = run_turn(client, message, session_key=session_key or "mcp")
    if out.get("error") or out.get("halt_reason"):
        raise RuntimeError(f"Native agent failed: {out.get('error') or out['halt_reason']}")
    return out.get("text") or ""


def _gateway_approval_wait(frame: dict[str, Any], request_id: str) -> str:
    """Block native tool execution until the gateway records a decision."""
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore()
    approval = store.create_approval(
        kind=str(frame.get("kind") or "tool"),
        prompt=str(frame.get("prompt") or "Approve native tool?"),
        options=list(frame.get("options") or ["once", "deny"]),
        request_id=request_id or None,
        fingerprint=str(frame.get("id") or ""),
        metadata={"native_id": frame.get("id"), "session": frame.get("session")},
    )
    waited = store.wait_for_approval(approval["approval_id"])
    return str(waited.get("decision") or "deny")


def _bridge_chat(bridge: Any, message: str, session: str = "mcp", request_id: str = "",
                 allowed_tools: list[str] | None = None, is_subordinate: bool = False) -> str:
    kwargs: dict[str, Any] = {}
    if allowed_tools is not None:
        kwargs["allowed_tools"] = allowed_tools
    if request_id:
        kwargs["turn_id"] = request_id
        kwargs["on_request"] = lambda frame: _gateway_approval_wait(frame, request_id)
    if is_subordinate:
        kwargs["is_subordinate"] = True
    out = bridge.turn(message, session=session or "mcp", **kwargs)
    if isinstance(out, dict) and (out.get("error") or out.get("halt_reason") or out.get("execution_unknown")):
        raise RuntimeError(f"Native agent has no confirmed result: {out.get('error') or out.get('halt_reason') or 'execution unknown'}")
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


def capability_inventory(bridge: Any | None = None) -> dict[str, Any]:
    """Return Jaeger's live tool inventory and shared protocol endpoints."""
    names: list[str] = []
    runtime_initialized = False
    inventory_error = None
    if bridge is not None:
        try:
            payload = bridge.query("list_tools")
            names = _tool_names(payload)
            if isinstance(payload, dict):
                runtime_initialized = bool(payload.get("runtime_initialized"))
        except Exception as exc:  # noqa: BLE001
            inventory_error = str(exc)
    apple_groups = {
        "calendar": ["get_events", "create_event", "calendar_list", "calendar_create"],
        "reminders": ["reminders_list", "reminders_create"],
        "contacts": ["lookup_contact"],
        "mail": ["send_email", "list_mail", "list_mailboxes", "move_mail"],
        "notes": ["notes_list", "notes_read", "notes_create"],
        "shortcuts": ["list_shortcuts", "run_shortcut", "shortcuts_list", "shortcuts_run"],
        "files": ["spotlight_search", "read_file", "write_file", "move_file", "copy_file"],
        "system": ["notify", "system_control", "media_control", "now_playing"],
    }
    groups = {
        group: {
            "agent_tools": tools,
            "entrypoint": "chat",
        }
        for group, tools in apple_groups.items()
    }
    result: dict[str, Any] = {
        "ok": True,
        "authority": "jaeger",
        "mcp": MCP_HTTP_URL,
        "a2a": A2A_URL,
        "external_mcp_tools": names,
        "external_mcp_runtime_initialized": runtime_initialized,
        "groups": groups,
        "apple": groups,
        "apple_authority": (
            "Apple capabilities remain behind Jaeger's chat controller, "
            "identity grants, approvals, and WorkLedger verification."
        ),
        "completion_authority": "JaegerAgentController+WorkLedger",
    }
    if inventory_error:
        result["inventory_error"] = inventory_error
    return result


def build_server(client: Any, instance: str, model: str | None,
                 run_turn: TurnFn | None = None, bridge: Any | None = None,
                 gateway: Any | None = None,
                 host: str = MCP_HTTP_HOST, port: int = MCP_HTTP_PORT) -> Any:
    """Build the FastMCP server exposing JaegerAI.

    ``run_turn`` defaults to the real ``run_for_voice`` (stdio / in-process).
    When ``bridge`` is provided (HTTP mode), tools call the live BridgeClient
    and do not boot a second model.
    When ``gateway`` is provided, turns route to the canonical Jaeger Gateway.
    """
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    if run_turn is None and bridge is None and gateway is None:
        from jaeger_ai.main import run_for_voice as run_turn  # noqa: PLW0127

    mcp = FastMCP(
        "jaeger",
        host=host,
        port=port,
        streamable_http_path=MCP_HTTP_PATH,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "localhost:*",
                "127.0.0.1:*",
                "[::1]:*",
                "100.74.2.15:*",
                "192.168.64.1:*",
            ],
            allowed_origins=[
                "http://localhost:*",
                "http://127.0.0.1:*",
                "http://100.74.2.15:*",
                "http://192.168.64.1:*",
            ],
        ),
    )

    @mcp.tool()
    @_off_event_loop
    def chat(message: str, session_id: str = "", request_id: str = "",
             allowed_tools: list[str] | None = None, is_subordinate: bool = False) -> str:
        """Send a message to the local JaegerAI agent and return its reply.

        The agent has its own tools, memory, and skills; this drives a full
        turn (it may take a while for a complex request). ``session_id``
        isolates Roundtable members and other concurrent callers so they
        do not collide on the default ``mcp`` session. ``request_id`` is the
        durable gateway/native turn identity and is not the dispatcher key.
        ``allowed_tools`` is an optional enforced grant: [] permits no tools;
        omitted preserves the normal lead policy. Child sessions keep their
        initial grant and cannot expand it on a later request.
        """
        session = (session_id or "").strip() or "mcp"
        if bridge is not None:
            return _bridge_chat(
                bridge, message, session=session, request_id=request_id,
                allowed_tools=allowed_tools, is_subordinate=is_subordinate,
            )
        if gateway is not None:
            res = gateway.turn(session, message)
            if not res.ok:
                raise RuntimeError(f"Gateway turn failed: {res.error or res.status}")
            return res.text
        from jaeger_agent.tool_executor import tool_allowlist
        with tool_allowlist(allowed_tools):
            return _run_chat(
                run_turn,
                client,
                message,
                session_key=session,
                request_id=request_id,
                is_subordinate=is_subordinate,
            )

    if bridge is not None:
        @mcp.tool()
        @_off_event_loop
        def cancel_turn(session_id: str = "", request_id: str = "") -> dict:
            """Request native cancellation. Does not claim the native effect stopped."""
            try:
                bridge.control("cancel", turn_id=request_id, session=session_id)
                return {"ok": True, "requested": True, "confirmed": False, "request_id": request_id}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "requested": False, "confirmed": False, "error": str(exc)}
    elif gateway is not None:
        @mcp.tool()
        @_off_event_loop
        def cancel_turn(session_id: str = "", request_id: str = "") -> dict:
            """Request Gateway turn cancellation."""
            try:
                gateway.cancel(session_id or "mcp", request_id)
                return {"ok": True, "requested": True, "confirmed": False, "request_id": request_id}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "requested": False, "confirmed": False, "error": str(exc)}

    @mcp.tool()
    @_off_event_loop
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
        elif gateway is not None:
            info["gateway"] = getattr(gateway, "base_url", "http://127.0.0.1:8810")
            info["transport"] = "gateway"
        return info

    @mcp.tool()
    @_off_event_loop
    def capability_inventory_tool() -> dict:
        """Return Jaeger's live tool inventory and shared protocol endpoints."""
        return capability_inventory(bridge=bridge)

    @mcp.tool()
    @_off_event_loop
    def finance_summary() -> dict:
        """Return net worth, liquid cash, credit debt, and balances from Monarch Money."""
        from jaeger_ai.features.finance.tools import finance_summary as _fn_summary
        return _fn_summary()

    @mcp.tool()
    @_off_event_loop
    def finance_audit(days: int = 7) -> dict:
        """Run budget pacing, anomaly detection, and spend velocity checks."""
        from jaeger_ai.features.finance.tools import finance_audit as _fn_audit
        return _fn_audit(days=days)

    if bridge is not None:
        @mcp.tool()
        @_off_event_loop
        def bridge_health() -> dict:
            """Health of the live Jaeger instance bridge (no model boot)."""
            return dict(bridge.health())

        @mcp.tool()
        @_off_event_loop
        def bridge_query(what: str, args_json: str = "{}") -> Any:
            """Run a bridge query against the live instance (list/config/identity/...)."""
            return bridge.query(what, _json_args(args_json))

        @mcp.tool()
        @_off_event_loop
        def bridge_command(command: str, args_json: str = "{}") -> Any:
            """Run a bridge command against the live instance."""
            return bridge.command(command, _json_args(args_json))

        @mcp.tool()
        @_off_event_loop
        def list_delegates() -> dict:
            """Delegate catalog: builtin runtimes plus any delegate_* bridge tools."""
            names: list[str] = []
            payload_error = None
            try:
                payload = bridge.query("list_tools")
                names = _tool_names(payload)
            except Exception as exc:  # noqa: BLE001
                payload_error = str(exc)
            builtin: list[str] = []
            registry_error = None
            try:
                from jaeger_agent.delegates import (
                    get_delegate_registry,
                    register_builtin_delegates,
                )
                register_builtin_delegates()
                builtin = [rt.runtime_id for rt in get_delegate_registry().list()]
            except Exception as exc:  # noqa: BLE001
                registry_error = str(exc)
            delegates = sorted({
                *(name for name in names if "delegate" in name.lower()),
                *builtin,
            })
            out: dict[str, object] = {
                "ok": not (payload_error and registry_error),
                "delegates": delegates,
                "tools": names,
                "runtimes": builtin,
            }
            if payload_error:
                out["bridge_error"] = payload_error
            if registry_error:
                out["registry_error"] = registry_error
            return out

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
        from jaeger_ai.features.agentgateway.constants import mcp_token_path

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
        from jaeger_ai.features.webui.adapter.bridge_client import BridgeClient

        instance = instance or default_instance_name()
        bridge = BridgeClient(instance=instance)
        health = bridge.health()
        if health.get("ok"):
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

        # Gateway fallback for HTTP
        from jaeger_ai.core.gateway.client import GatewayTurnClient, GatewayUnavailable
        gw = GatewayTurnClient()
        try:
            gw_probe = gw.probe()
            if gw_probe.get("service") == "jaeger-gateway" or gw_probe.get("component") == "jaeger-gateway":
                server = build_server(None, instance, "gateway", gateway=gw, host=args.host, port=args.port)
                token = resolve_mcp_token()
                import uvicorn

                uvicorn.run(http_app(server, token), host=args.host, port=args.port)
                return 0
        except (GatewayUnavailable, Exception):
            pass

        print(
            f"[jaeger-mcp] Neither live bridge nor canonical Jaeger Gateway (127.0.0.1:8810) is available for {instance}. "
            "Start the Gateway with 'jaeger gateway daemon'.",
            file=sys.stderr,
        )
        return 1

    from jaeger_ai.core.instance.instance import default_instance_name
    from jaeger_ai.features.webui.adapter.bridge_client import BridgeClient

    instance = instance or default_instance_name()
    bridge = BridgeClient(instance=instance)
    health = bridge.health()
    if health.get("ok"):
        model = None
        try:
            ident = bridge.query("identity")
            if isinstance(ident, dict):
                model = ident.get("model")
        except Exception:  # noqa: BLE001
            model = None
        server = build_server(None, instance, model, bridge=bridge)
        server.run()
        return 0

    # Gateway fallback for stdio
    from jaeger_ai.core.gateway.client import GatewayTurnClient, GatewayUnavailable
    gw = GatewayTurnClient()
    try:
        gw_probe = gw.probe()
        if gw_probe.get("service") == "jaeger-gateway" or gw_probe.get("component") == "jaeger-gateway":
            server = build_server(None, instance, "gateway", gateway=gw)
            server.run()
            return 0
    except (GatewayUnavailable, Exception):
        pass

    # Neither bridge nor gateway is running. Truthfully report the Gateway is unavailable,
    # rather than attempting to boot an in-process model that crashes on uninstalled Ollama.
    print(
        f"[jaeger-mcp] Neither live bridge nor canonical Jaeger Gateway (127.0.0.1:8810) is running for {instance}. "
        "Start the Gateway with 'jaeger gateway daemon'.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
