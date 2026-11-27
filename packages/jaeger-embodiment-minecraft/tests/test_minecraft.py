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


def test_voyager_control_primitives_and_skill_library(tmp_path: Path) -> None:
    from jaeger_embodiment_minecraft import MinecraftSkillLibrary, load_control_primitives

    prims = load_control_primitives()
    assert "mineBlock" in prims and "craftItem" in prims and len(prims) >= 10

    lib = MinecraftSkillLibrary(tmp_path)
    s1 = lib.upsert_skill(
        name="craftWoodenPickaxe",
        description="Gather oak logs, craft planks, sticks, and a wooden pickaxe",
        code="async function craftWoodenPickaxe(bot) { /* verified */ }",
        tags=["craft", "pickaxe", "wood"],
    )
    assert s1.version == 1 and s1.verified_runs == 1
    hits = lib.retrieve("need a wooden pickaxe to mine stone")
    assert hits and hits[0].name == "craftWoodenPickaxe"


def test_mindcraft_coop_modes_actions_and_chat_inbox(tmp_path: Path) -> None:
    from jaeger_embodiment_minecraft.embodiment import MINEFLAYER_DIR

    assert (MINEFLAYER_DIR / "lib" / "coopModes.js").is_file()
    assert (MINEFLAYER_DIR / "lib" / "coopActions.js").is_file()
    assert (MINEFLAYER_DIR.parent.parent.parent / "NOTICE").is_file()

    mc = MinecraftEmbodiment(tmp_path)
    obs = mc.observe()
    modes = obs["state"]["modes"]
    assert modes["self_preservation"]["enabled"] is True
    assert modes["auto_eat"]["enabled"] is True
    assert modes["self_defense"]["enabled"] is True
    assert modes["unstuck"]["enabled"] is True
    assert modes["follow_player"]["enabled"] is False

    # Co-op follow, mode toggle, stop, eat, and chat inbox all work cleanly offline & persist
    follow_res = mc.act("follow_player", {"player": "Matthew", "distance": 4})
    assert follow_res["ok"] is True
    assert follow_res["state"]["modes"]["follow_player"] == {"enabled": True, "target": "Matthew", "distance": 4}

    mode_res = mc.act("set_mode", {"mode": "self_defense", "enabled": False})
    assert mode_res["ok"] is True
    assert mode_res["state"]["modes"]["self_defense"]["enabled"] is False

    stop_res = mc.act("stop_actions")
    assert stop_res["ok"] is True
    assert stop_res["state"]["modes"]["follow_player"]["enabled"] is False

    inbox = mc.act("read_chat")
    assert inbox["ok"] is True and isinstance(inbox["messages"], list) and isinstance(inbox["nearby_players"], list)
