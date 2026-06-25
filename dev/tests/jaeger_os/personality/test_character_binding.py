"""Character binding — the canonical-vs-active split.

bound_character (manifest.json) = who the instance IS; active_character file =
who it plays right now. active_character_id falls back to the binding, and
bind_character moves the binding (the deliberate, verified rebind).
"""

import json

from jaeger_os.personality.character import (
    active_character_id, bind_character, bound_character_id, set_active_character,
)


def _manifest(root, **extra):
    (root / "manifest.json").write_text(
        json.dumps({"instance_name": "t", **extra}), encoding="utf-8")


def test_unbound_falls_back_to_default(tmp_path):
    assert bound_character_id(tmp_path) == ""
    assert active_character_id(tmp_path) == "jarvis"


def test_active_falls_back_to_binding_not_global_default(tmp_path):
    _manifest(tmp_path, bound_character="kamina")
    # no active_character file → resolves to the BOUND character, not jarvis
    assert active_character_id(tmp_path) == "kamina"


def test_active_override_wins_but_binding_unchanged(tmp_path):
    _manifest(tmp_path, bound_character="kamina")
    set_active_character(tmp_path, "simon")          # session override
    assert active_character_id(tmp_path) == "simon"
    assert bound_character_id(tmp_path) == "kamina"  # binding untouched


def test_bind_moves_binding_and_sets_active(tmp_path):
    _manifest(tmp_path, bound_character="kamina")
    bind_character(tmp_path, "simon")                # deliberate rebind
    assert bound_character_id(tmp_path) == "simon"
    assert active_character_id(tmp_path) == "simon"
    # other manifest fields survive the raw rewrite
    doc = json.loads((tmp_path / "manifest.json").read_text())
    assert doc["instance_name"] == "t"
