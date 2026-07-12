"""Pre-flight context-window guardrail.

The bug we're guarding against: the assembled prompt grows past the
server's loaded context window and the call hard-fails with
``Requested tokens (X) exceed context window of (Y)``. JROS's reactive
guardrail (``cloud_errors.friendly_error_text``) catches it *after* the
fact and prints a helpful message — but the turn still failed.

This file pins the *preventive* layer:

  - A char-based token estimator, conservative by default (overshoots
    rather than undershoots — better to trim one turn too many than
    to overflow by one token).
  - A budget that subtracts a reserve for the completion + a safety
    margin from the ctx window.
  - A trimmer that drops oldest history until the prompt fits, while
    preserving: the system prompt, the most recent user turn, and any
    in-flight assistant/tool messages from the current turn.
  - A typed ``ContextOverflow`` raised when even max trimming doesn't
    fit — caller renders an actionable error.
  - A separate per-tool-result truncator so a 5 MB ``run_shell`` dump
    can't poison the next turn.
"""

from __future__ import annotations

import pytest

from jaeger_ai.agent.util.context_guard import (
    ContextBudget,
    ContextGuard,
    ContextOverflow,
)


# ── token estimator ────────────────────────────────────────────────


def test_estimator_returns_zero_for_empty_text():
    g = ContextGuard(ContextBudget())
    assert g.estimate_text_tokens("") == 0


def test_estimator_scales_roughly_linearly_with_length():
    """The char-heuristic doesn't have to be exact — but it must scale.
    1000 chars should produce ~10x what 100 chars produces."""
    g = ContextGuard(ContextBudget(chars_per_token=3.0))
    small = g.estimate_text_tokens("x" * 100)
    big = g.estimate_text_tokens("x" * 1000)
    assert 8 * small <= big <= 12 * small


def test_estimator_is_conservative_by_default():
    """Default ratio of 3.0 chars/token *overestimates* English text
    (real ratio is closer to 3.5–4.0). Overshooting is the right bias:
    we'd rather trim one extra turn than overflow by one token."""
    g = ContextGuard(ContextBudget())
    # Pure ASCII English — real tokenizers give ~25 tokens for this 120-char
    # sentence. Our estimator should be at least that high.
    sentence = "The quick brown fox jumps over the lazy dog. " * 2  # ~90 chars
    assert g.estimate_text_tokens(sentence) >= 25


# ── budget arithmetic ──────────────────────────────────────────────


def test_prompt_budget_subtracts_completion_reserve_and_margin():
    """If the server is loaded at 16384 and we reserve 1024 for the
    answer + 256 safety margin, the prompt may use at most 15104 tokens."""
    b = ContextBudget(ctx_window=16384, reserve_for_completion=1024,
                      safety_margin=256)
    assert b.prompt_budget == 16384 - 1024 - 256


def test_prompt_budget_floors_at_zero_for_misconfiguration():
    """A user who set ``reserve_for_completion`` higher than ``ctx_window``
    shouldn't get a negative budget — they'll get an immediate
    ContextOverflow on the first turn, which surfaces the bad config."""
    b = ContextBudget(ctx_window=1024, reserve_for_completion=2048)
    assert b.prompt_budget == 0


# ── message-list estimation ────────────────────────────────────────


def _msg(role, content="hi", **kw):
    """Helper — builds the OpenAI-shape Message TypedDict the loop uses."""
    return {"role": role, "content": content, **kw}


def test_estimate_messages_sums_role_content_and_tools():
    """The prompt size includes the system prompt, every message in
    history, and the tool schemas. Missing one of those is how Phase 2
    will under-count and re-introduce the bug."""
    g = ContextGuard(ContextBudget(chars_per_token=3.0))
    msgs = [
        _msg("user", "hello"),
        _msg("assistant", "hi there"),
        _msg("user", "what time?"),
    ]
    just_system = g.estimate_messages_tokens([], system_prompt="x" * 300, tools=[])
    with_history = g.estimate_messages_tokens(
        msgs, system_prompt="x" * 300, tools=[],
    )
    assert with_history > just_system


