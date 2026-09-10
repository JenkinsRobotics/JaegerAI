"""Single-model streaming transcription with two-pass prefix agreement.

Reuse continuous capture, segmentation, wake gating and final delivery. Only
text shared by consecutive growing-buffer decodes becomes a stable caption.
The final decode still goes through the normal speech gate before execution.
"""
from __future__ import annotations

from typing import Callable

from ..continuous.pipeline import WhisperSTTContinuous


def agreed_prefix(previous: str, current: str) -> str:
    """Return the common word prefix, preserving the newest spelling."""
    words = []
    for old, new in zip(previous.split(), current.split()):
        if old.casefold() != new.casefold():
            break
        words.append(new)
    return " ".join(words)


class WhisperSTTLocalAgreement(WhisperSTTContinuous):
    """Continuous microphone adapter with stable partial captions."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._previous_hypothesis = ""
        self._stable_text = ""
        self._on_partial: Callable[[str], None] | None = None

    def set_on_partial(self, callback: Callable[[str], None] | None) -> None:
        self._on_partial = callback

    def _rolling_transcribe(self) -> None:
        if not self._in_speech:
            return
        audio = self._current_phrase_audio()
        if audio is None:
            return
        text = self._transcribe(audio)
        if not text:
            return
        stable = agreed_prefix(self._previous_hypothesis, text)
        self._previous_hypothesis = text
        self._current_text = text
        # Captions grow monotonically during a phrase. Corrections to already
        # confirmed words are carried by the final transcript.
        old_words = self._stable_text.casefold().split()
        new_words = stable.casefold().split()
        if len(new_words) > len(old_words) and new_words[:len(old_words)] == old_words:
            self._stable_text = stable
            if self._on_partial is not None:
                self._on_partial(stable)

    def _reset_agreement(self) -> None:
        self._previous_hypothesis = ""
        self._stable_text = ""

    def _close_phrase(self) -> None:
        try:
            super()._close_phrase()
        finally:
            self._reset_agreement()

    def set_paused(self, paused: bool) -> None:
        super().set_paused(paused)
        if paused:
            self._reset_agreement()
