"""Self-check for the node test-harness: boot a node on a private bus,
drive it with a synthetic input, capture its output."""

from jaeger_os.nodes.base import Node
from jaeger_os.nodes.testing import NodeHarness
from jaeger_os.transport import topics


class _EchoNode(Node):
    """Minimal node — echo each transcript back as a speech command
    (the illustrative example from the Node docstring)."""

    def setup(self) -> None:
        self.bus.subscribe(topics.SENSE_TRANSCRIPT, self._on)

    def _on(self, msg) -> None:
        self.bus.publish(topics.SpeechCommand(
            text=f"echo: {msg.text}", correlation_id=msg.correlation_id))


def test_harness_boots_drives_and_captures():
    h = NodeHarness(lambda bus: _EchoNode(
        bus=bus, name="echo", install_signal_handlers=False))
    with h:
        out = h.capture(topics.ACT_SPEECH)
        h.publish(topics.Transcript(text="hello", correlation_id="c1"))
        assert h.wait(lambda: len(out) >= 1, timeout_s=2.0), "no echo captured"
    assert out[0].text == "echo: hello", out[0]
    assert out[0].correlation_id == "c1", out[0]


if __name__ == "__main__":
    test_harness_boots_drives_and_captures()
    print("node harness self-check OK")
