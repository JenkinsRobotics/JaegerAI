"""``LocalLlamaAdapter`` — in-process llama-cpp tests with a stub Llama.

No real GGUF, no real weights — a ``FakeLlama`` injected at
construction time exercises the chat-completion surface and the
drift-parser layering. The Phase 3 OpenAI adapter tests already cover
the wire format the parent class handles; this file focuses on what
the subclass adds.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from jaeger_ai.agent import LocalLlamaAdapter
from jaeger_ai.agent.loop.interrupt import AgentInterrupted


class _FakeLlama:
    """Duck-types ``llama_cpp.Llama.create_chat_completion``."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return self._response


def _mk_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """llama-cpp returns a plain dict (not a typed object). The adapter
    must parse that shape unchanged."""
    msg: dict[str, Any] = {"content": content}
    if tool_calls is not None:
        msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc.get("arguments", {})),
                },
            }
            for tc in tool_calls
        ]
    return {
        "choices": [{"message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


# ── construction ───────────────────────────────────────────────────


class _HybridLlama:
    """Duck-types both ``create_chat_completion`` AND
    ``create_completion`` (the lower-level path the thinking toggle
    routes to) + exposes a chat template with ``enable_thinking`` in
    metadata, so the adapter detects this fake as a hybrid model."""

    _HYBRID_TEMPLATE = (
        "{%- if add_generation_prompt %}{{- 'BOS' }}{%- endif %}"
        "{%- for m in messages %}{{- '|' + m.role + ':' + (m.content or '') }}"
        "{%- endfor %}"
        "{%- if enable_thinking is defined and not enable_thinking %}"
        "{{- '|NOTHINK' }}{%- else %}{{- '|THINK' }}{%- endif %}"
    )

    def __init__(self) -> None:
        self.last_chat_kwargs: dict[str, Any] | None = None
        self.last_completion_kwargs: dict[str, Any] | None = None
        self.metadata = {"tokenizer.chat_template": self._HYBRID_TEMPLATE}

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.last_chat_kwargs = kwargs
        return _mk_response("structured-path")

    def create_completion(self, **kwargs: Any) -> Any:
        self.last_completion_kwargs = kwargs
        return {
            "id": "x", "model": "fake",
            "choices": [{"text": "direct-path", "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 1},
        }


def test_constructor_requires_path_or_pre_loaded_llama():
    """Calling ``call()`` without either is the failure point — but
    construction is allowed so callers can build the adapter lazily."""
    a = LocalLlamaAdapter()
    with pytest.raises(ValueError, match="model_path"):
        a._ensure_client()


def test_explicit_llama_skips_load_entirely():
    fake = _FakeLlama(_mk_response("hi"))
    a = LocalLlamaAdapter(llama=fake)
    client = a._ensure_client()
    # The facade is built from the injected Llama, not from disk.
    assert client._llama is fake


def test_describe_uses_filename_when_path_given():
    a = LocalLlamaAdapter(model_path="/tmp/fake-model.gguf")
    assert "fake-model.gguf" in a.describe()
    assert "local-llama" in a.describe()


def test_provider_and_name_set_to_local_llama():
    """``/runtime`` shows the adapter's ``name``; pick precise labels so
    a user picking the local model sees 'local-llama' rather than the
    parent class's generic 'openai'."""
    a = LocalLlamaAdapter()
    assert a.name == "local-llama"
    assert a.provider == "local-llama"


# ── format → call → parse round-trip ───────────────────────────────


def test_format_messages_injects_native_dialect_per_family():
    """The adapter injects tools in the model's OWN dialect (we match
    the model). A Hermes/chatml model gets <tool_call>; a Mistral model
    gets [TOOL_CALLS] — never the wrong one forced on it."""
    from pydantic import BaseModel
    from jaeger_os.core.tools.tool_schema import ToolDef

    class _A(BaseModel):
        x: int

    tool = ToolDef(name="calc", description="calc", args_model=_A,
                   fn=lambda x: {"ok": True})

    # Hermes-named model → chatml dialect.
    a = LocalLlamaAdapter(model_path="/m/Hermes-3-Llama-3.1-8B.gguf")
    kw = a.format_messages([{"role": "user", "content": "hi"}], [tool], "sys")
    sys_text = next(m["content"] for m in kw["messages"] if m["role"] == "system")
    assert "<tool_call>" in sys_text
    assert "<tools>" in sys_text
    assert "[TOOL_CALLS]" not in sys_text  # not forced into Mistral format

    # Mistral-named model → mistral dialect.
    b = LocalLlamaAdapter(model_path="/m/Mistral-Nemo-Instruct-2407.gguf")
    kw = b.format_messages([{"role": "user", "content": "hi"}], [tool], "sys")
    sys_text = next(m["content"] for m in kw["messages"] if m["role"] == "system")
    assert "[TOOL_CALLS]" in sys_text
    assert "<tool_call>" not in sys_text  # not forced into Hermes format


def test_format_messages_gemma_injects_no_prose():
    """Gemma works through structured tools= — the adapter must NOT
    add prose for it (avoid perturbing a model that already routes)."""
    from pydantic import BaseModel
    from jaeger_os.core.tools.tool_schema import ToolDef

    class _A(BaseModel):
        x: int

    tool = ToolDef(name="calc", description="calc", args_model=_A,
                   fn=lambda x: {"ok": True})
    a = LocalLlamaAdapter(model_path="/m/gemma-4-26B-A4B-it.gguf")
    kw = a.format_messages([{"role": "user", "content": "hi"}], [tool], "sys")
    sys_text = next(m["content"] for m in kw["messages"] if m["role"] == "system")
    # System is just the original — no injected tool block.
    assert "<tools>" not in sys_text
    assert "[AVAILABLE_TOOLS]" not in sys_text
    # But structured tools= is still passed (gemma's working channel).
    assert "tools" in kw and kw["tools"]


def test_format_messages_prose_family_drops_structured_tools():
    """Prose families are driven entirely as TEXT — the structured
    ``tools=`` param is dropped so the conversation never routes through
    the model's fragile GGUF tool template (DeepSeek-R1 crashes on dict
    args; Hermes builds strip the tool section). The catalogue is in the
    system prose instead."""
    from pydantic import BaseModel
    from jaeger_os.core.tools.tool_schema import ToolDef

    class _A(BaseModel):
        x: int

    tool = ToolDef(name="calc", description="calc", args_model=_A,
                   fn=lambda x: {"ok": True})
    a = LocalLlamaAdapter(model_path="/m/Hermes-3-Llama-3.1-8B.gguf")
    kw = a.format_messages([{"role": "user", "content": "hi"}], [tool], "sys")
    assert not kw.get("tools")  # structured channel dropped for prose families
    sys_text = next(m["content"] for m in kw["messages"] if m["role"] == "system")
    assert "<tools>" in sys_text  # catalogue lives in the prose instead


def test_enable_thinking_none_preserves_default_path():
    """Default ``enable_thinking=None`` must NOT touch the structured
    chat-completion path — same behaviour as before the toggle landed.
    Critical: the in-flight benchmark depends on this guarantee."""
    fake = _HybridLlama()
    a = LocalLlamaAdapter(llama=fake)  # enable_thinking defaults to None
    kw = a.format_messages([{"role": "user", "content": "hi"}], [], "sys")
    assert "_thinking_prompt" not in kw
    a.call(kw, threading.Event())
    assert fake.last_chat_kwargs is not None
    assert fake.last_completion_kwargs is None


def test_enable_thinking_false_routes_through_manual_render():
    """A hybrid model with ``enable_thinking=False`` must bypass
    ``create_chat_completion`` and call ``create_completion`` on a
    template-rendered prompt that carries the flag — that's the only
    way to take Qwen3.x / gemma-4 out of reasoning mode (the chat API
    won't take the kwarg)."""
    fake = _HybridLlama()
    a = LocalLlamaAdapter(llama=fake, enable_thinking=False)
    kw = a.format_messages([{"role": "user", "content": "hi"}], [], "sys")
    assert "_thinking_prompt" in kw, "format_messages must stash the rendered prompt"
    assert "NOTHINK" in kw["_thinking_prompt"]
    a.call(kw, threading.Event())
    assert fake.last_completion_kwargs is not None, "must use create_completion"
    assert fake.last_chat_kwargs is None, "structured path must NOT also fire"


def test_enable_thinking_true_renders_with_think_flag():
    """For symmetry: forcing ``enable_thinking=True`` also takes the
    manual-render path so think-ON and think-OFF runs use the SAME
    code path and are directly comparable in the bench."""
    fake = _HybridLlama()
    a = LocalLlamaAdapter(llama=fake, enable_thinking=True)
    kw = a.format_messages([{"role": "user", "content": "hi"}], [], "sys")
    assert "_thinking_prompt" in kw
    assert "THINK" in kw["_thinking_prompt"]
    assert "NOTHINK" not in kw["_thinking_prompt"]


def test_enable_thinking_no_op_on_non_hybrid_model():
    """A non-hybrid model (template has no ``enable_thinking``) ignores
    the toggle — the structured path runs unchanged. Safety net for
    always-reasoning models (DeepSeek-R1) and plain models (gemma-3)."""
    fake = _FakeLlama(_mk_response("ok"))   # no metadata → non-hybrid
    a = LocalLlamaAdapter(llama=fake, enable_thinking=False)
    kw = a.format_messages([{"role": "user", "content": "hi"}], [], "sys")
    assert "_thinking_prompt" not in kw, (
        "non-hybrid model: thinking toggle must be a no-op"
    )


def test_thinking_path_response_is_chat_shaped_for_parse_response():
    """The manual-render path uses ``create_completion`` whose response
    is text-shaped. The facade must wrap it into the chat-completion
    shape so ``OpenAIAdapter.parse_response`` decodes it unchanged —
    otherwise the agent loop crashes on the missing ``message`` field."""
    fake = _HybridLlama()
    a = LocalLlamaAdapter(llama=fake, enable_thinking=False)
    kw = a.format_messages([{"role": "user", "content": "hi"}], [], "sys")
    raw = a.call(kw, threading.Event())
    assert raw["choices"][0]["message"]["role"] == "assistant"
    assert raw["choices"][0]["message"]["content"] == "direct-path"


def test_reasoning_model_gets_higher_stall_floor():
    """A reasoning model legitimately thinks for minutes; the watchdog
    floor is raised so it doesn't fire mid-think (which would corrupt
    the KV cache → crash the next call). Verify a low caller timeout
    is bumped to the reasoning floor."""
    import threading
    from unittest.mock import patch

    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake,
                          model_path="/m/DeepSeek-R1-0528-Qwen3-8B.gguf")
    captured: dict[str, Any] = {}
    real = __import__("jaeger_ai.agent.loop.interrupt",
                      fromlist=["interruptible_call"]).interruptible_call

    def _spy(fn, ev, **kw):
        captured.update(kw)
        return real(fn, ev, **kw)

    with patch("jaeger_ai.agent.adapters.openai.interruptible_call", _spy):
        a.call({"model": "x", "messages": []}, threading.Event(),
               stale_timeout=120.0)
    assert captured["stale_timeout"] == 300.0, (
        "reasoning model's 120s caller timeout should be raised to the "
        "300s reasoning floor"
    )


def test_non_reasoning_model_keeps_caller_timeout():
    """A plain model keeps whatever timeout the caller passed — the
    floor only applies to reasoning models."""
    import threading
    from unittest.mock import patch

    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake, model_path="/m/Qwen3.5-9B.gguf")
    captured: dict[str, Any] = {}
    real = __import__("jaeger_ai.agent.loop.interrupt",
                      fromlist=["interruptible_call"]).interruptible_call

    def _spy(fn, ev, **kw):
        captured.update(kw)
        return real(fn, ev, **kw)

    with patch("jaeger_ai.agent.adapters.openai.interruptible_call", _spy):
        a.call({"model": "x", "messages": []}, threading.Event(),
               stale_timeout=120.0)
    assert captured["stale_timeout"] == 120.0


def test_parse_response_strips_think_keeps_tool_call():
    """A reasoning model emits <think>…</think> then a tool call. The
    adapter must strip the think block but still surface the call."""
    a = LocalLlamaAdapter(llama=_FakeLlama(_mk_response("x")))
    raw = _mk_response(
        '<think>I should check the time</think>\n'
        '<tool_call>{"name": "get_time", "arguments": {}}</tool_call>'
    )
    msg = a.parse_response(raw)
    # Think block gone from visible content.
    assert "<think>" not in (msg.get("content") or "")
    # Tool call salvaged.
    names = [tc.get("name") for tc in (msg.get("tool_calls") or [])]
    assert "get_time" in names


def test_parse_response_strips_think_plain_answer():
    """Reasoning then a plain answer — visible content is just the
    answer, not the monologue."""
    a = LocalLlamaAdapter(llama=_FakeLlama(_mk_response("x")))
    raw = _mk_response("<think>deliberating at length</think>It is 5pm.")
    msg = a.parse_response(raw)
    assert msg.get("content") == "It is 5pm."


def test_facade_coerces_none_content_to_empty_string():
    """A pure tool-call assistant turn carries ``content=None`` (OpenAI
    wire shape). Many GGUF templates render content with an unguarded
    ``'</think>' in content`` and crash on None (DeepSeek-R1). The
    in-process facade must feed the template ``""`` instead. We send a
    history with a None-content assistant turn and assert what reaches
    ``create_chat_completion``."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    history = [
        {"role": "user", "content": "what time is it"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "x", "type": "function",
                         "function": {"name": "get_time", "arguments": "{}"}}]},
        {"role": "tool", "content": "12:00", "tool_call_id": "x"},
    ]
    a.call({"model": "x", "messages": history}, threading.Event())
    sent = fake.last_kwargs["messages"]
    assistant = next(m for m in sent if m.get("role") == "assistant")
    assert assistant["content"] == "", "None content must become empty string"
    # Non-None content is untouched.
    assert all(
        m["content"] is not None for m in sent if "content" in m
    )


def test_parse_response_salvages_bare_json_tool_call():
    """DeepSeek-R1 / Qwen / Llama emit tool calls as BARE JSON with no
    envelope: ``{"name": ..., "arguments": ...}``. The old guard
    (``if "<" not in text: return``) skipped the parser for these, so
    the JSON leaked out as a plain-text answer (the 2026-05-28
    DeepSeek-R1 0% flatline). Verify the parser now runs + the call
    is salvaged + the content is nulled."""
    a = LocalLlamaAdapter(llama=_FakeLlama(_mk_response("x")))
    raw = _mk_response(
        '{"name": "get_time", "arguments": {"timezone": "Asia/Shanghai"}}'
    )
    msg = a.parse_response(raw)
    names = [tc.get("name") for tc in (msg.get("tool_calls") or [])]
    assert "get_time" in names, "bare-JSON tool call must be salvaged"
    # The raw JSON must NOT surface as the visible answer.
    assert not (msg.get("content") or "").strip().startswith("{")


def test_parse_response_bare_json_after_think():
    """Reasoning model: <think> … </think> then a bare-JSON call.
    Strip think AND salvage the bare JSON."""
    a = LocalLlamaAdapter(llama=_FakeLlama(_mk_response("x")))
    raw = _mk_response(
        '<think>shanghai is UTC+8</think>\n'
        '{"name": "get_time", "arguments": {"timezone": "Asia/Shanghai"}}'
    )
    msg = a.parse_response(raw)
    names = [tc.get("name") for tc in (msg.get("tool_calls") or [])]
    assert "get_time" in names


def test_parse_response_plain_text_no_false_tool_call():
    """A genuine plain-text answer with no JSON/envelope must NOT be
    misread as a tool call (guard against over-eager salvage)."""
    a = LocalLlamaAdapter(llama=_FakeLlama(_mk_response("x")))
    msg = a.parse_response(_mk_response("It is 5pm in Shanghai."))
    assert not (msg.get("tool_calls") or [])
    assert msg.get("content") == "It is 5pm in Shanghai."


def test_call_dispatches_to_llama_with_strip_http_kwargs():
    """``api_key`` / ``base_url`` / ``timeout`` make no sense in-process
    — the facade must strip them before handing kwargs to llama-cpp."""
    fake = _FakeLlama(_mk_response("ack"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {"model": "x", "messages": [], "max_tokens": 64},
        threading.Event(),
        api_key="should-be-stripped",
        base_url="http://nowhere",
        timeout=30,
    )
    assert fake.last_kwargs is not None
    assert "api_key" not in fake.last_kwargs
    assert "base_url" not in fake.last_kwargs
    assert "timeout" not in fake.last_kwargs
    assert fake.last_kwargs["model"] == "x"


def test_call_wires_logits_processor_for_clean_abort():
    """``create_chat_completion`` doesn't accept ``stopping_criteria``,
    so the facade attaches a ``logits_processor`` bound to the abort
    flag: it raises to stop a stalled decode cleanly instead of letting
    it be abandoned (which corrupts the shared KV cache)."""
    from jaeger_ai.agent.adapters.local_llama import _AbortGeneration
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    a.call({"model": "x", "messages": []}, threading.Event())
    proc = fake.last_kwargs.get("logits_processor")
    assert proc, "logits_processor must be passed to llama-cpp"
    # Flag clear → pass scores through; flag set → raise to stop.
    scores = [0.1, 0.2]
    assert proc[0]([1, 2], scores) is scores
    a._abort_flag.set()
    with pytest.raises(_AbortGeneration):
        proc[0]([1, 2], scores)


def test_stale_abort_stops_wedged_decode_and_keeps_instance_usable():
    """End-to-end: a WEDGED decode (no tokens flowing — the logits
    processor never runs, like a hang inside prefill) trips the
    no-progress watchdog, the abort flag is set for the worker to
    honour, the context is reset, and a SUBSEQUENT call on the same
    instance still succeeds (no cascade)."""
    import time as _time

    class _WedgedLlama:
        """First call hangs WITHOUT producing tokens (the processor is
        never invoked, so no progress is reported); it polls the abort
        flag the way a real decode notices ``stopping_criteria`` and
        exits once the watchdog's on_abandon sets it. Later calls
        return normally — proving the instance is still usable."""
        def __init__(self, abort_flag: Any) -> None:
            self.calls = 0
            self.resets = 0
            self._abort = abort_flag

        def reset(self) -> None:
            self.resets += 1

        def create_chat_completion(self, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                for _ in range(2000):
                    if self._abort.is_set():
                        from jaeger_ai.agent.adapters.local_llama import (
                            _AbortGeneration,
                        )
                        raise _AbortGeneration()
                    _time.sleep(0.005)
            return _mk_response("partial")

    a = LocalLlamaAdapter(llama=_FakeLlama(_mk_response("seed")))
    llama = _WedgedLlama(a._abort_flag)
    a._llama = llama
    a._client = None  # rebuild facade around the wedged stub
    with pytest.raises(Exception) as ei:
        a.call({"model": "x", "messages": []}, threading.Event(),
               stale_timeout=0.2)
    assert "StaleCallTimeout" in type(ei.value).__name__ or "stale" in str(ei.value).lower()
    # The aborted decode triggered a context reset so the next case
    # starts clean (prevents the post-abort segfault cascade).
    assert llama.resets >= 1
    # The instance is NOT poisoned: a fresh call still works.
    out = a.call({"model": "x", "messages": []}, threading.Event())
    assert out is not None
    assert llama.calls >= 2


def test_token_progress_prevents_false_stall_on_slow_decode():
    """A slow-but-HEALTHY decode (tokens flowing, total time well past
    the stale cap) must NOT be killed: the per-token progress beacon
    keeps resetting the no-progress timer. This is the daily-driver
    case the old total-elapsed semantics broke — every long local
    answer died at the cap."""
    import time as _time

    class _SlowHealthyLlama:
        def create_chat_completion(self, **kwargs: Any) -> Any:
            proc = kwargs.get("logits_processor") or []
            # ~0.6s of 'decoding', touching progress every 20ms.
            for _ in range(30):
                for p in proc:
                    p([1], [0.0])
                _time.sleep(0.02)
            return _mk_response("long answer, finished healthy")

    a = LocalLlamaAdapter(llama=_SlowHealthyLlama())
    # stale cap far below total duration; with per-token progress the
    # call must still complete.
    out = a.call({"model": "x", "messages": []}, threading.Event(),
                 stale_timeout=0.2)
    parsed = a.parse_response(out)
    assert parsed["content"] == "long answer, finished healthy"


def test_parse_response_decodes_native_tool_calls():
    """When llama-cpp's chat handler DOES parse the call structurally,
    the parent's ``parse_response`` handles it — no drift fallback
    needed."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(
        content=None,
        tool_calls=[{"id": "c1", "name": "get_time", "arguments": {"tz": "UTC"}}],
    )
    parsed = a.parse_response(raw)
    assert parsed["tool_calls"][0]["name"] == "get_time"
    assert parsed["tool_calls"][0]["arguments"] == {"tz": "UTC"}


def test_parse_response_salvages_drift_tool_calls_from_text():
    """When the chat handler leaves the call as text (Gemma 4 quirk),
    the drift parser must catch it AND the envelope must be stripped
    from the visible content."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(
        content=(
            'thinking… '
            '<tool_call>{"name": "get_time", "arguments": {"tz": "PST"}}</tool_call>'
        ),
    )
    parsed = a.parse_response(raw)
    assert parsed["tool_calls"][0]["name"] == "get_time"
    assert parsed["tool_calls"][0]["arguments"] == {"tz": "PST"}
    assert "<tool_call>" not in (parsed["content"] or "")
    assert "thinking" in parsed["content"]


def test_parse_response_merges_structured_and_drift_calls():
    """Real-world: chat handler gives us ONE structured call and the
    model emits a SECOND one as text. The dispatcher needs both."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(
        content='<tool_call>{"name": "second", "arguments": {"k": 1}}</tool_call>',
        tool_calls=[{"id": "c1", "name": "first", "arguments": {}}],
    )
    parsed = a.parse_response(raw)
    names = [tc["name"] for tc in parsed["tool_calls"]]
    assert names == ["first", "second"]


def test_parse_response_plain_text_passes_through_unchanged():
    """No `<` in the content means the drift parser never fires — fast
    path. Phase-8 also surfaces ``finish_reason`` on the message; the
    invariant is the content / role / no-tool-calls — finish_reason is
    additive."""
    fake = _FakeLlama(_mk_response("plain answer"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(content="plain answer")
    parsed = a.parse_response(raw)
    assert parsed["role"] == "assistant"
    assert parsed["content"] == "plain answer"
    assert "tool_calls" not in parsed


# ── capabilities + health ──────────────────────────────────────────


def test_supports_reports_in_process_capability_set():
    """No parallel-tools claim — the wire format doesn't guarantee it
    across the local-model menagerie. Streaming follows the flag."""
    a = LocalLlamaAdapter()
    assert a.supports("parallel_tools") is False
    assert a.supports("caching") is False
    assert a.supports("streaming") is False
    assert a.supports("vision") is False


def test_health_check_ok_when_client_constructable():
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    health = a.health_check()
    assert health["ok"] is True
    assert "loaded" in health["detail"]


def test_health_check_fails_when_no_path_and_no_llama():
    a = LocalLlamaAdapter()
    health = a.health_check()
    assert health["ok"] is False
    assert "model_path" in health["detail"]


# ── Jinja chat-template compatibility ───────────────────────────────


def test_call_decodes_tool_call_arguments_back_to_dict():
    """Regression: llama-cpp's Jinja chat templates (Qwen3.5, Gemma,
    Hermes) iterate ``tool_call.arguments|items`` — they need a dict,
    not the JSON-encoded string the OpenAI wire format uses. The facade
    must convert before passing to ``create_chat_completion`` or the
    template crashes with ``Can only get item pairs from a mapping``
    on the second turn of any tool-using conversation."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {
            "model": "x",
            "messages": [
                {"role": "user", "content": "go"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "bump",
                            # OpenAI wire format: JSON-encoded string.
                            "arguments": '{"x": 1, "y": "two"}',
                        },
                    }],
                },
                {
                    "role": "tool",
                    "tool_call_id": "c1",
                    "content": '{"ok": true}',
                },
            ],
        },
        threading.Event(),
    )
    assert fake.last_kwargs is not None
    sent_msg = fake.last_kwargs["messages"][1]
    sent_args = sent_msg["tool_calls"][0]["function"]["arguments"]
    # The decoded dict is what the Jinja template iterates.
    assert sent_args == {"x": 1, "y": "two"}
    assert isinstance(sent_args, dict)


def test_call_passes_through_already_dict_arguments():
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{
                        "function": {"name": "x", "arguments": {"already": "dict"}},
                    }],
                },
            ],
        },
        threading.Event(),
    )
    sent = fake.last_kwargs["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert sent == {"already": "dict"}


def test_call_handles_malformed_json_arguments_string_gracefully():
    """A drift-recovered tool call might carry malformed JSON. The
    facade must not crash — feed an empty dict to the template so
    rendering proceeds, even if the values are missing."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{
                        "function": {"name": "x", "arguments": "{not: json"},
                    }],
                },
            ],
        },
        threading.Event(),
    )
    sent = fake.last_kwargs["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert sent == {}


def test_in_process_call_passes_through_stale_timeout():
    """Stall watchdog wiring (2026-05-27): the in-process adapter now
    forwards the caller's ``stale_timeout`` to ``interruptible_call``
    instead of forcing it to None.

    Earlier the adapter overrode the timeout to None because abandoning
    a llama-cpp worker mid-decode corrupts the KV cache. The new
    posture: we cannot SAFELY cancel the worker thread, but we can
    raise ``StaleCallTimeout`` from the main thread so the agent loop
    surfaces a recoverable error to the user. The leaked worker is
    documented as a known caveat; the alternative (hang forever, no
    recovery) is worse — confirmed by 11+ minute Metal stalls on
    "do a self check" before this fix."""
    import threading
    from unittest.mock import patch

    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)

    captured: dict[str, Any] = {}
    real_interruptible = __import__(
        "jaeger_ai.agent.loop.interrupt", fromlist=["interruptible_call"]
    ).interruptible_call

    def _spy(fn, ev, **kw):
        captured.update(kw)
        return real_interruptible(fn, ev, **kw)

    with patch("jaeger_ai.agent.adapters.openai.interruptible_call", _spy):
        a.call(
            {"model": "x", "messages": []},
            threading.Event(),
            stale_timeout=120.0,
        )
    assert captured["stale_timeout"] == 120.0, (
        "caller's stale_timeout must flow through to interruptible_call "
        "so the stall watchdog actually fires"
    )


