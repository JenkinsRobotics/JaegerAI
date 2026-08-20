"""The session context payload — what the bridge hands the agent, in order.

Contract: base prompt (safety → name → SOUL.md identity → framework →
AGENTS.md directives → dynamic blocks), then the runtime identity tier,
then the frozen facts tier. The session stream follows as MESSAGES and is
never spliced into the payload.

The regression these exist for: the composition lived inline in
``_ensure_session_agent``, so ``_refresh_character_prompt`` — which
rebuilds mid-session when the persona or a context document changes —
reassigned the base prompt alone and silently dropped the runtime and
facts tiers for the rest of the session.

Every file read here is stubbed or points at ``tmp_path``: no test needs
a real instance directory, so CI and a developer box run the same paths.
"""

from __future__ import annotations

import pytest

from jaeger_ai import main
from jaeger_ai.core.instance.instance import (
    InstanceLayout,
    context_document_signature,
)


@pytest.fixture()
def stub_tiers(monkeypatch):
    """The two session-scoped tiers, stubbed to recognisable markers."""
    monkeypatch.setattr(main, "_runtime_identity_block", lambda: "RUNTIME_TIER")
    monkeypatch.setattr(main, "_facts_snapshot_block", lambda: "FACTS_TIER")


def test_payload_order_is_base_then_runtime_then_facts(stub_tiers) -> None:
    payload = main.compose_session_prompt("BASE_PROMPT")
    assert payload.index("BASE_PROMPT") < payload.index("RUNTIME_TIER")
    assert payload.index("RUNTIME_TIER") < payload.index("FACTS_TIER")


def test_empty_tiers_are_omitted_cleanly(monkeypatch) -> None:
    monkeypatch.setattr(main, "_runtime_identity_block", lambda: "")
    monkeypatch.setattr(main, "_facts_snapshot_block", lambda: "")
    assert main.compose_session_prompt("BASE_PROMPT") == "BASE_PROMPT"


def test_a_missing_facts_tier_does_not_shift_the_runtime_tier(
        monkeypatch) -> None:
    monkeypatch.setattr(main, "_runtime_identity_block", lambda: "RUNTIME_TIER")
    monkeypatch.setattr(main, "_facts_snapshot_block", lambda: "")
    payload = main.compose_session_prompt("BASE_PROMPT")
    assert payload == "BASE_PROMPT\n\nRUNTIME_TIER"


class _Agent:
    """Only what ``_refresh_character_prompt`` / ``apply_live_character`` touch."""

    def __init__(self) -> None:
        self.system_prompt = ""
        self.messages: list[dict] = []


def test_refresh_keeps_every_tier(tmp_path, stub_tiers, monkeypatch) -> None:
    """The regression: a mid-session rebuild must produce the SAME shape
    as construction, not just the base prompt."""
    layout = InstanceLayout(root=tmp_path)
    monkeypatch.setitem(main._pipeline, "layout", layout)
    monkeypatch.setitem(main._pipeline, "active_character_sig", "stale")
    monkeypatch.setattr(
        "jaeger_agent.prompts.prompts.build_system_prompt",
        lambda _layout: "REBUILT_BASE",
    )
    agent = _Agent()
    main._refresh_character_prompt(agent)

    assert "REBUILT_BASE" in agent.system_prompt
    assert "RUNTIME_TIER" in agent.system_prompt
    assert "FACTS_TIER" in agent.system_prompt
    assert agent.system_prompt == main.compose_session_prompt("REBUILT_BASE")


def test_refresh_is_a_no_op_when_nothing_changed(
        tmp_path, stub_tiers, monkeypatch) -> None:
    """It runs on the turn path — an unchanged signature must not pay for
    a rebuild (or reassign the prompt and break the prefix cache)."""
    layout = InstanceLayout(root=tmp_path)
    monkeypatch.setitem(main._pipeline, "layout", layout)
    builds: list[int] = []
    monkeypatch.setattr(
        "jaeger_agent.prompts.prompts.build_system_prompt",
        lambda _layout: builds.append(1) or "BASE",
    )
    agent = _Agent()
    main._refresh_character_prompt(agent)      # first call seeds the signature
    first = len(builds)
    main._refresh_character_prompt(agent)      # nothing changed on disk
    assert len(builds) == first


def test_editing_a_context_document_triggers_a_rebuild(
        tmp_path, stub_tiers, monkeypatch) -> None:
    """Dynamic ingestion has to reach a RUNNING agent: the prompt is
    cached, so an edited SOUL.md needs the signature to move."""
    layout = InstanceLayout(root=tmp_path)
    monkeypatch.setitem(main._pipeline, "layout", layout)
    builds: list[str] = []
    monkeypatch.setattr(
        "jaeger_agent.prompts.prompts.build_system_prompt",
        lambda _layout: builds.append("build") or "BASE",
    )
    agent = _Agent()
    main._refresh_character_prompt(agent)
    before = len(builds)
    (tmp_path / "SOUL.md").write_text("a new identity")
    main._refresh_character_prompt(agent)
    assert len(builds) == before + 1


def test_apply_live_character_rebuilds_prompt_and_drops_history(
        tmp_path, stub_tiers, monkeypatch) -> None:
    """A HUD pick has to change the RUNNING agent, not just the files.
    Cached prompt + leftover Jarvis turns would keep answering as Jarvis
    after the operator selected Clanker."""
    layout = InstanceLayout(root=tmp_path)
    monkeypatch.setitem(main._pipeline, "layout", layout)
    monkeypatch.setattr(
        "jaeger_agent.prompts.prompts.build_system_prompt",
        lambda _layout: "CLANKER_BASE",
    )
    agent = _Agent()
    agent.system_prompt = "OLD_JARVIS"
    agent.messages = [
        {"role": "user", "content": "who are you"},
        {"role": "assistant", "content": "I am Jarvis, sir."},
    ]
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {"desktop-app": agent})

    main.apply_live_character()

    assert "CLANKER_BASE" in agent.system_prompt
    assert agent.messages == []
    # Signature is seeded so the next turn's refresh is a no-op, not a
    # second rebuild that would miss the just-applied payload.
    assert main._pipeline.get("active_character_sig")


# ── the signature itself ────────────────────────────────────────────


def test_signature_is_stable_without_documents(tmp_path) -> None:
    assert context_document_signature(tmp_path) == \
        context_document_signature(tmp_path)


def test_signature_tracks_each_document(tmp_path) -> None:
    empty = context_document_signature(tmp_path)
    (tmp_path / "SOUL.md").write_text("who")
    with_soul = context_document_signature(tmp_path)
    (tmp_path / "AGENTS.md").write_text("how")
    with_both = context_document_signature(tmp_path)
    assert empty != with_soul != with_both
    assert with_soul != with_both


def test_layout_names_both_documents(tmp_path) -> None:
    layout = InstanceLayout(root=tmp_path)
    assert layout.soul_path.name == "SOUL.md"
    assert layout.directives_path.name == "AGENTS.md"
