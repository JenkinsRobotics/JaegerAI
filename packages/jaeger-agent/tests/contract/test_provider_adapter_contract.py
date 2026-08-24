"""Shared ProviderAdapter contract.

A fake adapter proves the loop-facing surface. Concrete adapters
(OpenAI, Anthropic, local llama, MLX) must remain subclasses so a
new backend cannot skip the ABC.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from jaeger_agent.adapters.anthropic import AnthropicAdapter
from jaeger_agent.adapters.base import KNOWN_FEATURES, ProviderAdapter
from jaeger_agent.adapters.hermes_xml import HermesXMLAdapter
from jaeger_agent.adapters.local_llama import LocalLlamaAdapter
from jaeger_agent.adapters.mlx import MLXAdapter
from jaeger_agent.adapters.openai import OpenAIAdapter
from jaeger_agent.schemas.message_types import Message
from jaeger_os.core.tools.tool_schema import ToolDef


class FakeAdapter(ProviderAdapter):
    name = "fake"

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.calls = 0

    def format_messages(self, messages, tools, system):
        return {"messages": messages, "system": system, "tools": tools}

    def call(self, formatted, interrupt_event, **kwargs):
        if interrupt_event.is_set():
            raise TimeoutError("interrupted")
        self.calls += 1
        return {"text": self.reply, "formatted": formatted}

    def parse_response(self, raw) -> Message:
        return Message(role="assistant", content=str(raw.get("text") or ""))

    def supports(self, feature: str) -> bool:
        return False


def test_fake_adapter_round_trips_a_text_turn():
    adapter = FakeAdapter("hello")
    formatted = adapter.format_messages(
        [Message(role="user", content="hi")],
        [],
        "you are a test",
    )
    raw = adapter.call(formatted, threading.Event())
    parsed = adapter.parse_response(raw)
    assert parsed["role"] == "assistant"
    assert parsed["content"] == "hello"
    assert adapter.calls == 1


def test_fake_adapter_honours_interrupt():
    adapter = FakeAdapter()
    ev = threading.Event()
    ev.set()
    with pytest.raises(TimeoutError):
        adapter.call({"messages": []}, ev)


def test_health_check_shape():
    result = FakeAdapter().health_check()
    assert "ok" in result
    assert "detail" in result


@pytest.mark.parametrize("cls", [
    OpenAIAdapter, AnthropicAdapter, LocalLlamaAdapter, MLXAdapter, HermesXMLAdapter,
])
def test_production_adapters_are_provider_adapters(cls):
    assert issubclass(cls, ProviderAdapter)
    for method in ("format_messages", "call", "parse_response", "supports"):
        assert hasattr(cls, method)


def test_known_features_are_the_capability_vocabulary():
    assert "streaming" in KNOWN_FEATURES
    assert "reasoning" in KNOWN_FEATURES
    assert FakeAdapter().supports("streaming") is False
