"""Stall detection — did the agent DO the work, or just promise to?

The failure this exists for: on a big batch request the model answers
with an intention rather than a result —

    "I'll start a comprehensive analysis. Let me begin by reading the
     notes in the first folder…"

— and the turn ends, because from the agent loop's point of view a reply
with no tool calls IS the final answer. The user watches the prompt come
back with nothing done.

This module is the check that turns that answer into another step. It is
deliberately a *pure text* predicate: the caller
(:mod:`jaeger_ai.interfaces.tui.app`'s turn worker) owns the step budget,
the stop flag, and re-firing the turn.

Two rules, in this order:

  1. **Veto first.** A question to the user, a stated blocker, or a
     plain completion claim ends the run. Continuing through a question
     would talk over someone who was asked something, and continuing
     through "done" would loop forever on a finished task.
  2. **Then evidence.** Only continue when the text *shows* a stall — a
     first-person promise of work not yet done, or an explicit
     "remaining / next up" marker. Silence is not evidence: an answer
     that simply does not say "done" is left alone.

Why not "continue until the model says DONE": weak local models rarely
emit a completion token reliably, so an absence-of-DONE rule re-fires
finished work until the budget burns out. Evidence-of-stall is the rule
that failed safe in the same situation for the loop's verify gate
(``jaeger_agent/loop/verify_gate.py`` — nudge, don't straitjacket).

Kill switch: ``JAEGER_AUTO_CONTINUE=0``.
"""

from __future__ import annotations

import os
import re

# The directive fed back as the next turn's user message. Wording is
# lifted from the loop's nudge family on purpose: name the failure, then
# say exactly what to do instead — weak models that are only told "don't
# do that" tend to answer with an apology and stop again.
CONTINUE_NUDGE = (
    "SYSTEM NUDGE: Do not narrate future actions and do not stop. "
    "Continue the task NOW by calling the tools needed for the next "
    "items, and keep going until every item is processed. When the "
    "work is genuinely finished, say so plainly and summarise what you "
    "produced."
)

# ── veto: reasons to end the run even in auto mode ──────────────────

# A direct question to the operator. The agent's ``clarify`` path and a
# plain "which folder did you mean?" both land here — auto mode governs
# execution, it does not get to ignore someone it just asked.
_QUESTION = re.compile(r"\?\s*(?:\[[^\]]*\]\s*)*$")

_BLOCKED = re.compile(
    r"\b(?:i (?:can'?t|cannot|am unable to|couldn'?t)|"
    r"needs? your (?:approval|confirmation|permission)|"
    r"waiting for (?:your |the )?(?:approval|confirmation|input|reply)|"
    r"permission denied|not authori[sz]ed|"
    r"blocked (?:by|on)|missing (?:the )?credential)\b",
    re.IGNORECASE,
)

# Inner-loop backstop already fired, or the model is narrating the same
# timeout / identical-call stall. Re-firing a new turn resets the
# per-turn counters and is how a Mail AppleScript hang became 60 tools.
_LOOP_BREAKER_TEXT = re.compile(
    r"timed out after \d+|"
    r"do not repeat without narrowing|"
    r"hit the same \S+ failure \d+ times|"
    r"called \S+ with identical arguments|"
    r"made \d+ tool calls in a single turn|"
    r"appleevents?.*timeout",
    re.IGNORECASE,
)

# Completion claims. Kept tight and result-shaped — "I've finished",
# "all 14 folders processed", "here is the summary" — so that a mid-run
# "I finished the first folder" cannot end a run that has 13 to go
# (hence the ``first|initial|this`` guard below).
_COMPLETE = re.compile(
    r"\b(?:task|work|job|analysis|processing|everything|all (?:items|files|"
    r"folders|notes|entries))\s+(?:is|are|has been|have been)?\s*"
    r"(?:now\s+)?(?:complete|completed|finished|done)\b"
    r"|\b(?:i(?:'ve| have)\s+(?:now\s+)?(?:finished|completed)\b)"
    r"|\b(?:here(?:'s| is)\s+the\s+(?:final\s+)?(?:summary|result|report|"
    r"distillation|breakdown))\b"
    r"|\bin summary\b|\bfinal summary\b|\ball done\b",
    re.IGNORECASE,
)
_PARTIAL_COMPLETE = re.compile(
    r"\b(?:first|initial|this|that|one|the current)\s+"
    r"(?:folder|file|note|batch|item|step|section)\b",
    re.IGNORECASE,
)

# ── evidence: the answer is a promise, not a result ─────────────────

# "Let me start by reading…", "I'll now go through…", "Next I will check…"
_PROMISE = re.compile(
    r"\b(?:let me|let's|i'?ll|i will|i'?m going to|i am going to|"
    r"i'?m about to|next[,]? i(?:'?ll| will)?|now i(?:'?ll| will)|"
    r"i shall|going to)\b[^.!?\n]{0,100}?"
    r"\b(?:read(?:ing)?|check(?:ing)?|process(?:ing)?|"
    r"analy[sz]e|analy[sz]ing|look(?:ing)?|review(?:ing)?|"
    r"continu(?:e|ing)|start(?:ing)?|begin(?:ning)?|scan(?:ning)?|"
    r"go through|gather(?:ing)?|collect(?:ing)?|extract(?:ing)?|"
    r"summari[sz]e|summari[sz]ing|writ(?:e|ing)|search(?:ing)?|"
    r"fetch(?:ing)?|list(?:ing)?|open(?:ing)?|examin(?:e|ing)|"
    r"inspect(?:ing)?|work through|iterate|walk through|dig into|"
    r"tr(?:y|ying))\b",
    re.IGNORECASE,
)

