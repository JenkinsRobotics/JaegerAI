"""Bundled engineering characters are Jaeger character/v1, not ARES lore."""

from __future__ import annotations

import re

from jaeger_ai.personality.character import characters_root, list_characters


ENGINEERING_IDS = {
    "systems_principal",
    "research_strategist",
    "robotics_architect",
    "reliability_auditor",
}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def test_engineering_characters_load_as_character_v1():
    loaded = {c.id: c for c in list_characters(characters_root())}
    missing = ENGINEERING_IDS - set(loaded)
    assert not missing, missing
    for cid in ENGINEERING_IDS:
        character = loaded[cid]
        soul = _flat(character.soul)
        assert character.soul, cid
        assert "do not grant capabilities" in soul
        assert "jaegerai is the authoritative runtime" in soul
        traits = character.personality.hexaco
        assert 0.0 <= traits.conscientiousness <= 1.0
        assert isinstance(traits.conscientiousness, float)


def test_engineering_souls_do_not_claim_ares_is_the_si():
    for character in list_characters(characters_root()):
        if character.id not in ENGINEERING_IDS:
            continue
        text = _flat(character.soul)
        assert "cognitive controller" not in text
        assert "maximum agency" not in text
        assert "self-healing" not in text

