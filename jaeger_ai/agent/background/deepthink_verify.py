"""Deep Think runner, Phase 1 — verify-before-done.

Design: dev/docs/reality/agentic_runners.md (Runner 2). The daemon used to mark a
task "completed" the moment ``run_command`` RETURNED — even if the model
answered "I couldn't do this". The assembly line's value is enforcement, so
completion is now decided by OBSERVABLE EVIDENCE, never by trust-by-return
or by model declarations:

  1. Tool-trace check — the ``tool_calls`` SQL table records every dispatch
     per session; a Deep Think task (skill development by definition) that
     made NO successful mutating call did not complete.
  2. Failure-signature check — the final text saying "I was unable / cannot
     complete" is an admission, and admissions of failure ARE trustworthy
     (a model may lie about success; it rarely lies about giving up).

On failure: ONE bounded replan cycle — the task is re-queued once with the
failure evidence appended so the retry starts informed; a second failure is
marked failed with the reason, never looped. The reflect step (already
wired in the daemon) captures the outcome either way.
"""

from __future__ import annotations

import re
from typing import Any


RETRY_TAG = "[deepthink-retry]"

# A successful call to any of these is evidence the task actually built or
# changed something. Deep Think tasks are skill-development by definition
# (the daemon preamble says "write files into skills/").
MUTATING_TOOLS: frozenset[str] = frozenset({
    "write_file", "append_file", "patch", "delete_file",
    "install_package", "reload_skills", "record_skill_revision",
    "package_skill", "execute_code", "terminal", "run_in_venv",
})

_FAILURE_SIGNATURES = re.compile(
    r"i\s+(?:was|am)\s+unable|unable\s+to\s+complete"
    r"|cannot\s+complete|can'?t\s+complete|could\s+not\s+complete"
    r"|i\s+(?:must\s+)?g[ai]ve\s+up|failed\s+to\s+complete"
    r"|i\s+couldn'?t\s+(?:finish|complete|do)",
    re.IGNORECASE,
)


def _successful_mutations(layout: Any, session_key: str) -> list[str]:
    """Distinct mutating tools that SUCCEEDED in the task's session — the
    observable trace, straight from the tool_calls audit table."""
    try:
        from jaeger_ai.core.memory import sqlite_store
        if not sqlite_store.is_bound():
            return []
        placeholders = ",".join("?" * len(MUTATING_TOOLS))
        rows = sqlite_store.connection().execute(
            f"SELECT DISTINCT tool_name FROM tool_calls "
            f"WHERE session_key = ? AND ok = 1 "
            f"AND tool_name IN ({placeholders})",
            (session_key, *sorted(MUTATING_TOOLS)),
        ).fetchall()
        return sorted(r["tool_name"] for r in rows)
    except Exception:  # noqa: BLE001 — evidence query must never crash the daemon
        return []


def verify_outcome(layout: Any, task_id: str,
                   answer: str) -> tuple[bool, str]:
    """Did the task verifiably complete? Returns ``(ok, evidence/reason)``."""
    text = (answer or "").strip()
    if _FAILURE_SIGNATURES.search(text):
        return False, "the final answer admits failure"
    mutated = _successful_mutations(layout, f"daemon_{task_id}")
    if not mutated:
        return False, ("no successful mutating tool call in the task's "
                       "session — nothing was built or changed")
    return True, f"verified: successful {', '.join(mutated)}"


def settle_task(queue: Any, layout: Any, task: Any, answer: str,
                extra_check: Any = None) -> str:
    """Decide a finished Deep Think run's fate from observable evidence.

    ``extra_check`` is an optional per-task-type verifier (a callable
    returning ``(ok, reason)``) layered ON TOP of the generic evidence —
    e.g. a skill-review task must also have recorded a new skill revision.

    Returns the action taken: ``"done"``, ``"retried"`` (one bounded replan
    cycle — the retry is queued pre-approved with the failure evidence
    appended), or ``"failed"`` (a retry that failed again; never loops)."""
    ok, evidence = verify_outcome(layout, task.id, answer)
    if ok and callable(extra_check):
        extra_ok, extra_reason = extra_check()
        if not extra_ok:
            ok, evidence = False, extra_reason
        else:
            evidence = f"{evidence}; {extra_reason}"
    if ok:
        queue.mark_done(task.id, f"completed by daemon ({evidence})")
        return "done"
    description = (task.description or "").strip()
    if description.startswith(RETRY_TAG):
        queue.mark_failed(task.id, f"verify failed after retry: {evidence}")
        return "failed"
    queue.mark_failed(task.id, f"verify failed: {evidence} — retrying once")
    tail = (answer or "").strip()[-500:]
    retry = queue.add(
        f"{RETRY_TAG} {description}\n\n"
        f"PREVIOUS ATTEMPT DID NOT VERIFY: {evidence}.\n"
        f"Its final answer ended with:\n{tail}\n\n"
        f"Fix the blocker and COMPLETE the task this time — the run is "
        f"verified by actual successful tool calls, not by claims.",
        source="agent", approved=True,
    )
    return f"retried:{retry.id}"


__all__ = ["settle_task", "verify_outcome", "RETRY_TAG", "MUTATING_TOOLS"]
