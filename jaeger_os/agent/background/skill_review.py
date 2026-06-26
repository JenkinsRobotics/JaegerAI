"""Skill self-improvement review — decides WHEN to improve a recipe-skill and
crafts the Deep Think task that does it, measured (smoke + benchmark) before the
rewrite is trusted. Phases 2-3 of dev/docs/process/SKILL_EVOLUTION_PLAN.md.

The heavy rewrite runs in the EXISTING Deep Think loop (idle/asleep, strong
model) — this module only proposes the task. Two governance layers, both
deliberately conservative by default:

  * the AUTOMATIC threshold trigger is OFF by default (``set_auto_trigger``);
    the operator enables it once they've watched the proposals. The agent can
    always request a review by hand regardless.
  * whether a proposal auto-applies vs waits for approval is the AUTONOMY MODE's
    call — ``auto`` → the task lands ``ready`` (self-applies in Deep Think),
    ``scoped``/``ask`` → ``backlog`` (the operator approves it).
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core import skill_notes

REVIEW_TAG = "skill-review"
DEFAULT_THRESHOLD = 3
_BAD = ("issues", "failed")

# Operator gate for the AUTOMATIC threshold trigger. Off = propose-only, by
# hand ("until watched", per the plan). Process-global like the runtime modes.
_state = {"auto_trigger": False}


def auto_trigger_enabled() -> bool:
    return _state["auto_trigger"]


def set_auto_trigger(on: bool) -> dict:
    _state["auto_trigger"] = bool(on)
    return {"ok": True, "auto_trigger": _state["auto_trigger"]}


def _bad_since_last_review(layout: Any, skill: str) -> int:
    """Issue/failure notes since the last ``reviewing`` marker — so a finished
    review resets the counter and the same skill isn't re-proposed forever."""
    notes = skill_notes.notes_for(layout, skill)
    last = max((i for i, n in enumerate(notes) if n.outcome == "reviewing"),
               default=-1)
    return sum(1 for n in notes[last + 1:] if n.outcome in _BAD)


def needs_review(layout: Any, skill: str, threshold: int = DEFAULT_THRESHOLD) -> bool:
    return _bad_since_last_review(layout, skill) >= threshold


def _open_review_exists(queue: Any, skill: str) -> bool:
    marker = f"[{REVIEW_TAG}:{skill}]"
    return any(marker in t.description and t.status not in ("done", "failed")
               for t in queue.all_tasks())


def review_description(layout: Any, skill: str) -> str:
    """The Deep Think task prompt — the MEASURED improvement loop, so the rewrite
    is only kept if it's provably better."""
    bad = _bad_since_last_review(layout, skill)
    return (
        f"[{REVIEW_TAG}:{skill}] Improve the '{skill}' skill from its usage "
        f"notes ({bad} issue/failure note(s) logged). Do it MEASURED, never on a "
        f"hunch:\n"
        f"1. Read the notes: skill_notes('{skill}') — find the recurring problem.\n"
        f"2. Baseline: benchmark_skill('{skill}') to record the current score.\n"
        f"3. Write a NEW version (skills/{skill}_vN/) that fixes the recurring "
        f"problem; keep/extend its smoke test to cover it.\n"
        f"4. reload_skills, then benchmark_skill('{skill}') again.\n"
        f"5. KEEP the new version ONLY if its smoke test passes AND the benchmark "
        f"delta is positive — otherwise REVERT (delete the new version dir).\n"
        f"6. skill_note('{skill}', 'smooth' or 'issues', "
        f"'<what you changed + the measured delta>')."
    )


def propose_review(layout: Any, skill: str, *, threshold: int = DEFAULT_THRESHOLD,
                   force: bool = False) -> dict:
    """Propose a Deep Think skill-review task. ``force`` skips the threshold (the
    agent explicitly requesting one). Deduped against an already-open review for
    the same skill. Approval follows the autonomy mode."""
    skill = (skill or "").strip()
    if not skill:
        return {"proposed": False, "reason": "no skill given"}
    if not force and not needs_review(layout, skill, threshold):
        return {"proposed": False, "reason": "below threshold"}
    from jaeger_os.agent.background.deep_think import queue_for_layout
    queue = queue_for_layout(layout)
    if _open_review_exists(queue, skill):
        return {"proposed": False, "reason": "review already queued"}
    from jaeger_os.core.runtime import autonomy
    approved = autonomy.current_autonomy() == "auto"
    task = queue.add(review_description(layout, skill), source="agent",
                     approved=approved)
    # Marker resets the counter so we don't re-propose while this one runs.
    skill_notes.add_note(layout, skill=skill, outcome="reviewing",
                         note="deep-think review queued")
    return {"proposed": True, "task_id": task.id, "skill": skill,
            "approved": approved, "status": "ready" if approved else "backlog"}


def maybe_propose_on_note(layout: Any, skill: str) -> dict | None:
    """Called after a note lands. Auto-proposes ONLY if the operator enabled the
    threshold trigger; otherwise a no-op (returns None)."""
    if not _state["auto_trigger"]:
        return None
    return propose_review(layout, skill)
