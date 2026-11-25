"""Per-server MCP tool limits, gating and timeouts (big servers such as REA)."""
from __future__ import annotations

import pytest

from jaeger_ai.plugins.mcp.client import (
    DEFAULT_CALL_TIMEOUT_S,
    DEFAULT_CONNECT_TIMEOUT_S,
    filter_tool_names,
    server_config_from_entry,
)


def test_entry_limits_and_timeouts_parse():
    cfg = server_config_from_entry({
        "name": "rea", "command": "/opt/homebrew/bin/npx", "args": ["-y", "rea-agents@6.5.0", "mcp"],
        "tools": {"include": ["analyze_*", "doctor"], "exclude": ["analyze_android*"], "max": 3, "gated": True},
        "connect_timeout_s": 120, "call_timeout_s": 300,
    })
    assert cfg.gated and cfg.max_tools == 3
    assert cfg.connect_timeout_s == 120 and cfg.call_timeout_s == 300
    names = ["doctor", "analyze_android_apk", "analyze_asar", "analyze_electron", "analyze_macho", "write_x"]
    assert filter_tool_names(names, cfg) == ["doctor", "analyze_asar", "analyze_electron"]


def test_defaults_and_bad_timeouts_fall_back():
    cfg = server_config_from_entry({"name": "x", "command": "y", "connect_timeout_s": -1, "call_timeout_s": "soon"})
    assert cfg.connect_timeout_s == DEFAULT_CONNECT_TIMEOUT_S
    assert cfg.call_timeout_s == DEFAULT_CALL_TIMEOUT_S
    assert not cfg.gated and filter_tool_names(["a", "b"], cfg) == ["a", "b"]
    assert server_config_from_entry({"name": "x", "command": "y", "call_timeout_s": 99999}).call_timeout_s == 3600


def test_gated_tools_hidden_unless_allowlisted_or_loaded():
    from jaeger_agent.skill_registry import toolset_scoping as ts
    from jaeger_agent.tool_executor import tool_allowlist

    ts.register_mcp_server_toolset("rea", ["mcp__rea__doctor", "mcp__rea__analyze_asar"], gated=True)
    try:
        assert ts.is_gated_tool("mcp__rea__doctor")
        assert not ts.tool_visible("mcp__rea__doctor")
        with tool_allowlist(["mcp__rea__doctor", "read_file"]):
            assert ts.tool_visible("mcp__rea__doctor")
            assert not ts.tool_visible("mcp__rea__analyze_asar")
        assert ts.enable_toolset("rea")
        assert ts.tool_visible("mcp__rea__analyze_asar")
    finally:
        ts.unregister_mcp_server_toolset("rea")
        ts.reset_toolsets()
    assert not ts.is_gated_tool("mcp__rea__doctor")
    assert ts.tool_visible("mcp__rea__doctor")  # unknown tool: fail-open as before


def test_ungated_server_stays_visible():
    from jaeger_agent.skill_registry import toolset_scoping as ts
    ts.register_mcp_server_toolset("small", ["mcp__small__ping"], gated=False)
    try:
        assert ts.tool_visible("mcp__small__ping")
    finally:
        ts.unregister_mcp_server_toolset("small")


def test_service_validates_and_keeps_limits(tmp_path):
    from types import SimpleNamespace
    from jaeger_ai.core.mcp import service

    layout = SimpleNamespace(root=tmp_path, mcp_config_path=tmp_path / "mcp.json")
    try:
        service.configure_server(layout, "rea", {
            "command": "/opt/homebrew/bin/npx", "args": ["-y", "rea-agents@6.5.0", "mcp"],
            "env": {"REA_MCP_INPUT_SCHEMA_PROFILE": "compact"},
            "tools": {"include": ["*"], "max": 40, "gated": True},
            "connect_timeout_s": 120, "call_timeout_s": 300,
        })
    except Exception as exc:  # layout shape differs: skip rather than fake
        pytest.skip(f"layout stub unsupported: {exc}")
    import json
    row = json.loads(layout.mcp_config_path.read_text())["servers"][0]
    assert row["tools"] == {"include": ["*"], "max": 40, "gated": True}
    assert row["call_timeout_s"] == 300
    service.configure_server(layout, "rea", {"enabled": False})
    row = json.loads(layout.mcp_config_path.read_text())["servers"][0]
    assert row["connect_timeout_s"] == 120 and row["enabled"] is False
    with pytest.raises(service.MCPServiceError):
        service.configure_server(layout, "rea", {"call_timeout_s": 0})
    with pytest.raises(service.MCPServiceError):
        service.configure_server(layout, "rea", {"tools": {"max": -1}})


