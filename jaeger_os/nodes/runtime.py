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
* :func:`ensure_audio_session_node` starts the one mic/AEC/STT owner
  for monolithic voice mode, so TUI and other consumers read
  ``/sense/transcript`` instead of opening their own mic.

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
from typing import Any, Callable, Optional

from jaeger_os.core.audio import AudioSession, AudioSessionConfig
from jaeger_os.nodes.audio_session import AudioSessionNode
from jaeger_os.nodes.base import NodeState
from jaeger_os.nodes.tts import Synthesizer, TTSNode
from jaeger_os.transport import Bus, InProcBus


_lock = threading.Lock()
_bus: Optional[Bus] = None
_tts_node: Optional[TTSNode] = None
_tts_thread: Optional[threading.Thread] = None
_synth = None  # KokoroTTS instance owned by the node
_audio_session_node: Optional[AudioSessionNode] = None
_audio_session_thread: Optional[threading.Thread] = None
_audio_session: Optional[AudioSession] = None


def _default_bus_factory() -> Bus:
    return InProcBus()


def _default_synth_factory() -> Synthesizer:
    # Late import — speak.py imports from this module, so a module-level
    # import would be circular.
    from jaeger_os.plugins.kokoro_tts import KOKORO_LANG, KokoroTTS
    from jaeger_os.core.tools.speak import _resolve_voice

    return KokoroTTS(voice=_resolve_voice(), lang=KOKORO_LANG)


def _default_tts_node_factory(
    *,
    bus: Bus,
    synthesizer: Synthesizer,
) -> TTSNode:
    return TTSNode(
        bus=bus,
        synthesizer=synthesizer,
        name="tts",
        install_signal_handlers=False,
    )


def _default_thread_factory(node: TTSNode) -> threading.Thread:
    return threading.Thread(
        target=node.run,
        name="brain-tts-node",
        daemon=True,
    )


def _default_audio_session_factory(
    config: AudioSessionConfig,
) -> AudioSession:
    # Wire the brain's LLM client + lock through so the node-owned
    # LLM gate (operator-locked 2026-06-07) can classify phrases
    # inside the session.  When the brain hasn't loaded yet (rare —
    # only voice-only configurations during early boot), the gate
    # degrades to deterministic filters and accepts unknown phrases.
    from jaeger_os.main import _pipeline
    llm_client = _pipeline.get("client")
    llm_lock = _pipeline.get("llm_lock")
    return AudioSession.build(
        config,
        tts_synth=get_synth(),
        llm_client=llm_client,
        llm_lock=llm_lock,
    )


def _default_audio_session_node_factory(
    *,
    bus: Bus,
    session: AudioSession,
) -> AudioSessionNode:
    return AudioSessionNode(
        bus=bus,
        session=session,
        name="audio_session",
        install_signal_handlers=False,
    )


def _default_audio_thread_factory(node: AudioSessionNode) -> threading.Thread:
    return threading.Thread(
        target=node.run,
        name="brain-audio-session-node",
        daemon=True,
    )


_bus_factory: Callable[[], Bus] = _default_bus_factory
_synth_factory: Callable[[], Synthesizer] = _default_synth_factory
_tts_node_factory: Callable[..., TTSNode] = _default_tts_node_factory
_thread_factory: Callable[[TTSNode], threading.Thread] = _default_thread_factory
_audio_session_factory: Callable[[AudioSessionConfig], AudioSession] = (
    _default_audio_session_factory
)
_audio_session_node_factory: Callable[..., AudioSessionNode] = (
    _default_audio_session_node_factory
)
_audio_thread_factory: Callable[[AudioSessionNode], threading.Thread] = (
    _default_audio_thread_factory
)


