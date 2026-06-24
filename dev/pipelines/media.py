#!/usr/bin/env python3
"""Media pipeline probe.

Boot the media node in isolation, stream a real image through it, and
capture the RGBA frame it publishes — the upstream-render → MediaFrame
path (the floating player / a Jetson node subscribe to the same frames).

    .venv/bin/python dev/pipelines/media.py [path-to-image-or-video]
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
_REPO = pathlib.Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    from jaeger_os.nodes.testing import NodeHarness
    from jaeger_os.nodes.media.node import MediaNode
    from jaeger_os.transport import topics

    if argv:
        asset = pathlib.Path(argv[0])
    else:  # fall back to any character card as a test image
        asset = next(
            (_REPO / "jaeger_os/personality/characters").rglob("card.png"), None)

    try:
        h = NodeHarness(lambda bus: MediaNode(bus=bus))
        with h:
            frames = h.capture(topics.SENSE_MEDIA_FRAME)
            states = h.capture(topics.SENSE_MEDIA_STATE)
            print("media node booted:", h.node.state.value)
            if asset and pathlib.Path(asset).exists():
                print(f"streaming: {asset}")
                h.publish(topics.MediaCommand(path=str(asset), loop=False))
                h.wait(lambda: frames, timeout_s=4.0)
            else:
                print("no test asset found — pass a path to stream one")
        if frames:
            f = frames[-1]
            print(f"OK — streamed a {f.width}x{f.height} RGBA frame "
                  f"({len(f.data)} bytes); media-state events: {len(states)}")
            return 0
        print("node ran but produced no frame")
        return 1
    except Exception as exc:  # noqa: BLE001
        print("media probe error:", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
