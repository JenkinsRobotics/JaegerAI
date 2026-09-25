"""LocalAgreement streaming STT.

The algorithm (whisper-streaming / LocalAgreement-2, Macháček et al.)
runs one model over overlapping
windows of the live buffer and confirm a word only once a later pass
still agrees on it.  Confirmed words are final; the unconfirmed tail is
the live partial.

The mechanics are identical to ``window`` mode — same ring buffer, same
cadence, same energy gate, same wake gate — so this is that class with
``commit="agreement"``.  The agreement rule itself lives in
``window.pipeline.commit_cursor`` (the karaoke word cursor
ported from MockingAgent's
``llm_listener/always_listening_word_cursor_pipeline.py``).

Use this mode when you want live captions AND a trustworthy final
transcript.  ``window`` mode gives captions but its "finals" are just
clock-driven window dumps; ``two_pass``/``continuous`` give good finals
but nothing until the phrase closes.  This is the one that gives both.
"""

from __future__ import annotations

from ..window.pipeline import WhisperSTTWindow


def agreed_prefix(previous: str, current: str) -> str:
    """Return the common word prefix, preserving the newest spelling."""
    words = []
    for old, new in zip(previous.split(), current.split()):
        if old.casefold() != new.casefold():
            break
        words.append(new)
    return " ".join(words)



class WhisperSTTLocalAgreement(WhisperSTTWindow):
    """Rolling window + word-cursor commit.  Same public API as every
    other method here, plus ``set_on_partial``."""

    label = "stt-agree"

    def __init__(self, **kwargs) -> None:
        # ponytail: a subclass rather than a copy — the ring buffer,
        # energy gate, wake gate and lifecycle are byte-identical to
        # window mode and only the commit rule differs. If the two ever
        # need to diverge structurally, split then, not now.
        kwargs["commit"] = "agreement"
        super().__init__(**kwargs)


__all__ = ["WhisperSTTLocalAgreement"]
