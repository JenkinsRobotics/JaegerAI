"""Tests for WebUI clarify wire (vendor API + native adapter broker)."""

from __future__ import annotations

import threading
import time

from jaeger_ai.features.webui import clarify_wire
from jaeger_ai.features.webui.clarify_wire import ClarifyBroker


def test_clarify_wire_describes_vendor_authority():
    info = clarify_wire.describe_wire()
    assert info["mode"] == "wire"
    assert "vendor/hermes-webui/api/clarify.py" in info["authority"]
    assert info["routes"]["pending"] == "/api/clarify/pending"
    assert info["chat_port"] == 8790
    assert "adapter_respond" in info["routes"]
    assert "ClarifyBroker" in info["native_broker"]
    assert "live" in info["status"]


def test_clarify_broker_submit_wait_respond():
    broker = ClarifyBroker(timeout_s=5)
    pending = broker.submit(session_key="s1", question="Which file?", clarify_id="c1")
    assert pending["clarify_id"] == "c1"
    assert broker.get_pending("s1")["question"] == "Which file?"

    answered: list[str] = []

    def _wait() -> None:
        answered.append(broker.wait("c1"))

    t = threading.Thread(target=_wait, daemon=True)
    t.start()
    time.sleep(0.05)
    assert broker.respond("c1", "README.md") is True
    t.join(timeout=2)
    assert answered == ["README.md"]
    assert broker.get_pending("s1") is None


def test_clarify_broker_timeout_returns_empty():
    broker = ClarifyBroker(timeout_s=0.05)
    broker.submit(session_key="s1", question="?", clarify_id="late")
    assert broker.wait("late") == ""
