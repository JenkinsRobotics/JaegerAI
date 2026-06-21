"""``MLXAdapter`` — rebuilt for parity with the llama.cpp path.

Pins the two operator-reported bugs from the first MLX attempt:

  1. tools were presented in a foreign dialect (hardcoded Hermes XML +
     ChatML markers for every model) → wrong/garbled tool calls;
  2. generation never stopped early — ``stop`` was dropped and every
     call ran out the full ``max_tokens`` budget → laggy turns.

``mlx_lm`` isn't a hard dependency: construction must never import it,
tests inject a runner OR a fake ``mlx_lm`` module into ``sys.modules``
to exercise the real streaming loop.
"""

from __future__ import annotations

import sys
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from jaeger_os.agent import MLXAdapter


class _FakeTokenizer:
    """Duck-types the two things the adapter reads: ``chat_template``
    (family detection) and ``apply_chat_template`` (prompt render)."""

    def __init__(self, chat_template: str = "") -> None:
        self.chat_template = chat_template
        self.rendered: list[list[dict[str, Any]]] = []

    def apply_chat_template(self, messages, add_generation_prompt=True,
                            tokenize=False):  # noqa: ARG002
        self.rendered.append(list(messages))
        body = "\n".join(
            f"<{m.get('role')}>{m.get('content') or ''}" for m in messages
        )
        return body + "\n<assistant>"


def _install_fake_mlx(monkeypatch, chunks: list[str]):
    """Plant a fake ``mlx_lm`` module whose ``stream_generate`` yields
    the given text chunks, tracking how many were CONSUMED — the
    early-stop assertion reads that counter."""
    consumed = {"n": 0}

    def stream_generate(model, tokenizer, *, prompt, **kw):  # noqa: ARG001
        def _gen():
            for text in chunks:
                consumed["n"] += 1
                yield SimpleNamespace(
                    text=text, finish_reason=None,
                    prompt_tokens=10, generation_tokens=consumed["n"],
                )
        return _gen()

    monkeypatch.setitem(
        sys.modules, "mlx_lm",
        SimpleNamespace(stream_generate=stream_generate),
    )
    return consumed


def _adapter_with_fake_model(chat_template: str = "") -> MLXAdapter:
    return MLXAdapter(
        model=object(),
        tokenizer=_FakeTokenizer(chat_template),
        model_name="qwen-test",
    )


# ── construction / lazy import ─────────────────────────────────────


def test_constructor_does_not_import_mlx_lm():
    a = MLXAdapter(model_path="dummy/model")
    assert a.name == "mlx"


def test_call_without_model_path_or_runner_raises():
    a = MLXAdapter()
    with pytest.raises(ValueError, match="model_path"):
        a.call({"messages": []}, threading.Event())


def test_describe_reports_target():
    assert "dummy/model" in MLXAdapter(model_path="dummy/model").describe()
    assert "mlx" in MLXAdapter(runner=lambda p, k: "").describe()


# ── bug #1 pin: tools in the model's OWN dialect ───────────────────


def test_tools_always_reach_the_model_even_for_unknown_family():
    """MLX has no structured tools channel — an unknown-family model
    must still get the Hermes fallback block rather than NOTHING (or
    the model answers as a plain chatbot)."""
    from pydantic import BaseModel

    class _Args(BaseModel):
        x: int = 1

    from jaeger_os.agent.schemas.tool_schema import ToolDef
    tool = ToolDef(name="bump", description="Bump.",
                   args_model=_Args, fn=lambda x=1: {"ok": True})

    a = _adapter_with_fake_model(chat_template="")
    out = a.format_messages(
        [{"role": "user", "content": "hi"}], [tool], "be brief",
    )
    system = out["messages"][0]
    assert system["role"] == "system"
    assert "be brief" in system["content"]
    # The tool catalogue is IN the prompt, one way or another.
    assert "bump" in system["content"]
    assert "<tool_call>" in system["content"] or "tool" in system["content"].lower()


def test_family_stops_follow_detected_dialect():
    """A llama3-template model must stop on llama3 markers, not the
    hardcoded ChatML one the old adapter used for everything."""
    a = _adapter_with_fake_model(
        chat_template="{{ bos_token }}<|start_header_id|>"
                      "<|eot_id|>{% endfor %}",
    )
    a.model_name = "Llama-3.2-3B-Instruct-MLX"
    out = a.format_messages([{"role": "user", "content": "hi"}], [], "")
    assert "<|eot_id|>" in out["stop"]


