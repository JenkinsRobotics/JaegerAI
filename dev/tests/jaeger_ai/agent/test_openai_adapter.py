"""``OpenAIAdapter`` — unit tests with an injected fake SDK client.

Covers the wire-format quirks that distinguish OpenAI from Anthropic
(JSON-string ``arguments``, ``tool`` role at top level, system inside
``messages``) plus the per-provider construction differences (placeholder
keys for local servers, base URL routing for Gemini / Ollama Cloud / LM
Studio).
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_ai.agent import OpenAIAdapter
from jaeger_ai.agent.adapters.openai import KNOWN_PROVIDERS
from jaeger_os.core.tools.tool_schema import ToolDef


# ── fake SDK client ────────────────────────────────────────────────


class _FakeCompletions:
    def __init__(self, response: Any):
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return self._response


class _FakeChat:
    def __init__(self, response: Any):
        self.completions = _FakeCompletions(response)


class _FakeModels:
    def __init__(self, raise_exc: Exception | None = None):
        self._raise = raise_exc

    def list(self) -> Any:
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(data=[])


class _FakeClient:
    def __init__(self, response: Any, models_raise: Exception | None = None):
        self.chat = _FakeChat(response)
        self.models = _FakeModels(models_raise)


def _mk_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    usage: dict[str, int] | None = None,
) -> Any:
    """Build an object shaped enough like a chat-completions response
    for ``parse_response`` — ``choices[0].message`` with ``content`` and
    optional ``tool_calls``."""
    raw_tcs = []
    for tc in (tool_calls or []):
        raw_tcs.append(SimpleNamespace(
            id=tc["id"],
            type="function",
            function=SimpleNamespace(
                name=tc["name"],
                arguments=tc["arguments"]
                if isinstance(tc["arguments"], str)
                else json.dumps(tc["arguments"]),
            ),
        ))
    message = SimpleNamespace(content=content, tool_calls=raw_tcs or None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage_obj = SimpleNamespace(**(usage or {})) if usage is not None else None
    return SimpleNamespace(choices=[choice], usage=usage_obj)


# ── tool / args fixtures ───────────────────────────────────────────


class _Args(BaseModel):
    x: int = Field(ge=0)


def _mk_tool() -> ToolDef:
    return ToolDef(
        name="bump",
        description="Bump a counter.",
        args_model=_Args,
        fn=lambda x: {"x_plus_one": x + 1},
    )


# ── construction + provider variants ───────────────────────────────


def test_known_providers_includes_the_five_supported_backends():
    assert {"openai", "lmstudio", "ollama", "ollama-cloud", "gemini"} == KNOWN_PROVIDERS


def test_local_servers_get_placeholder_key_when_none_supplied():
    a = OpenAIAdapter(provider="lmstudio", model="x", base_url="http://localhost:1234/v1")
    assert a._resolve_key() == "lm-studio"
    b = OpenAIAdapter(provider="ollama", model="x", base_url="http://localhost:11434/v1")
    assert b._resolve_key() == "ollama"


def test_cloud_providers_get_no_placeholder_key():
    """``openai`` / ``ollama-cloud`` / ``gemini`` legitimately require
    a real key; no placeholder should be injected."""
    a = OpenAIAdapter(provider="openai", model="x")
    assert a._resolve_key() == ""
    b = OpenAIAdapter(provider="ollama-cloud", model="x")
    assert b._resolve_key() == ""
    c = OpenAIAdapter(provider="gemini", model="x")
    assert c._resolve_key() == ""


def test_explicit_api_key_wins_over_placeholder():
    a = OpenAIAdapter(provider="lmstudio", model="x", api_key="real-key")
    assert a._resolve_key() == "real-key"


def test_describe_includes_provider_model_and_endpoint():
    a = OpenAIAdapter(
        provider="gemini",
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    desc = a.describe()
    assert "gemini" in desc
    assert "gemini-2.0-flash" in desc
    assert "generativelanguage" in desc


def test_name_reflects_provider_for_status_line():
    a = OpenAIAdapter(provider="ollama-cloud", model="x")
    assert a.name == "ollama-cloud"


# ── format_messages ────────────────────────────────────────────────


def test_format_messages_prepends_top_level_system_as_first_message():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    out = a.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        system="you are a robot",
    )
    assert out["messages"][0] == {"role": "system", "content": "you are a robot"}
    assert out["messages"][1] == {"role": "user", "content": "hi"}


def test_format_messages_translates_assistant_tool_calls_to_function_objects():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    out = a.format_messages(
        messages=[
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "calling",
                "tool_calls": [
                    {"id": "c1", "name": "bump", "arguments": {"x": 1}},
                ],
            },
        ],
        tools=[],
        system="",
    )
    assistant = out["messages"][1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "calling"
    tool_call = assistant["tool_calls"][0]
    assert tool_call == {
        "id": "c1",
        "type": "function",
        "function": {"name": "bump", "arguments": '{"x": 1}'},
    }


def test_format_messages_assistant_with_no_text_keeps_content_none():
    """When the model only made tool calls, ``content`` is ``None`` —
    OpenAI accepts the explicit null, but the key must still be present."""
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    out = a.format_messages(
        messages=[
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "name": "bump", "arguments": {}}],
            },
        ],
        tools=[],
        system="",
    )
    assert out["messages"][0]["content"] is None
    assert "tool_calls" in out["messages"][0]


def test_format_messages_tool_role_carries_tool_call_id_at_top_level():
    """Unlike Anthropic (tool_result nested in user), OpenAI keeps the
    tool role at top level with ``tool_call_id``."""
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    out = a.format_messages(
        messages=[
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "bump",
                "content": '{"x_plus_one": 2}',
            },
        ],
        tools=[],
        system="",
    )
    assert out["messages"][0] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": '{"x_plus_one": 2}',
    }


def test_format_messages_includes_tools_with_openai_schema():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    out = a.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[_mk_tool()],
        system="",
    )
    assert "tools" in out
    assert out["tools"][0]["type"] == "function"
    assert out["tools"][0]["function"]["name"] == "bump"


def test_format_messages_coerces_non_string_tool_content():
    """Internal tool results are arbitrary Python; the adapter stringifies
    via ``json.dumps`` so the wire payload is always a string."""
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    out = a.format_messages(
        messages=[
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "bump",
                "content": {"ok": True, "x_plus_one": 2},  # dict instead of str
            },
        ],
        tools=[],
        system="",
    )
    assert out["messages"][0]["content"] == '{"ok": true, "x_plus_one": 2}'


def test_format_messages_unknown_role_raises():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    with pytest.raises(ValueError, match="unknown message role"):
        a.format_messages(
            messages=[{"role": "alien", "content": "??"}],
            tools=[],
            system="",
        )


def test_format_messages_temperature_top_p_max_tokens_carried_through():
    a = OpenAIAdapter(
        provider="openai", model="x",
        max_tokens=512, temperature=0.7, top_p=0.5,
        client=_FakeClient(_mk_response("ok")),
    )
    out = a.format_messages([{"role": "user", "content": "hi"}], [], "")
    assert out["max_tokens"] == 512
    assert out["temperature"] == 0.7
    assert out["top_p"] == 0.5


# ── call ───────────────────────────────────────────────────────────


def test_call_dispatches_to_chat_completions_with_merged_kwargs():
    fake = _FakeClient(_mk_response("hi"))
    a = OpenAIAdapter(
        provider="openai", model="x", stream_transport=False, client=fake,
    )
    out = a.call(
        {"model": "x", "messages": [], "max_tokens": 4096, "temperature": 0.0, "top_p": 0.95},
        threading.Event(),
        seed=42,  # extra kwarg
    )
    assert out is fake.chat.completions._response
    assert fake.chat.completions.last_kwargs is not None
    assert fake.chat.completions.last_kwargs["seed"] == 42


def _mk_chunk(
    content: str | None = None,
    tool_call: dict[str, Any] | None = None,
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
) -> Any:
    """One streaming chunk in the SDK's delta shape."""
    tcs = None
    if tool_call is not None:
        tcs = [SimpleNamespace(
            index=tool_call.get("index", 0),
            id=tool_call.get("id"),
            function=SimpleNamespace(
                name=tool_call.get("name"),
                arguments=tool_call.get("arguments"),
            ),
        )]
    delta = SimpleNamespace(content=content, tool_calls=tcs)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(**usage) if usage else None,
    )


