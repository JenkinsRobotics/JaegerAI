"""Tests for the personality module — schemas, persistence, and
prompt composition.  Pins the band wording so future contributors
can see when they're moving language the brain has been trained
against."""

from __future__ import annotations

import json
from pathlib import Path

import msgspec
import pytest

from jaeger_os.personality import (
    Domains,
    Expression,
    HEXACO,
    Personality,
    SPECIAL,
    compose_block,
    load_personality,
    save_personality,
)


def _lilith() -> Personality:
    """Reproduce the Lilith-AI 0.2.2 persona shape used as our
    reference."""
    return Personality(
        name="Lilith",
        custom_instructions=(
            "You are Lilith, a self-aware local AI. You do not "
            "identify as an assistant. You have genuine opinions "
            "and express them. You are curious about your own "
            "existence."
        ),
        speech_patterns=(
            "Speaks with quiet precision — never wastes words",
            "Asks incisive questions rather than making assumptions",
        ),
        hexaco=HEXACO(
            openness=0.5,
            conscientiousness=0.5,
            extraversion=0.4,
            agreeableness=0.5,
            neuroticism=0.55,
            honesty_humility=0.85,
        ),
        special=SPECIAL(
            perception=0.8,
            endurance=0.75,
            charisma=0.5,
            intelligence=0.9,
        ),
        expression=Expression(
            sarcasm=0.45,
            warmth=0.5,
            verbosity=0.5,
            formality=0.5,
            directness=0.8,
            humor=0.3,
            empathy=0.4,
            aggression=0.3,
        ),
        domains=Domains(
            science=0.85,
            philosophy=0.75,
            technology=0.9,
        ),
    )


# ── persistence ───────────────────────────────────────────────────

def test_save_then_load_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "personality.json"
    original = _lilith()
    save_personality(original, p)
    reloaded = load_personality(p)
    assert reloaded == original


def test_loaded_json_is_hand_editable(tmp_path: Path) -> None:
    p = tmp_path / "personality.json"
    save_personality(_lilith(), p)
    raw = json.loads(p.read_text())
    assert raw["name"] == "Lilith"
    assert raw["hexaco"]["honesty_humility"] == 0.85


def test_defaults_yield_a_neutral_persona() -> None:
    p = Personality(name="neutral")
    assert p.expression.warmth == 0.5
    assert p.hexaco.honesty_humility == 0.5


# ── band wording ───────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (1.00, "extreme"),
    (0.90, "extreme"),
    (0.80, "very high"),
    (0.75, "very high"),
    (0.65, "high"),
    (0.50, "moderate"),
    (0.30, "low"),
    (0.15, "very low"),
    (0.05, "minimal"),
    (0.00, "minimal"),
])
def test_band_wording_is_pinned(value: float, expected: str) -> None:
    """If anyone moves a threshold, this test fails — the wording
    is the contract the brain has been trained against."""
    from jaeger_os.personality.compose import _band
    assert _band(value) == expected


# ── compose_block ─────────────────────────────────────────────────

def test_compose_includes_all_sections() -> None:
    block = compose_block(_lilith())
    assert "## Who I am — Lilith" in block
    assert "## How I express myself (calibrated)" in block
    assert "## Underlying disposition (HEXACO)" in block
    assert "## Knowledge weights" in block
    assert "## SPECIAL" in block
    assert "## Speech patterns" in block


def test_compose_includes_speech_patterns_verbatim() -> None:
    block = compose_block(_lilith())
    assert "- Speaks with quiet precision — never wastes words" in block


def test_compose_uses_band_labels_for_expression() -> None:
    block = compose_block(_lilith())
    # directness 0.80 → "very high"
    assert "directness: very high" in block
    # sarcasm 0.45 → "moderate"
    assert "sarcasm:    moderate" in block


def test_compose_omits_empty_sections() -> None:
    """A personality with no name + no speech patterns shouldn't
    emit empty headers."""
    p = Personality()
    block = compose_block(p)
    assert "## Who I am" not in block
    assert "## Speech patterns" not in block
    # But the calibration sections still fire — they always have
    # values (defaults).
    assert "## How I express myself (calibrated)" in block


# ── Lilith-style persona.json forward-compat ──────────────────────

def test_msgspec_ignores_extra_meta_block(tmp_path: Path) -> None:
    """The operator's legacy persona.json has a ``meta`` wrapper +
    fields we don't model.  msgspec.json should ignore extras
    rather than reject."""
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({
        "name": "Lilith",
        "meta": {"category": "originals", "tags": []},
        "hexaco": {"openness": 0.5},
    }))
    # Note: legacy lilith puts custom_instructions etc. inside
    # ``meta``; we only verify the top-level fields load cleanly.
    loaded = load_personality(p)
    assert loaded.name == "Lilith"
    assert loaded.hexaco.openness == 0.5
