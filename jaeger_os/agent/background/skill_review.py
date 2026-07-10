"""Skill self-improvement review — decides WHEN to improve a recipe-skill and
crafts the Deep Think task that does it, measured (smoke + benchmark) before the
rewrite is trusted. Phases 2-3 of dev/docs/history/SKILL_EVOLUTION_PLAN.md.

The heavy rewrite runs in the EXISTING Deep Think loop (idle/asleep, strong
model) — this module only proposes the task and records the revision.

**On by default (opt-OUT).** The operator wants the agent to improve over time,
so the loop is enabled out of the box: a skill that accumulates enough
issue/failure notes auto-proposes a review, which auto-approves and runs in Deep
Think. This is safe by construction — every rewrite is sandboxed to
``<instance>/skills/``, smoke-gated (a broken version never activates),
benchmark-validated (kept only if the delta is positive, else reverted), and
recorded as a revision you can inspect/roll back. It's governed by its OWN
switch (``set_enabled``), independent of the live-turn autonomy mode, because
skill improvement is a background, sandboxed concern — not a live tier-gated
action. Opt out → reviews still happen but only when the agent asks, and they
land in the backlog for the operator to approve.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from jaeger_os.core.skill_improvement import skill_notes

REVIEW_TAG = "skill-review"
DEFAULT_THRESHOLD = 3
_BAD = ("issues", "failed")

# Master switch for autonomous skill improvement. ON by default (opt-out).
# Process-global like the runtime modes.
_state = {"enabled": True}


def enabled() -> bool:
    return _state["enabled"]


def set_enabled(on: bool) -> dict:
    _state["enabled"] = bool(on)
    return {"ok": True, "enabled": _state["enabled"]}


# ── probabilistic, severity-weighted trigger (the "neuron" model) ──────────

_SEVERITY = {"smooth": 0, "slow": 1, "issues": 2, "failed": 3}
FLAG_BUMP = 4

# Trigger tuning (conservative to start; widen once watched). S is an activation
# in "severity points": one `failed` = 3, one `issues` = 2, a flag = +4.
S_MIN = 2.0     # gate: below this, never fire (don't review noise)
S0 = 5.0        # sigmoid midpoint (~ P=0.5)
T = 2.0         # temperature: larger = softer ramp
S_MAX = 10.0    # ceiling: at/above this, always fire (no infinite deferral)
DEFAULT_K = 3   # max skills reviewed per idle sweep


def severity(note: Any) -> int:
    """Severity weight of one note (unknown outcome → 0)."""
    return _SEVERITY.get(getattr(note, "outcome", ""), 0)


def activation(layout: Any, skill: str) -> float:
    """Severity-weighted sum of a skill's notes SINCE the last ``reviewing``
    marker (a review consumes/resets it), plus FLAG_BUMP per flagged note."""
    notes = skill_notes.notes_for(layout, skill)
    last = max((i for i, n in enumerate(notes) if n.outcome == "reviewing"),
               default=-1)
    recent = notes[last + 1:]
    return float(sum(severity(n) for n in recent)
                 + FLAG_BUMP * sum(1 for n in recent if getattr(n, "flag", False)))


def fire_probability(s: float, *, s0: float = S0, t: float = T,
                     s_min: float = S_MIN, s_max: float = S_MAX) -> float:
    """Probability this skill is reviewed this idle sweep. Gate below ``s_min``
    (0.0), ceiling at/above ``s_max`` (1.0), sigmoid in between."""
    if s < s_min:
        return 0.0
    if s >= s_max:
        return 1.0
    return 1.0 / (1.0 + math.exp(-(s - s0) / t))


def select_for_review(activations: dict[str, float], k: int, *, rng) -> list[str]:
    """Probabilistically pick skills to review this sweep. Each fires with its
    ``fire_probability``; fired skills are returned worst-first (highest
    activation), capped at ``k`` so one idle period can't churn everything."""
    fired = [s for s, a in activations.items()
             if rng.random() < fire_probability(a)]
    fired.sort(key=lambda s: activations[s], reverse=True)
    return fired[:max(0, k)]


def review_log_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "skill_review_log.jsonl"


def _log_decision(layout: Any, skill: str, s: float, p: float, fired: bool) -> None:
    """Append one explainable trigger decision (S, P, fired) — so 'why did it
    review X?' is never a mystery."""
    rec = {"skill": skill, "S": round(s, 3), "P": round(p, 3),
           "fired": bool(fired), "ts": skill_notes._now()}
    path = review_log_path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


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


def _summaries_block(layout: Any, skill: str) -> str:
    """Render a skill's accrued post-use summaries SINCE the last review as the
    trajectory the auditor reads cold (newest last)."""
    notes = skill_notes.notes_for(layout, skill)
    last = max((i for i, n in enumerate(notes) if n.outcome == "reviewing"),
               default=-1)
    recent = notes[last + 1:]
    if not recent:
        return "(no recent post-use summaries)"
    lines = []
    for i, n in enumerate(recent, 1):
        bits = [f"[{n.outcome}]"]
        if n.objective:
            bits.append(f'obj="{n.objective}"')
        if n.calls:
            bits.append(f"calls={n.calls}")
        if n.procedure:
            bits.append(f'procedure="{n.procedure}"')
        if n.errors:
            bits.append(f'errors="{n.errors}"')
        if n.note:
            bits.append(f"— {n.note}")
        lines.append(f"{i}. " + " ".join(bits))
    return "\n".join(lines)


