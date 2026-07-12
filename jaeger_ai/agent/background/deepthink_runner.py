"""Deep Think runner, Phase 2 — the staged assembly line.

Design: dev/docs/reality/agentic_runners.md (Runner 2). The background tier is the
one place the hard pipeline pays: latency-free, unattended, huge contexts,
objective success criteria. Stages, all runner-owned:

  1. PLAN — one bounded model call writes a numbered execution plan; the
     runner SAVES it as an artifact (``memory/deepthink_plans/<id>.md``)
     before any execution. A retry task re-plans with the failure evidence
     already in its description, which is the replan loop.
  2. EXECUTE — the fluid loop runs in the task's dedicated clean session,
     with the plan riding in the prompt so the 4B/coder model doesn't have
     to hold the roadmap in its head mid-task.
  3. VERIFY — Phase-1 observable evidence (tool-trace + failure admission)
     PLUS per-task-type programmatic checks: a ``[skill-review:<name>]``
     task must ALSO have recorded a new skill revision (the measured
     keep-only-if-better loop's receipt). Declarations never count.
  4. SETTLE — verified → done (with the evidence); unverified → ONE
     informed, pre-approved retry; a retry that fails again → failed.

The daemon calls :func:`run_one_task`; ``run_command`` is injected to keep
this module import-clean of main.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from jaeger_ai.agent.background.deepthink_verify import settle_task

_SKILL_REVIEW_RE = re.compile(r"\[skill-review:([^\]]+)\]")

_PLAN_DIRECTIVE = (
    "You are planning an autonomous Deep Think task. Write a CONCISE "
    "numbered execution plan for it: which tools you will call, which "
    "files you will create or change (Deep Think work lands in skills/), "
    "and how the result can be VERIFIED by tool calls (a run, a test, a "
    "reload). 3-8 steps, plain text, no preamble.\n\nTASK:\n{task}"
)


def _generate_plan(client: Any, description: str) -> str:
    """Stage 1: one bounded planning call. Best-effort — '' on any failure
    (the execute stage then runs exactly as Phase 1 did)."""
    try:
        result = client.chat(
            [{"role": "user",
              "content": _PLAN_DIRECTIVE.format(task=description)}],
            max_tokens=400,
            temperature=0.3,
            top_p=0.9,
            stream=False,
        )
        return (getattr(result, "text", None) or "").strip()
    except Exception:  # noqa: BLE001 — planless execution beats no execution
        return ""


def _save_plan_artifact(layout: Any, task_id: str, description: str,
                        plan: str) -> Path | None:
    """The plan checkpoint: persisted BEFORE execution so every Deep Think
    run leaves an inspectable trail (what it intended vs what it did)."""
    if not plan:
        return None
    try:
        plans_dir = Path(layout.memory_dir) / "deepthink_plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        path = plans_dir / f"{task_id}.md"
        path.write_text(
            f"# Deep Think plan — task {task_id}\n\n"
            f"## Task\n{description}\n\n## Plan\n{plan}\n",
            encoding="utf-8",
        )
        return path
    except OSError:
        return None


def _skill_review_check(layout: Any, description: str) -> (
        Callable[[], tuple[bool, str]] | None):
    """Per-task-type verify: a skill-review task must leave a RECEIPT — a
    newly recorded skill revision (benchmark-gated by the review recipe).
    Returns a closure capturing the pre-run revision state, or None for
    generic tasks."""
    m = _SKILL_REVIEW_RE.search(description or "")
    if not m:
        return None
    skill = m.group(1).strip()
    try:
        from jaeger_ai.core.skill_improvement import skill_revisions
        before = skill_revisions.latest(layout, skill)
        before_ts = getattr(before, "ts", None)
    except Exception:  # noqa: BLE001
        before_ts = None

    def _check() -> tuple[bool, str]:
        try:
            from jaeger_ai.core.skill_improvement import skill_revisions
            after = skill_revisions.latest(layout, skill)
        except Exception:  # noqa: BLE001
            return False, f"couldn't read the revision log for '{skill}'"
        if after is None or getattr(after, "ts", None) == before_ts:
            return False, (f"no new revision recorded for '{skill}' — the "
                           f"measured review loop didn't complete")
        return True, f"new revision {after.version} recorded for '{skill}'"

    return _check


def run_one_task(client: Any, queue: Any, layout: Any, task: Any,
                 run_command_fn: Callable[..., str]) -> str:
    """Drive one Deep Think task through the staged pipeline. Returns the
    settle action ("done" / "retried:<id>" / "failed")."""
    description = (task.description or "").strip()

    # Stage 1 — PLAN (checkpoint saved before any execution).
    plan = _generate_plan(client, description)
    artifact = _save_plan_artifact(layout, task.id, description, plan)
    if artifact is not None:
        print(f"[jaeger-daemon] {task.id}: plan saved -> {artifact}",
              flush=True)

    # Arm the per-task-type verifier BEFORE execution — it snapshots the
    # pre-run state (e.g. the latest skill revision) so only receipts
    # produced BY THIS RUN count as evidence.
    extra = _skill_review_check(layout, description)

    # Stage 2 — EXECUTE, plan-informed, in the task's dedicated session.
    prompt = (
        "Deep Think task — complete it fully, writing files into skills/ "
        f"and installing deps as needed:\n\n{description}"
    )
    if plan:
        prompt += (
            "\n\nYOUR EXECUTION PLAN (follow it; adapt only when a step "
            f"fails):\n{plan}"
        )
    answer = run_command_fn(client, prompt, session_key=f"daemon_{task.id}")

    # Stage 3+4 — VERIFY on observable evidence, then SETTLE.
    return settle_task(queue, layout, task, answer, extra_check=extra)


__all__ = ["run_one_task"]
