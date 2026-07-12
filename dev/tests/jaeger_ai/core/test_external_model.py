"""External-model pipeline — schema, key resolution, provider validation.

Post-pydantic-ai-removal, the external client no longer constructs a
``pydantic_ai.Model`` instance — adapter selection lives in
:mod:`jaeger_os.agent.loop.runtime_bridge`. What stays in
``core/external_model.py`` is config-shape + key resolution + the
``chat()`` shim that fast-finalize calls. This test file pins those.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.models.external_model import (
    ExternalModelClient,
    ExternalModelError,
    _merge_consecutive,
    resolve_api_key,
    validate_external_provider,
)
from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, ModelConfig


# ── local-first invariant ───────────────────────────────────────────


def test_external_model_disabled_by_default():
    """A fresh ExternalModelConfig — and a Config that omits the
    section entirely — must NOT enable an external brain."""
    assert ExternalModelConfig().enabled is False
    cfg = Config(
        instance_name="t",
        model=ModelConfig(model_path="/tmp/x.gguf"),
    )
    assert cfg.external_model.enabled is False
    assert cfg.external_model.provider == "lmstudio"


def test_config_rejects_unknown_external_field():
    """extra='forbid' on ExternalModelConfig catches typo'd keys."""
    with pytest.raises(Exception):
        ExternalModelConfig(enabled=True, provdier="lmstudio")  # typo


# ── key resolution ──────────────────────────────────────────────────


def test_resolve_api_key_from_env(monkeypatch):
    ext = ExternalModelConfig(provider="openai", api_key_env="MY_KEY_VAR")
    monkeypatch.setenv("MY_KEY_VAR", "sk-from-env")
    assert resolve_api_key(ext, layout=None) == "sk-from-env"


def test_resolve_api_key_conventional_env(monkeypatch):
    ext = ExternalModelConfig(provider="anthropic", api_key_env="")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-conventional")
    assert resolve_api_key(ext, layout=None) == "sk-ant-conventional"


def test_resolve_api_key_absent_returns_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ext = ExternalModelConfig(provider="openai", api_key_env="")
    assert resolve_api_key(ext, layout=None) == ""


def test_resolve_ollama_cloud_key_from_conventional_env(monkeypatch):
    ext = ExternalModelConfig(provider="ollama-cloud", api_key_env="")
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-cloud-key")
    assert resolve_api_key(ext, layout=None) == "ollama-cloud-key"


def test_resolve_gemini_key_from_conventional_env(monkeypatch):
    ext = ExternalModelConfig(provider="gemini", api_key_env="")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    assert resolve_api_key(ext, layout=None) == "gemini-key"


# ── provider validation ────────────────────────────────────────────


def test_validate_lmstudio_injects_placeholder_key():
    """LM Studio runs locally; any non-empty key is accepted. The
    validator injects ``"lm-studio"`` when no key is supplied so the
    adapter doesn't refuse to construct."""
    ext = ExternalModelConfig(enabled=True, provider="lmstudio", model="m")
    assert validate_external_provider(ext, api_key="") == "lm-studio"


def test_validate_ollama_cloud_requires_key():
    """Ollama Cloud is a real cloud endpoint — no placeholder."""
    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
    )
    with pytest.raises(ExternalModelError):
        validate_external_provider(ext, api_key="")


def test_validate_ollama_cloud_passes_real_key_through():
    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
    )
    assert validate_external_provider(ext, api_key="real") == "real"


def test_validate_anthropic_requires_key():
    ext = ExternalModelConfig(enabled=True, provider="anthropic", model="claude-x")
    with pytest.raises(ExternalModelError):
        validate_external_provider(ext, api_key="")


def test_validate_anthropic_passes_real_key_through():
    ext = ExternalModelConfig(enabled=True, provider="anthropic", model="claude-opus-4-7")
    assert validate_external_provider(ext, api_key="fake-key") == "fake-key"


def test_validate_gemini_requires_key():
    ext = ExternalModelConfig(
        enabled=True, provider="gemini", model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    with pytest.raises(ExternalModelError):
        validate_external_provider(ext, api_key="")


# ── client surface ─────────────────────────────────────────────────


def test_external_client_surface():
    """The client exposes ``kind`` / ``model_name`` / ``provider`` /
    ``chat`` / ``connectivity_check`` / ``describe`` — the surface the
    new agent layer's :func:`jaeger_os.agent.loop.runtime_bridge.
    _adapter_for_client` and the fast-finalize fallback both read."""
    ext = ExternalModelConfig(enabled=True, provider="lmstudio", model="local-model")
    client = ExternalModelClient(ext, layout=None)
    assert client.kind == "external"
    assert client.model_name == "local-model"
    assert client.provider == "lmstudio"
    assert client.llm is None
    assert hasattr(client, "chat") and hasattr(client, "connectivity_check")
    assert "lmstudio" in client.describe()


def test_external_model_provider_gemini_accepted():
    ext = ExternalModelConfig(provider="gemini", model="gemini-2.5-flash")
    assert ext.provider == "gemini"


def test_external_model_rejects_bogus_provider():
    with pytest.raises(Exception):
        ExternalModelConfig(provider="bogus-provider")


def test_gemini_client_surface(monkeypatch):
    """Gemini client construction succeeds when the conventional key
    is present in the environment."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    ext = ExternalModelConfig(
        enabled=True, provider="gemini", model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    client = ExternalModelClient(ext, layout=None)
    assert client.kind == "external"
    assert client.provider == "gemini"
    assert "gemini" in client.describe()
    assert "generativelanguage" in client.describe()


# ── anthropic message shaping ───────────────────────────────────────


def test_merge_consecutive_collapses_same_role():
    """Anthropic is strict about role alternation; the fast-finalize
    path sends two user turns in a row — they must merge into one."""
    merged = _merge_consecutive([
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "c"},
    ])
    assert merged == [
        {"role": "user", "content": "a\n\nb"},
        {"role": "assistant", "content": "c"},
    ]