def test_estimate_messages_counts_tool_call_args_and_results():
    """A tool call's ``arguments`` JSON and the tool result's ``content``
    are both on the wire; both must be counted. This is the failure
    mode the user just hit — a big tool result blew the budget."""
    g = ContextGuard(ContextBudget(chars_per_token=3.0))
    big_result = "x" * 10_000
    msgs = [
        _msg("assistant", None, tool_calls=[{
            "id": "c1", "name": "run_shell",
            "arguments": {"command": "ls -la"},
        }]),
        {"role": "tool", "tool_call_id": "c1",
         "name": "run_shell", "content": big_result},
    ]
    tokens = g.estimate_messages_tokens(msgs, system_prompt="", tools=[])
    # The 10K-char result alone is ~3000+ tokens at 3.0 chars/tok.
    assert tokens >= 3_000


# ── history trim ───────────────────────────────────────────────────


def test_trim_drops_oldest_first_when_over_budget():
    """The trimmer drops the oldest non-system message first. Stops as
    soon as the prompt fits — doesn't over-trim. The user's latest
    question and the in-flight tool chain always stay."""
    g = ContextGuard(ContextBudget(
        ctx_window=200, reserve_for_completion=0, safety_margin=0,
        chars_per_token=1.0,   # easier math for the test
    ))
    msgs = [
        _msg("user", "x" * 100),       # oldest — droppable, will go
        _msg("assistant", "y" * 50),   # middle — droppable if needed
        _msg("user", "z" * 100),       # LATEST user turn — undroppable
    ]
    # Combined ≈ 285 tokens; dropping just the oldest brings us to ~175,
    # which fits under the 200-token budget — so the trimmer should
    # drop msg0 and stop.
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    # At least one message dropped (the oldest user); the latest user
    # message is preserved verbatim.
    assert result.dropped_count >= 1
    assert msgs[0] not in result.messages
    assert result.messages[-1]["content"] == "z" * 100


def test_trim_preserves_in_flight_tool_chain():
    """A trim mid-turn must NOT delete the assistant/tool messages that
    belong to the current in-flight turn — the model needs to see its
    own most recent tool call to continue."""
    g = ContextGuard(ContextBudget(
        ctx_window=80, reserve_for_completion=0, safety_margin=0,
        chars_per_token=1.0,
    ))
    msgs = [
        _msg("user", "x" * 100),                  # old, droppable
        _msg("user", "y" * 30),                    # current turn user msg — KEEP
        _msg("assistant", None, tool_calls=[{
            "id": "c1", "name": "get_time", "arguments": {}}]),
        {"role": "tool", "tool_call_id": "c1",
         "name": "get_time", "content": "noon"},
    ]
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    # The earliest user (100 tokens) got dropped; the rest stay together.
    assert result.dropped_count == 1
    assert result.messages[0]["content"] == "y" * 30
    assert any(m.get("role") == "tool" for m in result.messages)


def test_trim_returns_unchanged_when_already_fits():
    """No work when the prompt already fits — and ``dropped_count`` is 0
    so a TUI status line doesn't say 'trimmed 0 turns'."""
    g = ContextGuard(ContextBudget(ctx_window=10_000))
    msgs = [_msg("user", "hi")]
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    assert result.dropped_count == 0
    assert result.messages == msgs


def test_trim_raises_when_even_max_trimming_doesnt_fit():
    """If the system prompt + latest user message + tool schemas alone
    overflow the budget, there's nothing to trim — fail with a typed
    error so the caller can render a useful message instead of just
    forwarding the server's hard error."""
    g = ContextGuard(ContextBudget(
        ctx_window=50, reserve_for_completion=0, safety_margin=0,
        chars_per_token=1.0,
    ))
    msgs = [_msg("user", "z" * 200)]   # latest user turn alone is too big
    with pytest.raises(ContextOverflow) as exc_info:
        g.trim_to_fit(msgs, system_prompt="x" * 100, tools=[])
    err = exc_info.value
    # The exception carries enough info for the renderer to surface
    # 'budget=X, needed=Y, undroppable=Z'.
    assert err.budget == 50
    assert err.estimated > 50


