"""Standalone tests for jaeger-models."""

from __future__ import annotations

import pytest

from jaeger_contracts import ModelPort
from jaeger_models import (
    ModelCatalog,
    ModelRouter,
    ReplayModel,
    StickyFallbackModel,
    safe_local_context_window,
)


def test_catalog_and_structured_output_selection() -> None:
    cat = ModelCatalog()
    p = cat.resolve("local/mlx-qwen3-coder")
    assert p.local_only is True
    assert p.context_window == 65_536
    assert cat.structured_output_mode("anthropic/claude-sonnet") == "native"


def test_sticky_fallback_pins_healthy_model_and_handles_overflow() -> None:
    primary = ReplayModel([RuntimeError("429 rate limit")], model_id="anthropic/claude-sonnet")
    fb = ReplayModel([{"content": "from-fb-1"}, {"content": "from-fb-2"}], model_id="google/gemini-pro")
    model = StickyFallbackModel(primary=primary, fallbacks=(fb,), sticky=True)
    assert isinstance(model, ModelPort)

    assert model.complete([{"role": "user", "content": "hi"}])["content"] == "from-fb-1"
    # Second call stays pinned to fb (preserves prompt cache; primary not hit again)
    assert model.complete([{"role": "user", "content": "next"}])["content"] == "from-fb-2"
    assert len(primary.calls) == 1
    assert len(fb.calls) == 2

    # Overflow routes to overflow_fallbacks
    ov_primary = ReplayModel([RuntimeError("413 context_length_exceeded")], model_id="local/llama-cpp")
    big = ReplayModel([{"content": "handled-overflow"}], model_id="google/gemini-pro")
    ov_model = StickyFallbackModel(primary=ov_primary, overflow_fallbacks=(big,))
    assert ov_model.complete([])["content"] == "handled-overflow"


def test_router_privacy_egress_and_auxiliary_routing() -> None:
    cloud = ReplayModel([{"content": "cloud"}], model_id="anthropic/claude-sonnet")
    aux = ReplayModel([{"content": "summary"}], model_id="local/llama-cpp")
    local = ReplayModel([{"content": "local-private"}], model_id="local/mlx-qwen3-coder")

    router = ModelRouter(primary=cloud, auxiliary=aux, local_only_model=local)
    assert isinstance(router, ModelPort)
    assert router.complete([], task_kind="compact")["content"] == "summary"
    assert router.complete([], sensitive=True)["content"] == "local-private"

    # Without local model, sensitive turn MUST fail closed against cloud model
    cloud_only_router = ModelRouter(primary=ReplayModel([{"content": "leak"}], model_id="anthropic/claude-sonnet"))
    with pytest.raises(PermissionError):
        cloud_only_router.complete([], sensitive=True)


def test_local_context_budgeter_prevents_256k_kv_cache_bloat() -> None:
    # 32 GB Mac caps unbounded 262K GGUF max to 48K while leaving 40K untouched
    assert safe_local_context_window(262_144, host_ram_gb=32.0) == 49_152
    assert safe_local_context_window(40_960, host_ram_gb=32.0) == 40_960
    assert safe_local_context_window(262_144, host_ram_gb=16.0) == 16_384
    assert safe_local_context_window(262_144, host_ram_gb=64.0) == 65_536
    # Explicit operator setting or env override is always respected (clamped to model max)
    assert safe_local_context_window(262_144, host_ram_gb=32.0, configured_ctx=65_536) == 65_536
    assert safe_local_context_window(262_144, host_ram_gb=32.0, env_override="32768") == 32_768


def test_response_fold_and_per_attempt_fallback_audit() -> None:
    from jaeger_models import ResponseFold

    fold = ResponseFold()
    fold = fold.apply({"type": "reasoning_delta", "delta": "think "})
    fold = fold.apply({"type": "text_delta", "delta": "hello "})
    fold = fold.apply({"type": "text_delta", "delta": "world"})
    fold = fold.apply({"type": "tool_call", "tool_call": {"id": "c1", "name": "read_file", "arguments": {}}})
    fold = fold.apply({"type": "finish", "finish_reason": "tool_calls", "usage": {"input_tokens": 10}})
    assert fold.text == "hello world"
    assert fold.reasoning == "think "
    assert len(fold.tool_calls) == 1 and fold.finish_reason == "tool_calls"
    assert fold.usage["input_tokens"] == 10

    seen_models: list[str] = []
    primary = ReplayModel([RuntimeError("503 overloaded")], model_id="anthropic/claude-sonnet")
    fb = ReplayModel([{"content": "ok"}], model_id="google/gemini-pro")
    sf = StickyFallbackModel(
        primary=primary,
        fallbacks=(fb,),
        prepare_request=lambda m, msgs, kw: (seen_models.append(m.name) or msgs, kw),
    )
    assert sf.complete([{"role": "user", "content": "hi"}])["content"] == "ok"
    assert len(seen_models) == 2
    assert [(a.model_name, a.ok) for a in sf.last_attempts] == [(primary.name, False), (fb.name, True)]
