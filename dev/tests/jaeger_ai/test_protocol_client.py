"""Client protocol + JrosClient SDK — the unified wire contract.

Tests the protocol builders/parse + drives ``JrosClient`` against a fake
bridge (no model boot) to pin the turn / tool-event / mid-turn-request flow.
"""

from __future__ import annotations

import sys

from jaeger_os.contract import protocol
from jaeger_ai.interfaces.client import JrosClient
from jaeger_ai.core.messages import AgentState, ChatReply, ToolEvent


def test_protocol_roundtrip_and_parse():
    assert protocol.parse("not json") is None
    assert protocol.parse('{"no":"discriminator"}') is None
    f = protocol.parse(protocol.encode(protocol.reply_frame("hi", None, "s1")))
    assert f == {"type": "reply", "text": "hi", "error": None, "session": "s1"}
    assert protocol.send_op("x", "s")["op"] == "send"
    assert protocol.quit_op() == {"op": "quit"}


def test_event_to_frame_maps_bus_messages():
    assert protocol.event_to_frame(ChatReply(text="r", session="s")) == \
        {"type": "reply", "text": "r", "error": None, "session": "s"}
    assert protocol.event_to_frame(AgentState(state="thinking", session="s")) == \
        {"type": "state", "busy": True, "session": "s"}
    assert protocol.event_to_frame(
        ToolEvent(name="web", phase="done", elapsed_s=1.0, session="s")) == \
        {"type": "tool", "name": "web", "phase": "done",
         "elapsed_s": 1.0, "session": "s"}


# A bridge that speaks the protocol without booting a model.
_FAKE_BRIDGE = r'''
import sys, json
def emit(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
emit({"type": "ready", "instance": "fake", "model": "m"})
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    req = json.loads(line)
    if req.get("op") == "quit": break
    if req.get("op") == "send":
        emit({"type": "state", "busy": True})
        emit({"type": "tool", "name": "echo", "phase": "done", "elapsed_s": 0.1})
        if "confirm" in req.get("text", ""):
            emit({"type": "request", "id": "r1", "kind": "approval",
                  "prompt": "ok?", "options": ["allow", "deny"]})
            resp = json.loads(sys.stdin.readline())
            emit({"type": "reply", "text": "answered:" + resp.get("answer", "?"),
                  "error": None})
        else:
            emit({"type": "reply", "text": "echo:" + req.get("text", ""),
                  "error": None})
        emit({"type": "state", "busy": False})
'''


def test_client_drives_a_bridge_turn():
    with JrosClient(command=[sys.executable, "-c", _FAKE_BRIDGE]) as c:
        assert c.ready == {"instance": "fake", "model": "m"}
        events: list[dict] = []
        out = c.turn("hello", on_event=events.append)
        assert out == {"text": "echo:hello", "error": None}
        assert any(e["type"] == "tool" and e["name"] == "echo" for e in events)


def test_client_answers_mid_turn_request():
    with JrosClient(command=[sys.executable, "-c", _FAKE_BRIDGE]) as c:
        c.start  # already started by __enter__
        out = c.turn("confirm please", on_request=lambda f: "allow")
        assert out["text"] == "answered:allow"
