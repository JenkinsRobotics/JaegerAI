"""Tests for Cross-Agent Memory, Local Models, and MCP Sync in JaegerAI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from jaeger_ai.core.prompt_documents import (
    CROSS_AGENT_FRAGMENT,
    load_cross_agent_memory,
    register_context_documents,
)
from jaeger_ai.core.models.local_discovery import (
    discover_local_ollama_models,
    DiscoveredModel,
)
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, ExternalModelConfig, load_yaml, dump_yaml
from jaeger_ai.core.models.external_model import ExternalModelClient
from jaeger_ai.core.models.configuration import configure_model, configure_fallback_chain
from jaeger_ai.core.mcp.service import sync_ares_mcp_servers, list_servers


def test_load_cross_agent_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify load_cross_agent_memory reads from ARES_HOME/memory/person.md."""
    ares_dir = tmp_path / ".ares"
    mem_dir = ares_dir / "memory"
    mem_dir.mkdir(parents=True)
    person_file = mem_dir / "person.md"
    person_file.write_text("# Test Person Profile\n- Favorite language: Python\n- Project: ARES", encoding="utf-8")

    monkeypatch.setenv("ARES_HOME", str(ares_dir))

    loaded = load_cross_agent_memory(cap=1000)
    assert "[CROSS-AGENT MEMORY & PREFERENCES]" in loaded
    assert "Favorite language: Python" in loaded
    assert "Project: ARES" in loaded


def test_load_cross_agent_memory_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify load_cross_agent_memory returns empty string when person.md is absent."""
    ares_dir = tmp_path / ".ares"
    monkeypatch.setenv("ARES_HOME", str(ares_dir))
    assert load_cross_agent_memory() == ""


def test_register_context_documents_includes_cross_agent():
    """Verify register_context_documents registers cross_agent_memory fragment."""
    try:
        from jaeger_agent.prompts import assemble
    except ImportError:
        pytest.skip("jaeger_agent not installed in this test runner")

    ok = register_context_documents()
    assert ok is True
    fragment_names = [f.name for f in assemble.PROMPT_FRAGMENTS]
    assert CROSS_AGENT_FRAGMENT in fragment_names


def test_discover_local_ollama_models_offline():
    """Verify discover_local_ollama_models handles unreachable server gracefully."""
    models = discover_local_ollama_models(base_url="http://127.0.0.1:59999")
    assert isinstance(models, list)
    assert len(models) == 0


def test_discover_local_ollama_models_mocked():
    """Verify discover_local_ollama_models correctly parses API response."""
    mock_payload = b'{"models": [{"name": "qwen2.5:3b", "size": 1930000000}, {"name": "gemma4:31b-mlx", "size": 18600000000}]}'
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        models = discover_local_ollama_models(base_url="http://localhost:11434")
        assert len(models) == 2
        assert models[0].filename == "qwen2.5:3b"
        assert models[0].source == "Ollama (Local)"
        assert models[0].size_gb == 1.93
        assert models[1].filename == "gemma4:31b-mlx"
        assert models[1].size_gb == 18.6


def test_external_model_client_local_ollama_config():
    """Verify ExternalModelClient can be configured for local Ollama without errors."""
    ext = ExternalModelConfig(
        enabled=True,
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model="qwen2.5:3b",
        max_tokens=256,
        timeout_s=30.0,
        ctx=32768,
    )
    client = ExternalModelClient(ext, layout=None)
    assert client.provider == "ollama"
    assert client.model_name == "qwen2.5:3b"


def test_configure_model_ladder_and_fallbacks(tmp_path: Path):
    """Verify configure_model and configure_fallback_chain write valid config.yaml."""
    inst_dir = tmp_path / "test_instance"
    inst_dir.mkdir(parents=True)
    cfg_file = inst_dir / "config.yaml"
    cfg = Config(instance_name="test_instance", model=ModelConfig(model_path="dummy.gguf"))
    dump_yaml(cfg_file, cfg)

    layout = InstanceLayout(inst_dir)

    # 1. Configure Primary Model to Ollama qwen2.5:3b
    res_m = configure_model(layout, provider="ollama", model="qwen2.5:3b", context_length=32768)
    assert res_m["ok"] is True
    assert res_m["provider"] == "ollama"
    assert res_m["model"] == "qwen2.5:3b"

    # 2. Configure Fallback Ladder
    fallbacks = [
        {"provider": "ollama", "model": "gemma4:31b-mlx", "base_url": "http://localhost:11434/v1"},
        {"provider": "ollama-cloud", "model": "qwen3.5:397b", "base_url": "https://ollama.com/v1"},
    ]
    res_fb = configure_fallback_chain(layout, fallbacks)
    assert res_fb["ok"] is True
    assert len(res_fb["fallback"]) == 2

    # 3. Reload and verify
    reloaded = load_yaml(layout.config_path, Config)
    assert reloaded.external_model.enabled is True
    assert reloaded.external_model.provider == "ollama"
    assert reloaded.external_model.model == "qwen2.5:3b"
    assert len(reloaded.external_model.fallback) == 2
    assert reloaded.external_model.fallback[0].model == "gemma4:31b-mlx"
    assert reloaded.external_model.fallback[1].model == "qwen3.5:397b"


def test_sync_ares_mcp_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify sync_ares_mcp_servers reads MCP servers from ARES and writes to mcp.json."""
    ares_dir = tmp_path / ".ares"
    cfg_dir = ares_dir / "config"
    cfg_dir.mkdir(parents=True)
    mcp_json = cfg_dir / "mcp.json"
    mcp_json.write_text(json.dumps({
        "servers": [
            {"name": "ares-fs", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
        ]
    }), encoding="utf-8")

    monkeypatch.setenv("ARES_HOME", str(ares_dir))

    inst_dir = tmp_path / "test_instance"
    inst_dir.mkdir(parents=True)
    layout = InstanceLayout(inst_dir)

    sync_res = sync_ares_mcp_servers(layout)
    assert sync_res["ok"] is True
    assert "ares-fs" in sync_res["servers"]

    servers_inv = list_servers(layout)
    srv_names = [s["name"] for s in servers_inv.get("servers", [])]
    assert "ares-fs" in srv_names
