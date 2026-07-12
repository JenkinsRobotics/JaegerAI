#!/usr/bin/env python3
"""tts_node_test.py — Track B.1 integration gate for the TTS node.

Two modes:

  --boot-only   load Kokoro + boot the TTS node + verify subscription
                installed; no audio output.  Safe to run autonomously
                (CI, headless dev) — Kokoro warms the model + opens
                the persistent player but no synthesis runs.

  --speak       full end-to-end gate.  Boots the node, publishes a
                /act/speech message via bus.request(), waits for the
                matching /sense/spoken ack.  Audible speech.
                Default when invoked from ``./launch --tts-test``.

Exit codes:
  0 = the requested mode succeeded
  1 = something failed; see stderr for the reason
"""

from __future__ import annotations

# Self-bootstrap so the import below works when invoked as a script.
import os.path as _osp
import sys as _sys
_REPO = _osp.dirname(_osp.dirname(_osp.dirname(_osp.abspath(__file__))))
if _REPO not in _sys.path:
    _sys.path.insert(0, _REPO)

import argparse
import time
import uuid

from jaeger_os.transport import topics
from jaeger_os.nodes import TTSNode
from jaeger_os.transport import InProcBus


def _build_synth():
    """Build a real KokoroTTS instance.  The class takes no instance/
    config dependency — it uses module-level defaults for voice + lang
    and resolves its audio backend lazily.  Returns the synth so the
    caller can tear it down."""
    from jaeger_kokoro_tts.nodes.kokoro_tts.engine import KokoroTTS
    return KokoroTTS()


def boot_only() -> int:
    """Load Kokoro + boot the TTS node + verify the subscription is
    installed.  No synthesis runs."""
    print("══ TTS node boot-only test ══════════════════════════════")
    print("Loading KokoroTTS (model + persistent player)...")
    t0 = time.perf_counter()
    synth = _build_synth()
    if synth is None:
        return 1
    try:
        warmup = synth.warm()
        print(f"  ✓ Kokoro warmed in {time.perf_counter() - t0:.1f}s "
              f"({warmup})")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ Kokoro warm failed: {type(exc).__name__}: {exc}",
              file=_sys.stderr)
        return 1

    bus = InProcBus()
    node = TTSNode(bus=bus, synthesizer=synth, name="tts")
    print("Booting TTSNode...")

    import threading
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.3)  # let setup() install the subscriber

    # Verify the subscription is live by inspecting the bus's
    # subscriber list.  This catches "setup() returned but didn't
    # actually subscribe" without producing audio.
    with bus._subs_lock:
        subscribers = bus._subscribers.get(topics.ACT_SPEECH, [])
    if len(subscribers) != 1:
        print(f"  ✗ expected 1 subscriber on {topics.ACT_SPEECH}, "
              f"got {len(subscribers)}", file=_sys.stderr)
        node.stop()
        thread.join(timeout=2.0)
        bus.close()
        return 1
    print(f"  ✓ {topics.ACT_SPEECH} has 1 subscriber (the TTS node)")
    print(f"  ✓ node state = {node.state.value}")

    print("Shutting down...")
    node.stop()
    thread.join(timeout=5.0)
    bus.close()
    print(f"  ✓ node state = {node.state.value}")

    print("\n══ summary ═══════════════════════════════════════════════")
    print("  ✓ PASS  boot-only — Kokoro loaded, TTS node lifecycle clean")
    return 0


def speak_test(text: str = "TTS node test. Track B.1 verification.") -> int:
    """Full end-to-end audio gate.  Speaks the given text via the
    TTS node, waits for /sense/spoken, reports timing."""
    print("══ TTS node end-to-end speak test ════════════════════════")
    print(f"Phrase: {text!r}")
    print("Loading KokoroTTS (model + persistent player)...")
    t0 = time.perf_counter()
    synth = _build_synth()
    if synth is None:
        return 1
    try:
        synth.warm()
        print(f"  ✓ Kokoro warmed in {time.perf_counter() - t0:.1f}s")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ Kokoro warm failed: {type(exc).__name__}: {exc}",
              file=_sys.stderr)
        return 1

    bus = InProcBus()
    node = TTSNode(bus=bus, synthesizer=synth, name="tts")

    import threading
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.3)

    cid = uuid.uuid4().hex
    print(f"\nPublishing /act/speech (cid={cid[:8]}...)")
    print("  Listen for the spoken phrase...")
    t_pub = time.perf_counter()
    ack = bus.request(
        topics.SpeechCommand(text=text, correlation_id=cid),
        ack_topic=topics.SENSE_SPOKEN,
        timeout_s=30.0,
    )
    t_done = time.perf_counter() - t_pub

    node.stop()
    thread.join(timeout=5.0)
    bus.close()

    print("\n══ summary ═══════════════════════════════════════════════")
    if ack is None:
        print(f"  ✗ FAIL  no /sense/spoken ack within 30s")
        return 1
    if not ack.ok:
        print(f"  ✗ FAIL  TTS node reported ok=False: {ack.reason}")
        return 1
    print(f"  ✓ PASS  /sense/spoken received in {t_done:.1f}s")
    print(f"          ack.ok = {ack.ok}")
    print(f"          ack.duration_s = {ack.duration_s:.2f}")
    print(f"          ack.correlation_id matched: {ack.correlation_id[:8]}…")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--boot-only", action="store_true",
        help="load Kokoro + node lifecycle; no audio output",
    )
    g.add_argument(
        "--speak", action="store_true",
        help="full end-to-end gate (default; produces audible speech)",
    )
    parser.add_argument(
        "--text", default="TTS node test. Track B point one verification.",
        help="phrase to speak (only used with --speak)",
    )
    args = parser.parse_args(argv)

    if args.boot_only:
        return boot_only()
    # Default to --speak when invoked without an explicit mode (matches
    # how ./launch --tts-test will call this).
    return speak_test(args.text)


if __name__ == "__main__":
    raise SystemExit(main())
