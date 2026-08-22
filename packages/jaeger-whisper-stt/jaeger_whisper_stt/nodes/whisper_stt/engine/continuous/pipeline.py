"""WhisperSTTContinuous — energy-segmented, rolling re-transcription.

Algorithm ported from VoiceLLM's continuous.py (which in turn came from
MockingAgent's hybrid phrase/word pipeline). Adapted for our agent flow:
no bus, exposes blocking `next_phrase()` like the two-pass node.

How it differs from two-pass:
  • Energy-based phrase segmentation (RMS threshold) instead of WebRTC VAD.
  • One Whisper model (default base.en), no fast/accurate cascade.
  • Rolling re-transcription of the growing phrase buffer every
    `transcribe_every_s` seconds, so by the time the phrase closes we
    already have a near-final transcription cached — no big Whisper hit
    at phrase end.

Use this mode when:
  • You want lower commit latency (each phrase is transcribed continuously
    as it grows, so the final commit is cheap).
  • You only need one Whisper model (lighter memory footprint).
  • Energy-based segmentation works for your environment (less robust
    against noisy backgrounds than VAD).

Wake-word handling:
  • require_wake_word=False — every closed phrase becomes a turn.
  • require_wake_word=True — committed text must contain a wake phrase;
    only the remainder (after the wake) is returned. `open_followup`
    opens a brief window where the wake phrase is not required.

Optional AEC integration: pass `aec` + `far_end_buffer` to the constructor
to enable echo cancellation on captured mic frames. Without it, callers
should use `set_paused(True)` during TTS playback.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections import deque
from difflib import SequenceMatcher
from typing import Any

import numpy as np

from .._base import (
    DEFAULT_WAKE_PHRASES,
    _MicStream,
    _find_wake_in_text,
    is_non_speech_marker,
    _normalize,
    _warm_stt,
    stt_verbose,
)


def _segments_text(result) -> str:
    if isinstance(result, str):
        return result.strip()
    return " ".join(s.text.strip() for s in result if s.text.strip()).strip()


class WhisperSTTContinuous:
    """Energy-segmented continuous STT. Public API matches WhisperSTTTwoPass."""

    def __init__(
        self,
        *,
        model_name: str = "base.en",
        require_wake_word: bool = False,
        wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES,
        wake_match_threshold: float = 0.78,
        # 0.4.0 alignment with the proven
        # ``dev/tools/audio_smoke/voice_assistant_persistent.py``
        # reference (operator-validated 2026-06-06).  Prior values
        # (15s follow-up, 12s max phrase, avaudio mic) had drifted
        # heavier and degraded wake-word transcription accuracy.
        followup_window_s: float = 10.0,
        sample_rate: int = 16000,
        block_ms: int = 30,
        phrase_timeout_s: float = 1.0,
        max_phrase_s: float = 8.0,
        transcribe_every_s: float = 0.6,
        min_transcribe_s: float = 0.4,
        energy_threshold: float = 0.005,
        post_padding_ms: int = 250,
        duplicate_similarity: float = 0.92,
        mic_queue_max_frames: int = 200,
        input_device: Any = None,
        aec: Any = None,
        far_end_buffer: Any = None,
        audio_backend: str = "sounddevice",
        voice_processing: bool | None = None,
    ) -> None:
        from pywhispercpp.model import Model as STTModel

        self.require_wake_word = require_wake_word
        self.wake_phrases = wake_phrases
        self.wake_match_threshold = wake_match_threshold
        self.followup_window_s = followup_window_s
        self.sample_rate = sample_rate
        self.block_ms = block_ms
        self.phrase_timeout_s = phrase_timeout_s
        self.max_phrase_s = max_phrase_s
        self.transcribe_every_s = transcribe_every_s
        self.energy_threshold = energy_threshold
        self.duplicate_similarity = duplicate_similarity

        self._frame_samples = int(sample_rate * block_ms / 1000)
        self._max_phrase_chunks = max(1, int(max_phrase_s * 1000 / block_ms))
        self._min_transcribe_samples = int(sample_rate * min_transcribe_s)
        self._post_pad_samples = int(sample_rate * post_padding_ms / 1000)

        print(f"[stt-cont] Loading {model_name}...", flush=True)
        t0 = time.perf_counter()
        self._model = STTModel(
            model_name,
            print_realtime=False, print_progress=False,
            single_segment=True, no_context=True,
        )
        print(f"[stt-cont] Ready ({time.perf_counter() - t0:.1f}s).", flush=True)
        _warm_stt(self._model, "stt-cont", sample_rate)

        self.mic = _MicStream(
            sample_rate=sample_rate, frame_samples=self._frame_samples,
            max_queue_frames=mic_queue_max_frames, device=input_device,
            aec=aec, far_end_buffer=far_end_buffer,
            audio_backend=audio_backend,
            voice_processing=voice_processing,
        )

        self._stop = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._committed_q: queue.Queue[str] = queue.Queue()

        self._phrase_chunks: deque[np.ndarray] = deque(maxlen=self._max_phrase_chunks)
        self._last_activity = time.monotonic()
        self._current_text = ""
        self._last_committed_text = ""
        self._in_speech = False
        # Wall-clock time the current phrase opened (first energy frame
        # of a new utterance).  Snapshotted so ``_commit`` can tell
        # whether a phrase that ends AFTER the follow-up deadline began
        # INSIDE the window — if the user started speaking before the
        # deadline they shouldn't be punished by a slow tail.  Reset
        # to 0 between phrases.
        self._phrase_started_at = 0.0

        self._state = "WAKE"  # "WAKE" | "FOLLOWUP"
        self._followup_deadline = 0.0
        # Barge-in hook — fires once per phrase, the first time we detect
        # sustained voice (energy above threshold). Voice_loop wires this
        # to tts.stop() for low-latency interruption.
        self._on_speech_detected = None
        self._speech_hook_fired = False

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        self.mic.start()
        self._loop_thread = threading.Thread(target=self._main_loop, daemon=True, name="whisper-stt-cont")
        self._loop_thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.mic.stop()
        except Exception:
            pass

    def set_paused(self, paused: bool) -> None:
        self.mic.set_paused(paused)
        if paused:
            self._phrase_chunks.clear()
            self._current_text = ""
            self._last_activity = time.monotonic()
            self._in_speech = False

    def open_followup(self) -> None:
        if self.require_wake_word:
            self._state = "FOLLOWUP"
            self._followup_deadline = time.time() + self.followup_window_s

    @property
    def in_speech(self) -> bool:
        """True when an unclosed phrase is buffered. Used by the voice loop
        for barge-in detection."""
        return self._in_speech

    @property
    def in_utterance(self) -> bool:
        """RAW signal — True from the first energy frame until the
        phrase closes.  For continuous mode this is identical to
        ``in_speech`` (energy-based segmentation has no separate
        confidence stage); kept as a property so call sites can use
        the same API across two_pass and continuous."""
        return self._in_speech

    def set_on_speech_detected(self, callback) -> None:
        """Install a callback fired the moment energy-based segmentation
        sees the start of a new phrase. Voice_loop wires this to
        tts.stop() for low-latency barge-in. Pass None to clear."""
        self._on_speech_detected = callback

    def drain_pending(self) -> None:
        """Drop any committed phrases that landed in the queue while we
        weren't reading (e.g. during TTS playback). Call after TTS
        finishes so a stale buffered phrase isn't read as the next turn."""
        with self._committed_q.mutex:
            self._committed_q.queue.clear()

    # ── Wake-word matching ─────────────────────────────────────────────
    def _extract_command(self, text: str) -> str | None:
        """Return the command remainder after stripping a wake phrase
        from the START of the transcript. None if no wake match.

        Wake phrase MUST be at the FIRST 2 tokens — VOICE-3 in
        docs/ROADMAP_0.2.0.md. Previously the matcher looked anywhere
        in the utterance, so a sentence that incidentally mentioned
        "hey jaeger" (e.g. quoting documentation) wrongly triggered.
        """
        norm = _normalize(text)
        if not norm:
            return None
        tokens = norm.split()

        # Exact head-match first — sorted by length so a longer phrase
        # (if any joins later) wins over its prefix.
        for phrase in sorted(self.wake_phrases, key=len, reverse=True):
            phrase_tokens = _normalize(phrase).split()
            n = len(phrase_tokens)
            if len(tokens) < n:
                continue
            head = " ".join(tokens[:n])
            if head == " ".join(phrase_tokens):
                tail = " ".join(tokens[n:]).strip()
                return tail or text.strip()

        # Fuzzy fallback — head window only, no longer anywhere-in-text.
        for phrase in self.wake_phrases:
            phrase_tokens = _normalize(phrase).split()
            n = len(phrase_tokens)
            if len(tokens) < n:
                continue
            head = " ".join(tokens[:n])
            if SequenceMatcher(None, head, " ".join(phrase_tokens)).ratio() \
                    >= self.wake_match_threshold:
                tail = " ".join(tokens[n:]).strip()
                return tail or text.strip()
        return None

    # ── Main loop ──────────────────────────────────────────────────────
    def _main_loop(self) -> None:
        next_transcribe_at = time.monotonic() + self.transcribe_every_s
        while not self._stop.is_set():
            self._drain_audio()
            now = time.monotonic()
            if self.mic.paused:
                self._last_activity = now
                time.sleep(0.05)
                continue
            if now >= next_transcribe_at:
                self._rolling_transcribe()
                next_transcribe_at = now + self.transcribe_every_s
            if self._phrase_is_closing(now):
                self._close_phrase()
            time.sleep(0.02)

    def _drain_audio(self) -> None:
        try:
            while True:
                chunk = self.mic.q.get_nowait()
                mono = chunk[:, 0].astype(np.float32).reshape(-1)
                self._phrase_chunks.append(mono)
                rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
                if rms >= self.energy_threshold:
                    self._last_activity = time.monotonic()
                    if not self._in_speech:
                        # Phrase opening — snapshot the wall-clock time
                        # so ``_commit`` can tell whether this phrase
                        # began inside the follow-up window even if it
                        # closes after the deadline.
                        self._phrase_started_at = time.time()
                        if self._on_speech_detected is not None \
                                and not self._speech_hook_fired:
                            # First energy crossing of this phrase —
                            # fire barge-in callback before any
                            # transcription work.
                            self._speech_hook_fired = True
                            try:
                                self._on_speech_detected()
                            except Exception:
                                pass
                    self._in_speech = True
        except queue.Empty:
            return

    def _current_phrase_audio(self) -> np.ndarray | None:
        if not self._phrase_chunks:
            return None
        audio = np.concatenate(list(self._phrase_chunks)).astype(np.float32)
        if audio.size < self._min_transcribe_samples:
            return None
        padding = np.zeros(self._post_pad_samples, dtype=np.float32)
        return np.concatenate([audio, padding])

    def _transcribe(self, audio: np.ndarray) -> str:
        try:
            return _segments_text(self._model.transcribe(audio, language="en"))
        except Exception as exc:
            print(f"[stt-cont] {exc}", file=sys.stderr)
            return ""

    def _rolling_transcribe(self) -> None:
        audio = self._current_phrase_audio()
        if audio is None:
            return
        text = self._transcribe(audio)
        if not text:
            return
        if SequenceMatcher(None, text, self._current_text).ratio() \
                >= self.duplicate_similarity:
            return
        self._current_text = text

    def _phrase_is_closing(self, now: float) -> bool:
        if not self._phrase_chunks:
            return False
        phrase_seconds = len(self._phrase_chunks) * self.block_ms / 1000.0
        quiet_seconds = now - self._last_activity
        return (
            quiet_seconds >= self.phrase_timeout_s
            or phrase_seconds >= self.max_phrase_s
        )

    def _close_phrase(self) -> None:
        # Snapshot the open time before we reset the per-phrase state,
        # so ``_commit`` can decide the follow-up gate based on when
        # the phrase BEGAN, not when it ended.
        phrase_started_at = self._phrase_started_at

        audio = self._current_phrase_audio()
        text = self._transcribe(audio) if audio is not None else self._current_text
        text = (text or "").strip()
        self._phrase_chunks.clear()
        self._current_text = ""
        self._in_speech = False
        # Re-arm the barge-in hook for the next phrase.
        self._speech_hook_fired = False
        self._phrase_started_at = 0.0
        if not text:
            return
        if SequenceMatcher(None, text, self._last_committed_text).ratio() \
                >= self.duplicate_similarity:
            return
        self._last_committed_text = text
        self._commit(text, phrase_started_at=phrase_started_at)

    def _commit(self, text: str, *, phrase_started_at: float = 0.0) -> None:
        # Phrase qualifies as a follow-up if it ended in window OR if
        # it BEGAN in window.  The "began in window" branch closes the
        # commit-time race demos surfaced — without it, a phrase that
        # straddles the deadline (user spoke at t=9s with a 10 s
        # window, phrase commits at t=11 s) gets misclassified as
        # WAKE-mode and rejected even though the user was clearly
        # still in conversation.
        in_followup_window = self._state == "FOLLOWUP" and (
            time.time() <= self._followup_deadline
            or (
                phrase_started_at > 0
                and phrase_started_at <= self._followup_deadline
            )
        )

        # Drop Whisper non-speech markers ([BLANK_AUDIO], (beep), …) in
        # modes where ANY committed phrase counts as a command, so the
        # agent doesn't burn a turn replying to its own playback tail
        # or to a click.  Wake-word mode passes through unchanged — the
        # wake matcher already rejects marker text downstream.
        marker_drop = not self.require_wake_word or in_followup_window
        if marker_drop and is_non_speech_marker(text):
            if stt_verbose():
                print(f"[skipped — non-speech: {text!r}]", flush=True)
            return

        # ``require_wake_word`` off → every committed phrase is a turn.
        # The legacy ``[heard]`` line stays so existing logs / tests
        # don't change shape — but only when JAEGER_STT_VERBOSE=1, so
        # normal voice use doesn't bury the conversation pane.
        if not self.require_wake_word:
            if stt_verbose():
                print(f"[heard]  {text!r}", flush=True)
            self._committed_q.put(text)
            return
        # In the follow-up window the previous turn already gated the
        # mic; this phrase rides through without a wake word.
        if in_followup_window:
            if stt_verbose():
                print(f"[follow-up]  {text!r}", flush=True)
            self._state = "WAKE"
            self._committed_q.put(text)
            return
        command = self._extract_command(text)
        if command:
            # Wake-word matched at the head — emit ``[heard]`` for the
            # trigger so logs show which utterance opened the turn.
            if stt_verbose():
                print(f"[heard]  {text!r}", flush=True)
            self._state = "WAKE"
            self._committed_q.put(command)
            return
        # VOICE-4 (legacy): pre-wake transcripts surface to stdout so
        # an operator debugging "the mic isn't responding" sees what
        # it heard.  Verbose-gated now — the voice-activity log in
        # the TUI is the operator's normal view.
        if stt_verbose():
            print(f"[mic heard {text!r} — not sent]", flush=True)

    # ── Public phrase pump ─────────────────────────────────────────────
    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Block (up to `timeout` s) waiting for the next committed user
        phrase. Returns the transcript string, or None on timeout."""
        try:
            return self._committed_q.get(timeout=timeout)
        except queue.Empty:
            return None
