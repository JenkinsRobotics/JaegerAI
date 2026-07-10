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
including the regression pin that mode="output_filter" (today's default)
never reaches the Mode-C branch and the structural invariant that
``perform_task`` (== drive_one_turn) never runs twice for one turn.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_os.core.instance.schemas import Config, PersonaConfig
from jaeger_os.main import (
    _pipeline,
    _persona_identity_block,
    _persona_lane_turn_result,
    _persona_mode,
    _run_persona_lane_turn,
)


@pytest.fixture(autouse=True)
def _reset_pipeline_config():
    saved = _pipeline.get("config")
    yield
    _pipeline["config"] = saved


# ── config default ────────────────────────────────────────────────────


def test_persona_config_mode_defaults_to_output_filter():
    pc = PersonaConfig()
    assert pc.mode == "output_filter"
    assert Config.model_fields["persona"].default_factory is PersonaConfig


def test_persona_config_rejects_frontend_mode():
    """Mode B (frontend) is design-only until built — no spec ahead of
    code. Only output_filter / agent_tool are valid today."""
    with pytest.raises(Exception):
        PersonaConfig(mode="frontend")


# ── _persona_mode: config + env override, both directions ───────────


def test_persona_mode_reads_config_default():
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig())
    assert _persona_mode() == "output_filter"


def test_persona_mode_reads_config_agent_tool():
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig(mode="agent_tool"))
    assert _persona_mode() == "agent_tool"


def test_persona_mode_missing_config_falls_back_to_output_filter():
    _pipeline["config"] = None
    assert _persona_mode() == "output_filter"
    _pipeline["config"] = SimpleNamespace()  # no .persona attr at all
    assert _persona_mode() == "output_filter"


def test_persona_mode_env_override_forces_agent_tool_on(monkeypatch):
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig())  # default output_filter
    monkeypatch.setenv("JAEGER_PERSONA_MODE", "agent_tool")
    assert _persona_mode() == "agent_tool"


def test_persona_mode_env_override_forces_output_filter_off(monkeypatch):
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig(mode="agent_tool"))
    monkeypatch.setenv("JAEGER_PERSONA_MODE", "output_filter")
    assert _persona_mode() == "output_filter"


def test_persona_mode_env_garbage_value_ignored(monkeypatch):
    _pipeline["config"] = SimpleNamespace(persona=PersonaConfig(mode="agent_tool"))
    monkeypatch.setenv("JAEGER_PERSONA_MODE", "not_a_real_mode")
    assert _persona_mode() == "agent_tool"  # falls back to config, not a crash


# ── shared identity framing (Station 3 + Mode C reuse the same text) ──


class _Character:
    def __init__(self, name: str, block: str = "## My voice"):
        self.name = name
        self._block = block

    def character_block(self) -> str:
        return self._block


def test_identity_block_prepends_framing_when_names_differ():
    block = _persona_identity_block("Ted", _Character("Lilith"))
    assert block.startswith("Your name is Ted.")
    assert "Lilith" in block
    assert "never present yourself as Lilith" in block
    assert block.endswith("## My voice")


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
    import jaeger_os.main as main_mod

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
        "jaeger_os.agent.loop.runtime_bridge.drive_one_turn", _fake_drive_one_turn,
    )

    def _fake_run_persona_turn(client, user_text, *, character_block, agent_name,
                                history, perform_task):
        # Exercise perform_task exactly once, like a real delegated turn.
        raw = perform_task(user_text)
        return f"styled: {raw}"

    monkeypatch.setattr(
        "jaeger_os.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
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
        "jaeger_os.agent.prompts.persona_lane.run_persona_turn", _fake_run_persona_turn,
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
