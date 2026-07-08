"""Module-contract smoke for ``jaeger_os.nodes.media`` — 0.8 M2c.

Not part of ``dev/tests`` (``pyproject.toml``'s ``testpaths`` doesn't
include this package — same pattern as the kokoro_tts/whisper_stt/
animation module-contract smokes). Run directly:

    pytest jaeger_os/nodes/media/tests
    python -m jaeger_os.nodes.media.tests.test_module_contract

``media`` is the "cheap recipe" (no config.py, no manifest entry, no
agent-facing tools) — this file proves the two things that still
matter for discovery + the node's own bus contract:

  1. ``module.yaml`` parses via :func:`jaeger_os.core.modules.load_module`
     (the real discovery loader, not a hand ``yaml.safe_load``, since
     there's no config-nesting concern to pin here).
  2. ``MediaNode``'s bus contract (ACT_MEDIA in -> MediaFrame + MediaState
     out) works end to end with a tiny real in-memory PNG — no manifest,
     no supervisor, just the node's own factory on an InProcBus.
"""

from __future__ import annotations

import pathlib
import threading
import time

from PIL import Image

from jaeger_os.core.modules import load_module
from jaeger_os.nodes.media import MediaNode, make_media_node
from jaeger_os.nodes.base import NodeState
from jaeger_os.transport import InProcBus, topics

_MODULE_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_module_yaml_validates() -> None:
    spec = load_module(_MODULE_DIR)
    assert spec.module == "media"
    assert spec.slot == "media"
    assert spec.version == "1.0.0"
    assert spec.consumes == ["/act/media"]
    assert spec.produces == ["/sense/media_frame", "/sense/media_state"]
    assert spec.tools == []
    assert spec.factory == "jaeger_os.nodes.media:make_media_node"
    assert spec.config == ""   # no config.py — deliberately unset
    assert spec.requires_libraries == ["PIL", "numpy"]


def test_command_frame_round_trip_with_a_tiny_image(tmp_path) -> None:
    """A real 2x2 PNG, decoded by the real ``ImageAdapter`` (no fakes —
    media has no engine-swap seam to fake around), streams exactly one
    held ``MediaFrame`` + a playing->not-playing ``MediaState`` pair."""
    img_path = tmp_path / "tiny.png"
    Image.new("RGBA", (2, 2), (10, 20, 30, 255)).save(img_path)

    bus = InProcBus()
    node: MediaNode = make_media_node(bus, {"width": 2, "height": 2})
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node.state != NodeState.RUNNING:
            time.sleep(0.01)
        assert node.state == NodeState.RUNNING

        frames: list[topics.MediaFrame] = []
        states: list[topics.MediaState] = []
        done = threading.Event()

        def _on_frame(msg: topics.TopicMessage) -> None:
            assert isinstance(msg, topics.MediaFrame)
            frames.append(msg)

        def _on_state(msg: topics.TopicMessage) -> None:
            assert isinstance(msg, topics.MediaState)
            states.append(msg)
            if len(states) >= 2:  # playing=True, then playing=False
                done.set()

        bus.subscribe(topics.SENSE_MEDIA_FRAME, _on_frame)
        bus.subscribe(topics.SENSE_MEDIA_STATE, _on_state)
        bus.publish(topics.MediaCommand(path=str(img_path), loop=False))

        assert done.wait(timeout=2.0), "no terminal MediaState pair"
        assert len(frames) == 1
        assert (frames[0].width, frames[0].height) == (2, 2)
        assert states[0].playing is True and states[0].kind == "image"
        assert states[-1].playing is False
    finally:
        node.stop()
        thread.join(timeout=2.0)
        bus.close()


if __name__ == "__main__":
    test_module_yaml_validates()
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_command_frame_round_trip_with_a_tiny_image(pathlib.Path(d))
    print("media module contract smoke: OK")
