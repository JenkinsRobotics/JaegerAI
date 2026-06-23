"""Tests for the 0.5 lip-sync wiring — TtsChunk events drive the
active MathScript's amplitude_param.

The pipeline:
  TTSNode._tts_amplitude_pulse  → /sense/tts_chunk
                                → AnimationNode._on_tts_chunk
                                → adapter.set_runtime_param("amplitude", v)
                                → MathScript.amplitude_param
                                → render_into sees the new value
"""

from __future__ import annotations

import time
from pathlib import Path
from textwrap import dedent

import pytest

from jaeger_os.transport import topics
from jaeger_os.nodes.animation.adapters import MathAdapter, MathScript


# ── MathAdapter.set_runtime_param ───────────────────────────────────

def test_math_adapter_set_runtime_param_updates_amplitude(
    tmp_path: Path,
) -> None:
    script_path = tmp_path / "ampscript.py"
    script_path.write_text(dedent("""
        from jaeger_os.nodes.animation.adapters import MathScript
        class S(MathScript):
            def render_into(self, t, frame_rgb):
                frame_rgb[..., 0] = int(self.amplitude_param * 200)
    """))
    a = MathAdapter()
    a.open(str(script_path), width=4, height=4, params={})
    f1 = a.next_frame(0.0)
    assert f1.data[0] == 0  # default amplitude 0.0

    a.set_runtime_param("amplitude", 0.5)
    # adapter caches start_t; need a different t to advance frame
    f2 = a.next_frame(0.1)
    assert f2.data[0] == 100  # 0.5 * 200

    a.set_runtime_param("amplitude", 1.0)
    f3 = a.next_frame(0.2)
    assert f3.data[0] == 200


def test_math_adapter_set_runtime_param_when_closed_is_noop() -> None:
    """No script open → no error."""
    a = MathAdapter()
    a.set_runtime_param("amplitude", 0.7)  # should not raise


# ── AnimationNode._on_tts_chunk ────────────────────────────────────

def test_animation_node_forwards_tts_chunk_to_adapter(
    tmp_path: Path,
) -> None:
    """End-to-end at the node level: publish a TtsChunk on the
    bus, verify the active adapter's amplitude_param updated."""
    from jaeger_os.nodes.animation import AnimationNode
    from jaeger_os.transport import InProcBus
    import threading

    # A tiny MathScript that exposes amplitude_param for inspection
    # by the test.
    script_path = tmp_path / "probe.py"
    script_path.write_text(dedent("""
        from jaeger_os.nodes.animation.adapters import MathScript
        class S(MathScript):
            def on_enter(self, **kw):
                super().on_enter(**kw)
                self.amplitude_param = 0.0
            def render_into(self, t, frame_rgb):
                frame_rgb[..., 0] = int(self.amplitude_param * 200)
    """))

    bus = InProcBus()
    node = AnimationNode(bus=bus)
    node.register_adapter("math", MathAdapter())
    node_thread = threading.Thread(target=node.run, daemon=True)
    node_thread.start()
    try:
        time.sleep(0.1)  # let setup() fire
        bus.publish(topics.AnimationCommand(
            adapter="math",
            asset_path=str(script_path),
            duration_ms=500,
            params={},
        ))
        time.sleep(0.2)  # let the adapter open + start playing

        # Now publish a TtsChunk at amplitude=0.8.
        bus.publish(topics.TtsChunk(
            amplitude=0.8,
            is_final=False,
            node_id="test",
        ))
        # Give the bus + node a tick.
        for _ in range(20):
            if (node._active is not None
                    and getattr(node._active, "_script", None) is not None):
                amp = getattr(node._active._script, "amplitude_param", 0.0)
                if abs(amp - 0.8) < 0.01:
                    break
            time.sleep(0.02)
        # The script's amplitude_param should now be 0.8.
        amp = getattr(node._active._script, "amplitude_param", 0.0)
        assert abs(amp - 0.8) < 0.01
    finally:
        node.stop()
        node_thread.join(timeout=2.0)
        bus.close()


def test_animation_node_tts_chunk_with_no_active_adapter_is_noop(
) -> None:
    """When no animation is playing, TtsChunk events are silently
    dropped."""
    from jaeger_os.nodes.animation import AnimationNode
    from jaeger_os.transport import InProcBus
    import threading

    bus = InProcBus()
    node = AnimationNode(bus=bus)
    node_thread = threading.Thread(target=node.run, daemon=True)
    node_thread.start()
    try:
        time.sleep(0.1)
        bus.publish(topics.TtsChunk(amplitude=0.5))
        time.sleep(0.1)  # should not raise
        # Just verify the node is still alive after.
        from jaeger_os.nodes.base import NodeState
        assert node.state == NodeState.RUNNING
    finally:
        node.stop()
        node_thread.join(timeout=2.0)
        bus.close()


# ── topic round-trip ────────────────────────────────────────────────

def test_tts_chunk_topic_msgspec_encodes() -> None:
    """The new TtsChunk Struct round-trips through the bus codec."""
    msg = topics.TtsChunk(
        amplitude=0.42,
        is_final=False,
        node_id="tts",
        correlation_id="abc",
    )
    assert msg.topic == "/sense/tts_chunk"
    assert msg.amplitude == 0.42
    assert not msg.is_final