def test_in_process_call_raises_stale_timeout_when_model_hangs():
    """End-to-end-ish: a llama-cpp call that never returns must
    surface ``StaleCallTimeout`` to the caller after the watchdog
    fires. This is the whole point of the 2026-05-27 watchdog fix —
    a hung Metal prefill used to lock the loop for 10+ minutes; now
    it bails in seconds with a clean exception."""
    import threading
    import time
    from jaeger_ai.agent.loop.interrupt import StaleCallTimeout

    class _HangingLlama:
        def create_chat_completion(self, **_kwargs):
            # Sleep longer than the test's stale_timeout. The adapter
            # cannot kill us, but the main thread should raise.
            time.sleep(5.0)
            return _mk_response("never reached")

    a = LocalLlamaAdapter(llama=_HangingLlama())
    started = time.perf_counter()
    with pytest.raises(StaleCallTimeout):
        a.call(
            {"model": "x", "messages": []},
            threading.Event(),
            stale_timeout=0.3,   # 300 ms — quick test
        )
    elapsed = time.perf_counter() - started
    # Should bail near the timeout, not after the 5s hang.
    assert elapsed < 2.0, (
        f"watchdog should fire near stale_timeout (0.3s); "
        f"actual {elapsed:.2f}s suggests it's still waiting for the call"
    )


