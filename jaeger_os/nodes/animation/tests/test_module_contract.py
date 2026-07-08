"""Module-contract smoke for ``jaeger_os.nodes.animation`` — 0.8 M2c.

Not part of ``dev/tests`` (``pyproject.toml``'s ``testpaths`` doesn't
include this package — same pattern as ``jaeger_os/nodes/kokoro_tts/
tests/test_module_contract.py`` / ``jaeger_os/nodes/whisper_stt/tests/
test_module_contract.py``). Run directly:

    pytest jaeger_os/nodes/animation/tests
    python -m jaeger_os.nodes.animation.tests.test_module_contract

Three things a module must get right, proven here without binding a
real WebSocket port or touching the skill-tree filesystem state:

  1. ``module.yaml`` parses and carries the fields the (future) module
     loader will require.
  2. The chassis-contract factory (``make_animation_node``) builds a
     live, correctly-wired node on an injected bus with the real L1-L4
     adapters registered — bridge disabled (``enable_bridge=False``),
     matching the ``--no-avatar`` / headless-test convention the
     existing ``ensure_animation_node`` tests already use.
  3. The node's actual bus contract (AnimationCommand in -> playing ->
     idle AnimationState out) works, via a fake adapter so no real
     rendering happens.
"""

from __future__ import annotations

import pathlib
import threading
import time

import yaml

from jaeger_os.nodes.animation import AnimationNode, make_animation_node
from jaeger_os.nodes.base import NodeState
from jaeger_os.transport import InProcBus, topics

_MODULE_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_module_yaml_validates() -> None:
    doc = yaml.safe_load((_MODULE_DIR / "module.yaml").read_text())
    assert doc["module"] == "animation"
    assert doc["slot"] == "animation"
    assert doc["version"] == "1.0.0"
    assert doc["consumes"] == [
        "/act/animation", "/act/animation_stop", "/sense/tts_chunk",
    ]
    assert doc["produces"] == ["/sense/animation_state"]
    assert doc["tools"] == ["set_avatar_state", "play_timeline", "warm_avatar"]
    assert doc["factory"] == "jaeger_os.nodes.animation:make_animation_node"
    assert doc["config"] == "avatar"
    assert doc["requires_libraries"] == ["websockets", "PIL", "numpy"]


def test_factory_builds_a_live_node_on_an_inproc_bus() -> None:
    """``make_animation_node`` (the ``module.yaml``'s ``factory:``
    entrypoint) constructs a real :class:`AnimationNode` with the L1-L4
    adapter set registered — no WebSocket bind (``enable_bridge=False``),
    no skill-tree filesystem writes required."""
    from jaeger_os.nodes import runtime as node_runtime

    node_runtime.shutdown()
    bus = InProcBus()
    node = make_animation_node(bus, {"enable_bridge": False})
    try:
        assert isinstance(node, AnimationNode)
        assert node.bus is bus
        assert node.known_adapters() == (
            "bitmap", "gif", "image", "math", "sprite",
        )
        # enable_bridge=False -> no live bridge sidecar.
        assert node_runtime._animation_bridge is None  # noqa: SLF001
    finally:
        node_runtime.shutdown()
        bus.close()


def test_command_state_round_trip_with_a_fake_adapter() -> None:
    """The node's bus contract, independent of ``make_animation_node``'s
    real adapter set: an AnimationCommand for a registered (fake)
    adapter produces "playing" then "idle" AnimationState events."""

    class _FakeAdapter:
        skill_id = ""
        level = 0

        def __init__(self) -> None:
            self._emitted = False

        def open(self, asset_path: str, *, width: int, height: int,
                 params: dict) -> None:
            self._emitted = False

        def close(self) -> None:
            pass

        def next_frame(self, t: float):
            if self._emitted:
                return None
            self._emitted = True
            from jaeger_os.nodes.animation import FrameBuffer
            return FrameBuffer(
                width=1, height=1, data=b"\x00\x00\x00\xff",
                duration_ms=0, is_final=True,
            )

    bus = InProcBus()
    node = AnimationNode(bus=bus, install_signal_handlers=False)
    node.register_adapter("fake", _FakeAdapter())
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node.state != NodeState.RUNNING:
            time.sleep(0.01)
        assert node.state == NodeState.RUNNING

        states: list[str] = []
        done = threading.Event()

        def _on_state(msg: topics.TopicMessage) -> None:
            assert isinstance(msg, topics.AnimationState)
            states.append(msg.state)
            if msg.state == "idle":
                done.set()

        bus.subscribe(topics.SENSE_ANIMATION_STATE, _on_state)
        bus.publish(topics.AnimationCommand(
            adapter="fake", asset_path="", duration_ms=0, node_id="test",
        ))
        assert done.wait(timeout=2.0), "no terminal idle AnimationState"
        assert "playing" in states and states[-1] == "idle"
    finally:
        node.stop()
        thread.join(timeout=2.0)
        bus.close()


if __name__ == "__main__":
    test_module_yaml_validates()
    test_factory_builds_a_live_node_on_an_inproc_bus()
    test_command_state_round_trip_with_a_fake_adapter()
    print("animation module contract smoke: OK")
