"""Tests for WebUI clarify wire (vendor API, no new folder)."""

from __future__ import annotations

from jaeger_ai.features.webui import clarify_wire


def test_clarify_wire_describes_vendor_authority():
    info = clarify_wire.describe_wire()
    assert info["mode"] == "wire"
    assert "vendor/hermes-webui/api/clarify.py" in info["authority"]
    assert info["routes"]["pending"] == "/api/clarify/pending"
    assert info["chat_port"] == 8790