def test_in_process_call_honours_caller_interrupt_event():
    """The REAL interrupt event flows through to ``interruptible_call``
    with the cooperative-abort hooks attached.

    History: an earlier revision swapped in an uncancellable dummy
    event, so a voice barge-in mid-decode did nothing until the
    generation ran to completion — minutes of dead air on a reasoning
    model. The cooperative abort (on_abandon sets the abort flag, the
    logits processor stops the decode at the next token, the context
    is reset) makes interrupting exactly as safe as the stall path,
    so the event must NOT be blocked any more."""
    import threading
    from unittest.mock import patch

    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    caller_event = threading.Event()
    seen: dict[str, Any] = {}

    def _spy(fn, ev, **kw):
        seen["same_event"] = ev is caller_event
        seen["has_abandon_hook"] = kw.get("on_abandon") is not None
        seen["joins_worker"] = (kw.get("join_on_abandon") or 0) > 0
        seen["has_progress"] = kw.get("progress") is not None
        return fn()

    with patch("jaeger_ai.agent.adapters.openai.interruptible_call", _spy):
        a.call({"model": "x", "messages": []}, caller_event)

    assert seen == {
        "same_event": True,
        "has_abandon_hook": True,
        "joins_worker": True,
        "has_progress": True,
    }


def test_interrupt_mid_decode_aborts_cooperatively_and_resets():
    """End-to-end: an interrupt that fires while the decode is running
    stops the generation at the next token (via the abort flag), the
    context is reset, and AgentInterrupted reaches the caller."""
    import threading
    import time as _time

    class _SpinningLlama:
        """Simulates a decode in progress: invokes the logits processor
        per 'token' (like real llama-cpp) until the abort raises."""
        def __init__(self) -> None:
            self.resets = 0
            self.last_kwargs: dict[str, Any] | None = None

        def reset(self) -> None:
            self.resets += 1

        def create_chat_completion(self, **kwargs: Any) -> Any:
            self.last_kwargs = kwargs
            proc = kwargs.get("logits_processor") or []
            for _ in range(2000):
                for p in proc:
                    p([1], [0.0])  # raises _AbortGeneration once flag set
                _time.sleep(0.005)
            return _mk_response("ran to completion")

    llama = _SpinningLlama()
    a = LocalLlamaAdapter(llama=llama)
    ev = threading.Event()

    def _barge_in() -> None:
        _time.sleep(0.15)
        ev.set()

    t = threading.Thread(target=_barge_in)
    t.start()
    started = _time.perf_counter()
    with pytest.raises(AgentInterrupted):
        a.call({"model": "x", "messages": []}, ev, stale_timeout=30.0)
    elapsed = _time.perf_counter() - started
    t.join()
    # The 2000×5ms spin would run ~10s to completion; the barge-in must
    # cut it short within the poll+join budget.
    assert elapsed < 3.0
    assert llama.resets >= 1


