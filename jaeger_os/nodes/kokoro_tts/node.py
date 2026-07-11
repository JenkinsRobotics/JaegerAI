"""tts.py — TTS node.  First Track B node.

Wraps the existing in-process :class:`KokoroTTS` engine as a Bus-
addressable node.  Subscribes to ``/act/speech`` (the brain's
text-to-speech command topic), runs synthesis + playback on the
node's own work thread, and publishes ``/sense/spoken`` as the ack
the brain's ``text_to_speech`` tool will await (Track B.2).

Why this is the right "first real node"
---------------------------------------
* TTS has a clean request → ack shape — easiest demonstration of
  the operator's "tools = networking, nodes = execution" contract.
* The existing :class:`KokoroTTS` engine is proven (0.3.0 ships it).
  We're wrapping it, not reimplementing.
* No mic / STT involvement — half the audio pipeline isolated from
  the change.
* Doesn't touch the brain or voice loop in this commit; Track B.2
  is the brain-side rewire (text_to_speech tool publishes /act/speech
  via the bus instead of calling speak() in-process).

Threading
---------
The bus delivery thread MUST NOT block on slow work; otherwise it
back-pressures every other subscriber on every other topic.  TTS
synthesis + playback takes hundreds of ms to seconds, so the
subscriber callback (``_on_speech_command``) only enqueues; the
node's own ``tick()`` drains the queue and runs synthesis serially
on the node thread.

Backpressure
------------
Internal queue is bounded (default 32 messages).  When full, the
new request gets an immediate failure ack (``ok=False``,
``reason="TTS queue full"``) so the brain's tool sees the rejection
right away rather than waiting for a timeout.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Protocol

from jaeger_os.transport import topics
from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus


class Synthesizer(Protocol):
    """The bit of :class:`KokoroTTS` the TTS node depends on.

    Production callers pass the real ``KokoroTTS`` instance.  Tests
    pass a mock that records calls and returns canned results.
    """

    def speak(self, text: str) -> dict[str, Any]:
        """Synthesize + play ``text``; block until playback finishes.
        Returns a dict with at least ``spoken: bool``; may also carry
        ``elapsed_s``, ``reason`` (when ok=False), ``text`` (cleaned),
        ``samples``."""
        ...

    def shutdown(self) -> None:
        """Tear the synthesizer down cleanly (close audio device,
        unload model)."""
        ...


class TTSNode(Node):
    """SUB ``/act/speech`` → synthesize → PUB ``/sense/spoken``.

    The synthesizer is dependency-injected so tests can substitute a
    mock without touching audio or model loading.  Production
    instantiation lives in ``dev/scripts/tts_node_test.py`` (the
    integration smoke) and at Track B.2 will move to the brain's
    boot path so the ``text_to_speech`` tool can route through the
    bus instead of calling KokoroTTS in-process.
    """

    def __init__(
        self,
        *,
        bus: Bus,
        synthesizer: Synthesizer,
        name: str = "tts",
        queue_maxsize: int = 32,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self.synthesizer = synthesizer
        # Per-message handoff from bus delivery thread → node thread.
        self._pending: "queue.Queue[topics.SpeechCommand]" = queue.Queue(
            maxsize=queue_maxsize,
        )
        # Correlation id for the speech currently inside synthesizer.speak().
        # A SpeechStop carrying a different id is stale and must not cut a
        # newer utterance that happened to start after the operator's stop.
        self._active_correlation_id: str | None = None

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        self.bus.subscribe(topics.ACT_SPEECH, self._on_speech_command)
        self.bus.subscribe(topics.ACT_SPEECH_STOP, self._on_speech_stop)
        self._log(
            f"subscribed to {topics.ACT_SPEECH} + {topics.ACT_SPEECH_STOP}"
        )

    def tick(self) -> None:
        """Drain one queued speech request per tick.  Synthesis runs
        synchronously on this thread; the next tick won't start until
        the current speech finishes playing."""
        try:
            msg = self._pending.get(timeout=0.1)
        except queue.Empty:
            return
        self._handle(msg)

    def teardown(self) -> None:
        try:
            self.bus.unsubscribe(topics.ACT_SPEECH, self._on_speech_command)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.bus.unsubscribe(
                topics.ACT_SPEECH_STOP, self._on_speech_stop,
            )
        except Exception:  # noqa: BLE001
            pass
        if self.synthesizer is not None:
            try:
                self.synthesizer.shutdown()
            except Exception as exc:  # noqa: BLE001
                self._log(f"synthesizer shutdown error: "
                          f"{type(exc).__name__}: {exc}")

    # ── subscriber + worker ──────────────────────────────────────

    def _on_speech_command(self, msg: topics.TopicMessage) -> None:
        """Called by the bus delivery thread.  Must return quickly —
        delegate slow work to the node tick()."""
        assert isinstance(msg, topics.SpeechCommand), (
            f"TTS node got unexpected topic: {msg.topic}"
        )
        try:
            self._pending.put_nowait(msg)
        except queue.Full:
            # Immediate-fail ack so the brain's tool sees rejection.
            self._publish_ack(
                msg, ok=False, reason="TTS queue full", duration_s=0.0,
            )

    def _on_speech_stop(self, msg: topics.TopicMessage) -> None:
        """Barge-in primitive: the voice loop (or any other coordinator)
        publishes :class:`SpeechStop` when it wants the in-flight speech
        cut.  We forward to ``synthesizer.stop()`` if the engine
        supports it; the in-flight ``synthesizer.speak()`` returns
        promptly with ``spoken=False`` and the worker's normal
        flow publishes the SpokenAck so any bus.request() in flight
        wakes up.

        Runs on the bus delivery thread — must not block.
        ``synthesizer.stop()`` is implemented as a flag flip on
        KokoroTTS, so it's effectively instant."""
        assert isinstance(msg, topics.SpeechStop), (
            f"TTS node got unexpected topic on speech_stop subscription: "
            f"{msg.topic}"
        )
        if (
            msg.correlation_id
            and self._active_correlation_id
            and msg.correlation_id != self._active_correlation_id
        ):
            self._log(
                "speech_stop ignored for stale correlation_id "
                f"{msg.correlation_id}"
            )
            return
        if msg.correlation_id and self._active_correlation_id is None:
            self._log(
                "speech_stop ignored because no matching speech is active"
            )
            return
        stop = getattr(self.synthesizer, "stop", None)
        if not callable(stop):
            self._log(
                "speech_stop received but synthesizer has no stop(); "
                "ignoring"
            )
            return
        try:
            stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"synthesizer stop() raised: "
                      f"{type(exc).__name__}: {exc}")

    def _handle(self, msg: topics.SpeechCommand) -> None:
        t0 = time.perf_counter()
        self._active_correlation_id = msg.correlation_id
        # 0.5 lip-sync proxy: emit /sense/tts_chunk events at ~30 Hz
        # while the synthesizer runs.  Amplitude is a sin-wave
        # placeholder; real RMS sampling is a 0.5.x followup once
        # Kokoro exposes streaming audio.
        amp_stop = threading.Event()
        cid_for_chunks = msg.correlation_id or ""
        amp_thread = threading.Thread(
            target=self._tts_amplitude_pulse,
            args=(amp_stop, cid_for_chunks),
            name=f"tts-amp-{cid_for_chunks[:8] or 'anon'}",
            daemon=True,
        )
        amp_thread.start()
        try:
            result = self.synthesizer.speak(msg.text)
        except Exception as exc:  # noqa: BLE001
            self._log(f"speak() raised: {type(exc).__name__}: {exc}")
            amp_stop.set()
            amp_thread.join(timeout=0.5)
            self._publish_ack(
                msg, ok=False,
                reason=f"{type(exc).__name__}: {exc}",
                duration_s=time.perf_counter() - t0,
            )
            return
        finally:
            amp_stop.set()
            amp_thread.join(timeout=0.5)
            self._active_correlation_id = None
        # Final 0-amplitude chunk so the face's mouth closes
        # cleanly when the utterance ends.
        try:
            self.bus.publish(topics.TtsChunk(
                amplitude=0.0,
                is_final=True,
                node_id=self.name,
                correlation_id=cid_for_chunks,
            ))
        except Exception:  # noqa: BLE001
            pass
        ok = bool(result.get("spoken", False))
        # Prefer the synthesizer's elapsed if it gives one (more
        # accurate — includes synth time, not just playback) but
        # fall back to wall-clock so the brain always gets a number.
        duration_s = float(
            result.get("elapsed_s") or (time.perf_counter() - t0)
        )
        reason = result.get("reason") if not ok else None
        self._publish_ack(msg, ok=ok, duration_s=duration_s, reason=reason)

    def _tts_amplitude_pulse(
        self,
        stop_event: threading.Event,
        correlation_id: str,
    ) -> None:
        """Emit ``/sense/tts_chunk`` events at ~30 Hz with a sin
        amplitude shape until ``stop_event`` is set.

        0.5.0 lip-sync proxy: not real audio sampling, but a
        believable mouth-open/close cycle so Lilith looks like
        she's saying something rather than staring blankly.  The
        sin frequency (~5 Hz) approximates syllable rate; the
        small jitter keeps it from looking mechanical.
        """
        import math
        import random
        interval_s = 1.0 / 30.0
        t0 = time.perf_counter()
        while not stop_event.is_set():
            t = time.perf_counter() - t0
            # Sin pulse with a small noise floor + jitter.
            base = (math.sin(2 * math.pi * 5.0 * t) + 1.0) / 2.0
            jitter = random.uniform(-0.1, 0.1)
            amplitude = max(0.0, min(1.0, base * 0.7 + 0.15 + jitter))
            try:
                self.bus.publish(topics.TtsChunk(
                    amplitude=amplitude,
                    is_final=False,
                    node_id=self.name,
                    correlation_id=correlation_id,
                ))
            except Exception:  # noqa: BLE001
                return
            stop_event.wait(timeout=interval_s)

    def _publish_ack(
        self,
        request: topics.SpeechCommand,
        *,
        ok: bool,
        duration_s: float,
        reason: str | None,
    ) -> None:
        self.bus.publish(topics.SpokenAck(
            ok=ok,
            duration_s=duration_s,
            reason=reason,
            node_id=self.name,
            correlation_id=request.correlation_id,
        ))
