"""JROS as an MCP server — let editors/clients (Claude Code, Cursor, Zed)
drive the agent as a tool. The other half of MCP: JROS is already an MCP
*client* (``plugins/mcp``); this exposes JROS *to* MCP.

Opt-in stdio, no daemon: the MCP client spawns this process; nothing is
always-on. It boots the agent in-process and exposes a small tool surface
over the MCP stdio transport. All agent/boot output is forced to stderr so
the MCP JSON-RPC stream on stdout stays clean.

Run: ``jaeger mcp`` (or ``python -m jaeger_os.interfaces.mcp_server``).
"""

from __future__ import annotations

import contextlib
import sys
from typing import Any, Callable

# Turn fn: (client, message, session_key=...) -> {"text": str, "error": str|None}
TurnFn = Callable[..., dict]


def _run_chat(run_turn: TurnFn, client: Any, message: str) -> str:
    """Drive one turn for the ``chat`` MCP tool. Agent/tool/model output is
    forced to stderr so it never corrupts the MCP JSON-RPC stdout stream."""
    with contextlib.redirect_stdout(sys.stderr):
        out = run_turn(client, message, session_key="mcp")
    if out.get("error"):
        return f"(agent error: {out['error']})"
    return out.get("text") or ""


def build_server(client: Any, instance: str, model: str | None,
                 run_turn: TurnFn | None = None) -> Any:
    """Build the FastMCP server exposing JROS. ``run_turn`` defaults to the
    real ``run_for_voice``; injectable for tests."""
    from mcp.server.fastmcp import FastMCP

    if run_turn is None:
        from jaeger_os.main import run_for_voice as run_turn  # noqa: PLW0127

    mcp = FastMCP("jros")

    @mcp.tool()
    def chat(message: str) -> str:
        """Send a message to the local JROS agent and return its reply.

        The agent has its own tools, memory, and skills; this drives a full
        turn (it may take a while for a complex request)."""
        return _run_chat(run_turn, client, message)

    @mcp.tool()
    def agent_info() -> dict:
        """Return the JROS agent's instance name and loaded model."""
        return {"instance": instance, "model": model or "unknown"}

    return mcp


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    from jaeger_os.core.instance.instance import default_instance_name
    from jaeger_os.interfaces.bridge import _model_name
    from jaeger_os.main import boot_for_tui

    instance = (argv[0] if argv else None) or default_instance_name()

    # Boot the agent with all noise on stderr; MCP owns stdout.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            boot = boot_for_tui(instance_name=instance)
        except Exception as exc:  # noqa: BLE001
            print(f"[jros-mcp] boot failed: {exc}", file=sys.stderr)
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
