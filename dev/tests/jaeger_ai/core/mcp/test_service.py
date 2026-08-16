from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.mcp import service


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "instance"
    root.mkdir()
    return SimpleNamespace(root=root, mcp_config_path=root / "mcp.json")


def test_configure_lists_and_masks_secrets(layout, monkeypatch):
    monkeypatch.setattr(service, "_runtime", lambda: ({}, {}, False))
    service.configure_server(layout, "search", {
        "command": "npx", "args": ["server"],
        "env": {"API_KEY": "secret", "MODE": "safe"},
    })

    result = service.list_servers(layout)
    assert result["owner"] == "jaeger"
    assert result["servers"][0]["env"] == {"API_KEY": "********", "MODE": "safe"}
    saved = json.loads(layout.mcp_config_path.read_text())
    assert saved["servers"][0]["env"]["API_KEY"] == "secret"
    assert layout.mcp_config_path.stat().st_mode & 0o777 == 0o600


def test_masked_secret_is_preserved_on_update(layout):
    service.configure_server(layout, "search", {"command": "one", "env": {"TOKEN": "secret"}})
    service.configure_server(layout, "search", {"command": "two", "env": {"TOKEN": "********"}})
    saved = json.loads(layout.mcp_config_path.read_text())
    assert saved["servers"][0]["env"]["TOKEN"] == "secret"


def test_toggle_remove_and_validation(layout):
    service.configure_server(layout, "web", {"command": "uvx", "enabled": True})
    assert service.set_server_enabled(layout, "web", False)["enabled"] is False
    assert service.remove_server(layout, "web")["removed"] is True
    with pytest.raises(service.MCPServiceError, match="stdio"):
        service.configure_server(layout, "remote", {"url": "https://example.test"})
    with pytest.raises(service.MCPServiceError, match="server name"):
        service.configure_server(layout, "../bad", {"command": "x"})


def test_live_tool_inventory_is_truthful(layout, monkeypatch):
    spec = SimpleNamespace(qualified_name="mcp:web/fetch", agent_name="mcp__web__fetch", server_name="web",
                           description="Fetch", input_schema={"properties": {"url": {}}})
    service.configure_server(layout, "web", {"command": "uvx"})
    monkeypatch.setattr(service, "_runtime", lambda: ({"web": [spec]}, {}, True))
    result = service.list_tools(layout)
    assert result["tools"][0]["name"] == "mcp__web__fetch"
    assert result["tools"][0]["qualified_name"] == "mcp:web/fetch"
    assert result["tools"][0]["schema_summary"] == [{
        "name": "url", "type": "unknown", "required": False, "description": "",
    }]
    assert result["unavailable_servers"] == []