def test_call_does_not_mutate_input_messages():
    """The facade walks messages defensively — the caller's list is
    NOT mutated, so re-using the same `formatted` dict across retries
    keeps working."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    msgs = [{
        "role": "assistant",
        "tool_calls": [{
            "function": {"name": "x", "arguments": '{"k": 1}'},
        }],
    }]
    a.call({"messages": msgs}, threading.Event())
    # Original input is still a JSON string — only the kwargs handed to
    # llama-cpp had the dict swap.
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"k": 1}'


def test_strip_tool_call_blocks_handles_gemma_inner_quote_markers():
    """Regression: a Gemma-4 tool call embeds ``<|"|>`` quote markers
    inside its args. The old ``call:[^<]*`` strip regex stopped at that
    first ``<`` and leaked the entire envelope into the visible answer
    (it surfaced in the TUI as a phantom 'thought'). The strip must
    remove the whole block so ``content`` comes back empty."""
    envelope = (
        '<|tool_call>call:speak{text:<|"|>'
        "Why don't scientists trust atoms? Because they make up everything!"
        '<|"|>}<tool_call|>'
    )
    stripped = LocalLlamaAdapter._strip_tool_call_blocks(envelope).strip()
    assert stripped == "", f"envelope leaked into visible text: {stripped!r}"


def test_strip_tool_call_blocks_keeps_surrounding_prose():
    """The stripper removes only the envelope, not the model's prose."""
    text = (
        "Sure! <|tool_call>call:get_time{timezone:<|\"|>Europe/Paris<|\"|>}"
        "<tool_call|> done."
    )
    out = LocalLlamaAdapter._strip_tool_call_blocks(text)
    assert "tool_call" not in out
    assert "Sure!" in out and "done." in out