def test_trim_keeps_the_latest_user_message_even_if_huge():
    """The latest user message is undroppable. Even if it alone is
    over budget, ``trim_to_fit`` must NOT silently drop it — that would
    leave the agent with no prompt at all and the next turn would
    spiral. Raise instead."""
    g = ContextGuard(ContextBudget(
        ctx_window=100, reserve_for_completion=0, safety_margin=0,
        chars_per_token=1.0,
    ))
    msgs = [_msg("user", "x" * 200)]
    with pytest.raises(ContextOverflow):
        g.trim_to_fit(msgs, system_prompt="", tools=[])


# ── per-tool result truncation ─────────────────────────────────────


def test_truncate_oversized_result_leaves_small_payload_alone():
    g = ContextGuard(ContextBudget(max_tool_result_chars=1000))
    out, was_truncated = g.truncate_oversized_result("hello")
    assert was_truncated is False
    assert out == "hello"


def test_truncate_oversized_result_caps_a_huge_string():
    """A multi-megabyte stdout from ``run_shell`` would dominate the
    next turn's context. Cap at ``max_tool_result_chars``, leave a
    breadcrumb saying how much was dropped."""
    g = ContextGuard(ContextBudget(max_tool_result_chars=1000))
    huge = "x" * 50_000
    out, was_truncated = g.truncate_oversized_result(huge)
    assert was_truncated is True
    assert isinstance(out, str)
    # ``preview_chars`` (default 1500) + a short marker footer. Allow
    # ~200 chars of slack for the footer; we don't want to pin its
    # exact phrasing here.
    assert len(out) <= 1500 + 200
    assert "truncated" in out.lower()
    # The original size is mentioned so the model knows what it lost.
    assert "50000" in out or "50,000" in out


def test_truncate_oversized_result_handles_dict_payloads():
    """JROS tools mostly return dicts. A dict whose JSON serialisation
    is huge should be truncated the same way — we serialise, check
    length, and if oversized replace with a marker dict that carries
    the original keys + a size note."""
    g = ContextGuard(ContextBudget(max_tool_result_chars=500))
    huge_dict = {"stdout": "x" * 5000, "exit_code": 0}
    out, was_truncated = g.truncate_oversized_result(huge_dict)
    assert was_truncated is True
    # The output must remain JSON-serialisable (so adapters can put it
    # on the wire). Either a string preview or a dict-shaped marker.
    import json
    json.dumps(out)


def test_truncate_returns_a_pure_passthrough_when_disabled():
    """``max_tool_result_chars=0`` disables the truncator entirely —
    e.g. for benchmarks that need full fidelity."""
    g = ContextGuard(ContextBudget(max_tool_result_chars=0))
    big = "x" * 100_000
    out, was_truncated = g.truncate_oversized_result(big)
    assert was_truncated is False
    assert out == big


def test_oversized_dict_persists_to_artifact_dir_when_set(tmp_path):
    """When ``artifact_dir`` is bound, the full oversized payload is
    written to disk and the marker dict carries an ``artifact_path``
    the model can ``read_file`` for the body the preview cut off."""
    g = ContextGuard(ContextBudget(
        max_tool_result_chars=500,
        artifact_dir=tmp_path,
    ))
    huge = {"stdout": "y" * 5000, "exit_code": 0}
    out, was_truncated = g.truncate_oversized_result(huge)
    assert was_truncated is True
    assert isinstance(out, dict)
    assert out.get("_truncated") is True
    assert "artifact_path" in out
    # The persisted file actually exists and holds the FULL original.
    import pathlib
    persisted = pathlib.Path(out["artifact_path"])
    assert persisted.is_file()
    body = persisted.read_text(encoding="utf-8")
    # The pre-serialised body contains the full stdout payload.
    assert "y" * 5000 in body
    # Marker carries a hint so the model knows to read the artifact.
    assert "hint" in out


