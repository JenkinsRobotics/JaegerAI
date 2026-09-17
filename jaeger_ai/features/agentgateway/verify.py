"""Protocol-level acceptance checks for Jaeger's native agent surfaces."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import Any

from jaeger_ai.contract.ports import A2A_URL, MCP_HTTP_URL


async def _verify_mcp(url: str) -> dict[str, Any]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = sorted(tool.name for tool in listed.tools)
            health = await session.call_tool("bridge_health")
            inventory = await session.call_tool("capability_inventory")
    return {
        "ok": not health.isError and not inventory.isError,
        "server": initialized.serverInfo.name,
        "tools": names,
        "bridge_health": not health.isError,
        "capability_inventory": not inventory.isError,
        "url": url,
    }


def _verify_a2a(url: str, timeout: float = 5.0) -> dict[str, Any]:
    card_url = f"{url.rstrip('/')}/.well-known/agent-card.json"
    request = urllib.request.Request(card_url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        document = json.load(response)
    interfaces = document.get("supportedInterfaces") or document.get("supported_interfaces") or []
    advertised = [item.get("url") for item in interfaces if isinstance(item, dict)]
    return {
        "ok": response.status == 200 and document.get("name") == "Jaeger",
        "name": document.get("name"),
        "advertised_urls": advertised,
        "url": url,
    }


async def verify_native_services(
    *, mcp_url: str = MCP_HTTP_URL, a2a_url: str = A2A_URL
) -> dict[str, Any]:
    """Verify both native protocols and return one machine-readable result."""
    result: dict[str, Any] = {"ok": False}
    try:
        result["mcp"] = await _verify_mcp(mcp_url)
    except Exception as exc:  # noqa: BLE001 - verifier must report all failures
        result["mcp"] = {"ok": False, "url": mcp_url, "error": str(exc)}
    try:
        result["a2a"] = await asyncio.to_thread(_verify_a2a, a2a_url)
    except Exception as exc:  # noqa: BLE001 - verifier must report all failures
        result["a2a"] = {"ok": False, "url": a2a_url, "error": str(exc)}
    result["ok"] = bool(result["mcp"].get("ok") and result["a2a"].get("ok"))
    return result


def verify_native_services_sync(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(verify_native_services(**kwargs))


__all__ = ["verify_native_services", "verify_native_services_sync"]
