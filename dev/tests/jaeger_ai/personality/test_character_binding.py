"""Character binding — the canonical-vs-active split.

bound_character (manifest.json) = who the instance IS; active_character file =
who it plays right now. active_character_id falls back to the binding, and
bind_character moves the binding (the deliberate, verified rebind).
"""

import json

from jaeger_ai.personality.character import (
    DEFAULT_CHARACTER_ID, active_character_id, bind_character, bound_character_id,
    set_active_character,
)


def _manifest(root, **extra):
    (root / "manifest.json").write_text(
        json.dumps({"instance_name": "t", **extra}), encoding="utf-8")


def test_unbound_falls_back_to_the_neutral_default(tmp_path):
    """A fresh instance is nobody in particular. The default sheet is the
    NEUTRAL one (2026-08-19) — with the character supplying the agent's
    name, a character-shaped default would name an agent nobody chose."""
    assert bound_character_id(tmp_path) == ""
    assert active_character_id(tmp_path) == "assistant"
    assert DEFAULT_CHARACTER_ID == "assistant"


def test_active_falls_back_to_binding_not_global_default(tmp_path):
    _manifest(tmp_path, bound_character="kamina")
    # no active_character file → the BOUND character, not the global default
    assert active_character_id(tmp_path) == "kamina"


def test_active_override_wins_but_binding_unchanged(tmp_path):
    _manifest(tmp_path, bound_character="kamina")
    set_active_character(tmp_path, "simon")          # session override
    assert active_character_id(tmp_path) == "simon"
    assert bound_character_id(tmp_path) == "kamina"  # binding untouched


def test_hud_select_is_a_bind(tmp_path):
    """The bridge ``select_character`` command must persist. A pick
    that only wrote active_character snapped back to bound_character
    on the next boot — the operator's 'swap to Jarvis' never stuck."""
    import types

    from jaeger_ai.interfaces import bridge

    _manifest(tmp_path, bound_character="clanker")
    set_active_character(tmp_path, "clanker")
    boot = types.SimpleNamespace(layout=types.SimpleNamespace(root=tmp_path))
    ok, err = bridge._command("select_character", {"id": "jarvis"}, boot)
    assert ok is True
    assert err is None
    assert bound_character_id(tmp_path) == "jarvis"
    assert active_character_id(tmp_path) == "jarvis"


def test_hud_select_applies_to_the_running_agent(tmp_path, monkeypatch):
    """Bind on disk is not enough — the live session agent has to drop
    the old voice and rebuild its prompt, or the next reply is still
    the previous character."""
    import types

    from jaeger_ai import main
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.interfaces import bridge

    _manifest(tmp_path, bound_character="clanker")
    set_active_character(tmp_path, "clanker")
    layout = InstanceLayout(root=tmp_path)
    monkeypatch.setitem(main._pipeline, "layout", layout)
    monkeypatch.setattr(
        "jaeger_agent.prompts.prompts.build_system_prompt",
        lambda _layout: "NEW_CHARACTER",
    )

    class _Agent:
        def __init__(self):
            self.system_prompt = "OLD_CHARACTER"
            self.messages = [{"role": "assistant", "content": "old voice"}]

    agent = _Agent()
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {"desktop-app": agent})
    boot = types.SimpleNamespace(layout=types.SimpleNamespace(root=tmp_path))
    ok, err = bridge._command("select_character", {"id": "jarvis"}, boot)
    assert ok is True and err is None
    assert "NEW_CHARACTER" in agent.system_prompt
    assert agent.messages == []


def test_bind_moves_binding_and_sets_active(tmp_path):
    _manifest(tmp_path, bound_character="kamina")
    bind_character(tmp_path, "simon")                # deliberate rebind
    assert bound_character_id(tmp_path) == "simon"
    assert active_character_id(tmp_path) == "simon"
    # other manifest fields survive the raw rewrite
    doc = json.loads((tmp_path / "manifest.json").read_text())
    assert doc["instance_name"] == "t"
