"""``HermesXMLAdapter`` — adapter unit tests with a stub runner.

The adapter calls into a ``(prompt, kwargs) -> str`` callable rather
than an SDK client, so unit testing is just a function substitution.
Covers the prompt assembly path (system + tools block + chat turns +
trailing assistant opener), the drift-aware parse path (with calls,
without calls, with multiple calls), and the end-to-end loop wiring
through :class:`JaegerAgent`.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_os.agent import (
    HermesXMLAdapter,
    JaegerAgent,
    clear_registry,
    register_tool,
)
from jaeger_os.agent.adapters.hermes_xml import HERMES_TOOL_INSTRUCTIONS
from jaeger_os.agent.schemas.tool_schema import ToolDef


class _Args(BaseModel):
    tz: str = Field(default="UTC")


def _mk_tool(name: str = "get_time") -> ToolDef:
    return ToolDef(
        name=name,
        description="Get the time.",
        args_model=_Args,
        fn=lambda tz="UTC": {"now": "12:00", "tz": tz},
    )


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


# ── format_messages ────────────────────────────────────────────────


def test_format_messages_includes_system_and_opens_assistant_turn():
    a = HermesXMLAdapter(runner=lambda p, k: "")
    out = a.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        system="you are a robot",
    )
    prompt = out["prompt"]
    assert "<|im_start|>system" in prompt
    assert "you are a robot" in prompt
    assert "<|im_start|>user\nhi" in prompt
    # Trailing assistant opener — the runner generates straight into it.
    assert prompt.rstrip().endswith("<|im_start|>assistant")
    assert out["stop"] == ["<|im_end|>"]


def test_format_messages_injects_hermes_instructions_when_tools_present():
    a = HermesXMLAdapter(runner=lambda p, k: "")
    out = a.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[_mk_tool()],
        system="",
    )
    assert HERMES_TOOL_INSTRUCTIONS.strip() in out["prompt"]
    assert "<tools>" in out["prompt"]
    assert '"name": "get_time"' in out["prompt"]


def test_format_messages_skips_instructions_when_explicitly_disabled():
    a = HermesXMLAdapter(
        runner=lambda p, k: "",
        inject_tool_instructions=False,
    )
    out = a.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[_mk_tool()],
        system="",
    )
    assert HERMES_TOOL_INSTRUCTIONS.strip() not in out["prompt"]
    # Tools block still renders — only the prose is suppressed.
    assert "<tools>" in out["prompt"]


def test_format_messages_renders_assistant_tool_calls_back_as_xml():
    """When replaying history to the model, prior tool calls must come
    back as ``<tool_call>`` blocks so the model recognises its own
    output format."""
    a = HermesXMLAdapter(runner=lambda p, k: "")
    out = a.format_messages(
        messages=[
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "calling",
                "tool_calls": [
                    {"id": "c1", "name": "get_time", "arguments": {"tz": "UTC"}},
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "get_time",
                "content": '{"now": "12:00"}',
            },
        ],
        tools=[],
        system="",
    )
    p = out["prompt"]
    assert "<tool_call>" in p
    assert '"name": "get_time"' in p
    assert "<tool_response>" in p
    assert '"now": "12:00"' in p


def test_format_messages_pulls_internal_system_into_header():
    """A mid-conversation ``system`` message must not appear in the
    chat turns — it joins the system header."""
    a = HermesXMLAdapter(runner=lambda p, k: "")
    out = a.format_messages(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "reminder rule"},
            {"role": "assistant", "content": "ok"},
        ],
        tools=[],
        system="base",
    )
    p = out["prompt"]
    # First <|im_start|>system block contains both bases.
    header_end = p.index("<|im_end|>")
    header = p[:header_end]
    assert "base" in header
    assert "reminder rule" in header
    # The system message should NOT appear again later in the prompt.
    assert p.count("reminder rule") == 1


def test_format_messages_stringifies_non_string_tool_content():
    a = HermesXMLAdapter(runner=lambda p, k: "")
    out = a.format_messages(
        messages=[
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "get_time",
                "content": {"now": "12:00", "tz": "UTC"},
            },
        ],
        tools=[],
        system="",
    )
    assert '"now": "12:00"' in out["prompt"]


# ── call ───────────────────────────────────────────────────────────


def test_call_passes_prompt_and_extra_kwargs_to_runner():
    seen: dict[str, Any] = {}

    def _runner(prompt: str, kw: dict[str, Any]) -> str:
        seen["prompt"] = prompt
        seen["kw"] = dict(kw)
        return "ack"

    a = HermesXMLAdapter(runner=_runner)
    out = a.call(
        {"prompt": "PROMPT", "stop": ["<|im_end|>"]},
        threading.Event(),
        temperature=0.5,  # extra kwarg
    )
    assert out == "ack"
    assert seen["prompt"] == "PROMPT"
    # The runner sees the loop's stop list + the extra kwarg.
    assert seen["kw"]["stop"] == ["<|im_end|>"]
    assert seen["kw"]["temperature"] == 0.5
    # ``last_usage`` records timing + sizes for the /runtime panel.
    assert a.last_usage is not None
    assert a.last_usage["prompt_chars"] == len("PROMPT")
    assert a.last_usage["response_chars"] == len("ack")


# ── parse_response ─────────────────────────────────────────────────


def test_parse_response_plain_text_no_tool_calls():
    a = HermesXMLAdapter(runner=lambda p, k: "")
    parsed = a.parse_response("the answer is 42")
    assert parsed == {"role": "assistant", "content": "the answer is 42"}


def test_parse_response_extracts_single_tool_call_and_strips_envelope():
    a = HermesXMLAdapter(runner=lambda p, k: "")
    raw = (
        'thinking… <tool_call>{"name": "get_time", "arguments": {"tz": "PST"}}'
        '</tool_call> done'
    )
    parsed = a.parse_response(raw)
    assert parsed["tool_calls"] is not None
    assert parsed["tool_calls"][0]["name"] == "get_time"
    assert parsed["tool_calls"][0]["arguments"] == {"tz": "PST"}
    # Envelope removed from visible content; surrounding text preserved.
    assert "thinking" in parsed["content"]
    assert "<tool_call>" not in parsed["content"]


def test_parse_response_handles_multiple_tool_calls():
    a = HermesXMLAdapter(runner=lambda p, k: "")
    raw = (
        '<tool_call>{"name": "a", "arguments": {}}</tool_call>'
        '<tool_call>{"name": "b", "arguments": {"k": 1}}</tool_call>'
    )
    parsed = a.parse_response(raw)
    assert [c["name"] for c in parsed["tool_calls"]] == ["a", "b"]


def test_parse_response_records_raw_text_for_diagnostics():
    a = HermesXMLAdapter(runner=lambda p, k: "")
    raw = "just text"
    a.parse_response(raw)
    assert a.last_raw_response == "just text"


def test_parse_response_returns_none_content_when_only_tool_call_present():
    """A response that's ONLY a tool-call envelope (no surrounding text)
    yields ``content=None`` — same shape Anthropic's tool-only response
    produces."""
    a = HermesXMLAdapter(runner=lambda p, k: "")
    raw = '<tool_call>{"name": "x", "arguments": {}}</tool_call>'
    parsed = a.parse_response(raw)
    assert parsed["content"] is None
    assert parsed["tool_calls"] is not None


# ── capabilities + health ──────────────────────────────────────────


def test_supports_reports_no_native_features():
    """Hermes-XML's parallel tool calls go via the drift parser, not a
    structured parallel-tools API — declare unsupported so the loop
    sequentialises by default."""
    a = HermesXMLAdapter(runner=lambda p, k: "")
    for feature in ("caching", "streaming", "parallel_tools", "vision", "reasoning"):
        assert a.supports(feature) is False


def test_health_check_returns_ok_when_runner_returns():
    a = HermesXMLAdapter(runner=lambda p, k: "pong")
    health = a.health_check()
    assert health["ok"] is True


def test_health_check_returns_failure_on_runner_exception():
    def _broken(p: str, k: dict[str, Any]) -> str:
        raise RuntimeError("model offline")

    a = HermesXMLAdapter(runner=_broken)
    health = a.health_check()
    assert health["ok"] is False
    assert "model offline" in health["detail"]


# ── end-to-end through JaegerAgent ─────────────────────────────────


def test_hermes_xml_adapter_drives_full_loop_to_completion():
    """The adapter round-trips a tool call through ``JaegerAgent``: the
    model emits ``<tool_call>``, the loop dispatches, the model finishes
    with plain text."""
    @register_tool("get_time", "Get time.", _Args)
    def _impl(tz: str = "UTC") -> dict:
        return {"now": "12:00", "tz": tz}

    responses = iter([
        '<tool_call>{"name": "get_time", "arguments": {"tz": "UTC"}}</tool_call>',
        "it is noon",
    ])

    def _runner(prompt: str, kw: dict[str, Any]) -> str:
        return next(responses)

    adapter = HermesXMLAdapter(runner=_runner)
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("what time is it?")
    assert result == "it is noon"
    assert [m["role"] for m in agent.messages] == [
        "user", "assistant", "tool", "assistant",
    ]
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    assert "12:00" in tool_msg["content"]