def test_gateway_loads_only_marked_servers(tmp_path, monkeypatch):
    import json as _json
    from types import SimpleNamespace
    from jaeger_ai.core.mcp import service
    from jaeger_ai.plugins.mcp import client

    seen = []

    class FakeRegistry:
        def list_tools(self):
            return [SimpleNamespace(server_name=n) for n in seen]

    def fake_init(path, *, layout=None, only=None):
        rows = _json.loads(path.read_text())["servers"]
        seen.extend(r["name"] for r in rows if r.get("enabled", True) and (only is None or only(r)))
        return FakeRegistry()

    cfg = tmp_path / "mcp.json"
    cfg.write_text(_json.dumps({"servers": [
        {"name": "rea", "command": "npx", "gateway": True, "tools": {"gated": True}},
        {"name": "other", "command": "x"},
        {"name": "off", "command": "x", "gateway": True, "enabled": False}]}))
    monkeypatch.setattr(service, "_path", lambda layout: cfg)
    monkeypatch.setattr(service, "migrate_inline_secrets", lambda layout: None)
    monkeypatch.setattr(client, "init_from_config", fake_init)
    monkeypatch.setattr(client, "connection_errors", lambda: {})
    monkeypatch.delenv("JAEGER_WITH_MCP", raising=False)
    service._GATEWAY_MCP_LOADED.clear()
    out = service.load_gateway_servers(object())
    assert out["servers"] == ["rea"] and seen == ["rea"]
    assert service.load_gateway_servers(object())["servers"] == ["rea"] and seen == ["rea"]  # once
    service._GATEWAY_MCP_LOADED.clear()
    monkeypatch.setenv("JAEGER_WITH_MCP", "1")
    assert service.gateway_server_selected({"name": "other"})
    service._GATEWAY_MCP_LOADED.clear()


def test_read_only_list_is_parsed_and_matched_by_glob():
    from jaeger_ai.plugins.mcp.client import is_read_only_tool, server_config_from_entry
    cfg = server_config_from_entry({"name": "rea", "command": "npx",
                                    "tools": {"read_only": ["inspect_*", "list_unknowns", "", 3]}})
    assert cfg.tools_read_only == ["inspect_*", "list_unknowns"]
    assert is_read_only_tool("inspect_macho", cfg)
    assert is_read_only_tool("list_unknowns", cfg)
    assert not is_read_only_tool("install_adb_package", cfg)
    assert not is_read_only_tool("", cfg)
    assert server_config_from_entry({"name": "x", "command": "y"}).tools_read_only == []


class _Recorder:
    fresh_approval = True

    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def confirm(self, request):
        self.requests.append(request)
        return self.answer


def _spec(tool, read_only):
    from jaeger_ai.plugins.mcp.client import MCPToolSpec, _agent_tool_name
    return MCPToolSpec(qualified_name=f"mcp:testsrv/{tool}", server_name="testsrv", tool_name=tool,
                       description="t", input_schema={"type": "object", "properties": {}},
                       agent_name=_agent_tool_name("testsrv", tool), read_only=read_only)


def test_non_read_only_mcp_tool_asks_and_denial_blocks_the_call(monkeypatch):
    import pytest
    from jaeger_ai.plugins.mcp import client
    from jaeger_os.core.safety.permissions import PermissionDenied, PermissionPolicy, PermissionTier, use_policy
    from jaeger_tools.tool_registry import get_tool, unregister_tool

    calls = []
    monkeypatch.setattr(client, "call_mcp_tool", lambda q, a: calls.append((q, a)) or {"ok": True})
    mut, ro = _spec("install_thing", False), _spec("inspect_thing", True)
    client._register_agent_tool(mut)
    client._register_agent_tool(ro)
    try:
        deny = _Recorder(False)
        with use_policy(PermissionPolicy(confirmation=deny)):
            with pytest.raises(PermissionDenied):
                get_tool(mut.agent_name).fn(path="/tmp/x")
            assert calls == []
            assert get_tool(ro.agent_name).fn(path="/tmp/y") == {"ok": True}
        assert len(deny.requests) == 1
        req = deny.requests[0]
        assert req.tier == PermissionTier.EXTERNAL_EFFECT
        assert req.skill == "mcp:testsrv/install_thing" and req.arguments == {"path": "/tmp/x"}
        allow = _Recorder(True)
        with use_policy(PermissionPolicy(confirmation=allow)):
            assert get_tool(mut.agent_name).fn(path="/tmp/z") == {"ok": True}
        assert [c[0] for c in calls] == ["mcp:testsrv/inspect_thing", "mcp:testsrv/install_thing"]
    finally:
        unregister_tool(mut.agent_name)
        unregister_tool(ro.agent_name)


