"""Per-family native tool presentation.

Principle under test: JROS presents tools in each model's OWN dialect
(we match the model; it never drifts to match us). These pins guard
the family classifier + the per-family rendering so a refactor can't
silently regress a family back to a foreign format.
"""

from __future__ import annotations

import json

import pytest

from jaeger_os.agent.dialects import (
    detect_family,
    detect_reasoning,
    render_tools_for as render_tool_presentation,
    strip_think_blocks,
)
from jaeger_os.agent.schemas.tool_schema import ToolDef
from pydantic import BaseModel


class _Args(BaseModel):
    city: str


def _tool(name: str = "get_weather") -> ToolDef:
    return ToolDef(
        name=name, description="Get weather by city",
        args_model=_Args, fn=lambda city: {"ok": True},
    )


# ── detect_family: name-based (finetunes invert template vs format) ──


def test_detect_hermes_is_chatml_despite_llama_base():
    """Hermes-3 is built on Llama-3 (template uses Llama-3 headers) but
    was trained to tool-call in ChatML <tool_call>. Name must win."""
    llama3_template = "<|start_header_id|>system<|end_header_id|>…"
    assert detect_family("Hermes-3-Llama-3.1-8B", llama3_template) == "chatml"


def test_detect_qwen_and_deephermes_are_chatml():
    assert detect_family("Qwen3.5-9B") == "chatml"
    assert detect_family("DeepHermes-AscensionMaze-RLAIF-8b") == "chatml"
    assert detect_family("DeepSeek-R1-0528-Qwen3-8B") == "chatml"


def test_detect_mistral_family():
    assert detect_family("Mistral-Nemo-Instruct-2407") == "mistral"
    assert detect_family("Ministral-3-14B-Reasoning") == "mistral"


def test_detect_gemma_and_gptoss_and_llama():
    assert detect_family("gemma-4-26B-A4B-it") == "gemma"
    assert detect_family("gpt-oss-20b-MXFP4") == "harmony"
    assert detect_family("Llama-3.2-3B-Instruct") == "llama3"


def test_detect_unknown_when_no_signal():
    assert detect_family("totally-novel-model-x") == "unknown"
    assert detect_family("") == "unknown"


def test_detect_template_signature_fallback():
    """When the name gives nothing, the chat-template markers classify."""
    assert detect_family("mystery", "<|im_start|>system") == "chatml"
    assert detect_family("mystery", "[INST] [TOOL_CALLS]") == "mistral"
    assert detect_family("mystery", "<start_of_turn>user") == "gemma"
    assert detect_family("mystery", "<|start_header_id|>system") == "llama3"


# ── render_tool_presentation: native dialects ────────────────────


def test_render_chatml_uses_tool_call_tags():
    out = render_tool_presentation("chatml", [_tool()])
    assert "<tools>" in out and "</tools>" in out
    assert "<tool_call>" in out
    # The schema JSON is embedded.
    assert "get_weather" in out


def test_render_mistral_uses_bracket_convention():
    out = render_tool_presentation("mistral", [_tool()])
    assert "[AVAILABLE_TOOLS]" in out
    assert "[TOOL_CALLS]" in out
    # Must NOT force the Hermes <tool_call> tag on Mistral.
    assert "<tool_call>" not in out


def test_render_llama3_uses_python_tag():
    out = render_tool_presentation("llama3", [_tool()])
    assert "<|python_tag|>" in out
    assert "<tool_call>" not in out
    assert "[TOOL_CALLS]" not in out


def test_render_gemma_injects_nothing():
    """Gemma's structured tools= path works — injecting prose would be
    redundant and risks perturbing a model that already routes well."""
    assert render_tool_presentation("gemma", [_tool()]) == ""


def test_render_unknown_injects_nothing():
    assert render_tool_presentation("unknown", [_tool()]) == ""


def test_render_empty_tools_is_empty():
    assert render_tool_presentation("chatml", []) == ""


# ── reasoning detection ──────────────────────────────────────────


def test_detect_reasoning_by_name():
    assert detect_reasoning("Ministral-3-14B-Reasoning-2512") is True
    assert detect_reasoning("DeepSeek-R1-0528-Qwen3-8B") is True
    assert detect_reasoning("DeepHermes-AscensionMaze-RLAIF-8b") is True
    assert detect_reasoning("Hermes-4.3-36B") is True  # hybrid reasoning
    assert detect_reasoning("QwQ-32B") is True


def test_detect_reasoning_false_for_plain_models():
    assert detect_reasoning("gemma-4-26B-A4B-it") is False
    assert detect_reasoning("Qwen3.5-9B") is False
    assert detect_reasoning("Mistral-Nemo-Instruct-2407") is False
    assert detect_reasoning("Hermes-3-Llama-3.1-8B") is False


def test_detect_reasoning_by_template():
    assert detect_reasoning("mystery", "...<think>...</think>...") is True


