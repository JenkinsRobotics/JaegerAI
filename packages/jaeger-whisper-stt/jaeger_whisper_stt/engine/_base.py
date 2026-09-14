"""Shared helpers used by both two_pass.py and continuous.py.

Plugin-internal — not exported through __init__.py. Both STT modes need:
  • _MicStream            — mic frames off the bus, pauseable queue
  • _warm_stt             — silence-pass priming so first phrase isn't slow
  • _normalize            — lowercase + strip punctuation for wake-word match
  • _find_wake_in_text    — substring + fuzzy wake-phrase matcher
  • DEFAULT_WAKE_PHRASES  — canonical wake-phrase list (handles Whisper
                            mishearings: yeager/yager/jager/jaeger)

`_VadWorker` is two-pass specific (energy-segmentation in continuous mode
replaces it), so it stays in two_pass.py.

THIS MODULE NO LONGER OPENS THE MICROPHONE. `jaeger_os.nodes.audio_io`
owns the device and publishes echo-cancelled frames on /sense/mic/pcm;
`_MicStream` below subscribes. That is what lets a wake-word detector or
a level meter have the same microphone at the same time — under the old
shape this module held the input stream and nothing else could get it.

AEC moved with the device. It needs the mic frame and the audio being
played TOGETHER per frame, so it belongs where both are native; keeping
it here would have meant shipping the far-end reference across a
boundary 100 times a second.
"""

from __future__ import annotations

import queue
import re
import time
from difflib import SequenceMatcher
from typing import Any

import threading

import numpy as np

#: The framework's log line, imported not wrapped. There used to be a
#: local shim here that fell back to ``print`` if jaeger-os was missing;
#: it guarded a case that cannot happen — ``jaeger-os>=0.10`` is the
#: first line of this module's requirements.txt, and the import right
#: below has always been unconditional.
from jaeger_os.app.logging import log as log
from jaeger_os.core.voice import is_non_speech_marker as is_non_speech_marker


_WAKE_PREFIXES = ("ok", "okay", "hey")
_ASSISTANT_NAMES = ("jaeger", "yeager", "yager", "jager")
DEFAULT_WAKE_PHRASES = tuple(f"{p} {n}" for p in _WAKE_PREFIXES for n in _ASSISTANT_NAMES)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _find_wake_in_text(
    text: str,
    wake_phrases: tuple[str, ...],
    wake_match_threshold: float,
) -> tuple[bool, str]:
    """Return (matched, remainder_after_wake). Wake phrase MUST be at
    the FIRST 2 tokens of the transcript — VOICE-3 in
    docs/ROADMAP_0.2.0.md.

    Previously the matcher looked anywhere in the utterance, which
    meant "Yes I think hey jaeger is cool" wrongly triggered. The
    new gate is "wake phrase is the opening of the sentence" —
    matches a real call to the agent without matching incidental
    mentions. Falls back to a fuzzy match on the same 2-token
    window for Whisper mishearings.
    """
    norm = _normalize(text)
    tokens = norm.split()
    if not tokens:
        return False, ""

    # All known wake phrases are 2 tokens ("hey jaeger", "ok jaeger",
    # …). If a longer phrase ever joins the set, the window grows
    # with it.
    for phrase in wake_phrases:
        phrase_tokens = phrase.split()
        n = len(phrase_tokens)
        if len(tokens) < n:
            continue
        head = " ".join(tokens[:n])
        if head == phrase:
            return True, " ".join(tokens[n:]).strip()

    # Fuzzy fallback — only on the head window, not anywhere in the
    # sentence. Threshold from the caller (default 0.78).
    for phrase in wake_phrases:
        phrase_tokens = phrase.split()
        n = len(phrase_tokens)
        if len(tokens) < n:
            continue
        head = " ".join(tokens[:n])
        if SequenceMatcher(None, head, phrase).ratio() >= wake_match_threshold:
            return True, " ".join(tokens[n:]).strip()

    return False, ""


def segments_text(result) -> str:
    """pywhispercpp returns a list of Segment; the pipelines want a
    string.  Tolerates a plain str so a fake model in a test can return
    one directly."""
    if isinstance(result, str):
        return result.strip()
    return " ".join(s.text.strip() for s in result if s.text.strip()).strip()


class WakeMissNotifier:
    """Report speech that was transcribed but carried no wake phrase.

    This is the single most common reason a wake-gated engine appears
    dead: it heard you perfectly and dropped the phrase because the wake
    word was missing. Until now the only trace was a debug log line, so
    an app could not tell "nothing was said" from "you weren't addressed"
    — the two look identical on the bus, because neither produces a
    message.

    The engine deliberately does NOT publish this itself. Every topic
    this module produces is published by ``AudioSessionNode``; a second
    publisher on ``/sys/gate/decision`` would mean two places to look
    when the voice-activity log is wrong. So the engine hands the text
    over and the node decides what it becomes — the same shape as
    ``set_on_partial`` and ``set_on_speech_detected``.
    """

    #: Class-level default so subclasses need no __init__ cooperation.
    _on_wake_miss = None

    def set_on_wake_miss(self, callback) -> None:
        """Install a callback taking the heard text. ``None`` clears it."""
        self._on_wake_miss = callback

    def _notify_wake_miss(self, text: str) -> None:
        """Log it, then hand it to whoever is listening.

        Runs on the decode thread, so a slow or throwing listener would
        stall recognition — hence the guard. A broken voice-activity log
        must never cost you the microphone.
        """
        log("stt", f"mic heard {text!r} — not sent", level="debug")
        callback = self._on_wake_miss
        if callback is None:
            return
        try:
            callback(text)
        except Exception:  # noqa: BLE001 — a listener never kills decode
            pass


