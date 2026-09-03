"""Jaeger-owned Agentgateway config and locator. No live binary spawn."""

from __future__ import annotations

from pathlib import Path

from jaeger_ai.features.gateway.config import config_is_stale, default_config, ensure_config
from jaeger_ai.features.gateway.constants import (
    A2A_BACKEND_PORT,
    A2A_GATEWAY_PORT,
    MCP_GATEWAY_PORT,
    MCP_HTTP_PORT,
)
from jaeger_ai.features.gateway.service import locate_binary, status


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
    assert backends == [f"127.0.0.1:{A2A_BACKEND_PORT}", f"127.0.0.1:{A2A_BACKEND_PORT}"]


def test_ensure_config_writes_token_file_without_embedding_it(tmp_path: Path) -> None:
    path = ensure_config(tmp_path)
    text = path.read_text(encoding="utf-8")
    token = (tmp_path / "gateway" / "client.token").read_text(encoding="utf-8").strip()
    assert token
    assert token not in text
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


def test_locate_binary_ignores_non_jaeger_user_link(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    assert locate_binary(tmp_path) is None
    row = status(tmp_path)
    assert row["running"] is False
    assert row["ports"]["mcp_gateway"] == 8811
    assert row["ports"]["a2a_gateway"] == 8812
