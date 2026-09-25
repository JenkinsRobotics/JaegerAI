"""WhisperSTTWindow — rolling-window STT with no phrase segmentation.

Ported from MockingAgent's ``PywisperCpp/pywhispercpp_examples`` precursors:

  • ``livestream_mic.py``                          -> commit="window"
  • ``llm_listener/always_listening_word_cursor_pipeline.py``
    (+ ``human_style_overlapping_memory_pipeline.py``)
                                                   -> commit="agreement"

Unlike ``two_pass`` (WebRTC VAD closes a phrase) and ``continuous``
(RMS energy closes a phrase), this pipeline NEVER waits for a phrase
boundary.  It keeps the last ``window_s`` of audio in a ring and
re-transcribes the whole ring every ``transcribe_every_s``.  That is
what buys real partials: you get text while the sentence is still being
spoken, not after it ends.

The two commit policies are the same machine with a different rule for
"which of those words are safe to keep":

``commit="window"``
    Captions mode.  Every pass is published as a partial; every
    ``window_s`` of new audio the current window text is published as a
    final.  Finals therefore arrive on a clock, NOT on sentence
    boundaries — a "final" here means "this is what the last N seconds
    sounded like", so this mode is for a live caption pane, not for
    turn-taking with an agent.  ``livestream_mic.py`` behaved exactly
    this way.

``commit="agreement"``
    LocalAgreement-2 (Macháček et al., whisper-streaming), implemented
    as the karaoke word cursor from the MockingAgent pipeline.  Whisper
    revises the *tail* of a window between passes but almost never the
    head, so a word that survives into a later pass is stable.  We
    keep a cursor of already-committed words, find where the newest
    transcript overlaps it, and commit only what lies beyond the
    overlap.  Committed text is final and never re-emitted; the
    uncommitted tail is the partial.  This is the mode that gives live
    captions AND a trustworthy final transcript.

WHY ONE CLASS FOR BOTH: the ring buffer, the energy gate, the model
call, the wake-word gate, and the pause/follow-up lifecycle are
identical.  Only ``_commit_from`` differs.  ``local_agreement`` is a
four-line subclass — see ``../local_agreement/pipeline.py``.

Mic ownership is the same as every other pipeline here: this does NOT
open the device.  ``jaeger_os.nodes.audio_io`` publishes echo-cancelled
frames on ``/sense/mic/pcm`` and ``_MicStream`` subscribes.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher
from typing import Any

import numpy as np

from .._base import (
    DEFAULT_WAKE_PHRASES,
    WakeMissNotifier,
    log,
    _MicStream,
    _find_wake_in_text,
    _warm_stt,
    is_non_speech_marker,
    offer_latest,
    segments_text,
)


_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def word_pairs(text: str) -> list[tuple[str, str]]:
    """``[(normalized, original), ...]``.

    Matching MUST be case- and punctuation-insensitive: Whisper decides
    between "moon" and "moon!" on the same audio depending on how much
    context follows it, so a raw string compare reports two identical
    windows as completely different and the cursor loses its place.
    The original spelling is carried alongside so the transcript we
    publish still reads like English rather than like a bag of tokens.
    """
    out = []
    for m in _WORD_RE.finditer(text):
        original = m.group(0)
        cleaned = re.sub(r"[^a-z0-9]", "", original.lower())
        if cleaned:
            out.append((cleaned, original))
    return out


def commit_cursor(
    committed: list[str],
    candidate: list[str],
    *,
    min_overlap: int = 2,
) -> int | None:
    """Where in ``candidate`` do the not-yet-committed words start?

    The rolling window always re-decodes audio we already took, so a
    new transcript is (old words we've seen) + (new words).  This finds
    the boundary by locating the longest suffix of ``committed`` inside
    ``candidate``.  Three cases:

    0. Nothing committed yet -> 0, everything is new.
    1. ``candidate`` STARTS with a suffix of ``committed`` — the normal
       case -> the boundary is just past that overlap.
    2. The overlap sits further INSIDE ``candidate``, which happens
       when the window scrolled and re-decoded a little context ahead
       of the cursor -> scan forward and cut there.

    Returns ``None`` when no overlap of at least ``min_overlap`` words
    exists.  That is deliberately NOT "so take everything": a lost
    anchor is exactly the state where taking the window duplicates
    seconds of already-published text.  The caller waits for the next
    pass — the window overlaps ~80%, so an anchor almost always
    reappears — and only resyncs after several consecutive failures.

    ``min_overlap`` stops one common word ("the", "a") from faking an
    alignment.
    """
    if not candidate or not committed:
        return 0

    max_overlap = min(len(committed), len(candidate))
    for size in range(max_overlap, min_overlap - 1, -1):
        if committed[-size:] == candidate[:size]:
            return size

    for start in range(1, len(candidate)):
        for size in range(min(len(committed), len(candidate) - start),
                          min_overlap - 1, -1):
            if committed[-size:] == candidate[start:start + size]:
                return start + size

    return None


def agreed_prefix_len(a: list[str], b: list[str]) -> int:
    """How many leading words two hypotheses agree on.

    This is the ``LocalAgreement-2`` rule itself.  Whisper revises the
    END of a window between passes and almost never the beginning, so a
    word that two consecutive decodes both produce, in the same
    position, is stable enough to publish as final.  Anything past the
    disagreement is still in flux and stays a partial.
    """
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


class WhisperSTTWindow(WakeMissNotifier):
    """Rolling-window STT.  Public API matches WhisperSTTTwoPass, plus
    ``set_on_partial`` for live (``is_final=False``) text."""

    #: Registry name reported in logs — subclasses override.
    label = "stt-window"

    def __init__(
        self,
        *,
        model_name: str = "base.en",
        commit: str = "window",
        require_wake_word: bool = False,
        wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES,
        wake_match_threshold: float = 0.78,
        followup_window_s: float = 10.0,
        language: str = "en",
        sample_rate: int = 16000,
        block_ms: int = 30,
        # 7 s window / 1.2 s cadence are the word-cursor demo's values.
        # Whisper's accuracy falls off under ~5 s of context and the
        # decode cost grows with the window, so this is the knee.
        window_s: float = 7.0,
        transcribe_every_s: float = 1.2,
        min_transcribe_s: float = 1.0,
        post_padding_ms: int = 250,
        energy_threshold: float = 0.008,
        duplicate_similarity: float = 0.92,
        min_commit_words: int = 1,
        min_overlap_words: int = 2,
        max_commit_words: int = 28,
        # Passes to keep waiting for the cursor to realign before
        # giving up and resyncing. 4 passes ~= 5 s at the default
        # cadence, comfortably longer than one window.
        resync_after_passes: int = 4,
        mic_queue_max_frames: int = 200,
        output_queue_max_phrases: int = 32,
        bus: Any = None,
    ) -> None:
        from pywhispercpp.model import Model as STTModel

        if commit not in ("window", "agreement"):
            raise ValueError(f"commit must be 'window' or 'agreement', got {commit!r}")
        if sample_rate <= 0 or block_ms <= 0:
            raise ValueError("sample_rate and block_ms must be positive")
        if window_s <= 0 or transcribe_every_s <= 0 or min_transcribe_s <= 0:
            raise ValueError("window and transcription intervals must be positive")
        if energy_threshold < 0:
            raise ValueError("energy_threshold cannot be negative")
        if output_queue_max_phrases <= 0:
            raise ValueError("output_queue_max_phrases must be positive")
        self.commit = commit
        self.require_wake_word = require_wake_word
        self.wake_phrases = wake_phrases
        self.wake_match_threshold = wake_match_threshold
        self.followup_window_s = followup_window_s
        self.language = language.strip() or "en"
        self.sample_rate = sample_rate
        self.block_ms = block_ms
        self.window_s = window_s
        self.transcribe_every_s = transcribe_every_s
        self.energy_threshold = energy_threshold
        self.duplicate_similarity = duplicate_similarity
        self.min_commit_words = min_commit_words
        self.min_overlap_words = min_overlap_words
        self.max_commit_words = max_commit_words
        self._resync_after_passes = resync_after_passes

        self._frame_samples = int(sample_rate * block_ms / 1000)
        self._window_frames = max(1, int(window_s * 1000 / block_ms))
        self._min_transcribe_samples = int(sample_rate * min_transcribe_s)
        self._post_pad_samples = int(sample_rate * post_padding_ms / 1000)

        log(self.label, f"loading {model_name}...")
        t0 = time.perf_counter()
        self._model = STTModel(
            model_name,
            print_realtime=False, print_progress=False,
            single_segment=True, no_context=True,
        )
        log(self.label, f"model loaded — {time.perf_counter() - t0:.1f}s", level="ok")
        _warm_stt(self._model, self.label, sample_rate, self.language)

        self.mic = _MicStream(
            sample_rate=sample_rate, frame_samples=self._frame_samples,
            max_queue_frames=mic_queue_max_frames, bus=bus,
        )

        self._stop = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._committed_q: queue.Queue[str] = queue.Queue(
            maxsize=output_queue_max_phrases,
        )

        self._ring: deque[np.ndarray] = deque(maxlen=self._window_frames)
        #: Normalized words already handed out as final — the cursor.
        #: Bounded so a long session can't grow it without limit; only
        #: the tail is ever compared against.
        self._committed_words: deque[str] = deque(maxlen=320)
        #: Last pass's uncommitted tail (normalized).  The other half of
        #: LocalAgreement: this pass commits what both agree on.
        self._prev_tail: list[str] = []
        #: Consecutive passes where the cursor found no anchor.
        self._no_anchor = 0
        self._last_partial = ""
        self._last_committed_text = ""
        #: commit="window" only — frames of new audio since the last
        #: rollover, which is what puts finals on a clock.
        self._frames_since_commit = 0
        self._in_speech = False
        self._speech_hook_fired = False
        self._on_speech_detected = None
        self._on_partial = None

        self._state = "WAKE"
        self._followup_deadline = 0.0
        self.last_phrase_timing: dict[str, float] = {}
        self._started = False
        self._decode_failures = 0
        self._output_drops = 0
        self._last_error: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if self._started:
            return
        if self._stop.is_set():
            raise RuntimeError("a stopped Whisper engine cannot be restarted")
        self.mic.start()
        self._loop_thread = threading.Thread(
            target=self._run_guarded, daemon=True, name=self.label)
        try:
            self._loop_thread.start()
        except Exception:
            self.mic.stop()
            raise
        self._started = True

    def stop(self) -> None:
        self._stop.set()
        try:
            self.mic.stop()
        except Exception:  # noqa: BLE001
            pass
        thread = self._loop_thread
        if thread is not None and thread.is_alive() \
                and threading.current_thread() is not thread:
            thread.join(timeout=5.0)
        if thread is not None and thread.is_alive():
            self._last_error = "recognition worker did not stop within 5 seconds"

    def set_paused(self, paused: bool) -> None:
        self.mic.set_paused(paused)
        if paused:
            # Drop the ring AND the cursor. Resuming after playback is a
            # new acoustic context; carrying the old cursor across would
            # make the first post-pause overlap search align against
            # words the speaker has long since moved past.
            self._ring.clear()
            self._committed_words.clear()
            self._prev_tail = []
            self._no_anchor = 0
            self._last_partial = ""
            self._frames_since_commit = 0
            self._in_speech = False

    def open_followup(self) -> None:
        if self.require_wake_word:
            self._state = "FOLLOWUP"
            self._followup_deadline = time.monotonic() + self.followup_window_s

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def in_utterance(self) -> bool:
        """Identical to ``in_speech`` here — energy gating has no separate
        confidence stage.  Kept so call sites use one API across modes."""
        return self._in_speech

    def set_on_speech_detected(self, callback) -> None:
        self._on_speech_detected = callback

    def set_on_partial(self, callback) -> None:
        """Install a callback receiving live, NOT-yet-final text as a
        plain str.  Fires on the pipeline's own thread every
        ``transcribe_every_s`` while speech is present, so it must not
        block.  ``AudioSessionNode`` wires this to
        ``Transcript(is_final=False)``.  Pass None to clear."""
        self._on_partial = callback

    def drain_pending(self) -> None:
        with self._committed_q.mutex:
            self._committed_q.queue.clear()

    # ── Main loop ──────────────────────────────────────────────────────
    def _run_guarded(self) -> None:
        try:
            self._main_loop()
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"
            log(self.label, f"recognition worker stopped: {self._last_error}",
                level="error")

    def _main_loop(self) -> None:
        next_transcribe_at = time.monotonic() + self.transcribe_every_s
        while not self._stop.is_set():
            self._drain_audio()
            now = time.monotonic()
            if self.mic.paused:
                self._stop.wait(0.05)
                continue
            if now >= next_transcribe_at:
                self._pass()
                next_transcribe_at = now + self.transcribe_every_s
            self._stop.wait(0.02)

    def _drain_audio(self) -> None:
        try:
            while True:
                chunk = self.mic.q.get_nowait()
                mono = chunk[:, 0].astype(np.float32).reshape(-1)
                self._ring.append(mono)
                self._frames_since_commit += 1
                rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                if rms >= self.energy_threshold:
                    if not self._in_speech and self._on_speech_detected \
                            and not self._speech_hook_fired:
                        self._speech_hook_fired = True
                        try:
                            self._on_speech_detected()
                        except Exception:  # noqa: BLE001
                            pass
                    self._in_speech = True
        except queue.Empty:
            return

    def _window_audio(self) -> np.ndarray | None:
        """The ring as one float32 array, or None if too short or too
        quiet.  The energy gate is not optional: with no VAD, a silent
        room would otherwise be decoded ~1x/second forever and emit a
        stream of ``[BLANK_AUDIO]`` markers."""
        if not self._ring:
            return None
        audio = np.concatenate(list(self._ring)).astype(np.float32)
        if audio.size < self._min_transcribe_samples:
            return None
        rms = float(np.sqrt(np.mean(np.square(audio))))
        if rms < self.energy_threshold:
            self._in_speech = False
            self._speech_hook_fired = False
            return None
        return np.concatenate([audio, np.zeros(self._post_pad_samples, dtype=np.float32)])

    def _transcribe(self, audio: np.ndarray) -> str:
        try:
            return segments_text(self._model.transcribe(
                audio, language=self.language,
            ))
        except Exception as exc:  # noqa: BLE001
            self._decode_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            log(self.label, self._last_error, level="error")
            return ""

    def _pass(self) -> None:
        """One rolling decode.  The commit policy also decides what the
        partial should say — in agreement mode the committed words have
        already been published as finals, so echoing the whole window
        would show every word twice."""
        audio = self._window_audio()
        if audio is None:
            return
        t_decoded = time.perf_counter()
        text = self._transcribe(audio)
        if not text or is_non_speech_marker(text):
            return
        self._commit_from(text, t_decoded)

    def _emit_partial(self, text: str) -> None:
        if self._on_partial is None:
            return
        if SequenceMatcher(None, text, self._last_partial).ratio() \
                >= self.duplicate_similarity:
            return
        self._last_partial = text
        try:
            self._on_partial(text)
        except Exception:  # noqa: BLE001
            # A partial is a display convenience — never let a slow or
            # broken consumer wedge the decode loop.
            pass

    # ── Commit policies ────────────────────────────────────────────────
    def _commit_from(self, text: str, t_decoded: float) -> None:
        if self.commit == "agreement":
            self._commit_agreement(text, t_decoded)
        else:
            self._commit_window(text, t_decoded)

    def _commit_window(self, text: str, t_decoded: float) -> None:
        """Captions mode — the whole window is the live caption, and it
        is flushed as a final once ``window_s`` of new audio has
        accumulated.  Finals land on a clock, not on sentence
        boundaries."""
        self._emit_partial(text)
        if self._frames_since_commit < self._window_frames:
            return
        self._frames_since_commit = 0
        if SequenceMatcher(None, text, self._last_committed_text).ratio() \
                >= self.duplicate_similarity:
            return
        self._last_committed_text = text
        self._commit(text, t_decoded)

    def _commit_agreement(self, text: str, t_decoded: float) -> None:
        """LocalAgreement-2.

        Two rules, in order.  The cursor says which words are past what
        we already published; the agreement says which of THOSE two
        consecutive decodes both produced.  Only the second group is
        final — that is what stops a word landing in the transcript as
        "decade" and being revised to "decay" a second later, because
        the revision happens while it is still only a partial.
        """
        pairs = word_pairs(text)
        if not pairs:
            return
        candidate = [norm for norm, _ in pairs]

        cursor = commit_cursor(list(self._committed_words), candidate,
                               min_overlap=self.min_overlap_words)
        if cursor is None:
            # Anchor lost. Waiting is nearly always right — the window
            # overlaps ~80% so the next decode usually realigns — but
            # if it never does we would go permanently deaf, so resync
            # from scratch after a few passes.
            self._no_anchor += 1
            if self._no_anchor < self._resync_after_passes:
                return
            cursor, self._no_anchor = 0, 0
            self._committed_words.clear()
            self._prev_tail = []
        else:
            self._no_anchor = 0

        tail = pairs[cursor:]
        tail_norm = [norm for norm, _ in tail]
        self._emit_partial(" ".join(orig for _, orig in tail))

        agreed = agreed_prefix_len(tail_norm, self._prev_tail)
        if agreed < self.min_commit_words:
            self._prev_tail = tail_norm
            return
        take = tail[:min(agreed, self.max_commit_words)]
        self._committed_words.extend(norm for norm, _ in take)
        # What is left over is the hypothesis the NEXT pass compares
        # against — it must exclude what we just committed, or the
        # comparison is off by the length of this commit.
        self._prev_tail = tail_norm[len(take):]
        self._commit(" ".join(orig for _, orig in take), t_decoded)

    # ── Wake gate + publish ────────────────────────────────────────────
    def _commit(self, text: str, t_decoded: float) -> None:
        text = text.strip()
        if not text:
            return
        self.last_phrase_timing = {
            "speech_end": t_decoded,
            "stt_done": time.perf_counter(),
        }
        in_followup = (self._state == "FOLLOWUP"
                       and time.monotonic() <= self._followup_deadline)
        if not self.require_wake_word or in_followup:
            log("stt", f"heard {text!r}", level="debug")
            self._state = "WAKE"
            if offer_latest(self._committed_q, text):
                self._output_drops += 1
            return
        matched, remainder = _find_wake_in_text(
            text, self.wake_phrases, self.wake_match_threshold)
        if matched and remainder:
            log("stt", f"heard {text!r}", level="debug")
            self._state = "WAKE"
            if offer_latest(self._committed_q, remainder):
                self._output_drops += 1
            return
        self._notify_wake_miss(text)

    # ── Public phrase pump ─────────────────────────────────────────────
    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Block (up to ``timeout`` s) for the next committed text.
        Returns the string, or None on timeout."""
        try:
            return self._committed_q.get(timeout=timeout)
        except queue.Empty:
            if (self._state == "FOLLOWUP"
                    and time.monotonic() > self._followup_deadline
                    and self._committed_q.empty()):
                self._state = "WAKE"
            return None

    def health(self) -> dict[str, Any]:
        thread = self._loop_thread
        return {
            "mode": "local_agreement" if self.commit == "agreement" else "window",
            "started": self._started,
            "running": bool(thread and thread.is_alive()),
            "state": self._state,
            "in_speech": self._in_speech,
            "pending_phrases": self._committed_q.qsize(),
            "output_queue_capacity": self._committed_q.maxsize,
            "output_drops": self._output_drops,
            "decode_failures": self._decode_failures,
            "cursor_resync_wait": self._no_anchor,
            "last_error": self._last_error,
            "mic": self.mic.health(),
        }


__all__ = ["WhisperSTTWindow", "commit_cursor", "agreed_prefix_len",
           "word_pairs"]
