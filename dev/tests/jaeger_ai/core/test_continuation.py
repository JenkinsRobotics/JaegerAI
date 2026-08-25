"""Stall detection — the predicate that decides whether an autonomous run
re-fires the turn.

The table is the specification: each string is the shape of a real reply
that ended a turn, and the verdict is what the run should do about it.
"""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime import continuation


@pytest.mark.parametrize(
    "reply,verdict",
    [
        # ── the failure this whole feature exists for ──
        ("I am starting a comprehensive analysis of your notes. Let me "
         "begin by reading the notes from each folder.", "continue"),
        ("Starting the analysis now.", "continue"),
        ("I'll now go through the remaining folders.", "continue"),
        ("Next I will check the Archive folder.", "continue"),
        ("I finished the first folder; 13 remain.", "continue"),
        ("Processed 3 of 14 folders.", "continue"),
        ("The get_note tool doesn't accept the x-coredata ID format. "
         "Let me try reading by title instead.", "continue"),
        # ── the answer is finished ──
        ("All 14 folders processed. Here is the final summary: ...",
         "complete"),
        ("I've finished — the distilled notes are in ~/notes.md.",
         "complete"),
        ("The task is complete.", "complete"),
        # ── the agent needs the user: never talk over it ──
        ("Which folder should I start with?", "question"),
        ("I can't read that folder — permission denied.", "blocked"),
        ("That needs your approval before I continue.", "blocked"),
        # ── ordinary finished answers ──
        ("The capital of France is Paris.", "settled"),
        ("I analysed the options and the second one is cheaper.",
         "settled"),
        ("", "empty"),
    ],
)
def test_classify(reply, verdict) -> None:
    assert continuation.classify(reply) == verdict


def test_a_question_wins_over_a_promise() -> None:
    """An answer that promises work *and* asks something must stop: the
    user was asked, and firing the next step would talk over them."""
    text = "Let me start reading the folders. Which one has priority?"
    assert continuation.classify(text) == "question"


def test_needs_continuation_honours_the_kill_switch(monkeypatch) -> None:
    stall = "Let me begin by reading each folder."
    assert continuation.needs_continuation(stall) is True
    monkeypatch.setenv("JAEGER_AUTO_CONTINUE", "0")
    assert continuation.enabled() is False
    assert continuation.needs_continuation(stall) is False


def test_inner_cap_halt_is_not_a_finished_job() -> None:
    assert continuation.hit_inner_cap(
        "hit max_iterations=24 without a final answer")
    assert continuation.hit_inner_cap("hit max_iterations=60 without a final answer")
    assert not continuation.hit_inner_cap("stalled")
    assert not continuation.hit_inner_cap(None)
    assert not continuation.hit_inner_cap("")


def test_loop_breaker_halt_is_terminal() -> None:
    assert continuation.is_loop_breaker(
        "called execute_code with identical arguments 4 times")
    assert continuation.is_loop_breaker(
        "hit the same execute_code failure 2 times")
    assert continuation.is_loop_breaker("made 25 tool calls in a single turn")
    assert not continuation.is_loop_breaker(
        "hit max_iterations=24 without a final answer")
    assert not continuation.is_loop_breaker(None)


def test_timeout_narration_is_blocked_not_continued() -> None:
    text = (
        "AppleScript timed out after 15s. Do not repeat without narrowing "
        "the query. Let me try a different script."
    )
    assert continuation.classify(text) == "blocked"


def test_prompts_restate_the_objective() -> None:
    prompt = continuation.continuation_prompt("distil every note")
    assert continuation.CONTINUE_NUDGE in prompt
    assert "distil every note" in prompt
    # Without an objective the directive stands alone — no empty header.
    assert continuation.continuation_prompt() == continuation.CONTINUE_NUDGE

    verify = continuation.verification_prompt("distil every note")
    assert continuation.VERIFY_NUDGE in verify and "distil every note" in verify
