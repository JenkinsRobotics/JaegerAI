"""Sensitivity gate stub — public→cloud, private→local, JSONL decision log."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_classify_private_keyword():
    from jaeger_ai.core.models.sensitivity_gate import classify

    klass, reason = classify("please rotate the password on the NAS")
    assert klass == "private"
    assert "keyword" in reason


def test_classify_public_weather():
    from jaeger_ai.core.models.sensitivity_gate import classify

    klass, reason = classify("what's the weather")
    assert klass == "public"
    assert reason == "default"


def test_decide_routes_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    from jaeger_ai.core.models import sensitivity_gate as gate

    # Reload helpers pick up env via operator_state_root
    model, provider, decision = gate.apply_sensitivity_routing(
        "what's the weather",
        model="glm-5.3-flash:cloud",
        provider="ollama-cloud",
    )
    assert decision.classification == "public"
    assert model == "glm-5.3-flash:cloud"
    assert provider == "ollama"

    model2, provider2, decision2 = gate.apply_sensitivity_routing(
        "here is my api key sk-abcdefghijklmnopqrstuvwxyz",
    )
    assert decision2.classification == "private"
    assert provider2 == "ollama"
    assert model2 == "gemma-4-26b:latest"

    log = tmp_path / "logs" / "sensitivity_gate.jsonl"
    assert log.is_file()
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert '"class": "public"' in lines[0]
    assert '"model": "glm-5.3-flash:cloud"' in lines[0]
    assert '"class": "private"' in lines[1]
    assert '"model": "gemma-4-26b:latest"' in lines[1]


def test_normalize_ollama_provider_lanes():
    from jaeger_ai.core.models.ollama_endpoint import normalize_ollama_provider

    assert normalize_ollama_provider("ollama-cloud") == "ollama"
    assert normalize_ollama_provider("ollama-local") == "ollama"
    assert normalize_ollama_provider("openai") == "openai"


def test_configure_model_remaps_ollama_cloud_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    from jaeger_ai.core.instance.schemas import Config, dump_yaml
    from jaeger_ai.core.models.configuration import configure_model

    root = tmp_path / "inst"
    root.mkdir()
    (root / "config.yaml").write_text(
        "instance_name: t\n"
        "model:\n  model_path: gemma-4-e4b-it-q4_k_m\n"
        "external_model:\n  enabled: false\n",
        encoding="utf-8",
    )

    class Layout:
        config_path = root / "config.yaml"

    result = configure_model(
        Layout(),
        provider="ollama-cloud",
        model="glm-5.3-flash:cloud",
    )
    assert result["ok"] is True
    assert result["provider"] == "ollama"
    cfg = Config.model_validate(
        __import__("yaml").safe_load(Layout.config_path.read_text(encoding="utf-8"))
    )
    assert cfg.external_model.enabled is True
    assert cfg.external_model.provider == "ollama"
    assert cfg.external_model.model == "glm-5.3-flash:cloud"
    assert "ollama.com" not in cfg.external_model.base_url
    assert cfg.external_model.api_key_credential == ""


def test_private_uses_config_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    from types import SimpleNamespace

    from jaeger_ai.core.models.sensitivity_gate import decide

    config = SimpleNamespace(
        external_model=SimpleNamespace(
            enabled=True,
            model="glm-5.3-flash:cloud",
            fallback=[
                SimpleNamespace(provider="ollama", model="gemma-4-26b:latest"),
            ],
        )
    )
    decision = decide("rotate the password please", config=config)
    assert decision.classification == "private"
    assert decision.model == "gemma-4-26b:latest"
    assert decision.provider == "ollama"