def offer_latest(target: queue.Queue, item: Any) -> bool:
    """Put ``item`` without blocking; evict the oldest item if full.

    Realtime speech must be bounded.  If a downstream consumer stalls, an
    unbounded transcript/audio queue turns a temporary delay into growing
    memory use and increasingly stale robot reactions.  ``True`` means an old
    item had to be dropped and should be reflected in health telemetry.
    """
    try:
        target.put_nowait(item)
        return False
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(item)
        except queue.Full:
            return True
        return True


# ``stt_verbose()`` used to live here: a module-private
# ``JAEGER_STT_VERBOSE`` switch, checked with an ``if`` at each of 19
# call sites before a ``print``. It is gone, and nothing replaced it —
# per-phrase traces are now ``log(..., level="debug")``, which the
# framework silences unless ``JAEGER_DEBUG=1`` (everything) or
# ``JAEGER_DEBUG=stt`` (this engine). One switch every module honours,
# instead of one env var per module that an operator had to find by
# reading source.


def _warm_stt(
    model, label: str, sample_rate: int, language: str = "en",
) -> None:
    """Run a 1.5-second silence transcription so the first real phrase doesn't
    pay model setup cost. Whisper rejects audio under 1000 ms (skips
    inference + warns), so 1.5 s is the safe minimum for warming."""
    warm_audio = np.zeros(int(sample_rate * 1.5), dtype=np.float32)
    log(label, "warming up...")
    t0 = time.perf_counter()
    try:
        list(model.transcribe(warm_audio, language=language))
    except Exception as exc:
        log(label, f"warm-up skipped: {exc}", level="warn")
    else:
        log(label, f"primed — {time.perf_counter() - t0:.1f}s", level="ok")


#: How long to wait for the first mic frame before warning that
#: nothing is publishing. Long enough that a slow driver boot does not
#: cry wolf, short enough that an operator sees it before giving up.
LIVENESS_TIMEOUT_S = 3.0
#: Once useful microphone frames have started, an older last-frame age means
#: the upstream audio driver stopped delivering.  The driver owns recovery;
#: this value makes the downstream failure visible in STT health as well.
MIC_STALE_S = 5.0