# ── think-block stripping ────────────────────────────────────────


def test_strip_closed_think_block():
    text = "<think>let me reason about this</think>The answer is 42."
    assert strip_think_blocks(text) == "The answer is 42."


def test_strip_keeps_tool_call_after_think():
    """The tool call comes AFTER </think> — stripping must keep it so
    the drift parser can still find it."""
    text = (
        "<think>I should call get_time</think>\n"
        '<tool_call>{"name": "get_time", "arguments": {}}</tool_call>'
    )
    out = strip_think_blocks(text)
    assert "<think>" not in out
    assert "<tool_call>" in out
    assert "get_time" in out


def test_strip_dangling_unclosed_think():
    """A model cut off mid-thought (no </think>) — drop from the tag
    to end so we don't leak a wall of partial reasoning."""
    text = "Here goes <think>reasoning that never closed because truncat"
    out = strip_think_blocks(text)
    assert "<think>" not in out
    assert out == "Here goes"


def test_strip_noop_when_no_think():
    assert strip_think_blocks("plain answer") == "plain answer"
    assert strip_think_blocks("") == ""


def test_textify_tool_history_chatml_drops_structured_tool_calls():
    """A prose family's tool-call history must become native text turns
    with NO structured ``tool_calls`` field — otherwise the model's GGUF
    template renders it and crashes (DeepSeek-R1)."""
    from jaeger_os.agent.dialects import textify_tool_history
    import json as _json
    wire = [
        {"role": "user", "content": "what time is it"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "1", "type": "function",
                         "function": {"name": "get_time",
                                      "arguments": _json.dumps({"tz": "UTC"})}}]},
        {"role": "tool", "content": "12:00 UTC"},
    ]
    out = textify_tool_history(wire, "chatml")
    # No message carries a structured tool_calls field anymore.
    assert all("tool_calls" not in m for m in out)
    asst = out[1]
    assert asst["role"] == "assistant"
    assert "<tool_call>" in asst["content"] and "get_time" in asst["content"]
    # Tool result became a plain user turn in the Hermes convention.
    assert out[2]["role"] == "user"
    assert "<tool_response>" in out[2]["content"] and "12:00 UTC" in out[2]["content"]


def test_textify_tool_history_passthrough_for_gemma():
    """Gemma keeps the structured path — history must be untouched."""
    from jaeger_os.agent.dialects import textify_tool_history
    wire = [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "1", "type": "function",
                         "function": {"name": "x", "arguments": "{}"}}]},
    ]
    assert textify_tool_history(wire, "gemma") is wire


def test_harmony_extracts_commentary_tool_call():
    """gpt-oss emits tool calls on the harmony ``commentary`` channel
    with a ``to=functions.NAME`` recipient — parse name + JSON args."""
    from jaeger_os.agent.dialects import harmony
    text = (
        '<|channel|>analysis<|message|>User asks the time.<|end|>'
        '<|start|>assistant<|channel|>commentary to=functions.get_time '
        '<|constrain|>json<|message|>{"timezone": "Asia/Shanghai"}'
    )
    calls = harmony.extract_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["args"] == {"timezone": "Asia/Shanghai"}


def test_harmony_clean_channels_prefers_final():
    from jaeger_os.agent.dialects import harmony
    text = (
        '<|channel|>analysis<|message|>thinking hard<|end|>'
        '<|channel|>final<|message|>It is 5pm in Shanghai.'
    )
    assert harmony.clean_channels(text) == "It is 5pm in Shanghai."


def test_harmony_clean_channels_strips_analysis_when_no_final():
    """A pure tool-call turn has no final channel — the answer should be
    empty (not the analysis/commentary text)."""
    from jaeger_os.agent.dialects import harmony
    text = (
        '<|channel|>analysis<|message|>need a tool<|end|>'
        '<|start|>assistant<|channel|>commentary to=functions.get_time '
        '<|message|>{"timezone": "UTC"}'
    )
    assert harmony.clean_channels(text) == ""


def test_parse_harmony_dispatcher_wraps_calls():
    from jaeger_os.agent.dialects import parse_harmony
    text = (
        '<|channel|>commentary to=functions.calculate '
        '<|message|>{"expression": "2+2"}'
    )
    calls, answer = parse_harmony(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "calculate"
    assert calls[0]["id"].startswith("harmony_")
    assert answer == ""


def test_render_embeds_valid_json_schema():
    """The embedded schema block must be parseable JSON so the model
    sees a well-formed tool catalogue."""
    out = render_tool_presentation("chatml", [_tool("calc"), _tool("clock")])
    start = out.index("<tools>") + len("<tools>")
    end = out.index("</tools>")
    schemas = json.loads(out[start:end].strip())
    assert isinstance(schemas, list)
    names = {s["function"]["name"] for s in schemas}
    assert names == {"calc", "clock"}
