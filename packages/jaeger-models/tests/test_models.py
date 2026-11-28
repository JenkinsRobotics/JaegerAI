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


def test_ollama_retries_502_before_stream_output(monkeypatch):
    from urllib.error import HTTPError

    from jaeger_models import providers

    delays = []
    attempts = []

    def stream(url, payload, **kwargs):
        attempts.append(payload)
        if len(attempts) < 3:
            try:
                raise HTTPError(url, 502, "upstream disconnected", {}, None)
            except HTTPError as exc:
                raise RuntimeError("HTTP 502") from exc
        yield '{"message":{"content":"Recovered"},"done":true}'

    monkeypatch.setattr(providers, "_post_stream_lines", stream)
    monkeypatch.setattr(providers.time, "sleep", delays.append)
    output = []
    with providers.bind_stream_sink(lambda kind, text: output.append(text)):
        result = providers.OllamaModel().complete([{"role": "user", "content": "Continue"}])
    assert result["content"] == "Recovered"
    assert output == ["Recovered"]
    assert delays == [0.5, 2.0]
    assert attempts[0] == attempts[-1]


def test_ollama_reports_truncated_stream_without_replaying_output(monkeypatch):
    from jaeger_models import providers

    def stream(*args, **kwargs):
        yield '{"message":{"content":"Partial"},"done":false}'

    monkeypatch.setattr(providers, "_post_stream_lines", stream)
    output = []
    with providers.bind_stream_sink(lambda kind, text: output.append(text)):
        with pytest.raises(RuntimeError, match="dropped after the response began"):
            providers.OllamaModel().complete([])
    assert output == ["Partial"]


def test_ollama_profile_falls_back_to_show_and_cloud_default(monkeypatch) -> None:
    from jaeger_models import providers

    monkeypatch.setattr(providers, "_get_json", lambda *args, **kwargs: {"models": []})
    monkeypatch.setattr(
        providers,
        "_post_json",
        lambda url, payload, **kwargs: {"model_info": {"qwen3.context_length": 65536}}
        if payload.get("name") == "qwen3:8b"
        else {},
    )
    assert providers.OllamaModel("qwen3:8b").profile("qwen3:8b").context_window == 65536
    assert providers.OllamaModel("mistral-large-4:cloud").profile("mistral-large-4:cloud").context_window == 131_072


def test_hwfit_cookbook_multi_modality_and_what_if() -> None:
    from jaeger_models import benchmark_model, recommend_models

    # 32 GB Mac: 70B won't fit, 8B/14B/Whisper/Kokoro/Nomic fit nicely
    report_32 = recommend_models(host_ram_gb=32.0, installed_names=["qwen3:8b"])
    assert report_32["ok"] is True
    assert report_32["hardware"]["simulated"] is True
    by_id = {r["recipe"]["recipe_id"]: r for r in report_32["recommendations"]}
    assert by_id["ollama/qwen3-8b"]["fit"] == "ideal"
    assert by_id["ollama/qwen3-8b"]["installed"] is True
    assert by_id["ollama/llama3.3-70b"]["fit"] == "wont_fit"
    assert by_id["mlx/kokoro-82m"]["fit"] == "ideal"
    assert by_id["mlx/flux-schnell-4bit"]["fit"] == "ideal"

    # Filter by modality
    stt_only = recommend_models(modality="stt", host_ram_gb=32.0)
    assert stt_only["count"] >= 2
    assert all(r["recipe"]["modality"] == "stt" for r in stt_only["recommendations"])

    # Quick benchmark
    bench = benchmark_model(ReplayModel([{"content": "Ready to assist you now."}], model_id="local/test"))
    assert bench["ok"] is True and bench["output_chars"] > 0


def test_model_roundtable_blind_critique_and_consensus() -> None:
    from jaeger_models import ModelRoundtable, RoundtableParticipant

    m1 = ReplayModel(
        [{"content": "Use aluminum 6061 for the chassis."}, {"content": "- Agree on 6061\n- Watch weight"}],
        model_id="local/qwen",
    )
    m2 = ReplayModel(
        [{"content": "Use carbon fiber plates with 6061 brackets."}, {"content": "- Hybrid is lightest"}],
        model_id="cloud/claude",
    )
    synth = ReplayModel([{"content": "Consensus: hybrid carbon + 6061 brackets."}], model_id="local/synth")

    rt = ModelRoundtable(
        [
            RoundtableParticipant(name="local/qwen", model=m1),
            RoundtableParticipant(name="cloud/claude", model=m2),
        ],
        synthesizer=synth,
    )
    report = rt.run(
        "Best chassis material for JP01?",
        blind=True,
        critique_round=True,
        consensus=True,
        seed=42,
    )
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["blind"] is True
    assert len(payload["responses"]) == 2
    # In blind mode model_name is masked to label while reveal_map holds true names
    assert all(r["model_name"] == r["label"] for r in payload["responses"])
    assert set(payload["reveal_map"].values()) == {"local/qwen", "cloud/claude"}
    assert "hybrid carbon" in payload["consensus"]
    assert all(r.get("critique") for r in payload["responses"])
    assert "# Roundtable Comparison" in report.to_markdown()
