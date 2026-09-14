"""WhisperSTTPhraseWord — ``continuous`` phrase segmentation, plus live
partials from the rolling re-transcription it was already doing.

Precursor: MockingAgent
``llm_listener/always_listening_hybrid_phrase_word_pipeline.py``.

``continuous`` mode already re-transcribes the growing phrase buffer
every ``transcribe_every_s`` — it just threw the intermediate text away
and only published when the phrase closed.  This mode publishes that
intermediate text as a partial.  Same compute, same finals, free live
captions.

How it compares to ``local_agreement``:

  • Partials here are scoped to the CURRENT PHRASE and reset when it
    closes, so the caption pane clears between utterances.  Finals land
    on real speech boundaries (RMS silence), which is what turn-taking
    with an agent wants.
  • ``local_agreement`` never segments, so its captions run continuously
    and its finals are word-committed, not phrase-committed.  Better for
    a always-on transcript of a room; worse for turn-taking.

Pick this one for an assistant that should also show what it is hearing.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from ..continuous.pipeline import WhisperSTTContinuous


class WhisperSTTPhraseWord(WhisperSTTContinuous):
    """Energy-segmented phrases (final) + rolling partials (live)."""

    label = "stt-phrase-word"
    health_mode = "phrase_word"

    def __init__(self, **kwargs) -> None:
        # ponytail: subclass, not a fork. The only behavioural delta is
        # "also emit the text you already computed", so a 3-method
        # override beats a 420-line copy that then drifts.
        super().__init__(**kwargs)
        self._on_partial = None
        self._last_partial = ""

    def set_on_partial(self, callback) -> None:
        """Install a callback receiving live, not-yet-final text for the
        phrase currently being spoken.  Fires on the pipeline thread —
        must not block.  Pass None to clear."""
        self._on_partial = callback

    def _rolling_transcribe(self) -> None:
        before = self._current_text
        super()._rolling_transcribe()
        if self._current_text and self._current_text != before:
            self._emit_partial(self._current_text)

    def _close_phrase(self) -> None:
        super()._close_phrase()
        # The phrase is committed; the caption pane should stop showing
        # its in-progress text. An empty partial is the clear signal.
        if self._last_partial:
            self._emit_partial("")

    def _emit_partial(self, text: str) -> None:
        if self._on_partial is None:
            return
        if text and SequenceMatcher(None, text, self._last_partial).ratio() \
                >= self.duplicate_similarity:
            return
        self._last_partial = text
        try:
            self._on_partial(text)
        except Exception:  # noqa: BLE001
            # A partial is a display convenience — a broken consumer
            # must not wedge the decode loop.
            pass

    def set_paused(self, paused: bool) -> None:
        super().set_paused(paused)
        if paused and self._last_partial:
            self._emit_partial("")


__all__ = ["WhisperSTTPhraseWord"]