class _FakeStream:
    """Iterable of chunks with a ``close`` the aggregator must call."""

    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        return iter(self._chunks)

    def close(self) -> None:
        self.closed = True


def test_call_streams_transport_by_default_and_aggregates():
    """Default posture: the request is streamed (``stream=True`` on the
    wire) and the chunks are re-aggregated into the plain response
    shape ``parse_response`` reads — fragmented tool-call arguments
    reassembled, usage captured, stream closed."""
    stream = _FakeStream([
        _mk_chunk(content="Hello "),
        _mk_chunk(content="world"),
        _mk_chunk(tool_call={"index": 0, "id": "c1", "name": "bump",
                             "arguments": '{"x"'}),
        _mk_chunk(tool_call={"index": 0, "arguments": ": 5}"}),
        _mk_chunk(finish_reason="tool_calls",
                  usage={"prompt_tokens": 7, "completion_tokens": 3,
                         "total_tokens": 10}),
    ])

    class _StreamingClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=self)
            self.last_kwargs: dict[str, Any] | None = None

        def create(self, **kwargs: Any) -> Any:
            self.last_kwargs = kwargs
            return stream

    client = _StreamingClient()
    a = OpenAIAdapter(provider="openai", model="x", client=client)
    raw = a.call({"model": "x", "messages": []}, threading.Event())

    assert client.last_kwargs["stream"] is True
    # The real OpenAI endpoint also gets the usage opt-in.
    assert client.last_kwargs["stream_options"] == {"include_usage": True}
    assert stream.closed is True

    parsed = a.parse_response(raw)
    assert parsed["content"] == "Hello world"
    assert parsed["tool_calls"][0]["name"] == "bump"
    assert parsed["tool_calls"][0]["arguments"] == {"x": 5}
    assert parsed["finish_reason"] == "tool_calls"
    assert raw["usage"]["total_tokens"] == 10