def test_prompt_renders_through_models_own_chat_template():
    a = _adapter_with_fake_model()
    out = a.format_messages([{"role": "user", "content": "hi"}], [], "sys")
    prompt = a._render_prompt(out["messages"])
    # The fake tokenizer's render — NOT hardcoded <|im_start|> ChatML.
    assert prompt.startswith("<system>")
    assert a._tokenizer.rendered  # template actually consulted


# ── bug #2 pin: generation ends when the answer does ───────────────


def test_stream_stops_at_family_marker_and_discards_rambling(monkeypatch):
    chunks = ["The answer", " is 42.", "<|im_end|>", "RAMBLE", "RAMBLE"]
    consumed = _install_fake_mlx(monkeypatch, chunks)
    a = _adapter_with_fake_model()
    raw = a.call(
        a.format_messages([{"role": "user", "content": "q"}], [], ""),
        threading.Event(),
    )
    msg = a.parse_response(raw)
    assert msg["content"] == "The answer is 42."
    # Generation STOPPED at the marker — the ramble chunks were never
    # pulled from the generator. (The old adapter consumed everything.)
    assert consumed["n"] == 3
    assert raw["finish_reason"] == "stop"


def test_stream_emits_deltas_and_ttft(monkeypatch):
    _install_fake_mlx(monkeypatch, ["Hel", "lo", "<|im_end|>"])
    a = _adapter_with_fake_model()
    deltas: list[str] = []
    a.call(
        a.format_messages([{"role": "user", "content": "q"}], [], ""),
        threading.Event(),
        on_delta=deltas.append,
    )
    assert deltas[:2] == ["Hel", "lo"]
    assert a.last_ttft_s is not None and a.last_ttft_s >= 0.0
    assert a.last_usage and a.last_usage.get("prompt_tokens") == 10


def test_interrupt_breaks_stream_at_token_boundary(monkeypatch):
    from jaeger_os.agent.loop.interrupt import AgentInterrupted

    ev = threading.Event()
    chunks = ["a"] * 50
    consumed = _install_fake_mlx(monkeypatch, chunks)

    # Fire the interrupt after the third chunk via the delta hook.
    def _barge_in(_piece: str) -> None:
        if consumed["n"] >= 3:
            ev.set()

    a = _adapter_with_fake_model()
    with pytest.raises(AgentInterrupted):
        a.call(
            a.format_messages([{"role": "user", "content": "q"}], [], ""),
            ev,
            on_delta=_barge_in,
        )
    assert consumed["n"] < 10  # stopped promptly, not after 50 chunks


# ── injected-runner path (tests / exotic backends) ─────────────────


def test_explicit_runner_path_post_trims_stops():
    def _runner(prompt: str, kw: dict[str, Any]) -> str:  # noqa: ARG001
        return "short answer<|im_end|>then it keeps rambling"

    a = MLXAdapter(runner=_runner)
    raw = a.call(
        a.format_messages([{"role": "user", "content": "q"}], [], ""),
        threading.Event(),
    )
    assert a.parse_response(raw)["content"] == "short answer"


# ── parse pipeline parity with llama.cpp ───────────────────────────


def test_parse_drift_extracts_tool_calls():
    a = MLXAdapter(runner=lambda p, k: "")
    parsed = a.parse_response(
        '<tool_call>{"name": "x", "arguments": {"k": 1}}</tool_call>'
    )
    assert parsed["tool_calls"][0]["name"] == "x"
    assert parsed["tool_calls"][0]["arguments"] == {"k": 1}


def test_parse_strips_think_blocks():
    a = MLXAdapter(runner=lambda p, k: "")
    parsed = a.parse_response("<think>let me ponder</think>It is noon.")
    assert parsed["content"] == "It is noon."


def test_parse_tags_thinking_exhaustion():
    a = MLXAdapter(runner=lambda p, k: "")
    parsed = a.parse_response({
        "text": "<think>endless deliberation that never concludes",
        "finish_reason": "length",
    })
    assert parsed.get("finish_reason") == "thinking_exhausted"
    assert not (parsed.get("content") or "").strip()


# ── bridge wiring ──────────────────────────────────────────────────


