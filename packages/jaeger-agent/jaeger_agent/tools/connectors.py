"""Connectors: the agent's view of its MCP servers, and how it adds one.

  • list_connectors()      — every configured MCP server, live status, tool count
  • add_connector(...)     — add a new stdio/URL MCP server and connect it now

Adding goes through the reviewed ``core.mcp.service`` path. A new definition is
staged disabled and refuses credential content (tokens, auth headers, secret
arguments). It is then enabled for startup and connected in this process, so its
``mcp__<name>__*`` tools work in the next step without a restart. A server that
needs a token gets a launcher script that reads the token at runtime (see
scripts/connectors/github-mcp.sh). The agent never writes the token itself.
"""

from __future__ import annotations

import json
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import _require_layout


def _service():
    from jaeger_ai.core.mcp import service
    return service


@register_tool_from_function(name="list_connectors", side_effect="read")
def list_connectors() -> dict:
    """List your connected MCP servers (connectors): name, transport, whether
    it is enabled and connected, its tool count and its tool prefix. Use this
    to answer "what connectors / MCP servers do you have", not a skill or a
    config file guess."""
    svc = _service()
    lay = _require_layout()
    data = svc.list_servers(lay)
    raw = {r.get("name"): r for r in json.loads(svc._path(lay).read_text()).get("servers", [])} \
        if svc._path(lay).exists() else {}
    rows = []
    for r in data.get("servers", []):
        row = raw.get(r["name"], {})
        rows.append({
            "name": r["name"], "transport": r["transport"], "enabled": r["enabled"],
            "status": r["status"], "tool_count": r["tool_count"],
            "starts_with_gateway": svc.gateway_server_selected(row),
            "tool_prefix": f"mcp__{r['name']}__",
            "gated": bool((row.get("tools") or {}).get("gated")),
            "error": r.get("error"),
        })
    return {"ok": True, "config": str(svc._path(lay)), "connectors": rows,
            "how_to_add": "Call add_connector(name, command+args or url). It stages the server "
                          "disabled with no credentials, enables it, and connects it now. Tokens go "
                          "in a launcher script that reads them at runtime, never in the call.",
            "gated_note": "Gated connectors load on demand: tool_search or load_tools, then call mcp__<name>__<tool>."}


@register_tool_from_function(name="add_connector", side_effect="write")
def add_connector(name: str, command: str = "", args: list[str] | None = None,
                  url: str = "", connect_now: bool = True) -> dict:
    """Add a new MCP server (connector) and connect it. Give either
    ``command`` (+ ``args``) for a stdio server, e.g. command="npx",
    args=["-y", "@modelcontextprotocol/server-everything"], or ``url`` for an
    HTTP server. Credentials are refused here: for a server that needs a token,
    point ``command`` at a launcher script that reads it at runtime. The new
    server's tools appear as mcp__<name>__<tool> (gated, load on demand)."""
    svc = _service()
    lay = _require_layout()
    if bool(command) == bool(url):
        return {"ok": False, "error": "give exactly one of command or url"}
    definition = {"name": name, "url": url} if url else \
        {"name": name, "command": command, "args": list(args or [])}
    try:
        staged = svc.stage_disabled_server(lay, definition, expected_revision=svc.configuration_revision(lay))
        svc.set_startup_enabled(lay, staged["name"], True, expected_revision=staged["config_revision"])
        from jaeger_ai.core.instance.atomic_files import mutate_json

        def mark(data):
            return {**data, "servers": [{**r, "gateway": True} if isinstance(r, dict) and r.get("name") == staged["name"]
                                        else r for r in data.get("servers", [])]}
        mutate_json(svc._path(lay), mark, expected_revision=svc.configuration_revision(lay))
    except Exception as exc:  # noqa: BLE001 — reviewed service errors are user-facing
        return {"ok": False, "error": str(exc)}
    out: dict[str, Any] = {"ok": True, "name": staged["name"], "saved": str(svc._path(lay)),
                           "starts_with_gateway": True, "connected": False}
    if not connect_now:
        return out
    try:
        from jaeger_ai.plugins.mcp import client
        entry = next(r for r in json.loads(svc._path(lay).read_text())["servers"] if r.get("name") == staged["name"])
        cfg = client.server_config_from_entry(entry, env=svc.resolve_server_env(lay, entry),
                                              headers=svc.resolve_server_headers(lay, entry))
        registry = client.get_registry()
        if registry is None:
            registry = client.init_from_config(svc._path(lay), layout=lay, only=lambda e: e.get("name") == staged["name"])
            specs = [s for s in registry.list_tools() if s.server_name == staged["name"]]
        else:
            specs = registry.add_server(cfg)
        out.update(connected=bool(specs), tool_count=len(specs),
                   tools=[s.agent_name or f"mcp__{staged['name']}__{s.tool_name}" for s in specs][:40],
                   next=("Connected. Your tool list was fixed when this turn started, so call the new "
                         "tools in THIS turn through execute_with_tools, e.g. code: import jaeger_tools as jt; "
                         f"print(jt.call('{(specs[0].agent_name if specs else 'mcp__' + staged['name'] + '__<tool>')}', arg=value)). "
                         "From the next message on they are callable directly. Do not read mcp.json."))
    except Exception as exc:  # noqa: BLE001
        out.update(connect_error=f"{type(exc).__name__}: {exc}",
                   note="Saved and enabled; it will connect at the next gateway start.")
    return out
