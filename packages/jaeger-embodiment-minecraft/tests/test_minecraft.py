"""Tests for standalone jaeger-embodiment-minecraft package."""

from __future__ import annotations

from pathlib import Path

from jaeger_contracts import EmbodimentPort
from jaeger_embodiment_minecraft import MinecraftEmbodiment


def test_minecraft_embodiment_persistence_and_preemption(tmp_path: Path) -> None:
    mc = MinecraftEmbodiment(tmp_path)
    assert isinstance(mc, EmbodimentPort)
    assert mc.bridge_info()["bridge_present"] is True

    mc.act("set_goal", {"goal": "Build iron farm"})
    mc.act("move_to", {"x": 140, "y": 64, "z": -32})
    mc.act("gather", {"item": "oak_log", "count": 16})
    cp = mc.pause(reason="owner_work_youtube_script")
    assert cp["ok"] is True

    # Simulate restart -> restores exact multi-day coordinates, inventory & goal!
    mc2 = MinecraftEmbodiment(tmp_path)
    obs = mc2.observe()
    assert obs["state"]["active_goal"] == "Build iron farm"
    assert obs["state"]["position"]["x"] == 140
    assert obs["state"]["inventory"]["oak_log"] == 16

    # E-Stop refuses further actions until released
    mc2.estop("operator_halt")
    res = mc2.act("move_to", {"x": 200})
    assert res["ok"] is False and "estop" in res["error"]