def test_bridge_selects_mlx_adapter_for_mlx_client_shape():
    from jaeger_os.agent.loop.runtime_bridge import _adapter_for_client

    fake_client = SimpleNamespace(
        _mlx_model=object(),
        _tokenizer=_FakeTokenizer(),
        model_name="Qwen3.5-9B-MLX-4bit",
    )
    adapter = _adapter_for_client(fake_client)
    assert isinstance(adapter, MLXAdapter)
    # The client's already-loaded pair is reused — no second load.
    assert adapter._model is fake_client._mlx_model
    assert adapter._tokenizer is fake_client._tokenizer
    assert "Qwen3.5" in adapter.describe()


# ── VoiceLLM port: stop-marker holdback in the delta stream ────────


def test_split_stop_marker_never_leaks_into_deltas(monkeypatch):
    """A stop marker straddling two chunks must not leak its head into
    the delta stream — TTS would read '<end_of' aloud (VoiceLLM field
    bug). The holdback scanner emits text only once it can no longer
    be part of a marker."""
    chunks = ["Hi the", "re<|im_", "end|>JUNK", "MORE JUNK"]
    consumed = _install_fake_mlx(monkeypatch, chunks)
    a = _adapter_with_fake_model()
    deltas: list[str] = []
    raw = a.call(
        a.format_messages([{"role": "user", "content": "q"}], [], ""),
        threading.Event(),
        on_delta=deltas.append,
    )
    assert a.parse_response(raw)["content"] == "Hi there"
    # No delta carries any fragment of the marker.
    assert "".join(deltas) == "Hi there"
    assert not any("<" in d for d in deltas)
    # Generation stopped at the marker chunk; junk never consumed.
    assert consumed["n"] == 3


def test_heldback_prefix_flushes_when_stream_ends(monkeypatch):
    """Text that LOOKS like a marker prefix but never becomes one is
    real content — it must flush at stream end, not vanish."""
    _install_fake_mlx(monkeypatch, ["the formula is a <", "b"])
    a = _adapter_with_fake_model()
    deltas: list[str] = []
    raw = a.call(
        a.format_messages([{"role": "user", "content": "q"}], [], ""),
        threading.Event(),
        on_delta=deltas.append,
    )
    assert a.parse_response(raw)["content"] == "the formula is a <b"
    assert "".join(deltas) == "the formula is a <b"


def test_scan_stream_text_pure_helper():
    from jaeger_os.agent.adapters.mlx import _scan_stream_text
    stops = ("<|im_end|>",)
    # Full marker in one piece → emit head, stop.
    emit, pending, stopped = _scan_stream_text("", "answer<|im_end|>tail", stops)
    assert (emit, pending, stopped) == ("answer", "", True)
    # Trailing prefix held back.
    emit, pending, stopped = _scan_stream_text("", "hello<|im_", stops)
    assert (emit, pending, stopped) == ("hello", "<|im_", False)
    # Held prefix completes into a marker on the next piece.
    emit, pending, stopped = _scan_stream_text("<|im_", "end|>x", stops)
    assert (emit, pending, stopped) == ("", "", True)
    # Held prefix disambiguates into plain text.
    emit, pending, stopped = _scan_stream_text("<|im_", "probable", stops)
    assert emit == "<|im_probable" and pending == "" and stopped is False


def test_sampler_built_when_temp_set(monkeypatch):
    """temp/top_p ride as a sampler= (mlx-lm ≥0.21 contract), never as
    bare kwargs that silently diverge or TypeError."""
    seen_kwargs: dict[str, Any] = {}

    def stream_generate(model, tokenizer, *, prompt, **kw):  # noqa: ARG001
        seen_kwargs.update(kw)
        def _gen():
            yield SimpleNamespace(text="ok<|im_end|>", finish_reason=None,
                                  prompt_tokens=1, generation_tokens=1)
        return _gen()

    sampler_obj = object()
    monkeypatch.setitem(
        sys.modules, "mlx_lm",
        SimpleNamespace(stream_generate=stream_generate),
    )
    monkeypatch.setitem(
        sys.modules, "mlx_lm.sample_utils",
        SimpleNamespace(make_sampler=lambda **kw: sampler_obj),
    )
    a = MLXAdapter(
        model=object(), tokenizer=_FakeTokenizer(), model_name="m",
        defaults={"max_tokens": 64, "temp": 0.7},
    )
    a.call(
        a.format_messages([{"role": "user", "content": "q"}], [], ""),
        threading.Event(),
    )
    assert seen_kwargs.get("sampler") is sampler_obj
    assert "temp" not in seen_kwargs
