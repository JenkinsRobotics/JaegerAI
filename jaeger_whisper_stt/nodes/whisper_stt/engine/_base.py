"""Shared helpers used by both two_pass.py and continuous.py.

Plugin-internal — not exported through __init__.py. Both STT modes need:
  • _MicStream            — sounddevice InputStream + pauseable queue
  • _warm_stt             — silence-pass priming so first phrase isn't slow
  • _normalize            — lowercase + strip punctuation for wake-word match
  • _find_wake_in_text    — substring + fuzzy wake-phrase matcher
  • DEFAULT_WAKE_PHRASES  — canonical wake-phrase list (handles Whisper
                            mishearings: yeager/yager/jager/jaeger)

`_VadWorker` is two-pass specific (energy-segmentation in continuous mode
replaces it), so it stays in two_pass.py.

AEC integration is OPTIONAL: if a caller passes an `aec` instance and a
`far_end_buffer` to `_MicStream`, near-end audio is filtered before being
queued. If no AEC is wired, mic frames pass through unchanged.
"""

from __future__ import annotations

import queue
import re
import sys
import time
from difflib import SequenceMatcher
from typing import Any

import numpy as np

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


def stt_verbose() -> bool:
    """Per-phrase STT debug prints (``[heard] ...``, ``[skipped ...]``,
    ``[follow-up] ...``) go to stdout when ``JAEGER_STT_VERBOSE=1``.

    Operator-flipped 2026-06-07 after live testing showed the debug
    output dominated the conversation pane during normal voice use.
    The boot-time setup prints (``[stt-cont] Loading...`` etc.)
    still fire regardless — they're once-per-session, not noise.

    Set the env var in the operator's shell or instance config when
    troubleshooting voice; otherwise the voice-activity log in the
    TUI (controlled by ``/quiet``) is the operator's view of the
    pipeline."""
    import os as _os
    return _os.environ.get("JAEGER_STT_VERBOSE") == "1"


def _warm_stt(model, label: str, sample_rate: int) -> None:
    """Run a 1.5-second silence transcription so the first real phrase doesn't
    pay model setup cost. Whisper rejects audio under 1000 ms (skips
    inference + warns), so 1.5 s is the safe minimum for warming."""
    warm_audio = np.zeros(int(sample_rate * 1.5), dtype=np.float32)
    print(f"[{label}] warming up...", flush=True)
    t0 = time.perf_counter()
    try:
        list(model.transcribe(warm_audio, language="en"))
    except Exception as exc:
        print(f"[{label}] warm-up skipped: {exc}", file=sys.stderr, flush=True)
    else:
        print(f"[{label}] primed ({time.perf_counter() - t0:.1f}s).", flush=True)


class _MicStream:
    """sounddevice InputStream + queue + pause flag.

    Optional AEC hook: if `aec` (object with `process(near, far)` method) and
    `far_end_buffer` (object with `pop_frame()` method) are passed in, each
    captured frame is filtered against the far-end reference before being
    queued. This is what makes barge-in possible — the mic stays open during
    TTS playback but the AI's own voice gets canceled out.

    If aec is None, frames pass through unchanged. Callers that don't want
    barge-in can use `set_paused(True)` during TTS instead.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        frame_samples: int,
        max_queue_frames: int = 200,
        device: Any = None,
        aec: Any = None,
        far_end_buffer: Any = None,
        audio_backend: str = "avaudio",
        voice_processing: bool | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queue_frames)
        self.paused = False
        self.aec = aec
        self.far_end_buffer = far_end_buffer
        self.audio_backend = audio_backend

        # 0.3.0: prefer AVAudioEngine via the avaudio_io bridge — kills
        # the PortAudio wedging bug class on macOS.  Falls back to
        # sounddevice transparently when the bridge can't load (non-
        # macOS, missing pyobjc-framework-AVFoundation, etc.) or when
        # the operator explicitly asks for the portaudio path via
        # ``--audio-backend portaudio``.
        if audio_backend == "avaudio":
            # Resolve the voice_processing default:
            #   • Operator-supplied value wins, always (None → auto).
            #   • Speexdsp AEC wired → voice_processing OFF so the
            #     operator's pipeline sees raw samples.  Stacking two
            #     AECs would double-cancel + add latency.
            #   • Otherwise → voice_processing ON.  Apple's pre-canned
            #     pipeline (AEC + NS + AGC) is what FaceTime uses, runs
            #     for free on macOS, and was validated in
            #     dev/tools/audio_smoke/voice_assistant_avaudio.py
            #     as the fix for agent-
            #     hears-itself when the mic stays open during TTS.
            #     Mic-pause mode also benefits (NS + AGC improve
            #     Whisper accuracy in noisy rooms).
            if voice_processing is None:
                voice_processing = aec is None
            try:
                from jaeger_os.core.audio.avaudio_io import InputStream as _AVInputStream
                self._stream = _AVInputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=frame_samples,
                    callback=self._cb,
                    voice_processing=voice_processing,
                )
                if voice_processing:
                    print("[mic] avaudio voice_processing=on "
                          "(Apple-native AEC + NS + AGC)",
                          flush=True)
                return
            except Exception as exc:  # noqa: BLE001
                print(f"[mic] avaudio backend unavailable ({exc}); "
                      "falling back to sounddevice", file=sys.stderr, flush=True)

        import sounddevice as sd  # deferred — plugin owns the import
        self._stream = sd.InputStream(
            device=device,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=frame_samples,
            callback=self._cb,
        )

    def _apply_aec(self, near: np.ndarray) -> np.ndarray:
        """Run AEC on a captured frame if AEC + far-end buffer are wired."""
        if self.aec is None or self.far_end_buffer is None:
            return near
        far = self.far_end_buffer.pop_frame(len(near))
        try:
            return self.aec.process(near, far)
        except Exception as exc:
            print(f"[mic] AEC passthrough on error: {exc}", file=sys.stderr, flush=True)
            return near

    def _cb(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[mic] {status}", file=sys.stderr)
        if self.paused or frames != self.frame_samples:
            return
        sample = indata.copy()
        if self.aec is not None:
            # AEC is per-channel mono; reshape to 1D, process, reshape back.
            mono = sample[:, 0]
            clean = self._apply_aec(mono)
            sample = clean.reshape(-1, 1)
        try:
            self.q.put_nowait(sample)
        except queue.Full:
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(sample)
            except queue.Full:
                pass

    def start(self) -> None:
        self._stream.start()

    def stop(self) -> None:
        try:
            self._stream.stop()
        finally:
            self._stream.close()

    def drain(self) -> None:
        with self.q.mutex:
            self.q.queue.clear()

    def set_paused(self, paused: bool) -> None:
        if paused == self.paused:
            return
        self.paused = paused
        if not paused:
            # Anything captured during the pause boundary is stale.
            self.drain()
