"""Personality schemas (msgspec.Struct).

All scalar fields are in ``[0.0, 1.0]`` — a normalised 0..1 range
the operator can think of as percentages.  ``compose_block``
maps these to human-readable phrases in the system prompt
("medium-high sarcasm", "extremely direct", etc.) so the brain
gets language, not numbers.

Schema mirrors the operator's Lilith-AI prior work exactly —
existing ``persona.json`` files load without conversion.
"""

from __future__ import annotations

from pathlib import Path

import msgspec


def _u(x: float) -> float:
    """Clamp to [0, 1]."""
    return max(0.0, min(1.0, float(x)))


class HEXACO(msgspec.Struct, kw_only=True):
    """The HEXACO personality model (Big-Six)."""

    openness: float = 0.5
    conscientiousness: float = 0.5
    extraversion: float = 0.5
    agreeableness: float = 0.5
    neuroticism: float = 0.5
    honesty_humility: float = 0.5


class SPECIAL(msgspec.Struct, kw_only=True):
    """Fallout-style stat block — operator-friendly metaphor for
    response-shaping traits that aren't strict personality."""

    strength: float = 0.5
    perception: float = 0.5
    endurance: float = 0.5
    charisma: float = 0.5
    intelligence: float = 0.5
    agility: float = 0.5
    luck: float = 0.5


class Expression(msgspec.Struct, kw_only=True):
    """Conversational sliders.  These map directly to phrases in
    the composed system-prompt block."""

    sarcasm: float = 0.0
    warmth: float = 0.5
    verbosity: float = 0.5
    formality: float = 0.5
    directness: float = 0.5
    humor: float = 0.3
    empathy: float = 0.5
    aggression: float = 0.0


class Domains(msgspec.Struct, kw_only=True):
    """Knowledge weights.  Higher values bias the agent toward
    using that topic as a lens when synthesising."""

    science: float = 0.5
    philosophy: float = 0.5
    technology: float = 0.5
    art: float = 0.5
    politics: float = 0.5
    psychology: float = 0.5
    nature: float = 0.5
    combat: float = 0.5


class Personality(msgspec.Struct, kw_only=True):
    """Top-level persona model.  Persists to
    ``<instance>/personality.json``."""

    name: str = ""
    description: str = ""
    custom_instructions: str = ""
    speech_patterns: tuple[str, ...] = ()
    hexaco: HEXACO = msgspec.field(default_factory=HEXACO)
    special: SPECIAL = msgspec.field(default_factory=SPECIAL)
    expression: Expression = msgspec.field(default_factory=Expression)
    domains: Domains = msgspec.field(default_factory=Domains)
    schema_version: int = 1


# ── load / save ────────────────────────────────────────────────────

def load_personality(path: Path) -> Personality:
    """Read a Personality JSON.  Forward-compat with
    Lilith-style ``persona.json`` files — those carry ``meta``
    blocks which msgspec ignores (no extra-field strictness)."""
    data = path.read_bytes()
    return msgspec.json.decode(data, type=Personality)


def save_personality(personality: Personality, path: Path) -> None:
    """Atomic write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(msgspec.json.encode(personality))
    tmp.replace(path)
