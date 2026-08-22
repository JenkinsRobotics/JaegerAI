"""WhisperSTTTwoPass — VAD-segmented two-pass STT.

Algorithm ported from VoiceLLM/MockingAgent's two_pass.py, adapted for our
agent flow (no bus; expose blocking `next_phrase()` instead).

How it works:
  1. VAD worker thread reads mic frames and accumulates speech.
  2. On phrase close (silence hangover OR max length), fast Whisper model
     transcribes the buffer (~50 ms typical latency).
  3. If wake-word gating is on, the fast text is matched against the wake
     phrases. Only matched phrases proceed.
  4. The accurate Whisper model re-transcribes the audio for a clean commit.
  5. Result lands in a queue that voice_loop drains via next_phrase().

Use this mode when:
  • Phrases have clear silence boundaries
  • You want the wake-word match to fire fast (fast model gates the
    accurate model so the heavy pass only runs when the fast model says
    "this might be for us")
"""

from __future__ import annotations

import collections
import queue
import sys
import threading
import time
from typing import Any

import numpy as np

from .._base import (
    DEFAULT_WAKE_PHRASES,
    _MicStream,
    _find_wake_in_text,
    is_non_speech_marker,
    _warm_stt,
    stt_verbose,
)


class _VadWorker(threading.Thread):
    """Reads MicStream frames, runs WebRTC VAD, finalizes phrases through
    the fast STT model."""

    def __init__(
        self,
        mic: _MicStream,
        fast_model,
        phrase_q: "queue.Queue[tuple[np.ndarray, str, float]]",
        stop_event: threading.Event,
        *,
        sample_rate: int,
        frame_ms: int,
        vad_aggressiveness: int,
        pre_roll_ms: int,
        post_padding_ms: int,
        silence_hangover_ms: int,
        min_speech_ms: int,
        max_speech_ms: int,
        barge_in_ms: int = 200,
        short_phrase_max_ms: int = 1500,
        short_phrase_hangover_ms: int = 350,
    ) -> None:
        import webrtcvad

        super().__init__(daemon=True, name="whisper-stt-vad")
        self.mic = mic
        self.fast_model = fast_model
        self.phrase_q = phrase_q
        self.stop_event = stop_event
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.vad = webrtcvad.Vad(vad_aggressiveness)
        self.silence_blocks_to_end = max(1, silence_hangover_ms // frame_ms)
        # Short-phrase early commit (VoiceLLM operator-feedback port):
        # quick utterances ("yes please", "good night") don't carry
        # mid-sentence pauses, so they commit after a much shorter
        # hangover instead of waiting out the full one — ~40% snappier
        # on exactly the turns where latency is most noticeable.
        # ``short_phrase_max_ms=0`` disables the path.
        self.short_phrase_max_blocks = max(0, short_phrase_max_ms // frame_ms)
        self.short_hangover_blocks = max(
            1, short_phrase_hangover_ms // frame_ms,
        )
        self.min_speech_blocks = max(1, min_speech_ms // frame_ms)
        self.max_speech_blocks = max(self.min_speech_blocks, max_speech_ms // frame_ms)
        self.pre_roll_blocks = max(0, pre_roll_ms // frame_ms)
        self.post_pad_samples = int(sample_rate * post_padding_ms / 1000)
        # Barge-in: fire on_speech_detected() once `barge_in_blocks` of
        # sustained speech is seen. Lower than min_speech_blocks so the
        # callback fires earlier than a full phrase commit.
        self.barge_in_blocks = max(1, barge_in_ms // frame_ms)
        # Caller (the parent STT node) installs this so it can be called
        # straight from the VAD thread without going through the main loop.
        self.on_speech_detected = None
        self._barge_fired = False
        # Exposed so the parent node can check whether speech is in progress
        # before expiring the follow-up window.  Two signals:
        #   in_utterance — RAW VAD signal: True from the first speech
        #                  frame until SILENCE_HANGOVER_MS of silence.
        #                  Used by ``next_phrase`` to refuse to expire
        #                  the follow-up window while ANY speech is
        #                  in progress, even speech that hasn't yet
        #                  crossed MIN_SPEECH_MS.  Catches utterances
        #                  starting right at the deadline.
        #   in_speech    — Confidence-gated: only True once we have
        #                  ``min_speech_blocks`` of voice.  Kept for
        #                  the barge-in path (sub-50 ms latency).
        self.in_utterance = False
        self.in_speech = False

    def _is_speech(self, chunk: np.ndarray) -> bool:
        pcm = (chunk[:, 0] * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
        return self.vad.is_speech(pcm, self.sample_rate)

    def _finalize(self, chunks: list[np.ndarray]) -> None:
        # The moment the hangover closed the phrase — the honest
        # "user stopped talking" timestamp every downstream latency
        # number hangs off (VoiceLLM metrics port).
        t_speech_end = time.perf_counter()
        audio = np.concatenate(chunks, axis=0).astype(np.float32).reshape(-1)
        audio = np.concatenate([audio, np.zeros(self.post_pad_samples, dtype=np.float32)])
        try:
            segments = self.fast_model.transcribe(audio, language="en")
            text = " ".join(s.text for s in segments).strip()
        except Exception as exc:
            print(f"[stt-fast] {exc}", file=sys.stderr)
            text = ""
        if text:
            self.phrase_q.put((audio, text, t_speech_end))

    def run(self) -> None:
        pre_roll: collections.deque[np.ndarray] = collections.deque(maxlen=self.pre_roll_blocks)
        speech: list[np.ndarray] = []
        speech_blocks = 0
        silent_blocks = 0
        in_speech = False

        while not self.stop_event.is_set():
            try:
                chunk = self.mic.q.get(timeout=0.3)
            except queue.Empty:
                continue
            is_speech = self._is_speech(chunk)
            if is_speech:
                if not in_speech:
                    speech = list(pre_roll)
                    speech_blocks = len(speech)
                    silent_blocks = 0
                    in_speech = True
                speech.append(chunk)
                speech_blocks += 1
                silent_blocks = 0
            elif in_speech:
                speech.append(chunk)
                silent_blocks += 1
            else:
                pre_roll.append(chunk)

            # Publish both signals — see __init__ for the contract.
            self.in_utterance = in_speech and silent_blocks < self.silence_blocks_to_end
            self.in_speech = self.in_utterance and speech_blocks >= self.min_speech_blocks

            # Low-latency barge-in hook — fires once per phrase as soon
            # as we've seen `barge_in_blocks` of sustained voice. Lower
            # than min_speech_blocks so the callback fires well before
            # the phrase is committed for transcription.
            if (
                in_speech
                and speech_blocks >= self.barge_in_blocks
                and not self._barge_fired
                and self.on_speech_detected is not None
            ):
                self._barge_fired = True
                try:
                    self.on_speech_detected()
                except Exception:
                    pass

            # Short utterances commit on the shorter hangover — they
            # don't carry mid-sentence pauses, so waiting out the full
            # window is pure dead air. ``speech_blocks`` counts voiced
            # frames only (trailing silence increments ``silent_blocks``
            # instead), so it IS the utterance length.
            hangover_blocks = (
                self.short_hangover_blocks
                if (
                    self.short_phrase_max_blocks
                    and speech_blocks <= self.short_phrase_max_blocks
                )
                else self.silence_blocks_to_end
            )
            phrase_done = (
                in_speech
                and speech_blocks >= self.min_speech_blocks
                and (
                    silent_blocks >= hangover_blocks
                    or speech_blocks >= self.max_speech_blocks
                )
            )
            if phrase_done:
                self._finalize(speech)
                speech = []
                speech_blocks = 0
                silent_blocks = 0
                in_speech = False
                self.in_speech = False
                self.in_utterance = False
                self._barge_fired = False
                pre_roll.clear()


class WhisperSTTTwoPass:
    """Two-pass STT — fast model gates, accurate model commits.

    `next_phrase(timeout)` returns the next committed user utterance (str)
    or None if no phrase arrived before the timeout. Voice_loop calls this
    in its main loop.
    """

    def __init__(
        self,
        *,
        fast_model_name: str = "base.en",
        accurate_model_name: str = "medium.en",
        require_wake_word: bool = False,
        wake_phrases: tuple[str, ...] = DEFAULT_WAKE_PHRASES,
        wake_match_threshold: float = 0.78,
        # 0.4.0 alignment: defaults match the proven reference
        # ``dev/tools/audio_smoke/voice_assistant_persistent.py``
        # the operator validated 2026-06-06.  Prior JROS values
        # (1000ms hangover, 12s max phrase, 15s follow-up, avaudio
        # mic) had drifted longer/heavier and degraded wake-word
        # transcription accuracy in practice.
        followup_window_s: float = 10.0,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        vad_aggressiveness: int = 2,
        pre_roll_ms: int = 240,
        post_padding_ms: int = 250,
        silence_hangover_ms: int = 700,
        min_speech_ms: int = 400,
        max_speech_ms: int = 8000,
        barge_in_ms: int = 200,
        # Short-phrase early commit (VoiceLLM operator-feedback port):
        # utterances shorter than ``short_phrase_max_ms`` commit after
        # only ``short_phrase_hangover_ms`` of silence — quick replies
        # ("yes please", "good night") land ~40% faster. Set
        # ``short_phrase_max_ms=0`` to disable.
        short_phrase_max_ms: int = 1500,
        short_phrase_hangover_ms: int = 350,
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
        frame_samples = sample_rate * frame_ms // 1000

        print(f"[stt-fast] Loading {fast_model_name}...", flush=True)
        t0 = time.perf_counter()
        self._fast = STTModel(
            fast_model_name,
            print_realtime=False, print_progress=False,
            single_segment=True, no_context=True,
        )
        print(f"[stt-fast] Ready ({time.perf_counter() - t0:.1f}s).", flush=True)
        _warm_stt(self._fast, "stt-fast", sample_rate)

        print(f"[stt-accurate] Loading {accurate_model_name}...", flush=True)
        t0 = time.perf_counter()
        self._accurate = STTModel(
            accurate_model_name,
            print_realtime=False, print_progress=False,
            single_segment=True, no_context=True,
        )
        print(f"[stt-accurate] Ready ({time.perf_counter() - t0:.1f}s).", flush=True)
        _warm_stt(self._accurate, "stt-accurate", sample_rate)

        self.mic = _MicStream(
            sample_rate=sample_rate, frame_samples=frame_samples,
            max_queue_frames=mic_queue_max_frames, device=input_device,
            aec=aec, far_end_buffer=far_end_buffer,
            audio_backend=audio_backend,
            voice_processing=voice_processing,
        )
        self._phrase_q: queue.Queue[tuple[np.ndarray, str, float]] = queue.Queue()
        self._stop = threading.Event()
        self._worker = _VadWorker(
            self.mic, self._fast, self._phrase_q, self._stop,
            sample_rate=sample_rate, frame_ms=frame_ms,
            vad_aggressiveness=vad_aggressiveness,
            pre_roll_ms=pre_roll_ms, post_padding_ms=post_padding_ms,
            silence_hangover_ms=silence_hangover_ms,
            min_speech_ms=min_speech_ms, max_speech_ms=max_speech_ms,
            barge_in_ms=barge_in_ms,
            short_phrase_max_ms=short_phrase_max_ms,
            short_phrase_hangover_ms=short_phrase_hangover_ms,
        )

        self._state = "WAKE"
        self._followup_deadline = 0.0
        # Speech-side timing of the most recent committed phrase
        # (VoiceLLM metrics port). Read by the audio session right
        # after ``next_phrase`` returns — same thread, no race.
        #   speech_end — perf_counter when the hangover closed the phrase
        #   stt_done   — perf_counter when the accurate pass finished
        self.last_phrase_timing: dict[str, float] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        self.mic.start()
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.mic.stop()
        except Exception:
            pass

    def set_paused(self, paused: bool) -> None:
        """Pause mic capture during TTS playback (when not using AEC)."""
        self.mic.set_paused(paused)

    def open_followup(self) -> None:
        """Open a follow-up window so the user can speak again without
        re-saying the wake word. No-op if wake-word gating is off."""
        if self.require_wake_word:
            self._state = "FOLLOWUP"
            self._followup_deadline = time.time() + self.followup_window_s

    @property
    def in_speech(self) -> bool:
        """True when VAD says the user is actively speaking (sustained
        past MIN_SPEECH_MS).  Used by the voice loop for barge-in
        detection."""
        return self._worker.in_speech

    @property
    def in_utterance(self) -> bool:
        """RAW VAD signal — True from the first speech frame until
        SILENCE_HANGOVER_MS of silence.  Used by ``next_phrase`` to
        refuse to expire the follow-up window mid-utterance, even for
        speech that hasn't yet crossed the MIN_SPEECH_MS confidence
        threshold (catches utterances starting right at the deadline).
        """
        return self._worker.in_utterance

    def set_on_speech_detected(self, callback) -> None:
        """Install a callback fired by the VAD thread the moment sustained
        voice is detected (after barge_in_ms of speech, well before the
        phrase is committed). Voice_loop wires this to tts.stop() for
        sub-50 ms barge-in latency. Pass None to clear."""
        self._worker.on_speech_detected = callback

    def drain_pending(self) -> None:
        """Drop any phrases the VAD finalized while we weren't reading
        (e.g. during TTS playback). Call after TTS finishes — otherwise
        a stale buffered phrase becomes the next 'user input'."""
        with self._phrase_q.mutex:
            self._phrase_q.queue.clear()

    # ── Wake-word matching ─────────────────────────────────────────────
    def _find_wake(self, text: str) -> tuple[bool, str]:
        return _find_wake_in_text(text, self.wake_phrases, self.wake_match_threshold)

    def _accurate_transcribe(self, audio: np.ndarray) -> str:
        segments = self._accurate.transcribe(audio, language="en")
        return " ".join(s.text for s in segments).strip()

    # ── Phrase pump ────────────────────────────────────────────────────
    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Block (up to `timeout` s) waiting for the next committed user
        phrase. Returns the transcript string, or None on timeout."""
        while not self._stop.is_set():
            try:
                audio, fast_text, t_speech_end = self._phrase_q.get(
                    timeout=timeout,
                )
            except queue.Empty:
                # No phrase pending — ONLY now is it safe to expire the
                # follow-up window.  Doing it before ``get`` lost a race
                # where ``_VadWorker`` finalized a phrase that straddled
                # the deadline and we'd then misclassify it as WAKE-mode
                # below.  Triple-guard so we also wait out any in-progress
                # utterance (raw VAD signal) AND any final phrase that
                # hasn't been popped off the queue yet.
                if (
                    self._state == "FOLLOWUP"
                    and time.time() > self._followup_deadline
                    and not self._worker.in_utterance
                    and self._phrase_q.empty()
                ):
                    self._state = "WAKE"
                return None

            command: str | None = None

            # Whisper non-speech markers ([BLANK_AUDIO], (beep), (music), …)
            # get dropped in modes where ANY transcribed phrase counts as
            # a command — otherwise the agent burns a turn replying to its
            # own playback tail or to a click.  Wake-required mode passes
            # through unchanged because the wake matcher already rejects
            # marker text.
            if not self.require_wake_word or self._state == "FOLLOWUP":
                if is_non_speech_marker(fast_text):
                    if stt_verbose():
                        print(f"[skipped — non-speech: {fast_text!r}]",
                              flush=True)
                    continue

            if not self.require_wake_word:
                if stt_verbose():
                    print(f"[heard]  {fast_text!r}", flush=True)
                command = self._accurate_transcribe(audio).strip() or fast_text
                # Re-check after accurate pass — markers can survive the
                # fast pass and surface only on the accurate model.
                if is_non_speech_marker(command):
                    if stt_verbose():
                        print(f"[skipped — non-speech: {command!r}]",
                              flush=True)
                    continue
            elif self._state == "FOLLOWUP":
                if stt_verbose():
                    print(f"[heard]  {fast_text!r}", flush=True)
                command = self._accurate_transcribe(audio).strip() or fast_text
                if is_non_speech_marker(command):
                    if stt_verbose():
                        print(f"[follow-up skipped — non-speech: "
                              f"{command!r}]", flush=True)
                    continue
                if stt_verbose():
                    print(f"[follow-up] {command!r}", flush=True)
            else:
                matched, remainder = self._find_wake(fast_text)
                if not matched:
                    # VOICE-4 (legacy): pre-wake transcripts surface
                    # so the user sees what the mic heard AND knows it
                    # wasn't sent.  Verbose-gated now — the TUI's
                    # voice-activity log is the normal operator view.
                    if stt_verbose():
                        print(f"[mic heard {fast_text!r} — not sent]",
                              flush=True)
                    continue
                # Wake matched — the trigger utterance lands in the log.
                if stt_verbose():
                    print(f"[heard]  {fast_text!r}", flush=True)
                accurate_text = self._accurate_transcribe(audio)
                a_matched, a_remainder = self._find_wake(accurate_text)
                if a_matched and (a_remainder or not remainder):
                    remainder = a_remainder
                    if stt_verbose():
                        print(f"[heard*] {accurate_text!r}", flush=True)
                if remainder:
                    command = remainder
                else:
                    # Wake-only utterance — wait briefly for the actual command.
                    with self._phrase_q.mutex:
                        self._phrase_q.queue.clear()
                    try:
                        cmd_audio, cmd_fast, t_speech_end = self._phrase_q.get(
                            timeout=6.0,
                        )
                    except queue.Empty:
                        if stt_verbose():
                            print("[no command — back to wake]", flush=True)
                        continue
                    if stt_verbose():
                        print(f"[heard]  {cmd_fast!r}", flush=True)
                    command = self._accurate_transcribe(cmd_audio).strip() or cmd_fast

            if not command:
                continue

            self._state = "WAKE"
            # Speech-side timing for this phrase — speech end stamped
            # by the VAD worker at hangover close, STT done stamped
            # here after the accurate pass. The audio session threads
            # these into the Transcript message.
            self.last_phrase_timing = {
                "speech_end": t_speech_end,
                "stt_done": time.perf_counter(),
            }
            return command
        return None
