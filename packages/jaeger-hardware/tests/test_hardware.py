"""Tests for standalone jaeger-hardware package (JP01 protocol + E-Stop latch)."""

from __future__ import annotations

import pytest

from jaeger_contracts import EmbodimentPort
from jaeger_hardware import AsciiBracketProtocol, EStopLatch, JP01Embodiment


def test_jp01_protocol_clamping_and_estop_latch() -> None:
    proto = AsciiBracketProtocol()
    assert proto.encode({"header": "MJ", "args": [90, 100, 10]}) == b"MJ[90,100,10]\n"
    evs = proto.feed(b"STATUS UPDATE temp=38C\nOK\n")
    assert evs[0].kind == "telemetry" and evs[1].kind == "line"

    latch = EStopLatch()
    bot = JP01Embodiment(estop_latch=latch, dry_run=True)
    assert isinstance(bot, EmbodimentPort)

    # Out-of-range pan is clamped safely to [30, 150]
    res = bot.act("head_move", {"pan_deg": 999, "tilt_deg": 95, "speed": 50})
    assert res["ok"] is True and res["pose"]["pan_deg"] == 150 and res["frame"] == "MJ[150,95,50]"

    # E-Stop refuses motion and refuses non-operator release!
    bot.estop("human_too_close")
    refused = bot.act("head_move", {"pan_deg": 90})
    assert refused["ok"] is False and "e-stop latched" in refused["error"]
    with pytest.raises(PermissionError):
        latch.release(source="agent")
    latch.release(source="operator")
    assert bot.act("face_expression", {"mood": "warm"})["ok"] is True
