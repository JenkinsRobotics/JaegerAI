"""The channel-agnostic messaging layer — shared by every bridge so the agent
acts the same on Telegram / Discord / iMessage (approvals + /mode + admin gate).
"""

import time

from jaeger_os.plugins import _messaging


def test_mode_command_parse() -> None:
    assert _messaging.mode_command("hello") == {}        # not a command
    assert _messaging.mode_command("/other") == {}        # different command
    r = _messaging.mode_command("/mode")                  # status
    assert "reply" in r and "mode:" in r["reply"]
    r = _messaging.mode_command("/mode high")             # switch
    assert r.get("switch") == "high" and "ack" in r
    r = _messaging.mode_command("/mode bogus")            # unknown
    assert "reply" in r and "unknown" in r["reply"]


def test_mode_result_formats_ok_and_error() -> None:
    assert "◆ mode: high" in _messaging.mode_result({"ok": True, "mode": "high"}, "high")
    assert _messaging.mode_result({"ok": False, "error": "boom"}, "high").startswith("✗")


def test_request_to_prompt_routes_only_its_channel() -> None:
    awaiting: dict = {}
    msg = type("R", (), {"session": "discord:123", "id": "rid",
                         "prompt": "Allow X?", "options": ("allow", "deny")})()
    out = _messaging.request_to_prompt("discord", msg, awaiting)
    assert out is not None
    recipient, text = out
    assert recipient == "123" and "Allow X?" in text and awaiting["123"] == "rid"
    # a request for a different channel is ignored (no cross-channel theft)
    assert _messaging.request_to_prompt("telegram", msg, {}) is None


def test_reply_as_approval_publishes_response() -> None:
    from jaeger_os.app.bus.inproc import InProcBus
    from jaeger_os.core.messages import AgentResponse

    bus = InProcBus()
    got: list = []
    bus.subscribe(AgentResponse.topic, lambda m: got.append((m.id, m.answer, m.session)))
    awaiting = {"55": "rid9"}
    assert _messaging.reply_as_approval("telegram", "55", "allow", awaiting, bus) is True
    time.sleep(0.1)
    assert got and got[0] == ("rid9", "allow", "telegram:55")
    assert "55" not in awaiting
    assert _messaging.reply_as_approval("telegram", "99", "x", awaiting, bus) is False
    bus.close()


def test_parse_admin_ids() -> None:
    assert _messaging.parse_admin_ids("123, 456 ,789") == {"123", "456", "789"}
    assert _messaging.parse_admin_ids("") == set()
