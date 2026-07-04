"""The verify gate — station 2 of the standard runner.

Design: dev/docs/agentic_runners.md ("soft loop, hard boundary"). The loop's
single exit door is "a response with no tool calls is the final answer" —
which lets two specific 4B failure modes slip out:

  * PLAN-halt — the model narrates ``PLAN: execute_code(...)`` and stops
    without emitting the call (attention lapse at the finish line).
  * claim-vs-action — the model *says* "I've noted/saved/scheduled it" but no
    matching tool call succeeded this turn (hallucinated execution).

The gate inspects the candidate final text with checks the runner can do for
free, and answers with at most ONE synthetic nudge per turn. It is SOFT by
construction: it never denies, never retries in a loop, and the nudge never
persists in session history. (The hard deny-and-retry version of this idea
regressed E4B 73→66 in 2026-07 — nudge, don't straitjacket.)

Kill switch: ``JAEGER_VERIFY_GATE=0``.
"""

from __future__ import annotations

import os
import re
from typing import Iterable


PLAN_NUDGE = (
    "SYSTEM NUDGE: You wrote a plan but did not execute it — a turn must "
    "not end on a PLAN line. Emit the tool call(s) for your plan NOW, in "
    "this same turn. Do not re-state the plan."
)

CLAIM_NUDGE = (
    "SYSTEM NUDGE: Your answer claims an action was completed, but no "
    "matching tool call succeeded this turn. Call the correct tool NOW — "
    "or state plainly that the action was NOT done."
)


def gate_enabled() -> bool:
    """The gate is on by default; ``JAEGER_VERIFY_GATE=0`` kills it."""
    return os.environ.get("JAEGER_VERIFY_GATE", "1").strip() != "0"


# ── check A: PLAN-halt ─────────────────────────────────────────────

_PLAN_LINE = re.compile(r"^\s*plan\s*:", re.IGNORECASE | re.MULTILINE)
# a tool-call-shaped reference: word( — validated against the REAL tool
# names by the caller, so prose like "Plan: we should think(!)" can't trip.
_CALLISH = re.compile(r"\b([a-z][a-z0-9_]{2,})\s*\(")


def _is_plan_halt(text: str, tool_names: Iterable[str]) -> bool:
    """True when the candidate answer is a narrated plan that names a real
    tool call it never made. The registered-tool requirement keeps a
    legitimate 'here is my plan, shall I proceed?' answer from tripping —
    the failure signature is specifically ``PLAN: execute_code(...)``."""
    if not _PLAN_LINE.search(text):
        return False
    names = set(tool_names)
    return any(m.group(1) in names for m in _CALLISH.finditer(text))


# ── check B: claim-vs-action ───────────────────────────────────────

# First-person completed-action claims, each mapped to the tool family that
# must have SUCCEEDED this turn for the claim to be true. Verb lists stay
# tight (mutation verbs only) so "I've analyzed the options" never trips.
_FP = r"\bi(?:'ve| have)\s+(?:now\s+)?(?:also\s+)?(?:already\s+)?(?:successfully\s+)?"

_CLAIM_FAMILIES: tuple[tuple[re.Pattern[str], frozenset[str]], ...] = (
    # file writes: "I've saved/written it to notes.txt"
    (re.compile(_FP + r"(?:saved|written|wrote)\b", re.IGNORECASE),
     frozenset({"write_file", "append_file", "patch", "delete_file",
                "execute_code", "terminal"})),
    # board filing: "I've added/filed a card", "I have noted them"
    (re.compile(_FP + r"(?:added|filed|noted|logged)\b", re.IGNORECASE),
     frozenset({"board_add", "board_update", "board_move", "board_delete",
                "remember", "memory", "todo", "skill_note", "reflect",
                "propose_deep_think_task", "write_file", "append_file"})),
    # memory: "I've remembered/stored that"
    (re.compile(_FP + r"(?:remembered|stored)\b", re.IGNORECASE),
     frozenset({"remember", "memory"})),
    # scheduling: "I've scheduled the reminder"
    (re.compile(_FP + r"scheduled\b", re.IGNORECASE),
     frozenset({"schedule_prompt"})),
    # deep-think queueing: "I've queued it for deep think"
    (re.compile(_FP + r"queued\b", re.IGNORECASE),
     frozenset({"propose_deep_think_task", "board_add"})),
    # deletion: "I've deleted/removed the file"
    (re.compile(_FP + r"(?:deleted|removed)\b", re.IGNORECASE),
     frozenset({"delete_file", "board_delete", "forget", "memory",
                "cancel_schedule", "terminal", "execute_code"})),
)


def _is_false_claim(text: str, tool_successes: Iterable[str]) -> bool:
    """True when the text makes a first-person completed-action claim whose
    tool family saw NO successful call this turn."""
    ok = set(tool_successes)
    for pattern, family in _CLAIM_FAMILIES:
        if pattern.search(text) and not (ok & family):
            return True
    return False


# ── the gate ───────────────────────────────────────────────────────


def verify_final(
    text: str,
    tool_successes: Iterable[str],
    tool_names: Iterable[str],
) -> str | None:
    """Inspect a candidate FINAL answer (a response with no tool calls).

    Returns the nudge string to inject (caller enforces once-per-turn and
    non-persistence), or ``None`` to accept the answer. Order matters: a
    PLAN-halt is the stronger signal — a plan that also says "I've noted"
    should get the plan nudge.
    """
    clean = (text or "").strip()
    if not clean or clean.startswith("["):   # halt/system notes pass through
        return None
    if _is_plan_halt(clean, tool_names):
        return PLAN_NUDGE
    if _is_false_claim(clean, tool_successes):
        return CLAIM_NUDGE
    return None


__all__ = ["verify_final", "gate_enabled", "PLAN_NUDGE", "CLAIM_NUDGE"]
