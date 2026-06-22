"""End-to-end integration: bus command → AnimationNode →
ImageAdapter → FrameBridge → WebSocket client receives the frame.

This is the "make it exist" milestone for the 0.5 avatar pipeline.
Architecture proven end-to-end with real Pillow + real WebSocket
delivery.  Visual verification (the Swift app actually shows the
image) is operator-side.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import pytest
import websockets
from PIL import Image

from jaeger_os.transport import topics
from jaeger_os.nodes.software.animation import (
    AnimationNode,
    FrameBuffer,
)
from jaeger_os.nodes.software.animation import bridge as _bridge
from jaeger_os.nodes.software.animation.adapters import ImageAdapter
from jaeger_os.skill_tree import SkillNode, SkillTreeRegistry
from jaeger_os.transport import InProcBus


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _png(tmp_path: Path, *, color: tuple) -> Path:
    p = tmp_path / "test.png"
    Image.new("RGBA", (8, 8), color).save(p)
    return p


# ── the headline integration test ──────────────────────────────────

def test_animation_command_renders_to_websocket_client(
    tmp_path: Path,
) -> None:
    """One command → one rendered frame → one byte-perfect arrival
    at a real WebSocket client."""
    asset = _png(tmp_path, color=(120, 200, 60, 255))

    # Skill-tree registered for the adapter so XP gets awarded.
    registry = SkillTreeRegistry.load()
    registry.register(SkillNode(
        id="animation.image",
        name="Image",
        category="animation",
        xp_to_mastery=100,
    ))

    # WebSocket bridge bound to a free port.
    port = _free_port()
    bridge = _bridge.FrameBridge(host="127.0.0.1", port=port)
    bridge.start()

    # Bus + node wired together.
    bus = InProcBus()
    node = AnimationNode(
        bus=bus,
        skill_registry=registry,
        frame_callback=bridge.publish_frame,
    )
    node.register_adapter("image", ImageAdapter())

    # WebSocket client.
    received_frames: list[bytes] = []
    received_event = threading.Event()

    async def _client() -> None:
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/frames",
        ) as ws:
            data = await asyncio.wait_for(ws.recv(), timeout=5.0)
            received_frames.append(data)
            received_event.set()

    def _run_client() -> None:
        try:
            asyncio.run(_client())
        except Exception:
            received_event.set()

    client_thread = threading.Thread(target=_run_client, daemon=True)
    client_thread.start()
    time.sleep(0.3)  # let client connect

    # Run the node briefly in a thread.
    node_thread = threading.Thread(target=node.run, daemon=True)
    node_thread.start()
    time.sleep(0.1)  # let setup() fire

    try:
        # Issue the command.
        bus.publish(topics.AnimationCommand(
            adapter="image",
            asset_path=str(asset),
            duration_ms=100,
            params={"width": 8, "height": 8, "fit": "fill"},
        ))
        # Wait for the client to see a frame.
        assert received_event.wait(timeout=5.0), (
            "no frame received within 5 s"
        )
        # The byte-perfect verification.
        header, pixels = _bridge.decode_frame(received_frames[0])
        assert header["w"] == 8
        assert header["h"] == 8
        assert header["format"] == "RGBA8"
        assert len(pixels) == 8 * 8 * 4
        # First pixel should be (close to) the source colour after fill
        # resize from 8×8 → 8×8 (identity).
        r, g, b, a = pixels[0:4]
        assert r > 100 and g > 180 and b > 40 and a == 255

        # XP should have been awarded.
        node_skill = registry.get("animation.image")
        # Wait briefly for the worker thread to award.
        for _ in range(20):
            if node_skill is not None and node_skill.xp > 0:
                break
            time.sleep(0.05)
            node_skill = registry.get("animation.image")
        assert node_skill is not None
        assert node_skill.xp == 1
    finally:
        node.stop()
        node_thread.join(timeout=2.0)
        bridge.stop()
        client_thread.join(timeout=2.0)
        bus.close()
