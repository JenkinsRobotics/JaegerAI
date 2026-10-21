"""The channel-agnostic messaging layer — shared by every bridge so the agent
acts the same on Telegram / Discord / iMessage (approvals + /mode + admin gate).
"""

import time
import pytest

from jaeger_ai.plugins import _messaging


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
    from jaeger_os.transport import InProcBus
    from jaeger_ai.core.messages import AgentResponse

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


@pytest.mark.parametrize('bridge_path', ['discord', 'telegram', 'imessage'])
def test_bridge_handler_type_error_after_effect_is_never_replayed(bridge_path):
    import importlib
    module=importlib.import_module('jaeger_ai.plugins.'+bridge_path+'.bridge')
    cls=getattr(module,{'discord':'DiscordBridge','telegram':'TelegramBridge','imessage':'IMessageBridge'}[bridge_path])
    bridge=cls.__new__(cls)
    calls=[]
    def handler(text,session_key=None):
        calls.append((text,session_key))
        raise TypeError('owned error after admitted effect')
    bridge._handler=handler
    with pytest.raises(TypeError,match='after admitted effect'):
        bridge._call_handler('owned text','owned-session')
    assert calls==[('owned text','owned-session')]


def test_handler_signature_is_selected_without_executing_a_probe():
    from jaeger_ai.plugins._messaging import call_handler_once
    calls=[]
    def legacy(text):
        calls.append(text);return 'owned reply'
    assert call_handler_once(legacy,'owned text',session_key='owned-session')=='owned reply'
    assert calls==['owned text']
    def unsupported(text,required_other_argument):
        calls.append('must not run')
    with pytest.raises(TypeError):
        call_handler_once(unsupported,'owned text',session_key='owned-session')
    assert calls==['owned text']
