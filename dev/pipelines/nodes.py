#!/usr/bin/env python3
"""Node-harness pipeline probe.

Boot a tiny echo node in isolation on a private bus, send it a synthetic
transcript, and print the echo it publishes back — the pattern for
vetting any node (media, animation_dev, …) without the whole app.

    .venv/bin/python dev/pipelines/nodes.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def main() -> int:
    from jaeger_os.nodes.base import Node
    from jaeger_os.nodes.testing import NodeHarness
    from jaeger_os.transport import topics

    class Echo(Node):
        def setup(self) -> None:
            self.bus.subscribe(topics.SENSE_TRANSCRIPT, self._on)

        def _on(self, msg) -> None:
            self.bus.publish(topics.SpeechCommand(
                text=f"echo: {msg.text}", correlation_id=msg.correlation_id))

    h = NodeHarness(lambda bus: Echo(bus=bus, name="echo",
                                     install_signal_handlers=False))
    with h:
        out = h.capture(topics.ACT_SPEECH)
        h.publish(topics.Transcript(text="hello pipeline", correlation_id="c1"))
        got = h.wait(lambda: len(out) >= 1, timeout_s=2.0)
    print("echo node booted on a private bus.")
    print("sent  : Transcript('hello pipeline')")
    print("got   :", out[0].text if got and out else "(no reply)")
    return 0 if (got and out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
