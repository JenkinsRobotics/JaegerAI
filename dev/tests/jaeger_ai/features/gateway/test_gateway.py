"""Jaeger-owned Agentgateway config and locator. No live binary spawn."""

from __future__ import annotations

import hashlib
from pathlib import Path

from jaeger_ai.features.agentgateway.config import config_is_stale, default_config, ensure_config
from jaeger_ai.features.agentgateway.constants import (
    A2A_BACKEND_PORT,
    A2A_GATEWAY_PORT,
    MCP_GATEWAY_PORT,
    MCP_HTTP_PORT,
)
from jaeger_ai.features.agentgateway.service import locate_binary, status


def test_default_config_targets_jaeger_not_archive_ports(tmp_path: Path) -> None:
    cfg = default_config(tmp_path)
    dumped = str(cfg)
    assert "ares" not in dumped.lower()
    assert ":8788" not in dumped
    assert cfg["mcp"]["port"] == MCP_GATEWAY_PORT
    target = cfg["mcp"]["targets"][0]
    assert target["name"] == "jaeger"
    assert target["mcp"]["host"] == f"http://127.0.0.1:{MCP_HTTP_PORT}/mcp"
    assert cfg["binds"][0]["port"] == A2A_GATEWAY_PORT
    backends = [
        backend["host"]
        for listener in cfg["binds"][0]["listeners"]
        for route in listener["routes"]
        for backend in route["backends"]
    ]
    assert backends == [f"127.0.0.1:{A2A_BACKEND_PORT}"] * 3
    policy = cfg["mcp"]["policies"]["apiKey"]
    token = (tmp_path / "gateway" / "mcp.token").read_text().strip()
    assert policy["mode"] == "strict"
    assert policy["keys"] == [{
        "keyHash": f"sha256:{hashlib.sha256(token.encode()).hexdigest()}"
    }]
    for route in cfg["binds"][0]["listeners"][0]["routes"]:
        assert route["policies"]["apiKey"]["mode"] == "strict"


def test_ensure_config_writes_token_file_without_embedding_it(tmp_path: Path) -> None:
    path = ensure_config(tmp_path)
    text = path.read_text(encoding="utf-8")
    token = (tmp_path / "gateway" / "client.token").read_text(encoding="utf-8").strip()
    mcp_token = (tmp_path / "gateway" / "mcp.token").read_text(encoding="utf-8").strip()
    assert token
    assert token not in text
    assert mcp_token not in text
    assert hashlib.sha256(mcp_token.encode()).hexdigest() in text
    assert "ares" not in text.lower()
    assert path.stat().st_mode & 0o077 == 0


def test_stale_archive_config_is_rewritten(tmp_path: Path) -> None:
    gateway = tmp_path / "gateway"
    gateway.mkdir()
    stale = gateway / "config.yaml"
    stale.write_text("mcp:\n  port: 8811\n  targets:\n  - name: system\n    stdio:\n      cmd: /tmp/ares\n")
    assert config_is_stale(stale)
    path = ensure_config(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "ares" not in text.lower()
    assert f"127.0.0.1:{MCP_HTTP_PORT}/mcp" in text


def test_security_migration_preserves_non_jaeger_targets(tmp_path: Path) -> None:
    gateway = tmp_path / "gateway"
    gateway.mkdir()
    path = gateway / "config.yaml"
    path.write_text(
        "mcp:\n  port: 8811\n  targets:\n"
        "  - name: jaeger\n    mcp:\n      host: http://127.0.0.1:8792/mcp\n"
        "  - name: custom\n    stdio:\n      cmd: /bin/custom\n"
        "binds:\n- port: 8812\n  listeners:\n  - routes:\n"
        "    - backends:\n      - host: 127.0.0.1:8796\n",
        encoding="utf-8",
    )

    ensure_config(tmp_path)

    text = path.read_text(encoding="utf-8")
    assert "name: custom" in text
    assert "apiKey:" in text


def test_locate_binary_ignores_non_jaeger_user_link(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    assert locate_binary(tmp_path) is None
    row = status(tmp_path)
    assert row["running"] is False
    assert row["ports"]["mcp_gateway"] == 8811
    assert row["ports"]["a2a_gateway"] == 8812


def test_config_presents_caller_tokens_to_jaeger_backends_by_env_reference(tmp_path: Path) -> None:
    """agentgateway authenticates to Jaeger's MCP/A2A servers (caller auth is
    mandatory there) using env-expanded backendAuth, never an inline value."""
    from jaeger_ai.features.agentgateway.config import A2A_BACKEND_TOKEN_ENV, MCP_BACKEND_TOKEN_ENV

    cfg = default_config(tmp_path)
    target = cfg["mcp"]["targets"][0]
    assert target["policies"]["backendAuth"] == {"key": f"${MCP_BACKEND_TOKEN_ENV}"}
    for route in cfg["binds"][0]["listeners"][0]["routes"]:
        for backend in route["backends"]:
            assert backend["policies"]["backendAuth"] == {"key": f"${A2A_BACKEND_TOKEN_ENV}"}


def test_config_without_backend_auth_is_stale(tmp_path: Path) -> None:
    path = ensure_config(tmp_path)
    assert not config_is_stale(path)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("backendAuth", "x-removed"), encoding="utf-8")
    assert config_is_stale(path)
    ensure_config(tmp_path)
    assert not config_is_stale(path)


def test_start_hands_backend_tokens_to_the_child_env_only(tmp_path: Path, monkeypatch) -> None:
    from jaeger_ai.core.gateway import caller_auth
    from jaeger_ai.features.agentgateway import service
    from jaeger_ai.features.agentgateway.config import A2A_BACKEND_TOKEN_ENV, MCP_BACKEND_TOKEN_ENV

    binary = tmp_path / "agentgateway"
    binary.write_text("#!/bin/sh\n")
    seen = {}

    class _Proc:
        pid = 4242

    def fake_popen(argv, env, **kwargs):
        seen["env"] = env
        return _Proc()

    monkeypatch.setattr(service, "locate_binary", lambda root=None: binary)
    monkeypatch.setattr(service, "read_pid", lambda root=None: None)
    monkeypatch.setattr(service.subprocess, "Popen", fake_popen)
    monkeypatch.delenv(MCP_BACKEND_TOKEN_ENV, raising=False)
    service.start(tmp_path)
    assert seen["env"][MCP_BACKEND_TOKEN_ENV] == caller_auth.read_token("mcp")
    assert seen["env"][A2A_BACKEND_TOKEN_ENV] == caller_auth.read_token("a2a")
    assert MCP_BACKEND_TOKEN_ENV not in __import__("os").environ
    text = (tmp_path / "gateway" / "config.yaml").read_text(encoding="utf-8")
    assert caller_auth.read_token("mcp") not in text
    assert caller_auth.read_token("a2a") not in text


def test_start_refuses_without_caller_tokens(tmp_path: Path, monkeypatch) -> None:
    import pytest

    from jaeger_ai.features.agentgateway import service

    empty = tmp_path / "no-tokens"
    empty.mkdir(mode=0o700)
    monkeypatch.setenv("JAEGER_CALLER_TOKEN_DIR", str(empty))
    with pytest.raises(service.GatewayError, match="caller token"):
        service.backend_token_env()
