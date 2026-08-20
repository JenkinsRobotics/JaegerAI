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
    """Bind on disk is not enough — the live session agent has to rebuild
    its prompt, or the next reply is still the previous character.

    It must do that WITHOUT dropping the conversation. A character is a
    prompt layer; the operator is still talking to the same assistant, so
    a costume change is not a reason to forget what was said. This test
    previously asserted ``agent.messages == []`` — it pinned the wipe as
    if it were the feature."""
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
    assert agent.messages == [{"role": "assistant", "content": "old voice"}]


def test_bind_moves_binding_and_sets_active(tmp_path):
    _manifest(tmp_path, bound_character="kamina")
    bind_character(tmp_path, "simon")                # deliberate rebind
    assert bound_character_id(tmp_path) == "simon"
    assert active_character_id(tmp_path) == "simon"
    # other manifest fields survive the raw rewrite
    doc = json.loads((tmp_path / "manifest.json").read_text())
    assert doc["instance_name"] == "t"


def test_character_swap_keeps_every_live_session(tmp_path, monkeypatch):
    """The wipe was never scoped to the session you were looking at.

    ``apply_live_character`` loops over EVERY live session agent, so one
    character pick used to clear conversations the operator was not even
    touching. Re-point them all; forget none of them.
    """
    from jaeger_ai import main
    from jaeger_ai.core.instance.instance import InstanceLayout

    _manifest(tmp_path, bound_character="clanker")
    set_active_character(tmp_path, "clanker")
    monkeypatch.setitem(main._pipeline, "layout", InstanceLayout(root=tmp_path))
    monkeypatch.setattr(
        "jaeger_agent.prompts.prompts.build_system_prompt",
        lambda _layout: "NEW_CHARACTER",
    )

    class _Agent:
        def __init__(self, note):
            self.system_prompt = "OLD_CHARACTER"
            self.messages = [{"role": "user", "content": note}]

    agents = {"webui-a": _Agent("a"), "webui-b": _Agent("b")}
    monkeypatch.setattr(main, "_jaeger_agents_by_session", agents)

    main.apply_live_character()

    for key, agent in agents.items():
        assert "NEW_CHARACTER" in agent.system_prompt, key
        assert agent.messages, f"{key} lost its conversation to a costume change"


def test_model_swap_carries_the_conversation_across_the_rebuild(monkeypatch):
    """A brain swap MUST rebuild the agent — the client is baked into its
    adapter, finalizer and context guard. It must not cost the operator
    the conversation: stash the turns on teardown, restore them onto the
    replacement.
    """
    from jaeger_ai import main

    class _Agent:
        def __init__(self, msgs):
            self.messages = list(msgs)

    turns = [
        {"role": "user", "content": "my name is Matthew"},
        {"role": "assistant", "content": "noted"},
    ]
    monkeypatch.setattr(
        main, "_jaeger_agents_by_session", {"webui-1": _Agent(turns)})
    monkeypatch.setattr(main, "_carried_session_messages", {})

    # The teardown half of apply_live_model, verbatim.
    for key in list(main._jaeger_agents_by_session):
        prior = list(getattr(
            main._jaeger_agents_by_session.get(key), "messages", None) or [])
        main.evict_session(key)
        if prior:
            main._carried_session_messages[key] = prior

    assert main._carried_session_messages["webui-1"] == turns

    # The re-seed half, as _ensure_session_agent performs it on the new agent.
    rebuilt = _Agent([])
    main._jaeger_agents_by_session["webui-1"] = rebuilt
    carried = main._carried_session_messages.pop("webui-1", None)
    assert carried, "the rebuild dropped the conversation"
    rebuilt.messages.extend(carried)

    assert rebuilt.messages == turns
    assert main._carried_session_messages == {}, "carry-over must not leak"
