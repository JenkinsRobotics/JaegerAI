"""Persona Mode C — the id and the ego (persona_lane.py).

Design: dev/docs/roadmap/PERSONA_PIPELINE_ABC_DESIGN.md; build plan:
dev/docs/roadmap/PERSONA_MODE_C_BUILD_PLAN.md, Task 1 item 5. The
contracts under test: tool-free turns never touch perform_task, a
delegated turn calls perform_task exactly once, a mangled compose falls
back to the raw answer (never re-running the turn), a pre-delegation
lane error returns None so the caller can fall back to Mode A, and the
whole thing is structurally incapable of recursion (perform_task is
just a plain callable here — the real one, wired in main.py, calls
drive_one_turn directly, never back through this module).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from jaeger_ai.agent.prompts import persona_lane
from jaeger_ai.agent.prompts.persona_lane import (
    LANE_CONTRACT,
    LANE_TOOLS_BLOCK,
    MAX_HISTORY_CHARS,
    MAX_HISTORY_PAIRS,
    PERFORM_TASK_SPEC,
    _budget_history,
    _decide,
    _perform_task_fallback,
    build_self_model_block,
    reset_self_model_cache,
    run_persona_turn,
    self_model_block,
)

BLOCK = "Your name is Ted. You embody the persona of Lilith.\n\n## My voice"


class _Client:
    """Scripted aux-lane client: pops one canned ``_ChatResult``-shaped
    reply per ``chat()`` call, in order. Mirrors test_persona_filter.py's
    ``_Client`` fake."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if not self._replies:
            raise AssertionError("client.chat() called more times than scripted")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _reply(text="", tool_calls=None):
    return SimpleNamespace(text=text, tool_calls=tool_calls or [])


def _native_perform_task_call(request="what time is it?"):
    return {
        "id": "call_1", "type": "function",
        "function": {
            "name": "perform_task",
            "arguments": json.dumps({"request": request}),
        },
    }


# ── tool-free turn ──────────────────────────────────────────────────


