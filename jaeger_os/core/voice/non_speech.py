"""Whisper non-speech marker filtering for always-on voice.

Whisper emits bracketed or parenthetical labels when it is forced to
transcribe silence, device clicks, wind, engines, or other ambient audio.
In no-wake-word voice mode those labels must not become agent turns.
"""

from __future__ import annotations

import re


_NON_SPEECH_MARKERS = frozenset({
    "blank_audio", "no_speech",
    "sound", "noise", "background noise", "silence",
    "beep", "beeping", "click", "clicking", "computer click",
    "mouse click", "keyboard click", "keyboard clicking",
    "keyboard clacking", "typing sounds", "tapping",
    "music", "applause", "laughter",
    "clapping", "paper rustling", "water splashing",
    "sigh", "sighs", "sniff", "sniffing", "breathing",
    "wind", "wind blowing", "air whooshing", "engine", "engine roaring",
    "engine revving", "motor", "motor noise",
})
_WRAPPED_MARKER_RE = re.compile(
    r"^\s*[\[\(]([^\]\)]{1,80})[\]\)]\s*[.!,?]*\s*$"
)


def is_non_speech_marker(text: str | None) -> bool:
    """True when ``text`` is a known non-speech transcript marker.

    The check strips ``[...]`` / ``(...)`` wrappers before matching, so
    real wrapped answers like ``(yes)`` are still accepted.
    """
    s = (text or "").strip()
    if not s:
        return True
    m = _WRAPPED_MARKER_RE.match(s)
    if m:
        inner = m.group(1).lower().strip(".!?, ")
        return inner in _NON_SPEECH_MARKERS
    lowered = s.lower().strip(".!?, ")
    return lowered in _NON_SPEECH_MARKERS


__all__ = ["is_non_speech_marker"]
