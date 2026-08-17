from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.mcp import service


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "instance"
    root.mkdir()
    credentials = root / "credentials"
    credentials.mkdir()
    return SimpleNamespace(root=root, mcp_config_path=root / "mcp.json",
                           credentials_dir=credentials)


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
    assert saved["servers"][0]["env"]["API_KEY"] == {
        "secret_ref": "mcp.search.API_KEY",
    }
    assert (layout.credentials_dir / "mcp.search.API_KEY").read_text().strip() == "secret"
    assert layout.mcp_config_path.stat().st_mode & 0o777 == 0o600


def test_masked_secret_is_preserved_on_update(layout):
    service.configure_server(layout, "search", {"command": "one", "env": {"TOKEN": "secret"}})
    service.configure_server(layout, "search", {"command": "two", "env": {"TOKEN": "********"}})
    saved = json.loads(layout.mcp_config_path.read_text())
    assert saved["servers"][0]["env"]["TOKEN"] == {
        "secret_ref": "mcp.search.TOKEN",
    }


def test_http_configuration_masks_and_resolves_headers(layout, monkeypatch):
    monkeypatch.setattr(service, "_runtime", lambda: ({}, {}, False))
    service.configure_server(layout, "remote", {
        "url": "https://mcp.example.test/v1",
        "headers": {"Authorization": "Bearer secret", "X-Mode": "safe"},
    })

    listed = service.list_servers(layout)["servers"][0]
    assert listed["transport"] == "http"
    assert listed["url"] == "https://mcp.example.test/v1"
    assert listed["headers"] == {"Authorization": "********", "X-Mode": "********"}
    saved = json.loads(layout.mcp_config_path.read_text())["servers"][0]
    assert saved["headers"]["Authorization"] == {
        "secret_ref": "mcp.remote.header.Authorization",
    }
    assert service.resolve_server_headers(layout, saved) == {
        "Authorization": "Bearer secret", "X-Mode": "safe",
    }

    service.configure_server(layout, "remote", {
        "url": "https://mcp.example.test/v2",
        "headers": {"Authorization": "********"},
    })
    saved = json.loads(layout.mcp_config_path.read_text())["servers"][0]
    assert saved["headers"]["Authorization"] == {
        "secret_ref": "mcp.remote.header.Authorization",
    }


def test_legacy_inline_secret_is_migrated_explicitly(layout):
    layout.mcp_config_path.write_text(json.dumps({"servers": [{
        "name": "legacy", "command": "server", "env": {"PASSWORD": "old-secret"},
    }]}))
    assert service.migrate_inline_secrets(layout) is True
    saved = json.loads(layout.mcp_config_path.read_text())
    assert saved["servers"][0]["env"]["PASSWORD"] == {
        "secret_ref": "mcp.legacy.PASSWORD",
    }
    assert "old-secret" not in layout.mcp_config_path.read_text()


def test_resolve_server_env_fails_closed_for_missing_credential(layout):
    with pytest.raises(service.MCPServiceError, match="missing MCP credential"):
        service.resolve_server_env(layout, {"env": {
            "TOKEN": {"secret_ref": "mcp.missing.TOKEN"},
        }})


def test_toggle_remove_and_validation(layout, monkeypatch):
    service.configure_server(layout, "web", {
        "command": "uvx", "enabled": True, "env": {"TOKEN": "remove-me"},
    })
    credential = layout.credentials_dir / "mcp.web.TOKEN"
    assert credential.exists()
    assert service.set_server_enabled(layout, "web", False)["enabled"] is False
    monkeypatch.setattr(service, "_runtime", lambda: ({}, {}, False))
    assert service.list_servers(layout)["servers"][0]["status"] == "disabled"
    assert service.remove_server(layout, "web")["removed"] is True
    assert not credential.exists()
    with pytest.raises(service.MCPServiceError, match="exactly one"):
        service.configure_server(layout, "remote", {
            "url": "https://example.test/mcp", "command": "uvx",
        })
    with pytest.raises(service.MCPServiceError, match="must use https"):
        service.configure_server(layout, "remote", {"url": "http://example.test/mcp"})
    with pytest.raises(service.MCPServiceError, match="embedded credentials"):
        service.configure_server(layout, "remote", {"url": "https://user:pass@example.test/mcp"})
    with pytest.raises(service.MCPServiceError, match="header name"):
        service.configure_server(layout, "remote", {
            "url": "https://example.test/mcp", "headers": {"Bad Header": "value"},
        })
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


def test_mcp_tool_results_redact_configured_credentials():
    from jaeger_ai.plugins.mcp.client import _redact_known_secrets

    secret = "configured-secret-value"
    payload = {
        "text": f"server echoed {secret}",
        "content": [{"type": "text", "text": secret}],
    }
    redacted = _redact_known_secrets(payload, {secret})
    assert secret not in json.dumps(redacted)
    assert redacted["text"] == "server echoed ********"


def test_mcp_connection_errors_never_expose_configured_credentials(
    tmp_path, monkeypatch, capsys
):
    from jaeger_ai.plugins.mcp import client

    secret = "opaque-connection-secret"
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"servers": [{
        "name": "broken",
        "command": "fixture",
        "env": {"API_KEY": secret},
    }]}))
    monkeypatch.setattr(
        client.MCPRegistry,
        "add_server",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"server rejected {secret}")
        ),
    )
    try:
        client.init_from_config(config)
        assert secret not in json.dumps(client.connection_errors())
        assert secret not in capsys.readouterr().out
    finally:
        client.shutdown_global()
