"""Tests for standalone jaeger-protocols package."""

from __future__ import annotations

from jaeger_protocols import build_a2ui_surface, to_acp_jsonrpc, to_agui_event


def test_agui_a2ui_and_acp_protocol_frames() -> None:
    ag = to_agui_event("text.delta", {"delta": "Hello"}, run_id="r1")
    assert ag["protocol"] == "ag-ui/1" and ag["type"] == "TEXT_MESSAGE_CONTENT"

    surf = build_a2ui_surface("yt_card", "Episode Review", [{"type": "button", "label": "Approve"}])
    assert surf["protocol"] == "a2ui/0.8" and len(surf["components"]) == 1

    acp = to_acp_jsonrpc("session/prompt", {"text": "status"}, req_id=1)
    assert acp["jsonrpc"] == "2.0" and acp["method"] == "session/prompt"
