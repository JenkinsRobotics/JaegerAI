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
