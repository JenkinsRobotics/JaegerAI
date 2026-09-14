"""The smallest complete JaegerOS program.

Run it:

    python3 examples/hello_bus.py

No manifest, no modules, no config — one bus, one node, one message.
Everything else in the framework is this shape with more pieces.
"""

import time

# One import. You never need to know that a Bus lives in `transport`
# or that Node lives in `nodes.base`.
from jaeger_os import InProcBus, Node, topics


# ── a node ───────────────────────────────────────────────────────
# A node is a class with four methods. The framework calls them; you
# never call them yourself.

class Greeter(Node):
    """Says something on the bus, once a second."""

    def setup(self):
        """Called once, before the loop. Subscribe here."""
        self.said = 0

    def tick(self):
        """Called over and over until the node is stopped.

        Do the work here, not in a subscriber callback — a callback
        runs on the bus's delivery thread, and blocking it stalls
        every other subscriber on every other topic.
        """
        self.said += 1
        self.publish(topics.SpeechCommand(text=f"hello #{self.said}"))
        time.sleep(1.0)

    def teardown(self):
        """Called once, on the way out. Release things here."""
        print(f"[greeter] said {self.said} things")


# ── wiring it up ─────────────────────────────────────────────────

def main():
    bus = InProcBus()

    # A subscriber is any function taking one message. This one is not
    # a node at all — anything can listen.
    def on_speech(msg):
        print(f"[listener] heard: {msg.text!r}")

    bus.subscribe(topics.ACT_SPEECH_SAY, on_speech)

    # Nodes run on their own thread. `run()` blocks, so start it in
    # one and stop it when you are done.
    import threading
    node = Greeter(bus=bus, name="greeter")
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()

    try:
        time.sleep(3.5)
    finally:
        node.stop()
        thread.join(timeout=2)
        bus.close()


if __name__ == "__main__":
    main()
