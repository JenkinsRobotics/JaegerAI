"""Tests for jaeger_ai.features.channels scaffold."""

from __future__ import annotations

from typing import Any

from jaeger_ai.features.channels import (
    ChannelAdapter,
    InboundMessage,
    OutboundMessage,
    PluginBridgeAdapter,
    bundled_catalog,
    get_registry,
    register_plugin_bridge,
)
from jaeger_ai.features.channels.catalog import lookup_channel
from jaeger_ai.features.channels.registry import ChannelRegistry


class _StubAdapter:
    channel_id = "signal"

    def __init__(self) -> None:
        self.started = False
        self.sent: list[OutboundMessage] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def send(self, message: OutboundMessage) -> dict[str, Any]:
        self.sent.append(message)
        return {"sent": True, "recipient": message.recipient_id}


def test_bundled_catalog_includes_live_and_planned():
    all_rows = bundled_catalog()
    ids = {r.id for r in all_rows}
    assert {"discord", "telegram", "imessage", "whatsapp", "signal"} <= ids
    live_only = bundled_catalog(include_planned=False)
    assert all(r.status != "planned" for r in live_only)
    assert lookup_channel("tg").id == "telegram"


def test_registry_send_and_protocol():
    reg = ChannelRegistry()
    adapter = _StubAdapter()
    assert isinstance(adapter, ChannelAdapter)
    reg.register(adapter)
    assert reg.list_ids() == ["signal"]
    result = reg.send("signal", "u1", "hello", thread_id="t1")
    assert result["sent"] is True
    assert adapter.sent[0].text == "hello"
    assert adapter.sent[0].thread_id == "t1"
    assert reg.send("nope", "u", "x")["sent"] is False


def test_inbound_dataclass_and_global_registry_isolated():
    msg = InboundMessage(channel_id="discord", sender_id="1", text="hi")
    assert msg.text == "hi"
    # Global registry starts empty for this process unless something else registered.
    assert isinstance(get_registry().list_ids(), list)


class _FakePluginBridge:
    def __init__(self) -> None:
        self.started = False
        self.sent: list[tuple[str, str]] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def send(self, recipient: str, text: str) -> dict:
        self.sent.append((recipient, text))
        return {"sent": True, "channel_id": recipient}


def test_plugin_bridge_adapter_registers_on_protocol():
    reg = ChannelRegistry()
    bridge = _FakePluginBridge()
    adapter = register_plugin_bridge("discord", bridge, registry=reg)
    assert isinstance(adapter, PluginBridgeAdapter)
    assert isinstance(adapter, ChannelAdapter)
    assert reg.list_ids() == ["discord"]
    result = reg.send("discord", "99", "ping")
    assert result["sent"] is True
    assert bridge.sent == [("99", "ping")]
