"""Tests for the unified model router, endpoint discovery, and sensitivity gate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from jaeger_ai.core.models import router


def test_router_classify_public_and_private():
    klass, reason = router.classify("what is the time")
    assert klass == "public"
    assert reason == "default"

    klass_priv, reason_priv = router.classify("please do not reveal this api_key")
    assert klass_priv == "private"
    assert "keyword" in reason_priv


def test_router_apply_sensitivity_routing(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))

    model, provider, decision = router.apply_sensitivity_routing(
        "tell me a joke",
        model="glm-5.3-flash:cloud",
        provider="ollama-cloud",
    )
    assert decision.classification == "public"
    assert model == "glm-5.3-flash:cloud"
    assert provider == "ollama"

    model_p, provider_p, decision_p = router.apply_sensitivity_routing(
        "my bank password is secret123",
    )
    assert decision_p.classification == "private"
    assert provider_p == "ollama"
    assert model_p == "gemma-4-26b:latest"


def test_router_endpoint_resolution(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.15.0.239:11434")
    assert router.resolve_ollama_base_url() == "http://10.15.0.239:11434/v1"
    assert router.resolve_ollama_base_url(openai_compat=False) == "http://10.15.0.239:11434"
    assert router.normalize_ollama_provider("ollama-local") == "ollama"


def test_log_decision_redacts_private_prompts(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))

    # 1. Private decision: text preview MUST NOT contain raw secrets
    secret_text = "super_secret_password_98765"
    _, _, priv_decision = router.apply_sensitivity_routing(
        secret_text,
        log=True,
    )
    log_file = tmp_path / "logs" / "sensitivity_gate.jsonl"
    assert log_file.is_file()
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line]
    last = lines[-1]
    assert last["class"] == "private"
    assert secret_text not in last["preview"]
    assert "<redacted:sha256=" in last["preview"]
    assert f":len={len(secret_text)}>" in last["preview"]

    # 2. Public decision: text preview is preserved up to 160 chars
    public_text = "this is a public inquiry"
    _, _, pub_decision = router.apply_sensitivity_routing(
        public_text,
        log=True,
    )
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line]
    last_pub = lines[-1]
    assert last_pub["class"] == "public"
    assert last_pub["preview"] == public_text
