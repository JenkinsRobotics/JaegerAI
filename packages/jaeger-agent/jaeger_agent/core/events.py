"""Core event contract + the annotator's turn shim.

Extracted 2026-09-02 from the VoiceLLM canonical implementation.
Keep in sync by re-extraction; behavior must stay byte-equivalent."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

class _TurnShim:
    """The annotator's turn contract, satisfied from engine state."""
    def __init__(self, audio, started_at, speech_ms):
        self.audio = audio
        self.started_at = started_at
        self.speech_ms = speech_ms


@dataclass
class Event:
    """One thing that happened, with enough context to render or assert on it.

    A callback taking (kind, text) would have been shorter, but every consumer
    then re-derives the same structure — the GUI needs latency separately from
    transcript, and a test needs to distinguish "ignored the television" from
    "never heard it". Naming the kinds once is cheaper than three parsers.
    """
    kind: str          # status | state | live | user | assistant | environment
                       # | overheard | self | audio | latency | submitted | session
    text: str = ""
    data: object = None  # assistant: display/channels/source output decision
    at: float = field(default_factory=time.time)


__all__ = [
    "_TurnShim",
    "Event",
]
