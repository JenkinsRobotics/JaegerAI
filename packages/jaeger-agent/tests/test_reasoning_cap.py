"""Reasoning cap for local thinking models (capability run 2026-10-09).

gemma-4-26b on Ollama: at the provider default a 300-token step answered
nothing (all reasoning); ``reasoning_effort=low`` answered in 6.8 s and
``none`` in 3.5 s. The cap is sent for local models, and a step that still
exhausts its budget thinking is retried once with reasoning off.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest

from jaeger_agent import OpenAIAdapter
from jaeger_agent.loop.runtime_bridge import reasoning_effort_for


@pytest.mark.parametrize("provider,model,configured,expected", [
    ("ollama", "gemma-4-26b:latest", None, "low"),
    ("ollama", "gemma-4-26b:latest", "auto", "low"),
    ("ollama", "glm-5.1:cloud", "auto", None),
    ("lmstudio", "qwen3", "auto", "low"),
    ("openai", "gpt-5", "auto", None),
    ("ollama", "gemma-4-26b:latest", "provider", None),
    ("ollama", "gemma-4-26b:latest", "high", "high"),
    ("openai", "o4", "medium", "medium"),
])
def test_reasoning_effort_policy(provider, model, configured, expected):
    assert reasoning_effort_for(provider, model, configured) == expected


def test_format_sends_reasoning_effort_only_when_set():
    capped = OpenAIAdapter(provider="ollama", model="g", reasoning_effort="low", client=object())
    plain = OpenAIAdapter(provider="ollama", model="g", client=object())
    msgs = [{"role": "user", "content": "hi"}]
    assert capped.format_messages(msgs, [], "").get("reasoning_effort") == "low"
    assert "reasoning_effort" not in plain.format_messages(msgs, [], "")


def _resp(content, reasoning, finish):
    msg = SimpleNamespace(content=content, tool_calls=None, reasoning=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)], usage=None)


class _Seq:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_thinking_exhausted_step_is_retried_once_without_reasoning():
    client = _Seq([_resp("", "long thoughts...", "length"), _resp("391", None, "stop")])
    a = OpenAIAdapter(provider="ollama", model="g", reasoning_effort="low", client=client, stream_transport=False)
    raw = a.call(a.format_messages([{"role": "user", "content": "17*23?"}], [], ""), threading.Event())
    assert [c.get("reasoning_effort") for c in client.calls] == ["low", "none"]
    assert a.parse_response(raw)["content"] == "391"
    assert a.last_reasoning_retry is True


def test_answered_step_is_not_retried():
    client = _Seq([_resp("391", "brief", "stop")])
    a = OpenAIAdapter(provider="ollama", model="g", reasoning_effort="low", client=client, stream_transport=False)
    a.call(a.format_messages([{"role": "user", "content": "q"}], [], ""), threading.Event())
    assert len(client.calls) == 1


def test_no_retry_when_the_adapter_is_not_capping():
    client = _Seq([_resp("", "long thoughts...", "length")])
    a = OpenAIAdapter(provider="openai", model="o4", client=client, stream_transport=False)
    a.call(a.format_messages([{"role": "user", "content": "q"}], [], ""), threading.Event())
    assert len(client.calls) == 1