def test_oversized_string_persists_alongside_preview(tmp_path):
    """String results take the truncate-with-marker path; the artifact
    is still written so the operator can recover the full bytes."""
    g = ContextGuard(ContextBudget(
        max_tool_result_chars=500,
        artifact_dir=tmp_path,
    ))
    huge = "z" * 50_000
    out, was_truncated = g.truncate_oversized_result(huge)
    assert was_truncated is True
    assert isinstance(out, str)
    # The marker footer mentions the on-disk path.
    assert "saved to" in out
    # Exactly one artifact file landed in the directory.
    artifacts = list(tmp_path.iterdir())
    assert len(artifacts) == 1
    assert artifacts[0].read_text(encoding="utf-8") == huge


def test_persistence_failure_falls_back_to_preview_only(tmp_path):
    """Artifact write is best-effort: a write hiccup must NOT block the
    tool dispatch — the marker just omits the path."""
    # Point artifact_dir at a path that can't be created (a file, not a dir).
    blocking_file = tmp_path / "not_a_dir"
    blocking_file.write_text("blocker")
    g = ContextGuard(ContextBudget(
        max_tool_result_chars=500,
        artifact_dir=blocking_file / "subdir" / "x",
    ))
    huge = {"stdout": "q" * 5000}
    out, was_truncated = g.truncate_oversized_result(huge)
    assert was_truncated is True
    # Dict path returns a marker dict without artifact_path on failure.
    assert isinstance(out, dict)
    assert out.get("_truncated") is True
    assert "artifact_path" not in out


# ── group-aware trim (assistant tool_calls + matching tool results) ───


def test_trim_drops_assistant_and_its_tool_results_together():
    """An assistant message with ``tool_calls`` must not be dropped
    while its matching ``tool`` result messages remain — the result
    becomes an orphan and OpenAI's API 400s on it. The trim drops
    the whole group atomically."""
    g = ContextGuard(ContextBudget(
        ctx_window=400, reserve_for_completion=0, safety_margin=0,
        chars_per_token=1.0,
    ))
    msgs = [
        # Old turn: assistant called two tools, two matching results.
        {"role": "assistant", "content": "x" * 50,
         "tool_calls": [
             {"id": "c1", "name": "get_time", "arguments": {}},
             {"id": "c2", "name": "calculate", "arguments": {"expression": "2+2"}},
         ]},
        {"role": "tool", "tool_call_id": "c1", "name": "get_time",
         "content": "noon"},
        {"role": "tool", "tool_call_id": "c2", "name": "calculate",
         "content": "4"},
        # Current turn's user message — undroppable.
        {"role": "user", "content": "z" * 250},
    ]
    result = g.trim_to_fit(msgs, system_prompt="", tools=[])
    # When trimming kicks in, the assistant-with-tool_calls AND both
    # tool results must drop together — never just the assistant
    # leaving orphaned tool messages, never the tool messages without
    # their assistant.
    roles_kept = [m["role"] for m in result.messages]
    if "tool" in roles_kept:
        assert "assistant" in roles_kept, (
            "tool result survived without its parent assistant — orphan"
        )
    # Latest user message preserved either way.
    assert result.messages[-1]["content"] == "z" * 250


def test_head_group_size_counts_only_matching_tool_results():
    """An unrelated ``tool`` message immediately after the head
    assistant (e.g. from a corrupted history) does NOT extend the
    group — the group stops at the first non-matching tool message
    and the next iteration will trim that one separately."""
    g = ContextGuard(ContextBudget(ctx_window=10_000))
    msgs = [
        {"role": "assistant", "content": "a",
         "tool_calls": [{"id": "c1", "name": "get_time", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "get_time",
         "content": "noon"},
        # Mismatched call id — doesn't belong to this assistant.
        {"role": "tool", "tool_call_id": "other", "name": "calculate",
         "content": "4"},
    ]
    assert g._head_group_size(msgs) == 2  # assistant + the matching tool


def test_head_group_size_for_a_plain_assistant_or_user_is_one():
    g = ContextGuard(ContextBudget(ctx_window=10_000))
    assert g._head_group_size([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]) == 1
    assert g._head_group_size([
        {"role": "assistant", "content": "hey"},  # no tool_calls
        {"role": "user", "content": "next"},
    ]) == 1
