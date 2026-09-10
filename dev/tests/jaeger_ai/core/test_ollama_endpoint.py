"""Ollama endpoint resolver — no baked 127.0.0.1 for container guests."""

from __future__ import annotations


def test_env_base_url_wins(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.64.1:11434")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    from jaeger_ai.core.models.ollama_endpoint import resolve_ollama_base_url

    assert resolve_ollama_base_url() == "http://192.168.64.1:11434/v1"
    assert resolve_ollama_base_url(openai_compat=False) == "http://192.168.64.1:11434"


def test_container_prefers_bridge(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("JAEGER_IN_CONTAINER", "1")
    import jaeger_ai.core.models.ollama_endpoint as ep

    monkeypatch.setattr(ep, "_reachable", lambda host, port=11434: host == "192.168.64.1")
    monkeypatch.setattr(ep, "_container_bridge_host", lambda: "192.168.64.1")
    assert ep.resolve_ollama_base_url() == "http://192.168.64.1:11434/v1"


def test_host_prefers_loopback_when_reachable(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("JAEGER_IN_CONTAINER", raising=False)
    import jaeger_ai.core.models.ollama_endpoint as ep

    monkeypatch.setattr(ep, "_running_in_container", lambda: False)
    monkeypatch.setattr(ep, "_reachable", lambda host, port=11434: host in {"127.0.0.1", "localhost"})
    assert ep.resolve_ollama_base_url() == "http://127.0.0.1:11434/v1"


def test_session_selection_repairs_loopback(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.64.1:11434/v1")
    from types import SimpleNamespace

    from jaeger_ai.core.models.session_selection import select_client

    class FakeClient:
        def __init__(self, ext, layout):
            self.ext = ext
            self.layout = layout
            self.model_name = ext.model
            self.provider = ext.provider

    monkeypatch.setattr(
        "jaeger_ai.core.models.external_model.ExternalModelClient",
        FakeClient,
    )
    config = SimpleNamespace(
        external_model=SimpleNamespace(
            enabled=True,
            provider="ollama",
            model="glm-5.3-flash:cloud",
            base_url="http://127.0.0.1:11434/v1",
            api_key_credential="x",
            api_key_env="Y",
            model_copy=lambda deep=True: SimpleNamespace(
                enabled=True,
                provider="ollama",
                model="glm-5.3-flash:cloud",
                base_url="http://127.0.0.1:11434/v1",
                api_key_credential="x",
                api_key_env="Y",
            ),
        )
    )
    default = SimpleNamespace(model_name="other", provider="ollama")
    client = select_client(default, config, layout=tmp_path, model="gemma-4-26b:latest", provider="ollama-local")
    assert client.provider == "ollama"
    assert client.ext.base_url == "http://192.168.64.1:11434/v1"
    assert client.ext.api_key_credential == ""
