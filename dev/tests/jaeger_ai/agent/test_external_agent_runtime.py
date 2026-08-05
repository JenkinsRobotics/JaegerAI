"""JaegerAI 0.10 consumes the external JaegerAgent runtime boundary."""

from __future__ import annotations

import queue
import types

from jaeger_agent import AgentBridge, Message, OpenAIAdapter, ProviderAdapter
from jaeger_agent import JaegerAgent
from jaeger_ai.core.agent_core import AgentCore
from jaeger_ai.core.messages import ChatMessage, ChatReply
from jaeger_os.transport import InProcBus


class _StubAdapter(ProviderAdapter):
    """Enough adapter to construct an agent. Never called."""

    name = "stub"

    def format_messages(self, messages, tools, system):
        return {}

    def call(self, formatted, interrupt_event, **kwargs):
        return {}

    def parse_response(self, raw) -> Message:
        return Message(role="assistant", content="")

    def supports(self, feature: str) -> bool:
        return False


def test_public_agent_kernel_is_supplied_by_jaeger_agent() -> None:
    """JaegerAI must not retain a second portable agent implementation."""

    assert Message.__module__.startswith("jaeger_agent")
    assert ProviderAdapter.__module__.startswith("jaeger_agent")
    assert OpenAIAdapter.__module__.startswith("jaeger_agent")
    # 0.11: this used to check ``__mro__[1]`` — the base of JaegerAI's
    # JaegerAgent SUBCLASS, which injected toolset resolution, tool
    # visibility and the per-turn file tracker. All three moved into the
    # module and became its defaults, so the subclass had nothing left to
    # add and was deleted. The class itself is now the module's, and
    # ``__mro__[1]`` is plain ``object``.
    assert JaegerAgent.__module__.startswith("jaeger_agent")
    assert JaegerAgent.__mro__[1] is object, (
        "a JaegerAI subclass reappeared — check whether what it injects "
        "belongs in jaeger_agent as a default instead"
    )


def test_the_module_defaults_its_own_tool_policy() -> None:
    """What the deleted subclass used to inject, the module now supplies.

    An embedder that never heard of JaegerAI must still get toolset
    scoping and the per-turn read tracker; without these defaults they
    silently got nothing.
    """
    agent = JaegerAgent(adapter=_StubAdapter())
    assert agent._toolset_resolver is not None
    assert agent._tool_visibility is not None
    assert agent._turn_start_hook is not None


def test_agent_core_round_trips_through_jaeger_agent(monkeypatch) -> None:
    import jaeger_ai.main as main

    cleaned: list[bool] = []
    monkeypatch.setattr(
        main,
        "boot_for_tui",
        lambda **_: types.SimpleNamespace(
            client=object(),
            cleanup=lambda: cleaned.append(True),
        ),
    )
    monkeypatch.setattr(
        main,
        "run_for_voice",
        lambda _client, text, session_key="gui": {
            "text": f"external: {text}",
            "error": None,
        },
    )

    bus = InProcBus()
    replies: queue.Queue[ChatReply] = queue.Queue()
    bus.subscribe(ChatReply.topic, replies.put)
    core = AgentCore(bus=bus, warmup=False)
    try:
        core.setup()
        assert isinstance(core.bridge, AgentBridge)
        assert core.bridge.__class__.__module__.startswith("jaeger_agent")
        bus.publish(ChatMessage(text="hello", session="test-session"))
        reply = replies.get(timeout=3.0)
        assert reply.text == "external: hello"
        assert reply.session == "test-session"
    finally:
        core.stop()
        bus.close()

    assert cleaned == [True]
