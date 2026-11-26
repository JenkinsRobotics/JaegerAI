"""Hearing for a caller that already holds the audio.

The ``stt`` slot's direct call, next to ``make_audio_session_node`` (the
bus node that owns the microphone). Whatever module fills the slot
exports ``open_hearing`` and returns an object with
``transcribe(pcm, language=, prompt=, abort=)``, ``model`` and
``compute``. Times are milliseconds, so a caller never learns
whisper.cpp's units.
"""

from __future__ import annotations

from typing import Any, Callable

from .offline import TranscriptSegment, _convert_segment

SAMPLE_RATE = 16000


class Hearing:
    """One loaded Whisper model. ``transcribe`` takes 16 kHz mono PCM."""

    def __init__(self, model: str = "base.en") -> None:
        import numpy as np
        from pywhispercpp.model import Model

        self.model = model
        self._model = Model(model, print_realtime=False, print_progress=False)
        # What the whisper.cpp build decodes on. "cuda" is read from the
        # same line but has not been run on real hardware.
        info = Model.system_info()
        self.compute = "metal" if "MTL" in info else "cuda" if "CUDA" in info else "cpu"
        try:    # the first decode pays the GPU warm-up, not the first clip
            self._model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language="en")
        except Exception:  # noqa: BLE001 — priming is best-effort
            pass

    def transcribe(
        self,
        pcm: Any,
        *,
        language: str = "en",
        prompt: str | None = None,
        abort: Callable[[], bool] | None = None,
    ) -> list[TranscriptSegment]:
        # ponytail: no lock. One decode at a time is the caller's job (the
        # agent already serialises); add one here when two callers share it.
        import numpy as np

        options: dict[str, Any] = {"language": language}
        if prompt:
            options["initial_prompt"] = prompt
        if abort is not None:
            options["abort_callback"] = abort
        audio = np.asarray(pcm, dtype=np.float32).reshape(-1)
        return [_convert_segment(s) for s in self._model.transcribe(audio, **options)]


def open_hearing(*, model: str = "base.en") -> Hearing:
    """Load ``model`` once and prime it."""
    return Hearing(model)


__all__ = ["Hearing", "open_hearing", "SAMPLE_RATE"]
