"""BusPlayer — publish synthesised audio instead of opening a speaker.

Drop-in for :class:`PersistentPlayer`. The engine's two playback paths
are written against that interface (``enqueue`` / ``mark_end`` /
``wait_until_drained`` / ``reset`` / ``cancel``), and the change worth
making is WHERE the audio goes, not how the synthesis loop is written —
so this keeps the shape and swaps the destination.

    KokoroTTS ──▶ /act/speaker/pcm ──▶ audio_io ──▶ the actual speaker

Three things that buys:

* **The speaker stops being exclusive.** Chimes are a second producer
  and always were; under the old shape both this player and
  ``core/audio/chimes.py`` opened the output device independently.
* **Echo cancellation gets the audio for free.** The driver writes
  every played frame into its own AEC reference. That used to require
  threading a ``ReferenceBuffer`` from here, through ``runtime.py``,
  into the STT engine's mic callback.
* **It can be somewhere else.** Synthesis on a workstation, playback on
  the robot, is now a transport question rather than a rewrite.

WHAT IT COSTS, honestly: this player no longer knows when audio
finished, because it no longer owns the device that finishes it. The
driver reports that on ``/act/speaker/state`` and
:meth:`wait_until_drained` waits for it. If no driver is running, that
wait times out rather than hanging — see :data:`DRAIN_GRACE_S`.
"""

from __future__ import annotations

import sys
import threading
from typing import Any

import numpy as np

from jaeger_os.app.logging import log

#: How long to keep waiting after the last chunk is sent before giving
#: up on ever hearing "idle". Covers the driver's own buffering; long
#: enough not to cut a sentence short, short enough that a missing
#: driver surfaces as a slow reply rather than a hang.
DRAIN_GRACE_S = 5.0


class BusPlayer:
    """Publishes audio; something else plays it."""

    SUPPORTED_BACKENDS = ("bus",)

    def __init__(
        self,
        *,
        bus: Any,
        backend: str = "bus",
        samplerate: int = 24000,
        channels: int = 1,
    ) -> None:
        self.bus = bus
        self.backend = "bus"
        self.samplerate = int(samplerate)
        self.channels = int(channels)

        # Kept because the engine prints them at open and includes them
        # in its result dicts. There is no local device to name.
        self.device_index = None
        self.device_name = "bus:/act/speaker/pcm"

        self._open = False
        self._idle = threading.Event()
        self._idle.set()               # nothing sent yet == drained
        self._ended = threading.Event()
        self._sent_samples = 0
        self._subscribed = False
        # Every utterance gets its own id.  Speaker state is shared by all
        # audio producers (TTS, chimes, notifications), so accepting an
        # unrelated "idle" edge would acknowledge speech that has not
        # actually finished.
        self._correlation_id: str | None = None
        self.last_error: str | None = None

    # ── lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        if self._subscribed:
            self._open = True
            return
        from jaeger_os.transport import topics
        self.bus.subscribe(topics.ACT_SPEAKER_STATE, self._on_speaker_state)
        self._subscribed = True
        self._open = True

    def is_open(self) -> bool:
        return self._open

    def close(self) -> None:
        if self._subscribed:
            from jaeger_os.transport import topics
            try:
                self.bus.unsubscribe(topics.ACT_SPEAKER_STATE,
                                     self._on_speaker_state)
            except Exception:  # noqa: BLE001
                pass
            self._subscribed = False
        self._open = False

    def reset(self) -> None:
        """Return to a clean idle state without tearing down the
        subscription — the engine calls this after a drain timeout."""
        self._idle.set()
        self._ended.clear()
        self._sent_samples = 0
        self.last_error = None

    def begin(self, correlation_id: str | None = None) -> None:
        """Start one logical utterance.

        The id is copied onto every PCM message and matched against the
        driver's completion signal.  ``None`` remains valid for standalone
        callers that do not need request/reply correlation.
        """
        self._correlation_id = correlation_id
        self.last_error = None
        self._ended.clear()
        self._sent_samples = 0

    # ── the audio path ───────────────────────────────────────────

    def enqueue(self, audio: np.ndarray) -> None:
        if audio is None:
            return
        if not isinstance(audio, np.ndarray):
            audio = np.asarray(audio, dtype=np.float32)
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.size == 0:
            return
        if not self._open:
            self.start()

        self._idle.clear()
        self._sent_samples += int(audio.size)
        from jaeger_os.transport import topics
        self.bus.publish(topics.AudioOutFrame(
            samples=audio.tobytes(),
            sample_rate=self.samplerate,
            channels=self.channels,
            correlation_id=self._correlation_id,
        ))

    def mark_end(self) -> None:
        """No more audio is coming for this utterance."""
        self._ended.set()

    def cancel(self) -> None:
        """Barge-in. Tell the driver to drop what is queued.

        Stopping synthesis alone is not enough: the sentence already
        published is on its way to the device, and that half-second is
        what makes an assistant feel deaf when you talk over it.
        """
        from jaeger_os.transport import topics
        try:
            self.bus.publish(topics.SpeakerStop(
                correlation_id=self._correlation_id,
            ))
        except Exception as exc:  # noqa: BLE001
            log("kokoro", f"speaker stop failed: {exc}", level="warn")
        self._idle.set()
        self._sent_samples = 0

    def wait_until_drained(self, timeout: float = 60.0) -> bool:
        """Block until the DEVICE finished playing, not until we
        finished sending.

        The distinction is the whole reason /act/speaker/state exists.
        A player that owned its stream could watch its own queue empty;
        one that publishes has to be told.
        """
        if self._idle.is_set():
            return True
        # Never wait longer than the audio could possibly last, plus
        # grace for the driver's own buffering. Without this bound a
        # missing driver hangs the speak() call forever.
        longest = self._sent_samples / float(self.samplerate) + DRAIN_GRACE_S
        drained = self._idle.wait(timeout=min(timeout, longest))
        if drained and self.last_error is not None:
            log("kokoro", f"speaker failed: {self.last_error}",
                level="error")
            return False
        if not drained:
            log("kokoro",
                f"no drain signal on /act/speaker/state after "
                f"{min(timeout, longest):.1f}s — is the audio_io driver "
                f"running? Publishing to an unconsumed topic succeeds "
                f"silently.", level="warn")
        return drained

    # ── the driver talking back ──────────────────────────────────

    def _on_speaker_state(self, msg: Any) -> None:
        if getattr(msg, "correlation_id", None) != self._correlation_id:
            return
        state = getattr(msg, "state", "")
        if state == "error":
            self.last_error = getattr(msg, "error", None) or "speaker error"
            self._idle.set()
        elif state == "idle":
            self._idle.set()


__all__ = ["BusPlayer", "DRAIN_GRACE_S"]
