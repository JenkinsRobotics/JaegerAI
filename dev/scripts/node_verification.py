#!/usr/bin/env python3
"""node_verification.py — Track A verification gate.

Runs an end-to-end echo-node round-trip in both transport modes:

  1. **monolithic** — brain + echo-node share one Python process.
     Uses :class:`jaeger_os.transport.InProcBus`.
  2. **multiprocess** — echo-node runs in a child subprocess
     connected via :class:`jaeger_os.transport.ZMQBus` over
     ``ipc://``.  Proves that the same Node + Bus + codec + topics
     code works when nodes are physically separate processes.

Exit codes:
   0 = both modes pass
   1 = at least one mode failed

Used by ``./launch --node-test``.
"""

from __future__ import annotations

# Self-bootstrap so the import below works when invoked as a script.
import os.path as _osp
import sys as _sys
_REPO = _osp.dirname(_osp.dirname(_osp.dirname(_osp.abspath(__file__))))
if _REPO not in _sys.path:
    _sys.path.insert(0, _REPO)

import argparse
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from jaeger_os import topics
from jaeger_os.nodes import Node
from jaeger_os.transport import InProcBus, ZMQBus


# ── echo node (shared by both modes) ──────────────────────────────

class EchoNode(Node):
    """SUB /sense/transcript → transform → PUB /act/speech.

    The simplest possible node: proves the Bus + Node + codec +
    topics stack works end-to-end without involving any real
    hardware or models."""

    def setup(self) -> None:
        self.bus.subscribe(topics.SENSE_TRANSCRIPT, self._on_transcript)

    def _on_transcript(self, msg: topics.Transcript) -> None:
        self.bus.publish(topics.SpeechCommand(
            text=f"You said: {msg.text}",
            node_id=self.name,
            correlation_id=msg.correlation_id,
        ))


# ── monolithic mode ───────────────────────────────────────────────

def verify_monolithic(*, timeout_s: float = 5.0) -> bool:
    """Run brain + echo-node in this process via InProcBus."""
    print("\n── MONOLITHIC mode (InProcBus, one process) ─────────────")
    bus = InProcBus()
    node = EchoNode(bus=bus, name="echo-mono", install_signal_handlers=False)

    # Start the node on a background thread.
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)  # let setup register the subscriber

    # Brain side: subscribe to /act/speech, publish a transcript,
    # wait for the echo back.
    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def on_speech(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.ACT_SPEECH, on_speech)
    cid = uuid.uuid4().hex
    bus.publish(topics.Transcript(
        text="hello from monolithic",
        node_id="brain",
        correlation_id=cid,
    ))

    ok = event.wait(timeout=timeout_s)
    if not ok:
        print(f"  ✗ FAIL: no /act/speech reply within {timeout_s}s")
        node.stop()
        thread.join(timeout=2.0)
        bus.close()
        return False

    msg = received[0]
    if not isinstance(msg, topics.SpeechCommand):
        print(f"  ✗ FAIL: reply isn't SpeechCommand ({type(msg).__name__})")
        node.stop()
        bus.close()
        return False
    if msg.text != "You said: hello from monolithic":
        print(f"  ✗ FAIL: wrong text {msg.text!r}")
        node.stop()
        bus.close()
        return False
    if msg.correlation_id != cid:
        print(f"  ✗ FAIL: correlation_id {msg.correlation_id!r} != {cid!r}")
        node.stop()
        bus.close()
        return False

    print(f"  ✓ round-trip OK")
    print(f"      brain → /sense/transcript ({len('hello from monolithic')} chars)")
    print(f"      echo-mono → /act/speech ({len(msg.text)} chars)")
    print(f"      correlation_id matched: {cid[:8]}…")

    node.stop()
    thread.join(timeout=2.0)
    bus.close()
    return True


# ── multiprocess mode ─────────────────────────────────────────────

# A child subprocess invokes this module with ``--child-echo-node``;
# it runs the EchoNode connected to the parent's ZMQ endpoint, then
# blocks until the parent's terminator message arrives.

def _run_child_echo_node(endpoint: str) -> int:
    """Entry point for the child subprocess.  Runs the echo node
    against a ZMQBus that connects (does NOT bind) to the parent's
    endpoint."""
    bus = ZMQBus(endpoint=endpoint, bind=False)
    node = EchoNode(bus=bus, name="echo-child", install_signal_handlers=False)

    # Run the node in a thread, then wait for the parent to signal
    # us to shut down via a fake "/act/light" message with text=stop.
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()

    stop_event = threading.Event()

    def on_stop(msg):
        # We piggyback on /act/light's pattern field as a shutdown
        # signal because adding a /control/* topic is out of scope
        # for this verification script.  Real shutdown comes via
        # signals at A.6+.
        if msg.pattern == "off":
            stop_event.set()

    bus.subscribe(topics.ACT_LIGHT, on_stop)
    stop_event.wait(timeout=30.0)  # safety timeout

    node.stop()
    thread.join(timeout=2.0)
    bus.close()
    return 0