def test_call_compat_providers_do_not_send_stream_options():
    """LM Studio / Ollama / Gemini-compat servers may reject the
    OpenAI-only ``stream_options`` field — it must stay off the wire
    for every provider except the real endpoint."""
    stream = _FakeStream([_mk_chunk(content="ok", finish_reason="stop")])

    class _StreamingClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=self)
            self.last_kwargs: dict[str, Any] | None = None

        def create(self, **kwargs: Any) -> Any:
            self.last_kwargs = kwargs
            return stream

    client = _StreamingClient()
    a = OpenAIAdapter(provider="lmstudio", model="x", client=client)
    a.call({"model": "x", "messages": []}, threading.Event())
    assert client.last_kwargs["stream"] is True
    assert "stream_options" not in client.last_kwargs


def test_call_interrupt_mid_stream_closes_and_raises():
    """An interrupt observed between chunks must close the HTTP stream
    (so the server stops generating) and surface AgentInterrupted."""
    from jaeger_ai.agent.loop.interrupt import AgentInterrupted

    ev = threading.Event()

    class _EndlessStream(_FakeStream):
        def __iter__(self):
            def _gen():
                yield _mk_chunk(content="a")
                ev.set()  # interrupt arrives while streaming
                yield _mk_chunk(content="b")
                yield _mk_chunk(content="c")
            return _gen()

    stream = _EndlessStream([])

    class _StreamingClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs: Any) -> Any:
            return stream

    a = OpenAIAdapter(provider="openai", model="x", client=_StreamingClient())
    with pytest.raises(AgentInterrupted):
        a.call({"model": "x", "messages": []}, ev)
    assert stream.closed is True


def test_call_omits_stream_when_transport_streaming_disabled():
    fake = _FakeClient(_mk_response("hi"))
    a = OpenAIAdapter(
        provider="openai", model="x", stream_transport=False, client=fake,
    )
    a.call({"model": "x", "messages": []}, threading.Event())
    assert "stream" not in fake.chat.completions.last_kwargs


# ── parse_response ─────────────────────────────────────────────────


def test_parse_response_returns_assistant_text_only():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("hi")))
    parsed = a.parse_response(_mk_response(content="hello"))
    # Phase-8: ``finish_reason`` is surfaced when the SDK provides it
    # so the agent's length-retry logic can read it. The other fields
    # stay pinned.
    assert parsed["role"] == "assistant"
    assert parsed["content"] == "hello"
    assert "tool_calls" not in parsed


def test_parse_response_lifts_tool_calls_with_json_decoded_arguments():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    raw = _mk_response(
        content=None,
        tool_calls=[{"id": "c1", "name": "bump", "arguments": {"x": 3}}],
    )
    parsed = a.parse_response(raw)
    assert parsed["role"] == "assistant"
    assert parsed["content"] is None
    assert parsed["tool_calls"] == [
        {"id": "c1", "name": "bump", "arguments": {"x": 3}},
    ]


def test_parse_response_decodes_malformed_json_to_raw_arguments_field():
    """A model emitting malformed JSON in ``arguments`` must not crash
    parsing — surface the raw string so the tool dispatcher can return
    a ValidationError-style result and the model self-corrects."""
    raw = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(
                id="c1",
                type="function",
                function=SimpleNamespace(name="bump", arguments='{"x": broken'),
            )],
        ))],
        usage=None,
    )
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    parsed = a.parse_response(raw)
    assert parsed["tool_calls"][0]["arguments"] == {"_raw_arguments": '{"x": broken'}


