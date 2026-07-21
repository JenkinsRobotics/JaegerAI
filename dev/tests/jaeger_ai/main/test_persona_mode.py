"""Persona Mode C glue in jaeger_os/main.py — the mode switch, the shared
identity-block builder, and the branch-selection helpers around
``_run_turn_via_jaeger_agent``. Design: dev/docs/roadmap/
PERSONA_PIPELINE_ABC_DESIGN.md; build plan: dev/docs/roadmap/
PERSONA_MODE_C_BUILD_PLAN.md, Task 1.

``run_persona_turn`` itself (the fake-client lane mechanics: tool-free,
delegated, compose-guard, lane-error) is covered in
dev/tests/jaeger_os/agent/test_persona_lane.py. This file covers the
main.py-side wiring: mode resolution (config default + env override in
both directions), the shared identity framing, and the
``_run_persona_lane_turn`` / ``_persona_lane_turn_result`` glue —
including the regression pin that mode="persona_last" (the explicit
Station-3-only path) never reaches the Mode-C branch, the fail-safe pin
that mode="persona_first" (today's default) with NO active character
behaves identically to persona_last, and the structural invariant that
``perform_task`` (== drive_one_turn) never runs twice for one turn.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.instance.schemas import (
    Config, ModelConfig, PersonaConfig, SkillsConfig,
)
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.main import (
    _agent_cache,
    _jaeger_agents_by_session,
    _pipeline,
    _persona_identity_block,
    _persona_lane_aux_available,
    _persona_lane_turn_result,
    _persona_mode,
    _run_persona_lane_turn,
    _run_turn_via_jaeger_agent,
    _spoke_via_tool,
)


@pytest.fixture(autouse=True)
def _reset_pipeline_config():
    saved = _pipeline.get("config")
    yield
    _pipeline["config"] = saved


# ── config default ────────────────────────────────────────────────────


def test_persona_config_mode_defaults_to_persona_first():
    pc = PersonaConfig()
    assert pc.mode == "persona_first"
    assert Config.model_fields["persona"].default_factory is PersonaConfig


def test_persona_config_rejects_frontend_mode():
    """Mode B (frontend) is design-only until built — no spec ahead of
    code. Only persona_last / persona_first are valid today."""
    with pytest.raises(Exception):
        PersonaConfig(mode="frontend")


# ── _persona_mode: config + env override, both directions ───────────


def test_persona_mode_reads_config_default():
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig())
    assert _persona_mode() == "persona_first"


def test_persona_mode_reads_config_persona_first():
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig(mode="persona_first"))
    assert _persona_mode() == "persona_first"


def test_persona_mode_missing_config_falls_back_to_persona_first():
    _pipeline["config"] = None
    assert _persona_mode() == "persona_first"
    _pipeline["config"] = SimpleNamespace()  # no .persona attr at all
    assert _persona_mode() == "persona_first"


def test_persona_mode_env_override_forces_persona_first_on(monkeypatch):
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig(mode="persona_last"))
    monkeypatch.setenv("JAEGER_PERSONA_MODE", "persona_first")
    assert _persona_mode() == "persona_first"


def test_persona_mode_env_override_forces_persona_last_off(monkeypatch):
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig(mode="persona_first"))
    monkeypatch.setenv("JAEGER_PERSONA_MODE", "persona_last")
    assert _persona_mode() == "persona_last"


def test_persona_mode_env_garbage_value_ignored(monkeypatch):
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig(mode="persona_first"))
    monkeypatch.setenv("JAEGER_PERSONA_MODE", "not_a_real_mode")
    assert _persona_mode() == "persona_first"  # falls back to config, not a crash


# ── shared identity framing (Station 3 + Mode C reuse the same text) ──


class _Character:
    def __init__(self, name: str, block: str = "## My voice"):
        self.name = name
        self._block = block

    def character_block(self) -> str:
        return self._block


def test_identity_block_substitutes_character_name_when_names_differ():
    # Hardened 2026-07-19: first-person bindings are scrubbed — every
    # occurrence of the character's name in the persona body becomes the
    # agent's name (case-insensitive). The framing then references the
    # character in THIRD person only ("modeled on X"), so the model can
    # draw on what it knows about a famous character without becoming it.
    block = _persona_identity_block(
        "Ted", _Character("Lilith", block="## My voice — Lilith\n\nYou are LILITH."))
    framing, body = block.split("\n\n", 1)
    assert framing.startswith("Your name is Ted")
    assert "modeled on Lilith" in framing
    assert "Lilith" not in body and "LILITH" not in body
    assert "## My voice — Ted" in body
    assert "You are Ted." in body


def test_identity_block_skips_framing_when_agent_name_matches_character():
    block = _persona_identity_block("Lilith", _Character("Lilith"))
    assert block == "## My voice"


def test_identity_block_skips_framing_when_agent_name_empty():
    block = _persona_identity_block("", _Character("Lilith"))
    assert block == "## My voice"


# ── _run_persona_lane_turn: fail-open + no-double-run glue ───────────


def test_run_persona_lane_turn_returns_none_none_when_no_layout():
    _pipeline["layout"] = None
    out = _run_persona_lane_turn(
        client=object(), jaeger_agent=SimpleNamespace(messages=[]),
        user_text="hi", character=_Character("Lilith"), lock=None,
    )
    assert out == (None, None)


def test_run_persona_lane_turn_fails_open_on_unexpected_exception(monkeypatch):
    """Any surprise inside the lane glue (not just inside run_persona_turn
    itself) must degrade to (None, None), never raise — Mode C is never
    allowed to produce a dead turn."""
    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    class _BoomCharacter:
        name = "Lilith"

        def character_block(self):
            raise RuntimeError("character sheet is corrupt")

    out = _run_persona_lane_turn(
        client=object(), jaeger_agent=SimpleNamespace(messages=[]),
        user_text="hi", character=_BoomCharacter(), lock=None,
    )
    assert out == (None, None)


def test_run_persona_lane_turn_drives_perform_task_via_drive_one_turn(monkeypatch):
    """perform_task must call drive_one_turn on the SAME jaeger_agent
    under the SAME lock discipline as the plain path — not re-enter
    _run_turn_via_jaeger_agent (recursion is structurally impossible:
    there is no such call in this closure at all)."""
    import jaeger_ai.main as main_mod

    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    calls: list[tuple[object, str]] = []

    def _fake_drive_one_turn(agent, text):
        calls.append((agent, text))
        return {
            "answer": "the raw clean-agent answer", "tool_activity": ["  ▸ get_time()"],
            "first_decision": {"tool": "get_time", "args": {}}, "elapsed_s": 0.01,
            "skipped": False, "halt_reason": None, "iterations": 2,
            "new_messages": [], "prompt_tokens": 10, "completion_tokens": 5,
            "ttft_s": 0.1,
        }

    monkeypatch.setattr(
        "jaeger_ai.agent.loop.runtime_bridge.drive_one_turn", _fake_drive_one_turn,
    )

    def _fake_run_persona_turn(client, user_text, *, character_block, agent_name,
                                history, perform_task):
        # Exercise perform_task exactly once, like a real delegated turn.
        raw = perform_task(user_text)
        return f"styled: {raw}"

    monkeypatch.setattr(
        "jaeger_ai.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
    )

    agent = SimpleNamespace(messages=[])
    persona_text, inner_result = _run_persona_lane_turn(
        client=object(), jaeger_agent=agent,
        user_text="what time is it?", character=_Character("Lilith"), lock=None,
    )
    assert persona_text == "styled: the raw clean-agent answer"
    assert inner_result is not None
    assert inner_result["answer"] == "the raw clean-agent answer"
    assert calls == [(agent, "what time is it?")]  # exactly one inner turn
    # A delegated turn's history bookkeeping is drive_one_turn's job (the
    # fake above doesn't touch agent.messages) — the glue must NOT
    # double-append on top of it.
    assert agent.messages == []


def test_run_persona_lane_turn_tool_free_has_no_inner_result(monkeypatch):
    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    def _fake_run_persona_turn(client, user_text, *, character_block, agent_name,
                                history, perform_task):
        return "an in-character answer, no delegation"

    monkeypatch.setattr(
        "jaeger_ai.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
    )

    agent = SimpleNamespace(messages=[])
    persona_text, inner_result = _run_persona_lane_turn(
        client=object(), jaeger_agent=agent,
        user_text="tell me a joke", character=_Character("Lilith"), lock=None,
    )
    assert persona_text == "an in-character answer, no delegation"
    assert inner_result is None  # the clean agent's loop never ran this turn
    # ... but the exchange is still recorded — a tool-free turn must not
    # silently vanish from session history (the next Mode-C turn's own
    # history read, and a later Mode A fallback, both depend on it).
    assert agent.messages == [
        {"role": "user", "content": "tell me a joke"},
        {"role": "assistant", "content": "an in-character answer, no delegation"},
    ]


def test_run_persona_lane_turn_reraises_when_drive_one_turn_raises_mid_delegation(monkeypatch):
    """CRITICAL regression: once perform_task has started drive_one_turn,
    a failure there must surface to the caller — the same failure UX a
    plain Mode-A turn hits at _run_turn_via_jaeger_agent's outer
    ``except Exception`` — rather than fall open into ``(None, None)``,
    which would make the Mode-C branch treat the turn as "never ran"
    and drive a SECOND, fresh drive_one_turn call for the same user
    turn. drive_one_turn must be called exactly ONCE and the exception
    must not be swallowed."""
    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    calls: list[tuple[object, str]] = []

    def _raising_drive_one_turn(agent, text):
        calls.append((agent, text))
        raise RuntimeError("model died mid-delegation")

    monkeypatch.setattr(
        "jaeger_ai.agent.loop.runtime_bridge.drive_one_turn", _raising_drive_one_turn,
    )

    def _fake_run_persona_turn(client, user_text, *, character_block, agent_name,
                                history, perform_task):
        return perform_task(user_text)  # propagate whatever perform_task raises

    monkeypatch.setattr(
        "jaeger_ai.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
    )

    agent = SimpleNamespace(messages=[])
    with pytest.raises(RuntimeError, match="model died mid-delegation"):
        _run_persona_lane_turn(
            client=object(), jaeger_agent=agent,
            user_text="what time is it?", character=_Character("Lilith"), lock=None,
        )
    assert calls == [(agent, "what time is it?")]  # exactly once — no re-run


def test_run_persona_lane_turn_pre_delegation_failure_still_falls_open(monkeypatch):
    """Companion to the re-raise test above: a failure BEFORE perform_task
    ever runs (attempted stays False) must still fall open to
    (None, None) — this is the existing invariant
    ``test_run_persona_lane_turn_fails_open_on_unexpected_exception``
    already pins; restated here beside the raising case so the two
    behaviours read as one deliberate contract, not a coincidence."""
    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    class _BoomCharacter:
        name = "Lilith"

        def character_block(self):
            raise RuntimeError("character sheet is corrupt")

    out = _run_persona_lane_turn(
        client=object(), jaeger_agent=SimpleNamespace(messages=[]),
        user_text="hi", character=_BoomCharacter(), lock=None,
    )
    assert out == (None, None)


def test_run_persona_lane_turn_repairs_delegated_history_to_real_exchange(monkeypatch):
    """IMPORTANT regression: JaegerAgent.run_turn (inside drive_one_turn)
    appends the id's PARAPHRASED request as the user turn and the raw,
    unstyled answer as the assistant turn — neither is what the user
    actually exchanged. After a successful delegated turn, the glue
    must rewrite those two entries to the real ``user_text`` and the
    real returned ``persona_text``, leaving any tool messages between
    them untouched."""
    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    def _fake_drive_one_turn(agent, text):
        # Mirrors JaegerAgent.run_turn's own bookkeeping shape: user
        # (paraphrase) -> assistant tool-call -> tool result -> final
        # assistant (raw) text.
        agent.messages.append({"role": "user", "content": text})
        agent.messages.append({
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "x", "name": "get_time", "arguments": {}}],
        })
        agent.messages.append({"role": "tool", "tool_call_id": "x", "content": "12:00"})
        agent.messages.append({"role": "assistant", "content": "The time is 12:00."})
        return {
            "answer": "The time is 12:00.", "tool_activity": ["  ▸ get_time()"],
            "first_decision": {"tool": "get_time", "args": {}}, "elapsed_s": 0.01,
            "skipped": False, "halt_reason": None, "iterations": 2,
            "new_messages": [], "prompt_tokens": 10, "completion_tokens": 5,
            "ttft_s": 0.1,
        }

    monkeypatch.setattr(
        "jaeger_ai.agent.loop.runtime_bridge.drive_one_turn", _fake_drive_one_turn,
    )

    def _fake_run_persona_turn(client, user_text, *, character_block, agent_name,
                                history, perform_task):
        raw = perform_task("what time is it? (id's paraphrase)")
        return f"Ah, it's 12:00, my dear — {raw}"

    monkeypatch.setattr(
        "jaeger_ai.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
    )

    agent = SimpleNamespace(messages=[])
    persona_text, inner_result = _run_persona_lane_turn(
        client=object(), jaeger_agent=agent,
        user_text="what time is it?", character=_Character("Lilith"), lock=None,
    )
    assert persona_text == "Ah, it's 12:00, my dear — The time is 12:00."
    # user entry repaired to what the user actually said, not the
    # id's paraphrase.
    assert agent.messages[0] == {"role": "user", "content": "what time is it?"}
    # tool call / tool result entries in between are untouched.
    assert agent.messages[1]["tool_calls"] == [{"id": "x", "name": "get_time", "arguments": {}}]
    assert agent.messages[2] == {"role": "tool", "tool_call_id": "x", "content": "12:00"}
    # final assistant entry repaired to what was actually returned.
    assert agent.messages[-1] == {"role": "assistant", "content": persona_text}


def test_run_persona_lane_turn_skips_compose_override_when_spoke_via_tool(monkeypatch):
    """MINOR: when the delegated turn's tool_activity shows
    ``text_to_speech`` ran, the id already spoke the RAW answer aloud
    this turn — showing the compose pass's restyled text would make
    what's displayed diverge from what was heard. The glue must
    override back to the inner turn's raw answer instead of the
    composed one."""
    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    def _fake_drive_one_turn(agent, text):
        return {
            "answer": "The time is 12:00.",
            "tool_activity": ["  ▸ text_to_speech(text='The time is 12:00.')"],
            "first_decision": {"tool": "text_to_speech", "args": {}}, "elapsed_s": 0.01,
            "skipped": False, "halt_reason": None, "iterations": 1,
            "new_messages": [], "prompt_tokens": 10, "completion_tokens": 5,
            "ttft_s": 0.1,
        }

    monkeypatch.setattr(
        "jaeger_ai.agent.loop.runtime_bridge.drive_one_turn", _fake_drive_one_turn,
    )

    def _fake_run_persona_turn(client, user_text, *, character_block, agent_name,
                                history, perform_task):
        raw = perform_task(user_text)
        return f"styled: {raw}"  # what compose WOULD have produced

    monkeypatch.setattr(
        "jaeger_ai.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
    )

    agent = SimpleNamespace(messages=[])
    persona_text, inner_result = _run_persona_lane_turn(
        client=object(), jaeger_agent=agent,
        user_text="what time is it?", character=_Character("Lilith"), lock=None,
    )
    assert persona_text == "The time is 12:00."  # raw, NOT "styled: ..."


def test_run_persona_lane_turn_composes_normally_when_no_speech_tool(monkeypatch):
    """Companion to the spoke-via-tool test: when no speech tool ran, the
    composed text is used unchanged (no regression on the ordinary
    delegated-and-composed path)."""
    class _BoomLayout:
        root = None
        identity_path = "/does/not/exist.yaml"

    _pipeline["layout"] = _BoomLayout()

    def _fake_drive_one_turn(agent, text):
        return {
            "answer": "The time is 12:00.", "tool_activity": ["  ▸ get_time()"],
            "first_decision": {"tool": "get_time", "args": {}}, "elapsed_s": 0.01,
            "skipped": False, "halt_reason": None, "iterations": 1,
            "new_messages": [], "prompt_tokens": 10, "completion_tokens": 5,
            "ttft_s": 0.1,
        }

    monkeypatch.setattr(
        "jaeger_ai.agent.loop.runtime_bridge.drive_one_turn", _fake_drive_one_turn,
    )

    def _fake_run_persona_turn(client, user_text, *, character_block, agent_name,
                                history, perform_task):
        raw = perform_task(user_text)
        return f"styled: {raw}"

    monkeypatch.setattr(
        "jaeger_ai.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
    )

    agent = SimpleNamespace(messages=[])
    persona_text, inner_result = _run_persona_lane_turn(
        client=object(), jaeger_agent=agent,
        user_text="what time is it?", character=_Character("Lilith"), lock=None,
    )
    assert persona_text == "styled: The time is 12:00."


# ── _persona_lane_aux_available: MINOR — the lane must never run its ──
# ── un-locked chats on the shared worker context ──────────────────────


def test_persona_lane_aux_available_true_when_aux_lane_up():
    client = SimpleNamespace(_aux_lane=lambda: object())
    assert _persona_lane_aux_available(client) is True


def test_persona_lane_aux_available_false_when_aux_ctx_zero_in_config():
    # Mirrors LlamaCppPythonClient._aux_lane(): ``model.aux_ctx: 0``
    # disables the lane, so it always returns None — never spawns a
    # second context.
    client = SimpleNamespace(_aux_lane=lambda: None)
    assert _persona_lane_aux_available(client) is False


def test_persona_lane_aux_available_false_when_aux_lane_raises():
    def _boom():
        raise RuntimeError("spawn failed")

    client = SimpleNamespace(_aux_lane=_boom)
    assert _persona_lane_aux_available(client) is False


def test_persona_lane_aux_available_true_for_clients_without_aux_lane():
    # MLX / external HTTP clients have no aux-context split at all — no
    # shared-worker-context hazard, so the gate never blocks them.
    client = SimpleNamespace()
    assert _persona_lane_aux_available(client) is True


# ── _spoke_via_tool: shared by the voice loop and the Mode-C guard ───


def test_spoke_via_tool_true_when_text_to_speech_ran():
    assert _spoke_via_tool(["  ▸ text_to_speech(text='hi')"]) is True


def test_spoke_via_tool_true_for_legacy_emoji_marker():
    assert _spoke_via_tool(["🔊 spoke: hi"]) is True


def test_spoke_via_tool_false_when_no_speech_tool_ran():
    assert _spoke_via_tool(["  ▸ get_time()"]) is False


def test_spoke_via_tool_false_for_empty_activity():
    assert _spoke_via_tool([]) is False


# ── _persona_lane_turn_result: dict shape drive_one_turn's callers expect ──


def test_persona_lane_turn_result_tool_free_synthesizes_empty_bookkeeping():
    import time
    started = time.perf_counter()
    out = _persona_lane_turn_result("in character answer", None, started=started)
    assert out["answer"] == "in character answer"
    assert out["tool_activity"] == []
    assert out["first_decision"] is None
    assert out["skipped"] is False
    assert out["halt_reason"] is None
    assert out["iterations"] == 0
    assert out["elapsed_s"] >= 0.0


def test_persona_lane_turn_result_delegated_carries_inner_bookkeeping():
    import time
    started = time.perf_counter()
    inner = {
        "answer": "raw answer", "tool_activity": ["  ▸ get_time()"],
        "first_decision": {"tool": "get_time", "args": {}}, "elapsed_s": 999.0,
        "skipped": True, "halt_reason": None, "iterations": 2,
        "new_messages": [], "prompt_tokens": 10, "completion_tokens": 5,
        "ttft_s": 0.1,
    }
    out = _persona_lane_turn_result("styled answer", inner, started=started)
    assert out["answer"] == "styled answer"  # persona text wins, not the raw inner answer
    assert out["tool_activity"] == inner["tool_activity"]
    assert out["first_decision"] == inner["first_decision"]
    assert out["iterations"] == 2
    assert out["skipped"] is False  # never treated as a deterministic skip-final
    assert out["elapsed_s"] != 999.0  # recomputed from the turn-level clock, not the inner call's


# ── _run_turn_via_jaeger_agent: mode=persona_last default-off pin ───


class _FakeExternalClient:
    """Duck-types ``core.external_model.ExternalModelClient`` — carries
    an ``.ext`` config object plus a resolved API key. Mirrors
    test_runtime_bridge.py's fake; adapter selection never reaches a
    real network call because ``drive_one_turn`` is monkeypatched
    below."""

    def __init__(self) -> None:
        self.ext = SimpleNamespace(
            provider="anthropic", model="test-model",
            base_url="https://example.test/v1", timeout_s=30.0,
        )
        self._api_key = "fake-key"


def test_run_turn_via_jaeger_agent_persona_last_mode_runs_once_no_lane(
    monkeypatch, tmp_path,
):
    """Behavioral pin: with persona.mode="persona_last" (explicit —
    persona_first is now the config default), a turn through the FULL
    _run_turn_via_jaeger_agent must call drive_one_turn exactly once, apply
    the persona output filter (Station 3) to the answer, and never touch
    the Mode-C lane (_run_persona_lane_turn) at all — the Mode-C branch
    condition must short-circuit on ``_persona_mode() != "persona_first"``
    before it reaches ``_persona_lane_aux_available`` or the lane glue."""
    import jaeger_ai.main as main_mod
    from jaeger_ai.agent import tools as agent_tools

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    agent_tools.bind(layout)  # jaeger_tools._audit needs a bound layout
    config = Config(
        instance_name="t", model=ModelConfig(model_path="/dev/null"),
        skills=SkillsConfig(run_smoke_tests=False),
        persona=PersonaConfig(mode="persona_last"),  # explicit — no longer the default
    )
    monkeypatch.setitem(_pipeline, "layout", layout)
    monkeypatch.setitem(_pipeline, "config", config)
    monkeypatch.setitem(_pipeline, "client", None)
    monkeypatch.setitem(_pipeline, "llm_lock", None)
    monkeypatch.setitem(_pipeline, "thinking_runner", None)
    _agent_cache.clear()
    _jaeger_agents_by_session.clear()

    client = _FakeExternalClient()

    drive_calls: list[tuple[object, str]] = []

    def _fake_drive_one_turn(agent, text):
        drive_calls.append((agent, text))
        return {
            "answer": "the plain agent answer", "tool_activity": [],
            "first_decision": None, "elapsed_s": 0.01, "skipped": False,
            "halt_reason": None, "iterations": 1, "new_messages": [],
            "prompt_tokens": 0, "completion_tokens": 0, "ttft_s": 0.0,
        }

    monkeypatch.setattr(
        "jaeger_ai.agent.loop.runtime_bridge.drive_one_turn", _fake_drive_one_turn,
    )

    filter_calls: list[str] = []

    def _fake_apply_persona_filter(answer: str) -> str:
        filter_calls.append(answer)
        return f"FILTERED: {answer}"

    monkeypatch.setattr(main_mod, "_apply_persona_filter", _fake_apply_persona_filter)

    lane_calls: list[str] = []

    def _fake_run_persona_lane_turn(client, jaeger_agent, user_text, character, lock):
        lane_calls.append(user_text)
        return None, None

    monkeypatch.setattr(
        main_mod, "_run_persona_lane_turn", _fake_run_persona_lane_turn,
    )

    try:
        result = _run_turn_via_jaeger_agent(
            client, "hello there", session_key="test-output-filter-session",
        )
    finally:
        _agent_cache.clear()
        _jaeger_agents_by_session.pop("test-output-filter-session", None)

    assert drive_calls != []
    assert len(drive_calls) == 1  # drive_one_turn called exactly once
    assert drive_calls[0][1] == "hello there"
    assert filter_calls == ["the plain agent answer"]  # Station 3 applied
    assert result["text"] == "FILTERED: the plain agent answer"
    assert lane_calls == []  # Mode-C lane never invoked in persona_last mode


def test_run_turn_via_jaeger_agent_persona_first_default_no_character_falls_safe(
    monkeypatch, tmp_path,
):
    """Fail-safe pin (persona_first is now the config DEFAULT): an instance
    with NO active character must behave EXACTLY like persona_last — the
    branch's own ``if character is not None`` guard (main.py, inside
    ``_run_turn_via_jaeger_agent``) is what makes this safe, verified here
    end to end rather than trusted by inspection. drive_one_turn runs
    exactly once, the Mode-C lane is never invoked (no closure is even
    built), and Station 3's output filter — a no-op without a character —
    leaves the answer untouched."""
    import jaeger_ai.main as main_mod
    import jaeger_ai.personality.character as character_mod
    from jaeger_ai.agent import tools as agent_tools

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    agent_tools.bind(layout)  # jaeger_tools._audit needs a bound layout
    config = Config(
        instance_name="t", model=ModelConfig(model_path="/dev/null"),
        skills=SkillsConfig(run_smoke_tests=False),
        persona=PersonaConfig(),  # mode="persona_first" — today's default
    )
    monkeypatch.setitem(_pipeline, "layout", layout)
    monkeypatch.setitem(_pipeline, "config", config)
    monkeypatch.setitem(_pipeline, "client", None)
    monkeypatch.setitem(_pipeline, "llm_lock", None)
    monkeypatch.setitem(_pipeline, "thinking_runner", None)
    # Genuinely no character (active_character_id() otherwise always
    # resolves to a default id — see persona_eval.py's `_set_character`
    # for the same pattern).
    monkeypatch.setattr(character_mod, "active_character", lambda root: None)
    _agent_cache.clear()
    _jaeger_agents_by_session.clear()

    client = _FakeExternalClient()
    # aux lane reports available so the ONLY thing stopping the lane is
    # the character check, not this precondition.
    monkeypatch.setattr(main_mod, "_persona_lane_aux_available", lambda client: True)

    drive_calls: list[tuple[object, str]] = []

    def _fake_drive_one_turn(agent, text):
        drive_calls.append((agent, text))
        return {
            "answer": "the plain agent answer", "tool_activity": [],
            "first_decision": None, "elapsed_s": 0.01, "skipped": False,
            "halt_reason": None, "iterations": 1, "new_messages": [],
            "prompt_tokens": 0, "completion_tokens": 0, "ttft_s": 0.0,
        }

    monkeypatch.setattr(
        "jaeger_ai.agent.loop.runtime_bridge.drive_one_turn", _fake_drive_one_turn,
    )

    filter_calls: list[str] = []

    def _fake_apply_persona_filter(answer: str) -> str:
        filter_calls.append(answer)
        return f"FILTERED: {answer}"

    monkeypatch.setattr(main_mod, "_apply_persona_filter", _fake_apply_persona_filter)

    lane_calls: list[str] = []

    def _fake_run_persona_lane_turn(client, jaeger_agent, user_text, character, lock):
        lane_calls.append(user_text)
        return None, None

    monkeypatch.setattr(
        main_mod, "_run_persona_lane_turn", _fake_run_persona_lane_turn,
    )

    try:
        result = _run_turn_via_jaeger_agent(
            client, "hello there", session_key="test-persona-first-no-character",
        )
    finally:
        _agent_cache.clear()
        _jaeger_agents_by_session.pop("test-persona-first-no-character", None)

    assert drive_calls != []
    assert len(drive_calls) == 1  # drive_one_turn called exactly once
    assert drive_calls[0][1] == "hello there"
    assert filter_calls == ["the plain agent answer"]  # Station 3 still runs (no-ops without a character)
    assert result["text"] == "FILTERED: the plain agent answer"
    assert lane_calls == []  # lane closure never built — the character-None guard short-circuits first