# Bare-participle openers the same models use: "Starting the analysis
# now.", "Beginning with the Life OS folder."
_GERUND_OPENER = re.compile(
    r"^\s*(?:ok(?:ay)?[,.]?\s*)?(?:starting|beginning|proceeding|"
    r"continuing|working on|kicking off)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Explicit "there is more to do" bookkeeping.
_REMAINING = re.compile(
    r"\b(?:remaining|remains?\b|still (?:to|need to|have to)|next up|"
    r"(?:folders?|files?|notes?|items?|entries)\s+left|"
    r"\d+\s+(?:of|/)\s*\d+\s+(?:folders?|files?|notes?|items?)|"
    r"i'?ll continue|to be continued|will continue)\b",
    re.IGNORECASE,
)


def enabled() -> bool:
    """Continuation is on by default. ``JAEGER_AUTO_CONTINUE=0`` kills it
    for a session; ``automation.continue_on_narration: false`` kills it
    for an instance."""
    if os.environ.get("JAEGER_AUTO_CONTINUE", "1").strip() == "0":
        return False
    try:
        from jaeger_ai.main import _pipeline
        cfg = _pipeline.get("config")
        automation = getattr(cfg, "automation", None)
        if automation is not None:
            return bool(automation.continue_on_narration)
    except Exception:  # noqa: BLE001 — config is optional here
        pass
    return True


def classify(text: str) -> str:
    """Why the run should stop, or ``"continue"``.

    Returns one of ``question`` · ``blocked`` · ``complete`` · ``empty``
    · ``settled`` · ``continue``. ``settled`` means "no evidence of a
    stall" — the ordinary end of a finished turn.
    """
    body = (text or "").strip()
    if not body:
        return "empty"
    if _QUESTION.search(body):
        return "question"
    if _BLOCKED.search(body) or _LOOP_BREAKER_TEXT.search(body):
        return "blocked"
    if _COMPLETE.search(body) and not _PARTIAL_COMPLETE.search(body):
        return "complete"
    if _PROMISE.search(body) or _GERUND_OPENER.search(body) \
            or _REMAINING.search(body):
        return "continue"
    return "settled"


def hit_inner_cap(halt_reason: str | None) -> bool:
    """True when a recoverable inner-turn boundary tripped.

    ``drive_one_turn`` winds down with a summary when it hits
    ``max_iterations``. That prose often looks settled. The outer loop
    must start the next step anyway.
    """
    reason = (halt_reason or "").lower()
    return (
        "max_iterations" in reason
        or "tool calls in a single turn" in reason
        or reason == "empty_response"
    )


def is_loop_breaker(halt_reason: str | None) -> bool:
    """True when the inner backstop halted a repeating failure.

    Unlike ``hit_inner_cap`` (budget spent, keep going), a loop-breaker
    halt is terminal: the next turn would reset the counters and spam
    the same failing tool.
    """
    reason = (halt_reason or "").lower()
    if not reason or hit_inner_cap(reason):
        return False
    if "identical arguments" in reason:
        return True
    if "failure" in reason and ("same" in reason or "times" in reason):
        return True
    return False


def needs_continuation(text: str) -> bool:
    """True when the answer promised work instead of delivering it."""
    return enabled() and classify(text) == "continue"


def continuation_prompt(objective: str = "") -> str:
    """The directive for the next auto-fired turn. The objective, when
    the run has one (``/plan`` sets it), is restated every step — a long
    run drifts otherwise, and restating costs one line."""
    if objective:
        return f"{CONTINUE_NUDGE}\n\nThe objective still in force:\n{objective}"
    return CONTINUE_NUDGE


VERIFY_NUDGE = (
    "VERIFICATION STEP: you reported the objective complete. Check it "
    "before we settle: re-read or list the artefacts you produced, "
    "confirm every item in scope was actually covered, and fix anything "
    "missing NOW with tool calls. Then reply with what you verified, "
    "where the deliverable is, and anything you could not complete."
)


def verification_prompt(objective: str = "") -> str:
    """One pass asking the agent to check its own claim of completion.

    A completion claim is exactly the thing the loop's verify gate
    exists to distrust (``jaeger_agent/loop/verify_gate.py``): a model
    that says "saved to notes.md" without a successful write is common
    enough to be a named failure mode. In a long unattended run nobody
    is watching to catch it, so the run spends one step catching it."""
    if objective:
        return f"{VERIFY_NUDGE}\n\nThe objective:\n{objective}"
    return VERIFY_NUDGE


__all__ = [
    "CONTINUE_NUDGE", "VERIFY_NUDGE", "enabled", "classify",
    "hit_inner_cap", "is_loop_breaker", "needs_continuation",
    "continuation_prompt", "verification_prompt",
]
