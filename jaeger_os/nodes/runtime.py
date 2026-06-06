"""runtime.py — brain-side singleton for the bus + co-located nodes.

The brain (``main.py``) has tools that publish + wait for acks via
the Bus.  Those tools need a Bus to talk to AND need the matching
node to be running to receive their messages.  This module is the
lazy-boot singleton that holds both.

Two operations
--------------
* :func:`get_bus` returns the brain's :class:`InProcBus`,
  creating it on first call.
* :func:`ensure_tts_node` starts (and warms, on first call) the
  TTS node so ``/act/speech`` has a subscriber.  Idempotent — safe
  to call from any tool's first invocation OR from ``warm_kokoro``
  during boot prewarm.

Track A.7 (the ZMQ broker) will add a multi-process variant: the
runtime asks the operator's ``--mode`` choice and either returns
``InProcBus`` (monolithic, today) or ``ZMQBus`` connected to a
broker (multiprocess).  Tools won't see the difference because
both implement the same Bus interface.

Shutdown
--------
:func:`shutdown` stops the TTS node, closes the bus, and clears
the singletons.  Idempotent.  Called from the brain's exit paths
so the Kokoro player teardown runs deterministically (lesson from
the 0.3.0 PortAudio segfault class).
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from jaeger_os.nodes.tts import TTSNode
from jaeger_os.transport import Bus, InProcBus


_lock = threading.Lock()
_bus: Optional[Bus] = None
_tts_node: Optional[TTSNode] = None
_tts_thread: Optional[threading.Thread] = None
_synth = None  # KokoroTTS instance owned by the node


def get_bus() -> Bus:
    """Return the brain's singleton Bus, creating it on first call.

    Today: always :class:`InProcBus`.  Track A.7 will introduce a
    ZMQ variant chosen by the operator's ``--mode`` flag.
    """
    global _bus
    with _lock:
        if _bus is None:
            _bus = InProcBus()
        return _bus


def ensure_tts_node(*, warm: bool = False) -> TTSNode:
    """Make sure a TTS node is running on the bus.  Idempotent.

    ``warm=True`` calls ``synth.warm()`` before returning so the
    Kokoro pipeline is preloaded — call this from
    :func:`jaeger_os.core.tools.speak.warm_kokoro` at boot so the
    first user-facing ``text_to_speech`` doesn't pay the 5-7 s
    weight-load tax.
    """
    global _tts_node, _tts_thread, _synth
    bus = get_bus()
    with _lock:
        if _tts_node is None:
            # Late import — speak.py imports from this module, so a
            # module-level import would be circular.
            from jaeger_os.plugins.kokoro_tts import KOKORO_LANG, KokoroTTS
            from jaeger_os.core.tools.speak import _resolve_voice

            voice = _resolve_voice()
            _synth = KokoroTTS(voice=voice, lang=KOKORO_LANG)
            _tts_node = TTSNode(
                bus=bus,
                synthesizer=_synth,
                name="tts",
                install_signal_handlers=False,
            )
            _tts_thread = threading.Thread(
                target=_tts_node.run,
                name="brain-tts-node",
                daemon=True,
            )
            _tts_thread.start()
            # Brief delay so the node's setup() registers the /act/speech
            # subscriber before any tool gets a chance to publish.  Without
            # this the first speak() can race the subscription install.
            time.sleep(0.1)
        if warm and _synth is not None:
            # Warm OUTSIDE the lock — Kokoro weight-load is several
            # seconds; holding _lock that long would block any other
            # caller of ensure_tts_node.  Re-grab to atomically mark
            # "warmed once".
            # Actually we're inside the lock here; release for the
            # warm and re-acquire isn't worth the complexity — at
            # boot there's only one caller anyway.
            try:
                _synth.warm()
            except Exception:  # noqa: BLE001
                # Warm failure is non-fatal — the first speak() will
                # warm lazily.  Log but proceed.
                import sys
                print(
                    "[runtime] kokoro warm at ensure_tts_node failed; "
                    "first speak() will pay the load tax",
                    file=sys.stderr, flush=True,
                )
        return _tts_node


def get_synth():
    """Expose the KokoroTTS instance the TTS node wraps.

    Used by ``warm_kokoro()`` so it can return Kokoro's own warm-
    report dict (matches the pre-0.4 signature)."""
    return _synth


def shutdown() -> None:
    """Stop the TTS node, close the bus.  Idempotent."""
    global _bus, _tts_node, _tts_thread, _synth
    with _lock:
        node = _tts_node
        thread = _tts_thread
        bus = _bus
        _tts_node = None
        _tts_thread = None
        _bus = None
        _synth = None
    if node is not None:
        node.stop()
        if thread is not None:
            thread.join(timeout=3.0)
    if bus is not None:
        bus.close()
