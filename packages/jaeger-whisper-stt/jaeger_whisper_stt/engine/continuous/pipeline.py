"""WhisperSTTContinuous — energy-segmented, rolling re-transcription.

Algorithm ported from VoiceLLM's continuous.py (which in turn came from
MockingAgent's hybrid phrase/word pipeline). Adapted for JaegerOS bus audio
and exposes blocking `next_phrase()` like the two-pass adapter.

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

AEC is NOT here any more — jaeger_os.nodes.audio_io owns it, because the
canceller needs the mic frame and the playing audio together per frame.
This pipeline receives already-cleaned audio.

`set_paused(True)` still exists and still suppresses this pipeline's
input during playback — but it is now LOCAL. It drops arriving frames
rather than stopping the device, because a shared microphone cannot let
one consumer starve the others.
"""

from __future__ import annotations

import queue
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
    is_non_speech_marker,
    offer_latest,
    segments_text,
    _warm_stt,
)


class WhisperSTTContinuous(WakeMissNotifier):
    """Energy-segmented continuous STT. Public API matches WhisperSTTTwoPass."""

    label = "stt-cont"
    health_mode = "continuous"

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
        language: str = "en",
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
        output_queue_max_phrases: int = 16,
        bus: Any = None,
    ) -> None:
        from pywhispercpp.model import Model as STTModel

        if sample_rate <= 0 or block_ms <= 0:
            raise ValueError("sample_rate and block_ms must be positive")
        if phrase_timeout_s <= 0 or max_phrase_s <= 0:
            raise ValueError("phrase_timeout_s and max_phrase_s must be positive")
        if transcribe_every_s <= 0 or min_transcribe_s <= 0:
            raise ValueError("transcription intervals must be positive")
        if energy_threshold < 0:
            raise ValueError("energy_threshold cannot be negative")
        if output_queue_max_phrases <= 0:
            raise ValueError("output_queue_max_phrases must be positive")

        self.require_wake_word = require_wake_word
        self.wake_phrases = wake_phrases
        self.wake_match_threshold = wake_match_threshold
        self.followup_window_s = followup_window_s
        self.language = language.strip() or "en"
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
        self._command_deadline = 0.0
        # Barge-in hook — fires once per phrase, the first time we detect
        # sustained voice (energy above threshold). Voice_loop wires this
        # to tts.stop() for low-latency interruption.
        self._on_speech_detected = None
        self._speech_hook_fired = False
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
            target=self._run_guarded, daemon=True, name=self.label,
        )
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
        except Exception:
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
            self._phrase_chunks.clear()
            self._current_text = ""
            self._last_activity = time.monotonic()
            self._in_speech = False

    def open_followup(self) -> None:
        if self.require_wake_word:
            self._state = "FOLLOWUP"
            self._followup_deadline = time.monotonic() + self.followup_window_s

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
    def _find_wake(self, text: str) -> tuple[bool, str]:
        """Return a leading wake match and its command remainder.

        A separate boolean preserves wake-only utterances: ``("matched", "")``
        arms the next phrase as a command instead of publishing the wake words.
        """
        return _find_wake_in_text(
            text, self.wake_phrases, self.wake_match_threshold,
        )

    # ── Main loop ──────────────────────────────────────────────────────
    def _run_guarded(self) -> None:
        """Keep an unexpected worker failure observable in node health."""
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
                self._last_activity = now
                self._stop.wait(0.05)
                continue
            if now >= next_transcribe_at:
                self._rolling_transcribe()
                next_transcribe_at = now + self.transcribe_every_s
            if self._phrase_is_closing(now):
                self._close_phrase()
            self._stop.wait(0.02)

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
                        self._phrase_started_at = time.monotonic()
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
            return segments_text(self._model.transcribe(
                audio, language=self.language,
            ))
        except Exception as exc:
            self._decode_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            log(self.label, self._last_error, level="error")
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
            time.monotonic() <= self._followup_deadline
            or (
                phrase_started_at > 0
                and phrase_started_at <= self._followup_deadline
            )
        )
        in_command_window = (
            self._state == "COMMAND"
            and time.monotonic() <= self._command_deadline
        )

        # Drop Whisper non-speech markers ([BLANK_AUDIO], (beep), …) in
        # modes where ANY committed phrase counts as a command, so the
        # agent doesn't burn a turn replying to its own playback tail
        # or to a click.  Wake-word mode passes through unchanged — the
        # wake matcher already rejects marker text downstream.
        marker_drop = (
            not self.require_wake_word
            or in_followup_window
            or in_command_window
        )
        if marker_drop and is_non_speech_marker(text):
            log("stt", f"skipped — non-speech: {text!r}", level="debug")
            return

        # ``require_wake_word`` off → every committed phrase is a turn.
        # The legacy ``[heard]`` line stays so existing logs / tests
        # don't change shape — but only under ``JAEGER_DEBUG=stt``, so
        # normal voice use doesn't bury the conversation pane.
        if not self.require_wake_word:
            log("stt", f"heard {text!r}", level="debug")
            if offer_latest(self._committed_q, text):
                self._output_drops += 1
            return
        # In the follow-up window the previous turn already gated the
        # mic; this phrase rides through without a wake word.
        if in_followup_window:
            log("stt", f"follow-up {text!r}", level="debug")
            self._state = "WAKE"
            if offer_latest(self._committed_q, text):
                self._output_drops += 1
            return
        if in_command_window:
            log("stt", f"command {text!r}", level="debug")
            self._state = "WAKE"
            if offer_latest(self._committed_q, text):
                self._output_drops += 1
            return
        matched, command = self._find_wake(text)
        if matched and command:
            # Wake-word matched at the head — emit ``[heard]`` for the
            # trigger so logs show which utterance opened the turn.
            log("stt", f"heard {text!r}", level="debug")
            self._state = "WAKE"
            if offer_latest(self._committed_q, command):
                self._output_drops += 1
            return
        if matched:
            # Wake-only utterance. Waiting here would block the node tick and
            # its health heartbeat, so arm state for the next finalized phrase.
            self.drain_pending()
            self._state = "COMMAND"
            self._command_deadline = time.monotonic() + 6.0
            return
        # VOICE-4 (legacy): pre-wake transcripts surface to stdout so
        # an operator debugging "the mic isn't responding" sees what
        # it heard.  Verbose-gated now — the voice-activity log in
        # the TUI is the operator's normal view.
        self._notify_wake_miss(text)

    # ── Public phrase pump ─────────────────────────────────────────────
    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Block (up to `timeout` s) waiting for the next committed user
        phrase. Returns the transcript string, or None on timeout."""
        try:
            return self._committed_q.get(timeout=timeout)
        except queue.Empty:
            if (self._state == "FOLLOWUP"
                    and time.monotonic() > self._followup_deadline
                    and not self._in_speech):
                self._state = "WAKE"
            if (self._state == "COMMAND"
                    and time.monotonic() > self._command_deadline):
                self._state = "WAKE"
            return None

    def health(self) -> dict[str, Any]:
        thread = self._loop_thread
        return {
            "mode": self.health_mode,
            "started": self._started,
            "running": bool(thread and thread.is_alive()),
            "state": self._state,
            "in_speech": self._in_speech,
            "pending_phrases": self._committed_q.qsize(),
            "output_queue_capacity": self._committed_q.maxsize,
            "output_drops": self._output_drops,
            "decode_failures": self._decode_failures,
            "last_error": self._last_error,
            "mic": self.mic.health(),
        }
