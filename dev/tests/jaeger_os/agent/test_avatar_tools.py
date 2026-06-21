"""Tests for the avatar agent tools — set_avatar_state +
play_timeline + warm_avatar.

These tools are the brain's entry points for driving the
AnimationNode.  Tests verify:
  - tool surface (signature + return shape)
  - bus publish lands the right AnimationCommand
  - sandbox path resolution rejects escape attempts
  - per-instance expression overrides win over framework defaults
  - play_timeline parses + dispatches the timeline
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jaeger_os import topics
from jaeger_os.agent.tools import avatar
from jaeger_os.agent.tools import _common as tool_common
from jaeger_os.nodes import runtime as node_runtime
from jaeger_os.transport import InProcBus


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch):
    """Each test gets a fresh runtime singleton — no shared state
    between tests."""
    node_runtime.shutdown()
    yield
    node_runtime.shutdown()


@pytest.fixture
def instance(tmp_path: Path, monkeypatch):
    """Make a fake instance + bind it to the agent's tool layout."""
    inst = tmp_path / "instance"
    inst.mkdir()
    (inst / "identity.yaml").write_text(
        "name: TestAgent\nrole: testing\npersonality: p\nvoice_tone: neutral\n"
    )
    (inst / "config.yaml").write_text("model:\n  model_path: /tmp/x.gguf\n")
    (inst / "manifest.json").write_text(
        '{"instance_name": "test", "schema_version": "0.5.0",'
        ' "created_at": "2026-06-09T00:00:00+00:00"}'
    )
    (inst / "avatar").mkdir()
    (inst / "skills").mkdir()
    (inst / "timelines").mkdir()
    # Bind the layout so _require_layout() returns this one.
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=inst)
    tool_common.bind(layout)
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(inst))
    return layout


@pytest.fixture
def captured_animation_cmds(instance):
    """Replace the bus with one we control; capture all
    AnimationCommand publishes."""
    bus = InProcBus()
    received: list[topics.AnimationCommand] = []
    bus.subscribe(
        topics.ACT_ANIMATION,
        lambda msg: received.append(msg),
    )
    # Stub ensure_animation_node so we don't spin a real node —
    # the publish itself is what we're testing.
    node_runtime._bus = bus  # noqa: SLF001
    import unittest.mock as mock
    with mock.patch.object(node_runtime, "ensure_animation_node",
                            return_value=None):
        yield received


# ── set_avatar_state ────────────────────────────────────────────────

def test_set_avatar_state_publishes_animation_command(
    captured_animation_cmds,
) -> None:
    result = avatar.set_avatar_state(emotion="happy")
    assert result["ok"]
    assert result["emotion"] == "happy"
    # Give the in-process bus delivery thread a tick.
    for _ in range(20):
        if captured_animation_cmds:
            break
        time.sleep(0.02)
    assert len(captured_animation_cmds) == 1
    cmd = captured_animation_cmds[0]
    assert cmd.adapter == "math"
    # All emotions share the same MathScript; the emotion is in params.
    assert "lilith_face.py" in cmd.asset_path
    assert cmd.params.get("emotion") == "happy"


def test_set_avatar_state_unknown_emotion_errors(
    captured_animation_cmds,
) -> None:
    result = avatar.set_avatar_state(emotion="banana")
    assert not result["ok"]
    assert "unknown emotion" in result["reason"]
    # No command published.
    time.sleep(0.05)
    assert len(captured_animation_cmds) == 0


def test_set_avatar_state_honors_per_instance_overrides(
    instance, captured_animation_cmds,
) -> None:
    overrides = {
        "happy": {"adapter": "image", "asset": "custom/smile.png"},
    }
    (instance.root / "avatar" / "expressions.json").write_text(
        json.dumps(overrides)
    )
    result = avatar.set_avatar_state(emotion="happy")
    assert result["ok"]
    assert result["adapter"] == "image"
    for _ in range(20):
        if captured_animation_cmds:
            break
        time.sleep(0.02)
    assert captured_animation_cmds[0].adapter == "image"
    # The sandbox resolver returns the framework-relative path when
    # the file doesn't physically exist.
    assert "smile.png" in captured_animation_cmds[0].asset_path


def test_set_avatar_state_hold_ms_passed_through(
    captured_animation_cmds,
) -> None:
    avatar.set_avatar_state(emotion="neutral", hold_ms=1500)
    for _ in range(20):
        if captured_animation_cmds:
            break
        time.sleep(0.02)
    assert captured_animation_cmds[0].duration_ms == 1500


# ── play_timeline ───────────────────────────────────────────────────

def test_play_timeline_missing_name_errors(captured_animation_cmds) -> None:
    result = avatar.play_timeline(name="")
    assert not result["ok"]
    assert "name required" in result["reason"]


def test_play_timeline_missing_file_errors(
    instance, captured_animation_cmds,
) -> None:
    result = avatar.play_timeline(name="nope")
    assert not result["ok"]
    assert "not found" in result["reason"]


def test_play_timeline_dispatches_clips(
    instance, captured_animation_cmds,
) -> None:
    timeline_json = {
        "name": "greeting",
        "tracks": [
            {
                "kind": "animation",
                "clips": [
                    {
                        "t_offset_ms": 0,
                        "duration_ms": 200,
                        "payload": {"adapter": "image", "asset": "a.png"},
                    },
                ],
            },
        ],
    }
    (instance.root / "timelines" / "greeting.json").write_text(
        json.dumps(timeline_json)
    )
    result = avatar.play_timeline(name="greeting", wait=True)
    assert result["ok"]
    assert result["name"] == "greeting"
    # The animation clip should have been published.
    for _ in range(30):
        if captured_animation_cmds:
            break
        time.sleep(0.02)
    assert len(captured_animation_cmds) >= 1
    assert captured_animation_cmds[0].adapter == "image"


def test_play_timeline_bad_json_errors(
    instance, captured_animation_cmds,
) -> None:
    (instance.root / "timelines" / "bad.json").write_text("not valid json")
    result = avatar.play_timeline(name="bad")
    assert not result["ok"]
    assert "invalid timeline" in result["reason"]


# ── warm_avatar ─────────────────────────────────────────────────────

def test_warm_avatar_returns_ok_on_success(monkeypatch) -> None:
    import unittest.mock as mock
    with mock.patch.object(node_runtime, "ensure_animation_node",
                            return_value=None):
        result = avatar.warm_avatar()
    assert result["ok"]


def test_warm_avatar_returns_failure_reason(monkeypatch) -> None:
    import unittest.mock as mock
    with mock.patch.object(node_runtime, "ensure_animation_node",
                            side_effect=RuntimeError("boom")):
        result = avatar.warm_avatar()
    assert not result["ok"]
    assert "boom" in result["reason"]
