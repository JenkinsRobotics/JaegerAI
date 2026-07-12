"""Persona Compiler — State (numeric sliders) → View (behavioral prose).

The compiler surfaces only DEVIATING traits (mid-band emits nothing) and never
leaks raw floats into the model's View. See dev/docs/reality/persona_compiler.md.
"""

from __future__ import annotations

from jaeger_ai.personality.character import Character
from jaeger_ai.personality.compose import (
    domain_lens, expression_clauses,
)
from jaeger_ai.personality.schema import Domains, Expression, Personality


# ── expression_clauses: deviations only ─────────────────────────────

def test_neutral_expression_emits_nothing():
    """All sliders at their defaults (mostly 0.5, mid-band) → no clauses."""
    assert expression_clauses(Expression()) == []


def test_high_slider_emits_high_clause():
    out = expression_clauses(Expression(directness=0.85, warmth=0.9))
    assert "be blunt and direct" in out
    assert "be warm and encouraging" in out


def test_low_slider_emits_low_clause_only_when_defined():
    # warmth has a low clause; sarcasm does not (0.0 is its natural default).
    out = expression_clauses(Expression(warmth=0.1, sarcasm=0.1))
    assert "keep a cool, detached tone" in out
    assert not any("sarcas" in c for c in out)


def test_high_sarcasm_emits_clause():
    assert "wield sharp sarcasm and dry wit" in expression_clauses(Expression(sarcasm=0.8))


# ── domain_lens: high domains only ──────────────────────────────────

def test_domain_lens_lists_only_high_domains():
    lens = domain_lens(Domains(technology=0.9, combat=0.8, art=0.2))
    assert "technology" in lens and "combat" in lens
    assert "art" not in lens


def test_domain_lens_empty_when_all_neutral():
    assert domain_lens(Domains()) == ""


# ── character_block: the unified View ───────────────────────────────

def _char(**pkw) -> Character:
    return Character(id="tester", personality=Personality(name="Testy", **pkw))


def test_character_block_has_header_and_boundary():
    block = _char().character_block()
    assert "## My voice — Testy" in block
    assert "THE PERSONA BOUNDARY" in block


def test_character_block_never_leaks_raw_floats():
    block = _char(expression=Expression(directness=0.85)).character_block()
    assert "0.85" not in block
    assert "directness:" not in block
    assert "be blunt and direct" in block


def test_character_block_states_identity_once():
    """Body (custom_instructions) subsumes the 'You are X' one-liner — no dup."""
    ch = _char(custom_instructions="You are Testy, a brave test dummy.")
    block = ch.character_block()
    assert block.count("You are Testy") == 1