class _MicStream:
    """Mic frames off the bus, with the queue+pause shape the pipelines
    already expect.

    Deliberately keeps `_MicStream`'s interface — `.q`, `.start()`,
    `.stop()`, `.set_paused()`, `.paused` — because the two pipelines
    are written against it and the change worth making here is WHERE
    the audio comes from, not how the VAD reads it.

    PAUSE IS LOCAL NOW. It used to stop the device. A shared microphone
    cannot honour that: one consumer pausing would starve every other
    subscriber. So a paused stream drops frames on arrival instead. The
    observable effect for this pipeline is identical, and the device
    keeps serving everyone else.
    """

    def __init__(
        self,
        *,
        bus: Any,
        sample_rate: int,
        frame_samples: int,
        max_queue_frames: int = 200,
    ) -> None:
        if bus is None:
            raise ValueError("_MicStream requires a JaegerOS bus")
        if sample_rate <= 0 or frame_samples <= 0:
            raise ValueError("sample_rate and frame_samples must be positive")
        if max_queue_frames <= 0:
            raise ValueError("max_queue_frames must be positive")
        self.bus = bus
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queue_frames)
        self.paused = False
        self._subscribed = False
        self._frames_seen = 0
        self._frames_valid = 0
        self._frames_dropped = 0
        self._rate_mismatches = 0
        self._invalid_frames = 0
        self._last_frame_at = 0.0
        self._started_at = 0.0
        self._last_error: str | None = None
        self._liveness: threading.Timer | None = None
        #: Leftover samples between bus frames — see _on_frame.
        self._carry: np.ndarray = np.empty(0, dtype=np.float32)
        self._warned_rate = False
        self._warned_format = False
        self._buffer_lock = threading.Lock()

    def _on_frame(self, msg: Any) -> None:
        self._frames_seen += 1
        if self.paused:
            return
        # SAMPLE RATE is a real wiring error — correcting it means
        # resampling, a DSP decision this class must not make silently.
        rate = getattr(msg, "sample_rate", self.sample_rate)
        if rate != self.sample_rate:
            self._rate_mismatches += 1
            if not self._warned_rate:      # once, not 100x a second
                log("mic", f"ignoring {rate} Hz audio (this pipeline is "
                           f"{self.sample_rate} Hz) — fix the driver's rate "
                           f"or the engine's sample_rate", level="warn")
                self._warned_rate = True
            return

        # FRAME SIZE is not. This used to drop any frame that was not
        # exactly frame_samples, which made the module deaf against a
        # perfectly good driver: jaeger_os's audio_io publishes 10 ms
        # frames because speexdsp's AEC requires fixed equal-length
        # near/far frames, while this pipeline's VAD wants 30 ms. Both
        # defaults are right for their own reasons, and neither side
        # can be declared the wiring error.
        #
        # So REGROUP instead of refusing. Buffering is lossless and
        # costs a copy — unlike resampling, which is why the original
        # refusal was correct about rate and wrong about size. Works in
        # both directions: 3 small frames in -> 1 block out, or 1 large
        # frame in -> several blocks out.
        try:
            channels = int(getattr(msg, "channels", 1))
            raw = msg.samples
            if channels != 1 or len(raw) % np.dtype(np.float32).itemsize:
                raise ValueError(
                    f"expected mono float32 PCM, got channels={channels}, "
                    f"bytes={len(raw)}"
                )
            samples = np.frombuffer(raw, dtype=np.float32)
        except Exception as exc:  # malformed bus input must not kill delivery
            self._invalid_frames += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            if not self._warned_format:
                log("mic", f"ignoring malformed audio frame ({exc})", level="warn")
                self._warned_format = True
            return

        self._frames_valid += 1
        self._last_frame_at = time.monotonic()
        with self._buffer_lock:
            self._carry = (samples if self._carry.size == 0
                           else np.concatenate((self._carry, samples)))
            n = self.frame_samples
            while self._carry.size >= n:
                self._offer(self._carry[:n].reshape(-1, 1))
                self._carry = self._carry[n:]

    def _offer(self, sample: np.ndarray) -> None:
        """Queue one VAD-sized block. Newest wins: a backed-up VAD
        should work on recent audio, not grind through a backlog from
        seconds ago."""
        try:
            self.q.put_nowait(sample)
        except queue.Full:
            self._frames_dropped += 1
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(sample)
            except queue.Full:
                pass

    def start(self) -> None:
        if self._subscribed:
            return
        from jaeger_os.transport import topics
        self.bus.subscribe(topics.SENSE_MIC_PCM, self._on_frame)
        self._subscribed = True
        self._started_at = time.monotonic()
        self._arm_liveness_check(topics.SENSE_MIC_PCM)

    def _arm_liveness_check(self, topic: str) -> None:
        """Say something if no audio ever arrives.

        This is the failure mode the driver split introduced, and it is
        the nastiest kind: subscribing to a topic nobody publishes
        SUCCEEDS. Without this the symptom is an agent that never hears
        you, reports healthy, and logs nothing — strictly worse than
        the ``OSError`` you used to get from a missing device.
        """
        def _check() -> None:
            if self._frames_valid:
                return
            log("mic",
                f"no audio on {topic} after {LIVENESS_TIMEOUT_S:.0f}s. "
                f"Nothing is publishing it — is the audio_io driver in "
                f"this app's node list? Subscribing to an unpublished "
                f"topic succeeds silently, so this warning is the only "
                f"symptom you get.", level="warn")

        self._liveness = threading.Timer(LIVENESS_TIMEOUT_S, _check)
        self._liveness.daemon = True
        self._liveness.start()

    def stop(self) -> None:
        if self._liveness is not None:
            self._liveness.cancel()
            self._liveness = None
        if not self._subscribed:
            return
        from jaeger_os.transport import topics
        try:
            self.bus.unsubscribe(topics.SENSE_MIC_PCM, self._on_frame)
        finally:
            self._subscribed = False
            self.drain()

    def drain(self) -> int:
        """Discard queued and partial audio, returning the number dropped."""
        with self._buffer_lock:
            self._carry = np.empty(0, dtype=np.float32)
        with self.q.mutex:
            count = len(self.q.queue)
            self.q.queue.clear()
        return count

    def set_paused(self, paused: bool) -> None:
        if paused == self.paused:
            return
        self.paused = paused
        # Audio on either side of a pause boundary belongs to different
        # acoustic contexts.  Keeping even the partial carry can splice the
        # robot's playback tail onto the next user's first syllable.
        self.drain()

    def health(self) -> dict[str, Any]:
        """Realtime ingress telemetry for node health and soak tests."""
        now = time.monotonic()
        age = None if not self._last_frame_at else now - self._last_frame_at
        grace = bool(self._started_at and now - self._started_at < LIVENESS_TIMEOUT_S)
        receiving = bool(
            self._subscribed
            and not self.paused
            and age is not None
            and age < MIC_STALE_S
        )
        return {
            "subscribed": self._subscribed,
            "paused": self.paused,
            "receiving": receiving,
            "startup_grace": grace,
            "frames_received": self._frames_seen,
            "frames_valid": self._frames_valid,
            "frames_dropped": self._frames_dropped,
            "rate_mismatches": self._rate_mismatches,
            "invalid_frames": self._invalid_frames,
            "queue_depth": self.q.qsize(),
            "queue_capacity": self.q.maxsize,
            "last_frame_age_s": age,
            "last_error": self._last_error,
        }
