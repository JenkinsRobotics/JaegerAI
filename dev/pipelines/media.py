#!/usr/bin/env python3
"""Media pipeline probe.

Boot the (imported, under-development) media node in isolation. This
surfaces the known gap: the node references bus topics that aren't
defined yet — exactly what "import dormant, vet in isolation" is for.

    .venv/bin/python dev/pipelines/media.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def main() -> int:
    from jaeger_os.nodes.testing import NodeHarness
    from jaeger_os.nodes.media.node import MediaNode

    try:
        h = NodeHarness(lambda bus: MediaNode(bus=bus))
        with h:
            print("media node booted:", h.node.state.value)
        print("OK — media node runs (topics are defined).")
        return 0
    except Exception as exc:  # noqa: BLE001
        print("media node FAILED to boot:", type(exc).__name__, exc)
        print()
        print("Known gap: nodes/media/node.py references topics.ACT_MEDIA /")
        print("MediaFrame / MediaState, which are NOT in transport/topics.py.")
        print("Fix: add those topic structs (mirror AnimationCommand), re-run.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
