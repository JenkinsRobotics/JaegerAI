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
    "music", "upbeat music", "background music", "applause", "laughter",
    "clapping", "paper rustling", "scissors snipping", "water splashing",
    "sigh", "sighs", "sniff", "sniffing", "breathing",
    "wind", "wind blowing", "air whooshing", "engine", "engine roaring",
    "engine revving", "motor", "motor noise",
})
_WRAPPED_MARKER_RE = re.compile(
    r"^\s*[\[\(]([^\]\)]{1,80})[\]\)]\s*[.!,?]*\s*$"
)
_WRAPPED_MARKER_TOKEN_RE = re.compile(r"[\[\(]([^\]\)]{1,80})[\]\)]")
# Whisper also hallucinates music/sound descriptions wrapped in ♪ or
# asterisks ("♪ music ♪", "*coughs*") on noise and silence — those
# wrappers never occur in real dictated speech, so the whole phrase is
# an artifact regardless of the inner words (VoiceLLM ingress-hardening
# port; each one previously paid a full LLM turn just to be ignored).
_SOUND_WRAPPED_RE = re.compile(r"^\s*[♪*].*[♪*]\s*[.!,?]*\s*$")


def is_non_speech_marker(text: str | None) -> bool:
    """True when ``text`` is a known non-speech transcript marker.

    The check strips ``[...]`` / ``(...)`` wrappers before matching, so
    real wrapped answers like ``(yes)`` are still accepted. ♪- and
    *-wrapped phrases are artifacts unconditionally.
    """
    s = (text or "").strip()
    if not s:
        return True
    if _SOUND_WRAPPED_RE.match(s):
        return True
    m = _WRAPPED_MARKER_RE.match(s)
    if m:
        inner = m.group(1).lower().strip(".!?, ")
        return inner in _NON_SPEECH_MARKERS
    wrapped = _WRAPPED_MARKER_TOKEN_RE.findall(s)
    if wrapped and _WRAPPED_MARKER_TOKEN_RE.sub("", s).strip(".!?, "):
        return False
    if wrapped:
        return all(
            marker.lower().strip(".!?, ") in _NON_SPEECH_MARKERS
            for marker in wrapped
        )
    lowered = s.lower().strip(".!?, ")
    return lowered in _NON_SPEECH_MARKERS


__all__ = ["is_non_speech_marker"]