def test_parse_response_handles_empty_choices():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    parsed = a.parse_response(SimpleNamespace(choices=[], usage=None))
    assert parsed == {"role": "assistant", "content": None}


def test_parse_response_stashes_usage_on_adapter():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    raw = _mk_response(
        content="hi",
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    )
    a.parse_response(raw)
    assert a.last_usage == {
        "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
    }


def test_parse_response_accepts_dict_shape_for_streaming_aggregators():
    """A streaming aggregator may yield plain dicts; the parse path must
    cope with either typed objects or dicts."""
    raw = {
        "choices": [{
            "message": {
                "content": "from dict",
                "tool_calls": [
                    {"id": "c1", "type": "function",
                     "function": {"name": "bump", "arguments": '{"x": 9}'}},
                ],
            },
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    parsed = a.parse_response(raw)
    assert parsed["content"] == "from dict"
    assert parsed["tool_calls"][0]["arguments"] == {"x": 9}
    assert a.last_usage["total_tokens"] == 2


# ── capabilities + health ──────────────────────────────────────────


def test_supports_streaming_is_false_token_streaming_not_exposed():
    """Transport-level streaming is an implementation detail of
    ``call`` — the loop still receives one whole message per step, so
    the capability the loop would key off stays False regardless of
    the transport flag."""
    a = OpenAIAdapter(provider="openai", model="x", stream_transport=False)
    b = OpenAIAdapter(provider="openai", model="x", stream_transport=True)
    assert a.supports("streaming") is False
    assert b.supports("streaming") is False


def test_supports_parallel_tools_true_by_default():
    a = OpenAIAdapter(provider="openai", model="x")
    assert a.supports("parallel_tools") is True


def test_supports_caching_false_no_marker_protocol():
    """OpenAI does prompt caching transparently; there's no marker API
    for the agent loop to drive. Report it as unsupported so callers
    don't add cache markers that get ignored."""
    a = OpenAIAdapter(provider="openai", model="x")
    assert a.supports("caching") is False


def test_health_check_returns_ok_on_models_list_success():
    a = OpenAIAdapter(provider="openai", model="x", client=_FakeClient(_mk_response("ok")))
    health = a.health_check()
    assert health["ok"] is True


def test_health_check_returns_failure_with_classified_message():
    a = OpenAIAdapter(
        provider="openai", model="x",
        client=_FakeClient(_mk_response("ok"), models_raise=RuntimeError("401: bad key")),
    )
    health = a.health_check()
    assert health["ok"] is False
    assert "RuntimeError" in health["detail"]
    assert "bad key" in health["detail"]


# ── round-trip with JaegerAgent ────────────────────────────────────


def test_openai_adapter_drives_jaeger_agent_loop_to_completion():
    """End-to-end smoke: ``JaegerAgent`` drives the adapter, dispatches
    a tool, gets a final answer. Confirms the OpenAI wire format
    round-trips cleanly through the loop."""
    from jaeger_ai.agent import (
        JaegerAgent,
        clear_registry,
        register_tool,
    )

    clear_registry()
    try:
        @register_tool("bump", "Bump.", _Args)
        def _impl(x: int) -> dict:
            return {"x_plus_one": x + 1}

        # Adapter returns: turn 1 → tool call; turn 2 → final text.
        # Stash both responses on a tiny script so the fake client can
        # serve them in order.
        responses = [
            _mk_response(
                content=None,
                tool_calls=[{"id": "c1", "name": "bump", "arguments": {"x": 5}}],
            ),
            _mk_response(content="x_plus_one is 6"),
        ]

        class _ScriptedClient:
            def __init__(self, responses: list[Any]) -> None:
                self._responses = list(responses)
                self.chat = SimpleNamespace(completions=self)

            def create(self, **_):
                return self._responses.pop(0)

        adapter = OpenAIAdapter(
            provider="openai", model="x", stream_transport=False,
            client=_ScriptedClient(responses),
        )
        agent = JaegerAgent(adapter=adapter)
        result = agent.run_turn("bump 5")
        assert result == "x_plus_one is 6"
        # user → assistant(tool_call) → tool(result) → assistant(final)
        assert [m["role"] for m in agent.messages] == [
            "user", "assistant", "tool", "assistant",
        ]
    finally:
        clear_registry()
