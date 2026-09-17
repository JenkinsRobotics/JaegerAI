from __future__ import annotations

import asyncio

from jaeger_ai.features.agentgateway import verify


def test_verify_native_services_combines_protocol_results(monkeypatch):
    async def mcp(_url):
        return {"ok": True, "tools": ["bridge_health"]}

    monkeypatch.setattr(verify, "_verify_mcp", mcp)
    monkeypatch.setattr(verify, "_verify_a2a", lambda _url: {"ok": True, "name": "Jaeger"})

    result = asyncio.run(verify.verify_native_services())

    assert result["ok"] is True
    assert result["mcp"]["tools"] == ["bridge_health"]
    assert result["a2a"]["name"] == "Jaeger"


def test_verify_native_services_reports_one_protocol_failure(monkeypatch):
    async def broken(_url):
        raise RuntimeError("MCP unavailable")

    monkeypatch.setattr(verify, "_verify_mcp", broken)
    monkeypatch.setattr(verify, "_verify_a2a", lambda _url: {"ok": True})

    result = asyncio.run(verify.verify_native_services())

    assert result["ok"] is False
    assert result["mcp"]["error"] == "MCP unavailable"
    assert result["a2a"]["ok"] is True
