"""Listeners that are not a live microphone.

Both satisfy :class:`jaeger_os.core.audio.STTAdapter` — the same protocol the
stt slot's microphone engines implement — so :class:`VoiceSession` cannot
tell them apart. That is the point: an unattended acceptance run exercises
the real session, Gateway and Entity path, with only the capture swapped.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
import time
from typing import Callable, Iterable


class WavFileListener:
    """Transcribe prepared 16 kHz mono WAV files with the stt slot's model.

    ``last_timing`` records when each phrase's audio ended (the moment it
    was handed over) and when its transcript was ready, so speech-end →
    transcript latency is measured on the real Whisper model.
    """

    def __init__(self, paths: Iterable[str | Path], *, model_name: str = "base.en") -> None:
        from pywhispercpp.model import Model

        self._queue = deque(Path(p) for p in paths)
        self._model = Model(model_name, print_realtime=False, print_progress=False,
                            single_segment=True, no_context=True)
        self.last_timing: dict[str, float] = {}
        self._on_speech: Callable[[], None] | None = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self._queue.clear()

    def set_paused(self, paused: bool) -> None:
        pass

    def set_on_speech_detected(self, callback: Callable[[], None] | None) -> None:
        self._on_speech = callback

    def open_followup(self) -> None:
        pass

    def drain_pending(self) -> None:
        pass

    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        if not self._queue:
            return None
        path = self._queue.popleft()
        if self._on_speech is not None:
            self._on_speech()
        audio = _read_wav_16k_mono(path)
        speech_end = time.time()
        segments = self._model.transcribe(audio, language="en")
        text = " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
        self.last_timing = {"speech_end": speech_end, "transcript_ready": time.time()}
        return text

    @property
    def exhausted(self) -> bool:
        return not self._queue


class TypedListener:
    """Text in place of speech — the fallback when there is no STT or mic."""

    def __init__(self, lines: Iterable[str] | None = None, *, prompt: str = "you> ") -> None:
        self._lines = deque(lines) if lines is not None else None
        self._prompt = prompt
        self.last_timing: dict[str, float] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        if self._lines is not None:
            self._lines.clear()

    def set_paused(self, paused: bool) -> None:
        pass

    def set_on_speech_detected(self, callback: Callable[[], None] | None) -> None:
        pass

    def open_followup(self) -> None:
        pass

    def drain_pending(self) -> None:
        pass

    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        if self._lines is not None:
            text = self._lines.popleft() if self._lines else None
        else:
            try:
                text = input(self._prompt)
            except EOFError:
                text = None
        now = time.time()
        self.last_timing = {"speech_end": now, "transcript_ready": now}
        return text

    @property
    def exhausted(self) -> bool:
        return self._lines is not None and not self._lines


def _read_wav_16k_mono(path: Path):
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getframerate() != 16000 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: need 16 kHz mono 16-bit PCM WAV")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
