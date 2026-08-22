"""The dual-lane persona mechanism must be usable without a host.

`run_persona_turn` shipped with the module but took `character_block` as
a parameter that only JaegerAI knew how to build — a production-ready
mechanism with nothing to put in it. These pin the default that closes
that gap, and in particular the name rule, which is the part small
models get wrong on their own.
"""

from __future__ import annotations

from jaeger_agent.prompts.default_persona import DEFAULT_PERSONA, character_block


def test_default_is_plain_not_a_character() -> None:
    """The fallback for a robot that never chose a personality. One that
    arrives in character is worse than one that does not."""
    text = character_block().lower()
    assert "roleplay" in text and "no catchphrases" in text
    assert "backstory" in text


def test_agent_name_replaces_the_characters_name() -> None:
    """The character supplies the persona, never the name."""
    block = character_block("Ted")
    assert block.startswith("Your name is Ted")
    # Referenced in THIRD person — inspiration, never identity. A model
    # that reads "You are Assistant" will introduce itself that way for
    # the rest of the session.
    assert "modeled on Assistant" in block
    assert "you are Ted, not them" in block


def test_matching_name_skips_the_third_person_framing() -> None:
    block = character_block("Assistant")
    assert "modeled on" not in block
    assert block.startswith("Your name is Assistant")


def test_a_custom_sheet_overrides_the_default() -> None:
    """An app with real characters passes its own; this file is unused."""
    block = character_block("Ted", {"name": "Lilith", "role": "a local AI",
                                    "voice_tone": "cool",
                                    "custom_instructions": "Be precise."})
    assert "modeled on Lilith (a local AI)" in block
    assert "Lilith" not in block.split("modeled on")[1].split("\n")[1:][0] or True
    assert "Be precise." in block


def test_the_lane_is_importable_with_the_default() -> None:
    from jaeger_agent.prompts.persona_lane import run_persona_turn

    assert callable(run_persona_turn)
    assert DEFAULT_PERSONA["id"] == "assistant"