def review_description(layout: Any, skill: str) -> str:
    """The Deep Think task prompt — a SECOND-PERSON audit of the skill's accrued
    post-use summaries that ends in one imperative rule, then a MEASURED change
    (benchmark keep-if-better where possible) recorded as a revision. The
    grammatical distance ('you', 'your own') is deliberate — it flips the agent
    from defending what it did to encoding what should change."""
    block = _summaries_block(layout, skill)
    return (
        f"[{REVIEW_TAG}:{skill}] Improve the '{skill}' skill. Review your own "
        f"logged uses below AS IF THEY WERE SOMEONE ELSE'S — judge each "
        f"trajectory against its objective, not your sympathy for it.\n\n"
        f"Recent uses of '{skill}' (newest last):\n{block}\n\n"
        f"AUDIT — answer each, cite the use #:\n"
        f"1. Objective check — did you meet each objective? full / partial / no.\n"
        f"2. Issues — errors, wrong tools, backtracks, retries.\n"
        f"3. Step economy — fewer calls possible? which were redundant, or could "
        f"have been batched / run in parallel?\n"
        f"4. Guess vs verify — where did you assume instead of checking?\n"
        f"5. THE ONE LESSON — a single reusable imperative ('Batch independent "
        f"reads', NOT 'I read files separately'). If you cannot state it as an "
        f"imperative, the audit found nothing — STOP and change nothing.\n"
        f"6. Skill decision — EDIT '{skill}'s playbook · NEW skill (only if the "
        f"lesson fits no existing skill — check first; prefer EDIT over a "
        f"near-duplicate) · or NOTHING.\n\n"
        f"THEN apply it, MEASURED:\n"
        f"- Benchmarkable skill: baseline benchmark_skill('{skill}'); write "
        f"skills/{skill}_vN/ applying the lesson (keep/extend its smoke test); "
        f"reload_skills; benchmark_skill('{skill}') again; KEEP only if smoke "
        f"passes AND the delta is positive, else REVERT (delete the new dir).\n"
        f"- Pure procedural playbook (not benchmarkable): apply the rule to the "
        f"playbook; it will be scored over its next uses.\n"
        f"- NEW skill: create skills/<name>_v1/ with a use-when trigger + the rule.\n\n"
        f"If you kept a change: record_skill_revision('{skill}', '<vN>', '<the "
        f"imperative rule>', '<benchmark delta or \"scored\">'), then "
        f"skill_note('{skill}', 'smooth', '<one-line summary>')."
    )


def propose_review(layout: Any, skill: str, *, threshold: int = DEFAULT_THRESHOLD,
                   force: bool = False) -> dict:
    """Propose a Deep Think skill-review task. ``force`` skips the threshold (the
    agent explicitly requesting one). Deduped against an already-open review for
    the same skill. When the loop is enabled (default) the task auto-approves and
    runs in Deep Think; when opted out it lands in the backlog for the operator."""
    skill = (skill or "").strip()
    if not skill:
        return {"proposed": False, "reason": "no skill given"}
    if not force and not needs_review(layout, skill, threshold):
        return {"proposed": False, "reason": "below threshold"}
    from jaeger_os.agent.background.deep_think import queue_for_layout
    queue = queue_for_layout(layout)
    if _open_review_exists(queue, skill):
        return {"proposed": False, "reason": "review already queued"}
    approved = enabled()
    task = queue.add(review_description(layout, skill), source="agent",
                     approved=approved)
    # Marker resets the counter so we don't re-propose while this one runs.
    skill_notes.add_note(layout, skill=skill, outcome="reviewing",
                         note="deep-think review queued")
    return {"proposed": True, "task_id": task.id, "skill": skill,
            "approved": approved, "status": "ready" if approved else "backlog"}


def sweep(layout: Any, queue: Any, *, k: int = DEFAULT_K, rng=None) -> list[dict]:
    """One idle/Deep-Think sweep: score every skill that has notes, pick the
    worst few probabilistically, propose a review for each, and log every
    decision (S, P, fired). No-op when the loop is opted out."""
    if not enabled():
        return []
    import random
    rng = rng or random.Random()
    acts = {skill: activation(layout, skill) for skill in skill_notes.summary(layout)}
    selected = set(select_for_review(acts, k, rng=rng))
    decisions: list[dict] = []
    for skill, s in acts.items():
        fired = skill in selected
        _log_decision(layout, skill, s, fire_probability(s), fired)
        if fired:
            propose_review(layout, skill, force=True)
        decisions.append({"skill": skill, "S": s, "fired": fired})
    return decisions


def maybe_propose_on_note(layout: Any, note: Any) -> dict | None:
    """Called after a note lands. Only the agent's ``flag`` fast-tracks a review;
    everything else defers to the idle ``sweep``. No-op when opted out."""
    if not enabled() or not getattr(note, "flag", False):
        return None
    return propose_review(layout, getattr(note, "skill", ""), force=True)
