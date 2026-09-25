"""Cancellation reaches the real loop, including the entry/late-signal races."""

import threading

from jaeger_agent import JaegerAgent, Message, ProviderAdapter
from jaeger_agent.core.cancellation import current_cancellation, turn_cancellation


class Adapter(ProviderAdapter):
    name = "cancellation-test"

    def __init__(self, event=None):
        self.event = event
        self.calls = 0
        self.started = threading.Event()

    def format_messages(self, messages, tools, system):
        return messages

    def call(self, formatted, interrupt_event, **kwargs):
        self.calls += 1
        self.started.set()
        if self.event is not None:
            assert interrupt_event is self.event
            assert interrupt_event.wait(2), "host cancellation never reached inference"
        return Message(role="assistant", content="done")

    def parse_response(self, raw):
        return raw

    def supports(self, feature):
        return False


def test_cancel_before_entry_is_not_cleared_and_next_turn_recovers():
    event = threading.Event()
    event.set()
    adapter = Adapter()
    agent = JaegerAgent(adapter=adapter, tools=[])
    with turn_cancellation(event):
        agent.run_turn("cancelled before start")
    assert adapter.calls == 0
    assert agent.last_halt_reason == "interrupted"
    assert current_cancellation() is None
    assert agent.run_turn("next") == "done"
    assert adapter.calls == 1


def test_cancel_during_inference_and_late_signal_is_request_scoped():
    event = threading.Event()
    adapter = Adapter(event)
    agent = JaegerAgent(adapter=adapter, tools=[])
    original = agent.interrupt_event
    errors = []

    def run():
        try:
            with turn_cancellation(event):
                agent.run_turn("long inference")
        except Exception as exc:  # noqa: BLE001 — return worker failures to pytest
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert adapter.started.wait(2)
        event.set()
        thread.join(3)
        assert not thread.is_alive()
        assert not errors
        assert agent.last_halt_reason == "interrupted"
        assert agent.interrupt_event is original
        assert not original.is_set()
    finally:
        event.set()
        thread.join(3)


def test_nested_cancellation_scopes_restore_the_host_scope():
    outer, inner = threading.Event(), threading.Event()
    with turn_cancellation(outer):
        with turn_cancellation(inner):
            assert current_cancellation() is inner
        assert current_cancellation() is outer
    assert current_cancellation() is None
