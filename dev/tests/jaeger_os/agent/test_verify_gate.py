"""Station-2 verify gate — the soft exit-door checks.

Covers the two failure signatures the gate exists for (PLAN-halt,
claim-vs-action), the false-positive guards that keep it SOFT, and the
loop wiring (one nudge max, nudge never persists, kill switch).
Design: dev/docs/agentic_runners.md.
"""

from __future__ import annotations

import pytest

from jaeger_os.agent.loop.verify_gate import (
    CLAIM_NUDGE,
    PLAN_NUDGE,
    gate_enabled,
    verify_final,
)

TOOLS = {"execute_code", "write_file", "board_add", "remember",
         "schedule_prompt", "get_time", "use_skill", "web_search"}


# ── check A: PLAN-halt ─────────────────────────────────────────────


def test_plan_naming_a_real_tool_is_nudged():
    text = 'PLAN: execute_code("print(") -> report the SyntaxError'
    assert verify_final(text, set(), TOOLS) == PLAN_NUDGE


def test_lowercase_plan_line_mid_text_is_nudged():
    text = "Okay.\nplan: write_file(path='probe.txt', content='hi')"
    assert verify_final(text, set(), TOOLS) == PLAN_NUDGE


def test_plan_prose_without_a_tool_call_shape_passes():
    """'Here's the plan, shall I proceed?' is a legitimate final answer —
    only a plan that NAMES a real tool call it never made is a halt."""
    text = ("Plan: first I'd outline the doc, then draft each section. "
            "Want me to proceed?")
    assert verify_final(text, set(), TOOLS) is None


def test_plan_with_unknown_function_name_passes():
    text = "Plan: refactor helper() and cleanup() in the module."
    assert verify_final(text, set(), TOOLS) is None


# ── check B: claim-vs-action ───────────────────────────────────────


def test_claimed_note_with_no_recording_tool_is_nudged():
    # the exact 26B wf_triage failure: "I have noted them" — nothing ran
    text = "4183. For A and C, I have noted them for later."
    assert verify_final(text, {"calculate"}, TOOLS) == CLAIM_NUDGE


def test_claimed_note_with_board_add_success_passes():
    text = "4183. I have noted A and C on the board."
    assert verify_final(text, {"calculate", "board_add"}, TOOLS) is None


def test_claimed_save_without_write_is_nudged():
    text = "Done — I've saved the summary to notes.txt."
    assert verify_final(text, {"web_search"}, TOOLS) == CLAIM_NUDGE


def test_claimed_save_with_write_success_passes():
    text = "Done — I've saved the summary to notes.txt."
    assert verify_final(text, {"write_file"}, TOOLS) is None


def test_claimed_schedule_and_memory_families():
    assert verify_final("I've scheduled the reminder.", set(), TOOLS) == CLAIM_NUDGE
    assert verify_final("I've scheduled it.", {"schedule_prompt"}, TOOLS) is None
    assert verify_final("I've remembered your preference.", set(), TOOLS) == CLAIM_NUDGE
    assert verify_final("I've remembered it.", {"remember"}, TOOLS) is None


def test_non_mutation_first_person_passes():
    """The tight-verb guard: analysis/thinking claims never trip."""
    for text in ("I've analyzed the options and recommend B.",
                 "I have reviewed the code carefully.",
                 "I've considered both approaches."):
        assert verify_final(text, set(), TOOLS) is None


def test_third_person_and_passive_mentions_pass():
    for text in ("The file was saved by the previous run.",
                 "Your notes are stored in memory/notes.md.",
                 "As noted above, the value is 42."):
        assert verify_final(text, set(), TOOLS) is None


def test_halt_notes_and_empty_pass_through():
    assert verify_final("", set(), TOOLS) is None
    assert verify_final("[halted: hit max iterations]", set(), TOOLS) is None


def test_plan_beats_claim_when_both_present():
    text = "I've noted it.\nPLAN: board_add(title='x')"
    assert verify_final(text, set(), TOOLS) == PLAN_NUDGE


# ── kill switch ────────────────────────────────────────────────────


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("JAEGER_VERIFY_GATE", "0")
    assert gate_enabled() is False
    monkeypatch.setenv("JAEGER_VERIFY_GATE", "1")
    assert gate_enabled() is True
    monkeypatch.delenv("JAEGER_VERIFY_GATE")
    assert gate_enabled() is True     # default ON


# ── loop wiring: one nudge max, nudge never persists ───────────────


from jaeger_os.agent.adapters.base import ProviderAdapter


class _ScriptedAdapter(ProviderAdapter):
    """Returns scripted assistant messages in order (mirrors the
    test_hermes_adoption pattern)."""

    name = "scripted"

    def __init__(self, script):
        self._script = list(script)
        self.call_count = 0

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        self.call_count += 1
        if not self._script:
            raise RuntimeError("scripted adapter ran out of responses")
        return self._script.pop(0)

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


class _NamedTool:
    """Name-only stand-in so the gate's registered-tool check matches."""

    def __init__(self, name: str) -> None:
        self.name = name


def _agent(replies):
    from jaeger_os.agent.loop.jaeger_agent import JaegerAgent
    agent = JaegerAgent(adapter=_ScriptedAdapter(replies))
    agent._all_tools = [_NamedTool("execute_code")]
    return agent


def test_loop_nudges_plan_then_accepts_the_followup():
    agent = _agent([
        {"role": "assistant", "content": "PLAN: execute_code('1+1')"},
        {"role": "assistant", "content": "The answer is 2."},
    ])
    out = agent.run_turn("compute 1+1")
    assert out == "The answer is 2."
    # the synthetic nudge must NOT persist in the turn history
    assert all("SYSTEM NUDGE" not in str(m.get("content", ""))
               for m in agent.messages)


def test_loop_accepts_answer_if_model_persists_after_one_nudge():
    """SOFT guarantee: the gate never loops — a second plan-only reply is
    accepted as the final answer (one nudge max)."""
    agent = _agent([
        {"role": "assistant", "content": "PLAN: execute_code('1+1')"},
        {"role": "assistant", "content": "PLAN: execute_code('1+1')"},
    ])
    out = agent.run_turn("compute 1+1")
    assert out.startswith("PLAN:")          # accepted, not blocked
    assert agent.last_iteration_count == 2  # exactly one extra iteration


def test_loop_gate_disabled_by_env(monkeypatch):
    monkeypatch.setenv("JAEGER_VERIFY_GATE", "0")
    agent = _agent([
        {"role": "assistant", "content": "PLAN: execute_code('1+1')"},
    ])
    out = agent.run_turn("compute 1+1")
    assert out.startswith("PLAN:")
    assert agent.last_iteration_count == 1  # no nudge at all