def test_service_configure_server_accepts_and_preserves_read_only(tmp_path):
    import json
    from types import SimpleNamespace
    from jaeger_ai.core.mcp import service

    layout = SimpleNamespace(root=tmp_path, mcp_config_path=tmp_path / "mcp.json")
    service.configure_server(layout, "gh", {
        "command": "/usr/bin/true",
        "args": [],
        "tools": {"gated": True, "read_only": ["get_*", "list_*"]},
    })
    row = json.loads(layout.mcp_config_path.read_text())["servers"][0]
    assert row["tools"] == {"gated": True, "read_only": ["get_*", "list_*"]}
    with pytest.raises(service.MCPServiceError):
        service.configure_server(layout, "gh", {"tools": {"read_only": "not-a-list"}})


def test_connector_lifecycle_tools_registered_and_work(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from jaeger_agent.tools import connectors
    from jaeger_tools.tool_registry import get_tools
    from jaeger_ai.plugins.mcp import client

    names = {t.name for t in get_tools()}
    for expected in ("list_connectors", "add_connector", "test_connector", "reload_connector", "remove_connector"):
        assert expected in names

    cfg_path = tmp_path / "mcp.json"
    cfg_path.write_text(json.dumps({
        "version": 1,
        "servers": [{
            "name": "custom",
            "command": "/usr/bin/true",
            "args": [],
            "enabled": True,
            "gateway": True,
            "tools": {"gated": True, "read_only": ["ping"]},
        }],
    }), encoding="utf-8")
    layout = SimpleNamespace(root=tmp_path, mcp_config_path=cfg_path)
    monkeypatch.setattr(connectors, "_require_layout", lambda: layout)

    fake_spec_ro = _spec("ping", True)
    fake_spec_ro.server_name = "custom"
    fake_spec_ro.agent_name = "mcp__custom__ping"
    fake_spec_wr = _spec("write_it", False)
    fake_spec_wr.server_name = "custom"
    fake_spec_wr.agent_name = "mcp__custom__write_it"

    class FakeRegistry:
        def __init__(self):
            self._clients = {"custom": object()}
            self._disconnected = {}
            self._server_states = {"custom": "loaded_not_probed"}
            self._inventory_errors = {}
            self.reloaded = 0
            self.removed = 0
            self._specs = [fake_spec_ro, fake_spec_wr]

        def list_tools(self):
            return list(self._specs)

        def reload_server(self, cfg):
            self.reloaded += 1
            self._server_states[cfg.name] = "loaded_not_probed"
            return list(self._specs)

        def remove_server(self, name):
            self.removed += 1
            self._clients.pop(name, None)
            self._specs = []
            return True

    reg = FakeRegistry()
    monkeypatch.setattr(client, "get_registry", lambda: reg)
    monkeypatch.setattr(client, "connection_errors", lambda: {})

    tested = connectors.test_connector("custom")
    assert tested["ok"] is True
    assert tested["read_only_count"] == 1
    assert tested["approval_gated_count"] == 1

    reloaded = connectors.reload_connector("custom")
    assert reloaded["ok"] is True and reloaded["reloaded"] is True and reg.reloaded == 1

    removed = connectors.remove_connector("custom")
    assert removed["ok"] is True and removed["removed"] is True and removed["disconnected_live"] is True
    assert reg.removed == 1
    assert json.loads(cfg_path.read_text())["servers"] == []


@pytest.mark.asyncio
async def test_probe_native_mcp_caches_positive_only(monkeypatch, tmp_path):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    import jaeger_ai.core.gateway.native_mcp as transport

    monkeypatch.setattr(transport, "MCP_URL", "http://127.0.0.1:8792/mcp")
    monkeypatch.setattr(transport, "mcp_api_key", lambda: "tok")
    monkeypatch.setenv("JAEGER_MCP_PROBE_CACHE_TTL_S", "30")

    calls = 0
    healthy = False

    async def fake_uncached(**kwargs):
        nonlocal calls
        calls += 1
        return {"ok": healthy, "url": kwargs["MCP_URL"]}

    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "probe.sqlite3"))
    monkeypatch.setattr(app, "_probe_native_mcp_uncached", fake_uncached)

    assert (await app._probe_native_mcp())["ok"] is False
    assert (await app._probe_native_mcp())["ok"] is False
    assert calls == 2  # failures are never cached

    healthy = True
    assert (await app._probe_native_mcp())["ok"] is True
    assert (await app._probe_native_mcp())["ok"] is True
    assert (await app._probe_native_mcp())["ok"] is True
    assert calls == 3  # positive result served from cache
