"""One identity per turn — the name the agent answers to.

Operator decision, 2026-08-19, reversing the 2026-07-05 framing. A
selected character IS the agent: its name is the only name in the prompt
and on every surface. Only the ``neutral`` sheet (``assistant``) yields,
and then identity.yaml's name comes through. Nothing names the framework
in a conversational turn.

These pin the JaegerAI side of that: the ``identity_name`` prompt
fragment (re-pointed in the dependency's registry from
:mod:`jaeger_ai.core.prompt_identity`), and the Mode-C self-model
header, which used to open "You are a Jaeger agent running locally on
this machine" three paragraphs under the character's own "You are
Clanker".

The block-building half lives in
dev/tests/jaeger_ai/main/test_persona_mode.py; the shared rule itself is
``personality.character.persona_display_name``. Kept apart from
test_prompt_identity.py, which covers a different thing under a similar
name: the framework document's own contents (Jaeger OS context, terminal
output rules) rather than who the agent says it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from jaeger_agent.prompts import assemble

from jaeger_ai.core.prompt_identity import (
    IDENTITY_FRAGMENT,
    SELF_MODEL_HEADER,
    agent_display_name,
    register_agent_identity,
)
from jaeger_ai.personality.character import characters_root


@dataclass
class _Layout:
    """The slice of a host layout the identity fragment reads."""

    root: Path

    @property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    @property
    def identity_path(self) -> Path:
        return self.root / "identity.yaml"


@pytest.fixture()
def layout(tmp_path) -> _Layout:
    register_agent_identity()
    (tmp_path / "identity.yaml").write_text(
        yaml.safe_dump({"name": "Ted", "role": "the house robot",
                        "personality": "plain and useful"}),
        encoding="utf-8",
    )
    return _Layout(root=tmp_path)


def _select(layout: _Layout, character_id: str) -> None:
    from jaeger_ai.personality.character import set_active_character
    set_active_character(layout.root, character_id)


def _fragment_text(layout: _Layout) -> str:
    fragment = next(f for f in assemble.PROMPT_FRAGMENTS
                    if f.name == IDENTITY_FRAGMENT)
    return fragment.build(assemble.FragmentContext(layout=layout, mode="agent"))


# ── the name itself ─────────────────────────────────────────────────


def test_a_selected_character_supplies_the_name(layout) -> None:
    """The whole point: pick Clanker, and the agent is Clanker. The
    instance's own name is not mentioned and not blended in."""
    _select(layout, "clanker")
    assert agent_display_name(layout) == "Clanker"


def test_the_neutral_sheet_yields_to_the_instance_name(layout) -> None:
    """``assistant`` is nobody in particular — this is how an operator
    gets "Ted, a plain assistant" rather than "Assistant"."""
    _select(layout, "assistant")
    assert agent_display_name(layout) == "Ted"


def test_the_shipped_assistant_sheet_is_the_neutral_one() -> None:
    """The neutral flag is a property of the sheet on disk, not a
    hardcoded id — but exactly one shipped sheet may carry it."""
    neutral = [
        d.name for d in sorted(characters_root().iterdir())
        if (d / "character.yaml").is_file()
        and (yaml.safe_load((d / "character.yaml").read_text(encoding="utf-8"))
             or {}).get("neutral")
    ]
    assert neutral == ["assistant"]


def test_an_unnamed_instance_falls_back_to_the_sheet_never_the_framework(
    tmp_path,
) -> None:
    """No readable identity.yaml → the neutral sheet's own label, which is
    what it is actually called. The point of the fallback chain is that no
    link in it is a framework brand: "Assistant" is a description, "Jaeger"
    would be an identity nobody chose."""
    register_agent_identity()
    name = agent_display_name(_Layout(root=tmp_path / "nope"))
    assert name == "Assistant"
    assert "jaeger" not in name.lower()


# ── the prompt fragment ─────────────────────────────────────────────


def test_the_fragment_states_the_character_name(layout) -> None:
    _select(layout, "clanker")
    assert _fragment_text(layout) == "Your name is Clanker."


def test_the_fragment_states_the_instance_name_when_neutral(layout) -> None:
    _select(layout, "assistant")
    assert _fragment_text(layout) == "Your name is Ted."


def test_the_fragment_never_states_a_framework_name(tmp_path) -> None:
    register_agent_identity()
    assert _fragment_text(_Layout(root=tmp_path / "nope")) == "Your name is Assistant."


def test_the_default_sheet_is_the_neutral_one(layout) -> None:
    """The two halves have to agree: an instance that never opened the
    picker plays the neutral sheet, so it answers to its own name."""
    from jaeger_ai.personality.character import DEFAULT_CHARACTER_ID
    assert DEFAULT_CHARACTER_ID == "assistant"
    assert agent_display_name(layout) == "Ted"


def test_the_fragment_keeps_its_place_and_kind() -> None:
    """Re-pointing replaces the dependency's entry in place — the
    inspector (``jaeger prompt show``) must still see one identity
    fragment, in its original slot, declared as instance data."""
    register_agent_identity()
    names = [f.name for f in assemble.PROMPT_FRAGMENTS]
    assert names.count(IDENTITY_FRAGMENT) == 1
    assert names.index("three_laws") < names.index(IDENTITY_FRAGMENT)
    assert names.index(IDENTITY_FRAGMENT) < names.index("framework")
    fragment = next(f for f in assemble.PROMPT_FRAGMENTS
                    if f.name == IDENTITY_FRAGMENT)
    assert fragment.kind == "instance"
    assert fragment.note


def test_registration_is_idempotent() -> None:
    register_agent_identity()
    first = next(f for f in assemble.PROMPT_FRAGMENTS
                 if f.name == IDENTITY_FRAGMENT)
    register_agent_identity()
    second = next(f for f in assemble.PROMPT_FRAGMENTS
                  if f.name == IDENTITY_FRAGMENT)
    assert first is second


# ── the Mode-C self-model header ────────────────────────────────────


def test_the_lane_header_names_no_framework() -> None:
    """The line that put "Jaeger" in the model's mouth. It still has to
    say the digest is not a tool list — that is what it is for."""
    from jaeger_agent.prompts import persona_lane

    register_agent_identity()
    assert persona_lane._SELF_MODEL_HEADER == SELF_MODEL_HEADER
    assert "jaeger" not in SELF_MODEL_HEADER.lower()
    assert "perform_task" in SELF_MODEL_HEADER


def test_the_assembled_digest_names_no_framework() -> None:
    """Patching the constant is worthless if a digest built before the
    patch is still cached — registration drops the cache."""
    from jaeger_agent.prompts import persona_lane

    persona_lane._SELF_MODEL_HEADER = "You are a Jaeger agent, actually."
    persona_lane.reset_self_model_cache()
    persona_lane.self_model_block()
    register_agent_identity()
    assert "jaeger" not in persona_lane.self_model_block().lower()
