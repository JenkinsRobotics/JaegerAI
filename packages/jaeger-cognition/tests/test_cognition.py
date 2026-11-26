"""Unit tests for jaeger-cognition: persistent world model, temporal awareness & 24/7 life loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_cognition import CognitiveLifeLoop, WorldModelStore
from jaeger_orchestration import ResourceGovernor


@pytest.mark.asyncio
async def test_cognitive_life_loop_runs_independently_of_chat_and_respects_priority(tmp_path: Path) -> None:
    world = WorldModelStore(tmp_path)
    gov = ResourceGovernor(memory_cap_gb=24.0, idle_cooldown_s=0.0)
    transitions: list[dict] = []
    mind = CognitiveLifeLoop(world=world, governor=gov, tick_interval_s=0.05, on_state_change=transitions.append)

    mc_steps: list[int] = []
    mind.register_idle_life_handler(
        "minecraft",
        lambda ctx: (mc_steps.append(ctx["tick"]), {"acted": True, "focus": "Mining iron in Minecraft", "emotion": "happy"})[1],
    )

    # 1. Perception ingestion updates evolving world model
    ev = mind.ingest_perception(modality="vision", kind="owner_present", payload={"room": "studio"}, salience=0.9)
    assert ev.modality == "vision"
    assert world.get("perception", "last_vision")["room"] == "studio"

    # 2. Idle tick runs Tier 3 Idle Life (Minecraft) without any chat prompt!
    st1 = await mind.step_once(trigger="temporal_tick")
    assert st1.mode == "idle_life"
    assert st1.emotion == "happy"
    assert len(mc_steps) == 1
    assert world.get("temporal", "clock")["tick"] == 1

    # 3. Owner Work arrives -> CognitiveLoop immediately yields to serving_owner and skips Minecraft!
    gov.begin_owner_work("youtube_script")
    st2 = await mind.step_once(trigger="owner_active")
    assert st2.mode == "serving_owner"
    assert st2.emotion == "focused"
    assert len(mc_steps) == 1  # Minecraft did NOT run while owner was active
    gov.end_owner_work()

    # 4. E-Stop latches -> CognitiveLoop halts immediately
    gov.trigger_estop("safety_test")
    st3 = await mind.step_once(trigger="estop")
    assert st3.mode == "estop"
    assert st3.emotion == "concerned"
    assert len(transitions) == 3

    # 5. World model persists cleanly across restart
    world2 = WorldModelStore(tmp_path)
    assert world2.get("system", "cognitive_state")["mode"] == "estop"
    assert len(world2.recent_perceptions(limit=10)) == 1