def get_bus() -> Bus:
    """Return the brain's singleton Bus, creating it on first call.

    Today: always :class:`InProcBus`.  Track A.7 will introduce a
    ZMQ variant chosen by the operator's ``--mode`` flag.
    """
    global _bus
    with _lock:
        if _bus is None:
            _bus = _bus_factory()
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
    synth_to_warm: Any = None
    with _lock:
        if _tts_node is None:
            _synth = _synth_factory()
            _tts_node = _tts_node_factory(bus=bus, synthesizer=_synth)
            _tts_thread = _thread_factory(_tts_node)
            _tts_thread.start()
            _wait_for_node_running(_tts_node, timeout_s=2.0)
        if warm and _synth is not None:
            synth_to_warm = _synth
        node = _tts_node
    if warm and synth_to_warm is not None:
        try:
            synth_to_warm.warm()
        except Exception:  # noqa: BLE001
            # Warm failure is non-fatal — the first speak() will
            # warm lazily.  Log but proceed.
            import sys
            print(
                "[runtime] kokoro warm at ensure_tts_node failed; "
                "first speak() will pay the load tax",
                file=sys.stderr, flush=True,
            )
    return node


def ensure_audio_session_node(
    *,
    config: AudioSessionConfig,
) -> AudioSessionNode:
    """Make sure exactly one audio session node owns the mic.

    The session factory receives the already-running TTS synth so
    monolithic AEC can share its ``reference_buffer`` directly.  This is
    intentional 0.4.0 coupling pending multiprocess reference transport.
    """
    global _audio_session_node, _audio_session_thread, _audio_session
    ensure_tts_node()
    bus = get_bus()
    with _lock:
        if _audio_session_node is None:
            _audio_session = _audio_session_factory(config)
            _audio_session_node = _audio_session_node_factory(
                bus=bus,
                session=_audio_session,
            )
            _audio_session_thread = _audio_thread_factory(_audio_session_node)
            _audio_session_thread.start()
            _wait_for_node_running(_audio_session_node, timeout_s=5.0)
        return _audio_session_node


def _wait_for_node_running(node: TTSNode, *, timeout_s: float) -> None:
    """Wait until ``node.setup()`` has completed.

    ``Node.run()`` sets state to RUNNING only after setup returns, so
    observing RUNNING means the TTS subscriber is installed.  This
    replaces the old fixed sleep which could race slow test or dev
    machines.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if node.state == NodeState.RUNNING:
            return
        if node.state == NodeState.FAILED:
            raise RuntimeError(
                f"TTS node failed during setup: {node.health().get('error')}"
            )
        time.sleep(0.01)
    raise TimeoutError("TTS node did not reach RUNNING state")


def get_synth():
    """Expose the KokoroTTS instance the TTS node wraps.

    Used by ``warm_kokoro()`` so it can return Kokoro's own warm-
    report dict (matches the pre-0.4 signature)."""
    return _synth


def get_audio_session() -> AudioSession | None:
    """Return the monolithic audio session, if started."""
    return _audio_session


def shutdown_audio_session_node() -> None:
    """Stop only the audio session node, leaving TTS/bus alive."""
    global _audio_session_node, _audio_session_thread, _audio_session
    with _lock:
        audio_node = _audio_session_node
        audio_thread = _audio_session_thread
        _audio_session_node = None
        _audio_session_thread = None
        _audio_session = None
    if audio_node is not None:
        audio_node.stop()
        if audio_thread is not None:
            audio_thread.join(timeout=3.0)


def shutdown() -> None:
    """Stop the TTS node, close the bus.  Idempotent."""
    global _bus, _tts_node, _tts_thread, _synth
    global _audio_session_node, _audio_session_thread, _audio_session
    with _lock:
        audio_node = _audio_session_node
        audio_thread = _audio_session_thread
        node = _tts_node
        thread = _tts_thread
        bus = _bus
        _audio_session_node = None
        _audio_session_thread = None
        _audio_session = None
        _tts_node = None
        _tts_thread = None
        _bus = None
        _synth = None
    if audio_node is not None:
        audio_node.stop()
        if audio_thread is not None:
            audio_thread.join(timeout=3.0)
    if node is not None:
        node.stop()
        if thread is not None:
            thread.join(timeout=3.0)
    if bus is not None:
        bus.close()
