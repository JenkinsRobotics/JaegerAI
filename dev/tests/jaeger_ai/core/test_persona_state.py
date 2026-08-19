"""Runtime persona state — per instance, never the character definition.

``adjust_trait`` used to write the character sheet in the bundled
library, so one robot's mid-conversation drift became every instance's
personality and fought the next package upgrade. These pin the split:
adaptation lands in ``<instance>/persona_state.yaml`` and is applied
over a definition that stays byte-identical.
"""

from __future__ import annotations

import pytest

from jaeger_ai.personality import persona_state
from jaeger_ai.personality.character import (
    active_character,
    active_character_signature,
    characters_root,
    load_character,
)


def test_no_state_file_means_no_overrides(tmp_path) -> None:
    assert persona_state.load_overrides(tmp_path, "assistant") == {}


def test_set_and_load_round_trip(tmp_path) -> None:
    persona_state.set_trait_override(tmp_path, "assistant", "expression",
                                     "sarcasm", 0.75)
    assert persona_state.load_overrides(tmp_path, "assistant") == {
        "expression": {"sarcasm": 0.75}}


def test_values_are_clamped(tmp_path) -> None:
    assert persona_state.set_trait_override(
        tmp_path, "assistant", "expression", "sarcasm", 4.2) == 1.0
    assert persona_state.set_trait_override(
        tmp_path, "assistant", "expression", "sarcasm", -3) == 0.0


def test_unknown_layer_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        persona_state.set_trait_override(tmp_path, "assistant", "vibes",
                                         "chill", 0.5)


def test_overrides_are_scoped_per_character(tmp_path) -> None:
    persona_state.set_trait_override(tmp_path, "assistant", "expression",
                                     "sarcasm", 0.9)
    persona_state.set_trait_override(tmp_path, "jarvis", "expression",
                                     "sarcasm", 0.1)
    assert persona_state.load_overrides(tmp_path, "assistant")["expression"][
        "sarcasm"] == 0.9
    assert persona_state.load_overrides(tmp_path, "jarvis")["expression"][
        "sarcasm"] == 0.1


def test_overrides_are_scoped_per_instance(tmp_path) -> None:
    """Two robots playing the same character do not share drift."""
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(), two.mkdir()
    persona_state.set_trait_override(one, "assistant", "expression",
                                     "sarcasm", 0.9)
    assert persona_state.load_overrides(two, "assistant") == {}


def test_clear_drops_one_character_or_all(tmp_path) -> None:
    persona_state.set_trait_override(tmp_path, "a", "expression", "sarcasm", 0.9)
    persona_state.set_trait_override(tmp_path, "b", "expression", "sarcasm", 0.9)
    persona_state.clear_overrides(tmp_path, "a")
    assert persona_state.load_overrides(tmp_path, "a") == {}
    assert persona_state.load_overrides(tmp_path, "b") != {}
    persona_state.clear_overrides(tmp_path)
    assert persona_state.load_overrides(tmp_path, "b") == {}


def test_a_corrupt_state_file_reads_as_no_overrides(tmp_path) -> None:
    persona_state.state_path(tmp_path).write_text("{{{ not yaml")
    assert persona_state.load_overrides(tmp_path, "assistant") == {}


def test_garbage_values_are_dropped_not_raised(tmp_path) -> None:
    """The file is hand-editable, so it is read defensively."""
    persona_state.state_path(tmp_path).write_text(
        "characters:\n"
        "  assistant:\n"
        "    traits:\n"
        "      expression:\n"
        "        sarcasm: not-a-number\n"
        "        warmth: 0.6\n"
        "      vibes:\n"
        "        chill: 0.5\n"
    )
    assert persona_state.load_overrides(tmp_path, "assistant") == {
        "expression": {"warmth": 0.6}}


def test_state_path_accepts_a_layout(tmp_path) -> None:
    from jaeger_ai.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=tmp_path)
    assert persona_state.state_path(layout) == persona_state.state_path(
        layout.root)


# ── applied over the definition ─────────────────────────────────────


def test_active_character_reflects_the_override(tmp_path) -> None:
    baseline = active_character(tmp_path)
    assert baseline is not None
    before = baseline.personality.expression.sarcasm
    target = 0.5 if before != 0.5 else 0.25
    persona_state.set_trait_override(tmp_path, baseline.id, "expression",
                                     "sarcasm", target)
    assert active_character(tmp_path).personality.expression.sarcasm == target


def test_the_character_definition_is_never_written(tmp_path) -> None:
    """The sheet ships with the package and the marketplace distributes
    it — runtime drift must not end up inside it."""
    character = active_character(tmp_path)
    sheet = characters_root() / character.id / "character.yaml"
    before = sheet.read_bytes()
    persona_state.set_trait_override(tmp_path, character.id, "expression",
                                     "sarcasm", 0.9)
    assert sheet.read_bytes() == before
    # …and a fresh load of the definition alone is unchanged.
    assert load_character(sheet.parent).personality.expression.sarcasm != 0.9 \
        or before != sheet.read_bytes()


def test_a_stale_override_for_a_missing_slider_is_ignored(tmp_path) -> None:
    persona_state.state_path(tmp_path).write_text(
        "characters:\n"
        "  assistant:\n"
        "    traits:\n"
        "      expression:\n"
        "        retired_slider: 0.9\n"
    )
    assert active_character(tmp_path) is not None   # loads, does not raise


def test_signature_changes_when_a_trait_is_adapted(tmp_path) -> None:
    """Instant-apply: the prompt is cached, so the refresh signature has
    to move when the agent adjusts itself."""
    before = active_character_signature(tmp_path)
    character = active_character(tmp_path)
    persona_state.set_trait_override(tmp_path, character.id, "expression",
                                     "sarcasm", 0.42)
    assert active_character_signature(tmp_path) != before
