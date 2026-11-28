"""Tests for standalone jaeger-youtube package."""

from __future__ import annotations

from pathlib import Path

from jaeger_youtube import (
    YouTubeStudioStore,
    plan_phased_research,
    probe_youtube_toolchain,
)


def test_phased_research_enforces_single_heavy_model_32gb() -> None:
    tools = probe_youtube_toolchain(["gemma4:12b", "qwen3-vl:8b"])
    assert tools["memory_policy"] == "single_heavy_model_per_phase_32gb"
    assert tools["vlm_model"] == "qwen3-vl:8b"
    assert tools["llm_model"] == "gemma4:12b"

    plan = plan_phased_research("PL1234567890", video_ids=["dQw4w9WgXcQ"])
    assert plan["max_concurrent_heavy_models"] == 1
    assert plan["auto_publish"] is False
    assert len(plan["phases"]) == 3
    assert plan["phases"][0]["heavy_model"] is None


def test_youtube_episode_studio_approval_gate_and_timeline(tmp_path: Path) -> None:
    store = YouTubeStudioStore(tmp_path)
    ep = store.create_episode(title="Building JP01 Autonomous Droid", target_duration_s=600)
    assert ep.stage == "idea"
    assert len(ep.timeline_clips) >= 4

    # Cannot skip to ready_to_publish without owner approval!
    ok, reason, _ = store.advance_stage(ep.episode_id, target_stage="ready_to_publish")
    assert ok is False and reason == "owner_approval_required_before_publish"

    # Advance through script -> approval_gate -> ready_to_publish WITH explicit approval
    ok_script, _, ep2 = store.advance_stage(ep.episode_id, target_stage="script")
    assert ok_script is True and ep2 is not None and ep2.assigned_role == "scriptwriter"

    ok_pub, _, ep3 = store.advance_stage(
        ep.episode_id,
        target_stage="ready_to_publish",
        owner_approved=True,
        approval_note="Thumbnail & script look sharp",
    )
    assert ok_pub is True and ep3 is not None and ep3.owner_approved is True and ep3.assigned_role == "publisher"
