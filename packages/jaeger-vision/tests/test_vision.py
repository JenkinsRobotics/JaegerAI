"""Tests for standalone jaeger-vision package."""

from __future__ import annotations

from jaeger_vision import RollingFrameBuffer


def test_rolling_frame_buffer_prunes_and_detects_scene_change() -> None:
    buf = RollingFrameBuffer(max_frames=3, max_total_mb=4.0)
    f1 = buf.push_frame(b"frame_a" * 100, summary="empty desk")
    f2 = buf.push_frame(b"frame_a" * 100, summary="empty desk")
    assert f1.scene_changed is True
    assert f2.scene_changed is False

    for i in range(5):
        buf.push_frame(f"frame_{i}".encode() * 100)

    stats = buf.stats()
    assert stats["resident_frames"] == 3
    assert stats["pruned_count"] == 4