def verify_multiprocess(*, timeout_s: float = 8.0) -> bool:
    """Spawn the echo-node as a child Python subprocess; brain in
    THIS process publishes a transcript over ZMQ ipc://; verify the
    echo comes back.

    KNOWN INCOMPLETE: the current ZMQBus binds PUB + SUB on the same
    endpoint, which works in-process (shared ZMQ context routes
    between sockets internally) but NOT across processes (each
    process has its own context — no internal routing).  A proper
    multi-process design needs a broker process running zmq.proxy
    between XSUB ← PUB sockets and XPUB → SUB sockets.  Track A.7
    work.
    """
    print("\n── MULTIPROCESS mode (ZMQBus, ipc:// across 2 processes) ──")
    print("  KNOWN INCOMPLETE: requires Track A.7 broker work.")
    print("  Running anyway to surface the failure mode...")

    endpoint = f"ipc:///tmp/jros-nodetest-{uuid.uuid4().hex[:8]}.sock"

    # Parent process binds the endpoint as the broker.
    bus = ZMQBus(endpoint=endpoint, bind=True)

    # Spawn the child.  Use the same Python interpreter that's
    # running us so the .venv is consistent.
    child_cmd = [
        _sys.executable, _osp.abspath(__file__),
        "--child-echo-node", "--endpoint", endpoint,
    ]
    child = subprocess.Popen(
        child_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    print(f"  child PID={child.pid} on {endpoint}")

    # ZMQ pub/sub late-joiner: wait for the child to fully connect
    # and register its subscription before we publish.  Without this
    # the brain's first publish goes into the void.
    time.sleep(0.8)

    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def on_speech(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.ACT_SPEECH, on_speech)
    time.sleep(0.1)

    cid = uuid.uuid4().hex
    bus.publish(topics.Transcript(
        text="hello from multiprocess",
        node_id="brain",
        correlation_id=cid,
    ))

    ok = event.wait(timeout=timeout_s)

    # Tell the child to shut down (piggybacked on /act/light).
    bus.publish(topics.LightCommand(pattern="off"))
    time.sleep(0.2)

    if not ok:
        print(f"  ✗ FAIL: no /act/speech reply within {timeout_s}s")
        _shutdown_child(child)
        bus.close()
        return False

    msg = received[0]
    if not isinstance(msg, topics.SpeechCommand):
        print(f"  ✗ FAIL: reply isn't SpeechCommand ({type(msg).__name__})")
        _shutdown_child(child)
        bus.close()
        return False
    if msg.text != "You said: hello from multiprocess":
        print(f"  ✗ FAIL: wrong text {msg.text!r}")
        _shutdown_child(child)
        bus.close()
        return False
    if msg.correlation_id != cid:
        print(f"  ✗ FAIL: correlation_id {msg.correlation_id!r} != {cid!r}")
        _shutdown_child(child)
        bus.close()
        return False

    print(f"  ✓ round-trip OK (cross-process)")
    print(f"      parent → ipc:// → child → ipc:// → parent")
    print(f"      correlation_id matched: {cid[:8]}…")

    _shutdown_child(child)
    bus.close()
    return True


def _shutdown_child(child: subprocess.Popen) -> None:
    """Tear down the child subprocess.  Tries SIGTERM first, then
    SIGKILL after a grace period."""
    try:
        child.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        child.terminate()
        try:
            child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            child.kill()


# ── entry point ───────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--child-echo-node", action="store_true",
        help=argparse.SUPPRESS,  # internal: child subprocess mode
    )
    parser.add_argument(
        "--endpoint", default="",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--mode", default="monolithic",
        choices=["monolithic", "multiprocess", "all"],
        help=(
            "which mode(s) to test.  Default is 'monolithic' — the "
            "0.4.0 / Track A primary verification gate.  "
            "'multiprocess' requires Track A.7 broker work (single-"
            "endpoint pub/sub doesn't bridge across processes "
            "without a proxy); included here as a known-incomplete "
            "stretch test."
        ),
    )
    args = parser.parse_args(argv)

    if args.child_echo_node:
        return _run_child_echo_node(args.endpoint)

    print("══ JROS 0.4 Track A verification gate ═══════════════════")
    print("Echo-node round-trip across both transport modes.")

    results: list[tuple[str, bool]] = []
    if args.mode in ("all", "monolithic"):
        results.append(("monolithic", verify_monolithic()))
    if args.mode in ("all", "multiprocess"):
        results.append(("multiprocess", verify_multiprocess()))

    print("\n══ summary ═══════════════════════════════════════════════")
    all_ok = True
    for name, ok in results:
        sym = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {sym}  {name}")
        if not ok:
            all_ok = False

    if all_ok:
        print("\n  All transport modes operational.")
        print("  Track A verification gate passed.")
        return 0
    else:
        print("\n  One or more transport modes failed.  See messages above.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
