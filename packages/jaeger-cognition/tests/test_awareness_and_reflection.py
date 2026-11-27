"""Tests for Live Self-Awareness Snapshot & Automatic Post-Task Reflection."""

from __future__ import annotations

from pathlib import Path

from jaeger_cognition import PostTaskReflector, WorldModelStore


def test_world_model_build_awareness_brief(tmp_path: Path) -> None:
    wm = WorldModelStore(tmp_path)
    wm.record_perception(
        modality="minecraft",
        kind="chat",
        payload={"summary": "[MC Chat] Matthew: Follow me to the cave!"},
        salience=0.9,
    )
    brief = wm.build_awareness_brief(
        governor={"host_available_gb": 18.4, "estop_active": False, "idle_life_status": "active"},
        droid={"awake": True, "pose": {"tracking": True}, "reflex": {"auto_park_enabled": True, "idle_park_s": 600}},
        minecraft={
            "state": {
                "connected": True,
                "position": {"x": 12, "y": 64, "z": -5},
                "biome": "plains",
                "health": 20.0,
                "food": 18.0,
                "nearby_players": [{"username": "Matthew"}],
                "modes": {"follow_player": {"enabled": True, "target": "Matthew"}},
            }
        },
        goals=[{"domain": "youtube", "title": "Film Episode 02 Co-Op"}],
        recent_actions=[{"kind": "minecraft", "summary": "Explored plains"}],
        pending_approvals=1,
        active_subagents=2,
    )
    assert "[Live Self-Awareness Snapshot]" in brief
    assert "18.4GB free" in brief
    assert "Droid Body: awake (tracking" in brief
    assert "Minecraft Body: LIVE @ (12,64,-5) plains" in brief
    assert "following=Matthew" in brief
    assert "Film Episode 02 Co-Op" in brief
    assert "Follow me to the cave!" in brief
    assert len(brief) <= 950


def test_post_task_reflector_captures_skill_and_deduplicates(tmp_path: Path) -> None:
    wm = WorldModelStore(tmp_path)
    recorded_lessons: list[dict] = []
    saved_skills: list[tuple[str, str]] = []
    published_events: list[tuple[str, dict]] = []

    class _FakeLearning:
        def record(self, **kwargs):
            recorded_lessons.append(kwargs)

    reflector = PostTaskReflector(
        learning_store=_FakeLearning(),
        world_model=wm,
        skill_saver=lambda name, md: saved_skills.append((name, md)),
        event_publisher=lambda ev, payload: published_events.append((ev, dict(payload))),
        min_tools_for_skill=3,
    )

    # 1. Trivial turn (<2 tools) is skipped cleanly
    trivial = reflector.reflect_sync(prompt="hi", result={"verdict": "completed", "tool_calls": [{"tool": "web_search"}]})
    assert trivial.reflected is False and trivial.reason == "trivial_turn"

    # 2. Multi-tool completed workflow records learning + captures reusable SKILL.md + publishes event
    rich_result = {
        "verdict": "completed",
        "content": "Fixed test suite and built bundle.",
        "tool_calls": [
            {"tool": "read_file"},
            {"tool": "edit_file"},
            {"tool": "shell"},
        ],
    }
    out = reflector.reflect_sync(prompt="Fix gateway test and verify build", result=rich_result, session_id="sess_1")
    assert out.reflected is True
    assert out.lesson_recorded is True
    assert out.skill_captured.startswith("auto-")
    assert len(saved_skills) == 1
    assert "name: auto-" in saved_skills[0][1]
    assert any(ev == "cognition.reflection" for ev, _ in published_events)

    # 3. Duplicate workflow signature does not create duplicate skills
    out2 = reflector.reflect_sync(prompt="Fix gateway test and verify build", result=rich_result, session_id="sess_1")
    assert out2.reflected is True
    assert out2.skill_captured == ""
    assert len(saved_skills) == 1

    # 4. E-Stop blocks reflection cleanly
    estop_ref = PostTaskReflector(is_estop=lambda: True)
    blocked = estop_ref.reflect_sync(prompt="anything", result=rich_result)
    assert blocked.reflected is False and blocked.reason == "estop_active"