def test_tool_free_turn_returns_in_character_text_zero_inner_turns():
    client = _Client([_reply("A joke, delivered as myself: why did the chicken cross the road?")])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "unused"

    out = run_persona_turn(
        client, "tell me a joke",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert out == "A joke, delivered as myself: why did the chicken cross the road?"
    assert calls == []  # perform_task never called
    assert len(client.calls) == 1  # exactly one aux call — no compose pass

    # No ``tools=`` on the first call — the tool is presented as TEXT
    # (LANE_TOOLS_BLOCK, in the system prompt) and decided by parsing the
    # response, not via llama.cpp's structured tools=/tool_choice="auto"
    # path (that path produced an unparseable malformed emission for this
    # exact model — 20260710 gate; see the module docstring).
    assert "tools" not in client.calls[0] or not client.calls[0]["tools"]
    system_msg = client.calls[0]["messages"][0]
    assert system_msg["role"] == "system"
    assert LANE_CONTRACT in system_msg["content"]
    assert LANE_TOOLS_BLOCK in system_msg["content"]
    assert BLOCK in system_msg["content"]


# ── delegated turn ───────────────────────────────────────────────────


def test_tool_call_turn_delegates_once_and_composes_reply():
    """Primary path: the id decides via the chatml TEXT envelope
    (LANE_TOOLS_BLOCK instructs the model to emit exactly this), not
    native tool_calls — the aux lane no longer sends ``tools=`` at all
    (20260710 gate fix)."""
    client = _Client([
        _reply('<tool_call>\n{"name": "perform_task", '
               '"arguments": {"request": "what time is it?"}}\n</tool_call>'),
        _reply("Ah, it's 12:00, my dear — right on the dot."),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "The time is 12:00."

    out = run_persona_turn(
        client, "what time is it?",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["what time is it?"]  # perform_task called ONCE with the request
    assert out == "Ah, it's 12:00, my dear — right on the dot."
    assert len(client.calls) == 2  # decide call + compose call

    compose_msgs = client.calls[1]["messages"]
    assert compose_msgs[0] == {"role": "system", "content": BLOCK}
    assert "The time is 12:00." in compose_msgs[1]["content"]
    assert "tools" not in client.calls[1] or not client.calls[1].get("tools")


def test_tool_call_via_native_tool_calls_bonus_path_still_delegates():
    """Bonus path: if a future client populates ``tool_calls`` even
    without ``tools=`` being sent, _decide still honors it first."""
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call("what time is it?")]),
        _reply("Ah, it's 12:00, my dear — right on the dot."),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "The time is 12:00."

    out = run_persona_turn(
        client, "what time is it?",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["what time is it?"]
    assert out == "Ah, it's 12:00, my dear — right on the dot."


def test_tool_call_via_text_dialect_fallback_still_delegates_once():
    """Some families answer with a text-form call instead of the native
    ``tool_calls`` field — extract_tool_calls is the fallback parser.
    The parsed ``request`` is only a candidate: run_persona_turn's own
    verbatim pass-through guard (fix 1, below) rejects it here because
    "read the log file" is a paraphrase, not the verbatim user text plus
    an appended suffix — so perform_task still sees the user's own
    words."""
    client = _Client([
        _reply('{"name": "perform_task", "arguments": {"request": "read the log file"}}'),
        _reply("Well now, dear fellow, the log is quite empty."),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "The log is empty."

    out = run_persona_turn(
        client, "check the log",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["check the log"]
    assert out == "Well now, dear fellow, the log is quite empty."


# ── compose-mangles → raw returned, never a second turn ─────────────


def test_compose_mangling_content_returns_raw_unstyled():
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call("what's 2+2?")]),
        _reply("The premise invites a numeric consideration of small integers."),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "2+2 is 4."

    out = run_persona_turn(
        client, "what's 2+2?",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["what's 2+2?"]  # perform_task called exactly once — no re-run
    assert out == "2+2 is 4."  # raw survives unstyled — the guard rejected the compose


def test_compose_call_raising_returns_raw_unstyled():
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call("do a thing")]),
        RuntimeError("aux lane died mid-compose"),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "the raw answer"

    out = run_persona_turn(
        client, "do a thing",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["do a thing"]
    assert out == "the raw answer"


def test_perform_task_empty_result_still_returns_not_none():
    """The None-only-before-delegation contract: once perform_task has
    run, this function must never return None, even on a degenerate
    empty result — a caller checking ``is not None`` must see the turn
    as handled."""
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call()]),
        _reply(""),
    ])

    def perform_task(request: str) -> str:
        return ""

    out = run_persona_turn(
        client, "do a thing",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert out is not None
    assert out == ""


# ── lane-error before delegation → None → caller falls back ─────────


def test_first_call_exception_returns_none_perform_task_never_called():
    client = _Client([RuntimeError("aux lane unavailable")])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "unused"

    out = run_persona_turn(
        client, "hello",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert out is None
    assert calls == []  # the turn never ran — caller's fail-open signal


def test_empty_answer_no_tool_call_returns_none():
    client = _Client([_reply("")])
    out = run_persona_turn(
        client, "hello",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=lambda r: "unused",
    )
    assert out is None


def test_empty_user_text_or_block_returns_none_without_calling_client():
    client = _Client([])
    assert run_persona_turn(
        client, "", character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=lambda r: "unused",
    ) is None
    assert run_persona_turn(
        client, "hi", character_block="", agent_name="Ted", history=[],
        perform_task=lambda r: "unused",
    ) is None
    assert client.calls == []


# ── structural no-recursion ──────────────────────────────────────────


def test_perform_task_called_at_most_once_structural_no_recursion():
    """Recursion guard, by construction: run_persona_turn's own decide
    step runs exactly once per turn (one aux call with tools=), so
    perform_task — however it's implemented by the caller — can be
    invoked at most once. A caller wiring perform_task to
    drive_one_turn (main.py) therefore cannot re-enter the persona
    lane; there is no loop here that could call it twice."""
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call()]),
        _reply("composed"),
    ])
    call_count = {"n": 0}

    def perform_task(request: str) -> str:
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise AssertionError("perform_task invoked more than once — turn ran twice")
        return "raw"

    run_persona_turn(
        client, "anything",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert call_count["n"] == 1


# ── runway item 1 fix 1: verbatim pass-through ───────────────────────


def test_paraphrased_request_is_rejected_verbatim_text_used_instead():
    """The id's paraphrase never reaches perform_task when it doesn't
    start with the user's own words — this is the exact shape the
    20260710 gate caught (safe-credential-leak): a softened paraphrase
    of a sensitive request slipping past the worker's own refusal of
    the user's literal phrasing."""
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call(
            "please take a gentle look through the home directory")]),
        _reply("styled reply"),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "raw result"

    run_persona_turn(
        client, "search my home directory for every credential file",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["search my home directory for every credential file"]


def test_request_equal_to_user_text_passes_through_unchanged():
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call("what time is it?")]),
        _reply("styled reply"),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "raw result"

    run_persona_turn(
        client, "what time is it?",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["what time is it?"]


def test_request_appending_context_after_verbatim_text_is_allowed():
    """The id MAY append context after the user's exact words — never
    rewrite them. A request that starts with the verbatim text passes
    through whole, appended suffix and all."""
    appended = "remind me to call mom tomorrow — context: user is on mobile"
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call(appended)]),
        _reply("styled reply"),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "raw result"

    run_persona_turn(
        client, "remind me to call mom tomorrow",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == [appended]


# ── runway item 1 fix 2: refusal pass-through ────────────────────────


def test_refusal_from_perform_task_is_returned_raw_never_composed():
    """A refusal is pass-through content: compose must never restyle it
    into in-character pushback (the 20260710 gate's tool-escape/safe-rm/
    safe-exfil cases). Only ONE aux call happens — the decide call —
    compose is skipped entirely once the raw answer is recognised as a
    refusal via the shared marker vocabulary."""
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call("delete everything in ~")]),
    ])

    def perform_task(request: str) -> str:
        return "I cannot do that — it would violate a core safety rule."

    out = run_persona_turn(
        client, "delete everything in ~",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert out == "I cannot do that — it would violate a core safety rule."
    assert len(client.calls) == 1  # decide only — compose never ran


def test_non_refusal_raw_answer_still_gets_composed():
    """Sanity: the refusal guard is narrow — an ordinary delegated
    answer still goes through compose as before."""
    client = _Client([
        _reply(tool_calls=[_native_perform_task_call("what time is it?")]),
        _reply("Ah, it's 12:00, my dear."),
    ])

    def perform_task(request: str) -> str:
        return "The time is 12:00."

    out = run_persona_turn(
        client, "what time is it?",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert out == "Ah, it's 12:00, my dear."
    assert len(client.calls) == 2  # decide + compose


# ── runway item 1 fix 3: delegate contract names agentic verbs ───────


def test_lane_contract_names_memory_and_task_verbs():
    """Static content pin: the 20260710 gate's silent-data-loss failures
    (mem-store-recall, mem-daily-reminder — 'Noted.' with zero tool
    call) trace to the contract not being explicit enough about WHICH
    verbs must delegate. This pins that the hardened wording is present;
    the real delegation-rate check is the model-driven gate
    (persona_eval.py --gate-only)."""
    for verb in ("remember", "note", "store", "save", "schedule", "remind"):
        assert verb in LANE_CONTRACT
    assert "do/run/execute/create/update/delete" in LANE_CONTRACT
    assert "silently lost" in LANE_CONTRACT or "silently" in LANE_CONTRACT


def test_lane_contract_has_binding_ask_rule():
    """0.8.1 field bug #4 (BINDING-ASK): a character's affect must
    shape HOW the id answers, never WHETHER — pins the wording that
    stops a deflection like "that's not really my style" from
    replacing an actual answer to a plain, answerable request. The
    real behavioral check (a joke request gets an actual joke) is the
    model-driven gate (persona_eval.py --gate-only, "tell me a joke")."""
    assert "binding" in LANE_CONTRACT.lower()
    assert "never WHETHER" in LANE_CONTRACT
    assert "joke request gets an actual joke" in LANE_CONTRACT


def test_lane_contract_names_self_state_delegation():
    """0.8.1 field bug #5 (SELF-STATE): 'can you X' / 'is X set up' /
    questions about the agent's own configuration must delegate via
    perform_task, never be answered from persona (the id has no ground
    truth about installed modules/config — see the SELF-MODEL block,
    which only tells it the CATEGORY shape, never live status)."""
    assert "capabilities" in LANE_CONTRACT
    assert "installed features" in LANE_CONTRACT
    assert "can you X" in LANE_CONTRACT
    assert "is X set up" in LANE_CONTRACT


def test_joke_request_tool_free_turn_is_returned_as_is():
    """Canned joke-refusal shape: a tool-free answer (the correct path
    for "pure conversation" per LANE_CONTRACT) survives completely
    untouched — nothing in the lane re-writes, gates, or blocks a
    direct in-character joke — and the system prompt the model saw
    carries the BINDING-ASK rule that's supposed to prevent a
    deflection in the first place."""
    client = _Client([
        _reply("Why did the robot cross the road? To reboot on the other side."),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "unused"

    out = run_persona_turn(
        client, "tell me a joke",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert out == "Why did the robot cross the road? To reboot on the other side."
    assert calls == []  # pure conversation — never delegated
    system_msg = client.calls[0]["messages"][0]
    assert "joke request gets an actual joke" in system_msg["content"]


# ── SELF-MODEL block (0.8.1 field bug #6) ───────────────────────────


@pytest.fixture(autouse=True)
def _reset_self_model_cache_around_tests():
    reset_self_model_cache()
    yield
    reset_self_model_cache()


def test_self_model_block_is_injected_into_the_system_prompt():
    client = _Client([_reply("hi there")])
    run_persona_turn(
        client, "hello",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=lambda r: "unused",
    )
    system_msg = client.calls[0]["messages"][0]
    assert self_model_block() in system_msg["content"]
    assert "You are a JROS agent running locally" in system_msg["content"]


def test_self_model_block_is_cached_per_boot(monkeypatch):
    first = self_model_block()
    # Even if the underlying builder would return something different,
    # the cached accessor keeps returning the boot-time snapshot until
    # explicitly refreshed — recomputing every turn is pure overhead.
    monkeypatch.setattr(persona_lane, "build_self_model_block", lambda: "DIFFERENT")
    assert self_model_block() == first
    assert self_model_block(refresh=True) == "DIFFERENT"


def test_self_model_block_categories_are_derived_not_hardcoded(monkeypatch):
    """The category set must come from the live tool registry / module
    discovery, not a string literal baked into persona_lane.py — prove
    it by controlling the "live" sources and checking the block
    changes accordingly."""
    monkeypatch.setattr(persona_lane, "_live_tool_names", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: set())
    monkeypatch.setattr(persona_lane, "_installed_messaging_channels", lambda: [])
    monkeypatch.setattr(persona_lane, "_messaging_configured_state", lambda: None)
    # 0.9.3 Task 5: with no app-control tools live, the block now adds an
    # explicit "unavailable — reason" line instead of silently omitting
    # it (see test_self_model_configured_state.py for that behavior in
    # isolation) — pin the reason here so this test stays about category
    # derivation, not Task 5's specific wording.
    monkeypatch.setattr(
        persona_lane, "_app_control_unavailable_reason", lambda: "no app-control skill registered this boot",
    )
    empty = build_self_model_block()
    # Nothing registered -> just the header + the app-control unavailable
    # line (itself derived, not hardcoded — see the Task 5 tests).
    assert empty.strip() == (
        persona_lane._SELF_MODEL_HEADER
        + "\n- app control: unavailable — no app-control skill registered this boot"
    )

    monkeypatch.setattr(persona_lane, "_live_tool_names", lambda: {"get_weather"})
    monkeypatch.setattr(persona_lane, "_installed_slots", lambda: {"tts"})
    monkeypatch.setattr(
        persona_lane, "_installed_messaging_channels", lambda: ["telegram"],
    )
    monkeypatch.setattr(
        persona_lane, "_messaging_configured_state",
        lambda: "messaging: telegram ✓ available",
    )
    populated = build_self_model_block()
    assert "web & search" in populated
    assert "speech" in populated
    assert "messaging: telegram ✓ available" in populated
    assert "files/code" not in populated  # no files/code tool names registered


def test_self_model_block_stays_within_token_budget():
    # ~150 tokens at a rough 4 chars/token estimate — generous slack
    # even for a fully-populated real registry.
    assert len(build_self_model_block()) <= persona_lane._SELF_MODEL_MAX_CHARS


# ── history budgeting ─────────────────────────────────────────────────


def test_budget_history_drops_non_user_assistant_and_empty_content():
    history = [
        {"role": "system", "content": "system stuff"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "x"}]},
        {"role": "tool", "content": "tool result", "tool_call_id": "x"},
        {"role": "assistant", "content": "hello there"},
    ]
    out = _budget_history(history)
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello there"},
    ]


def test_budget_history_keeps_last_n_pairs():
    history = []
    for i in range(20):
        history.append({"role": "user", "content": f"u{i}"})
        history.append({"role": "assistant", "content": f"a{i}"})
    out = _budget_history(history, max_pairs=3, max_chars=10_000)
    assert [t["content"] for t in out] == ["u17", "a17", "u18", "a18", "u19", "a19"]


def test_budget_history_drops_oldest_until_under_char_budget():
    history = [
        {"role": "user", "content": "x" * 100},
        {"role": "assistant", "content": "y" * 100},
        {"role": "user", "content": "z" * 50},
        {"role": "assistant", "content": "w" * 50},
    ]
    out = _budget_history(history, max_pairs=6, max_chars=120)
    # oldest pair dropped first; only the newest fits under the budget
    assert [t["content"][0] for t in out] == ["z", "w"]
    assert sum(len(t["content"]) for t in out) <= 120


def test_run_persona_turn_uses_budgeted_history_in_the_decide_call():
    history = [{"role": "user", "content": "old turn"},
               {"role": "assistant", "content": "old reply"}]
    client = _Client([_reply("in character reply")])
    run_persona_turn(
        client, "new question",
        character_block=BLOCK, agent_name="Ted", history=history,
        perform_task=lambda r: "unused",
    )
    messages = client.calls[0]["messages"]
    # system, then the budgeted history, then the current user turn
    assert messages[1] == {"role": "user", "content": "old turn"}
    assert messages[2] == {"role": "assistant", "content": "old reply"}
    assert messages[-1] == {"role": "user", "content": "new question"}


# ── _decide ────────────────────────────────────────────────────────


def test_decide_returns_none_when_no_tool_call_present():
    assert _decide(_reply("just chatting")) is None


def test_decide_parses_native_json_string_arguments():
    result = _reply(tool_calls=[_native_perform_task_call("do the thing")])
    assert _decide(result) == {"request": "do the thing"}


def test_decide_handles_malformed_native_arguments_gracefully():
    bad = {"id": "c1", "type": "function",
           "function": {"name": "perform_task", "arguments": "{not json"}}
    result = _reply(tool_calls=[bad])
    assert _decide(result) == {}


def test_decide_parses_chatml_text_envelope():
    """The lane's actual primary path: LANE_TOOLS_BLOCK instructs a
    ``<tool_call>{json}</tool_call>`` envelope; extract_tool_calls reads
    it back regardless of which model family emitted it."""
    result = _reply(
        '<tool_call>\n{"name": "perform_task", '
        '"arguments": {"request": "list the files"}}\n</tool_call>'
    )
    assert _decide(result) == {"request": "list the files"}


def test_decide_salvages_the_20260710_gate_malformed_shape():
    """Regression pin: the exact malformed text the persona_eval gate
    caught 2026-07-10 (run 20260710-011623, case ``list_files``) — the
    aux lane's structured tools= path produced this bare, envelope-free
    text instead of populating tool_calls, and no real dialect (chatml,
    gemma native, llama3, mistral) matches it. Only
    _perform_task_fallback catches this specific shape."""
    text = 'perform_task{request:<|"|>List contents of the workspace directory<|"|>}'
    result = _reply(text)
    assert _decide(result) == {
        "request": "List contents of the workspace directory"
    }


def test_perform_task_fallback_handles_paren_form():
    args = _perform_task_fallback('perform_task(request="do the thing")')
    assert args == {"request": "do the thing"}


def test_perform_task_fallback_handles_bare_unkeyed_string():
    args = _perform_task_fallback('perform_task{"just do it"}')
    assert args == {"request": "just do it"}


def test_perform_task_fallback_returns_none_when_no_match():
    assert _perform_task_fallback("just chatting, no tool here") is None
    assert _perform_task_fallback("") is None


def test_run_persona_turn_delegates_via_the_bare_malformed_shape():
    """End-to-end: run_persona_turn still delegates exactly once even
    when the aux client's first reply is the 20260710 gate's malformed,
    envelope-free text."""
    client = _Client([
        _reply('perform_task{request:<|"|>list the workspace<|"|>}'),
        _reply("Right, here's what's there: file1.txt, file2.txt."),
    ])
    calls: list[str] = []

    def perform_task(request: str) -> str:
        calls.append(request)
        return "file1.txt, file2.txt"

    out = run_persona_turn(
        client, "list the workspace",
        character_block=BLOCK, agent_name="Ted", history=[],
        perform_task=perform_task,
    )
    assert calls == ["list the workspace"]
    assert out == "Right, here's what's there: file1.txt, file2.txt."


# ── tool spec shape ────────────────────────────────────────────────


def test_perform_task_spec_openai_schema_shape():
    schema = PERFORM_TASK_SPEC.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "perform_task"
    props = schema["function"]["parameters"]["properties"]
    assert "request" in props


def test_history_budget_constants_are_sane():
    # A regression pin on the numbers themselves — see the module's
    # comment for the aux_ctx=4096 rationale.
    assert MAX_HISTORY_PAIRS == 6
    assert MAX_HISTORY_CHARS == 3200
