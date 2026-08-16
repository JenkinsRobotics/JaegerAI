"""Ollama / Ollama Cloud context autodetection.

The OpenAI-compat catalogue does not carry a window. These pin the
``/api/show`` parse order (hosted vs local), the name estimate, and
the rule that Cloud never sends ``options.num_ctx`` — a leftover
local 8K would shrink a 128K hosted model.
"""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_ai.core.models.ollama_context import (
    clear_show_cache,
    estimate_model_context_length,
    is_hosted_ollama,
    native_ollama_root,
    parse_show_context,
    resolve_serving_context,
    should_inject_num_ctx,
)


def setup_function() -> None:
    clear_show_cache()


def test_native_root_strips_v1_suffix():
    assert native_ollama_root("https://ollama.com/v1") == "https://ollama.com"
    assert native_ollama_root("http://localhost:11434/v1") == "http://localhost:11434"
    assert native_ollama_root("http://localhost:11434") == "http://localhost:11434"


def test_hosted_detection_covers_provider_url_and_cloud_tag():
    assert is_hosted_ollama(provider="ollama-cloud")
    assert is_hosted_ollama(base_url="https://ollama.com/v1")
    assert is_hosted_ollama(model="qwen3.5:397b-cloud")
    assert is_hosted_ollama(model="qwen3.5:397b:cloud")
    assert not is_hosted_ollama(
        provider="ollama", base_url="http://localhost:11434/v1", model="llama3.2",
    )


def test_hosted_show_prefers_model_info_over_num_ctx():
    """Cloud: GGUF training max is authoritative. The operator-side
    ``num_ctx`` may be a cap the user cannot raise."""
    data = {
        "model_info": {"qwen3.context_length": 131072},
        "parameters": "num_ctx 8192\n",
    }
    ctx, source = parse_show_context(data, hosted=True)
    assert ctx == 131072
    assert source == "model_info"


def test_local_show_prefers_num_ctx_over_model_info():
    """Local: Modelfile ``num_ctx`` is the KV cache Ollama will allocate."""
    data = {
        "model_info": {"llama.context_length": 131072},
        "parameters": "num_ctx 32768\ntemperature 0.7\n",
    }
    ctx, source = parse_show_context(data, hosted=False)
    assert ctx == 32768
    assert source == "num_ctx"


def test_show_falls_back_when_preferred_field_missing():
    hosted_ctx, hosted_src = parse_show_context(
        {"parameters": "num_ctx 16384\n"}, hosted=True,
    )
    assert hosted_ctx == 16384 and hosted_src == "num_ctx"
    local_ctx, local_src = parse_show_context(
        {"model_info": {"gemma.context_length": 8192}}, hosted=False,
    )
    assert local_ctx == 8192 and local_src == "model_info"


def test_estimate_known_cloud_families():
    assert estimate_model_context_length("qwen3.5:397b") == 131_072
    assert estimate_model_context_length("kimi-k2:1t") == 262_144
    assert estimate_model_context_length("gpt-oss:120b") == 131_072
    assert estimate_model_context_length("deepseek-v3.1:671b") == 65_536
    assert estimate_model_context_length("deepseek-v4-flash:preview") == 1_048_576
    assert estimate_model_context_length("deepseek-v4-pro:cloud") == 1_048_576


def test_resolve_uses_estimate_for_cloud_when_probe_fails(monkeypatch):
    from jaeger_ai.core.models import ollama_context as oc

    monkeypatch.setattr(oc, "query_ollama_show", lambda *a, **k: None)
    ctx, source = resolve_serving_context(
        provider="ollama-cloud",
        model="qwen3.5:397b",
        base_url="https://ollama.com/v1",
        configured_ctx=0,
        fallback_ctx=8192,
    )
    assert ctx == 131_072
    assert source == "estimate"


def test_resolve_explicit_ctx_above_local_default_wins(monkeypatch):
    from jaeger_ai.core.models import ollama_context as oc

    monkeypatch.setattr(
        oc, "query_ollama_show",
        lambda *a, **k: {"model_info": {"qwen3.context_length": 131072}},
    )
    ctx, source = resolve_serving_context(
        provider="ollama-cloud",
        model="qwen3.5:397b",
        base_url="https://ollama.com/v1",
        configured_ctx=262_144,
    )
    assert ctx == 262_144
    assert source == "configured"


def test_cloud_never_injects_num_ctx():
    assert should_inject_num_ctx(
        provider="ollama-cloud", base_url="https://ollama.com/v1",
        model="qwen3.5:397b", source="model_info",
    ) is False
    assert should_inject_num_ctx(
        provider="ollama", base_url="http://localhost:11434/v1",
        model="qwen3.5:397b:cloud", source="num_ctx",
    ) is False


def test_local_injects_only_modelfile_num_ctx():
    assert should_inject_num_ctx(
        provider="ollama", base_url="http://localhost:11434/v1",
        model="llama3.2", source="num_ctx",
    ) is True
    assert should_inject_num_ctx(
        provider="ollama", base_url="http://localhost:11434/v1",
        model="llama3.2", source="model_info",
    ) is False


def test_external_cloud_client_records_loaded_ctx_and_skips_num_ctx(monkeypatch):
    from jaeger_ai.core.instance.schemas import ExternalModelConfig
    from jaeger_ai.core.models import ollama_context as oc
    from jaeger_ai.core.models.external_model import ExternalModelClient

    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    monkeypatch.setattr(
        oc, "query_ollama_show",
        lambda *a, **k: {"model_info": {"qwen3.context_length": 131072}},
    )
    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
    )
    client = ExternalModelClient(ext, layout=None)
    assert client.loaded_ctx == 131072
    assert client.num_ctx is None


def test_budget_uses_cloud_estimate_instead_of_leftover_local(monkeypatch):
    """Regression: local model.ctx=32768 used to win over a 128K cloud
    model because the estimate only fired at ≤8192."""
    import jaeger_ai.main as main
    from jaeger_ai.core.models import ollama_context as oc
    from jaeger_ai.main import _context_budget_for

    monkeypatch.setattr(oc, "query_ollama_show", lambda *a, **k: None)
    saved_client = main._pipeline.get("client")
    saved_layout = main._pipeline.get("layout")
    main._pipeline["client"] = None
    main._pipeline["layout"] = None
    try:
        cfg = SimpleNamespace(
            model=SimpleNamespace(ctx=32_768, max_tokens=1024),
            external_model=SimpleNamespace(
                enabled=True, provider="ollama-cloud", ctx=0, max_tokens=4096,
                model="qwen3.5:397b", base_url="https://ollama.com/v1",
            ),
        )
        ctx, reserve = _context_budget_for(cfg)
        assert ctx == 131_072
        assert reserve == 4096
    finally:
        main._pipeline["client"] = saved_client
        main._pipeline["layout"] = saved_layout
