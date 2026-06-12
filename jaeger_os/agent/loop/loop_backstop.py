"""Loop backstop — guarantees a turn terminates.

The agent loop trusts the model to stop calling tools when it has the
answer. Real models occasionally don't: a tight (tool, args) loop, a
runaway count of legitimate-looking calls, or the same semantic failure
hit over and over. Three counters here catch each pattern and surface a
human-readable halt reason. The counter thresholds are the same as the
pre-refactor pydantic-ai loop in ``main.py`` — kept identical so the
benchmark suite can compare apples to apples across the refactor.

Hermes-adoption (2026-06): the backstop now also WARNS the model one
step before it halts. A cold halt teaches the model nothing — the turn
just dies; an in-result warning ("this looks like a loop; change
strategy, don't abandon tools") lets it self-correct and finish the
task. Warning thresholds sit below the halt thresholds; the halt rules
are unchanged.

Stateless on purpose: callers own the dicts and pass them in. That keeps
the agent loop's per-turn state visible at the call site and the helpers
trivially unit-testable.
"""

from __future__ import annotations

from typing import Any

# Observed legitimate multi-step work tops out near ~16 tool calls and
# varies its arguments. These limits are a safety net, not a fine-grained
# iteration tuner — bump them if real workloads need it, but don't lower.
MAX_TOOL_CALLS = 24
MAX_IDENTICAL_CALLS = 4
MAX_SEMANTIC_FAILURES = 2

# Warn-before-halt thresholds (Hermes ``tool_guardrails`` pattern).
# A warning never blocks execution — it rides on the tool result so the
# model sees the pattern while it can still change course.
WARN_IDENTICAL_CALLS = 2      # halt at 4 — warn from the 2nd repeat
WARN_SEMANTIC_FAILURES = 1    # halt at 2 — warn on the 1st repeat


def call_signature(tool_name: str, args: Any) -> str:
    """A stable per-call key — ``tool|args``. The same shape the existing
    :mod:`jaeger_os.core.tool_guardrails` uses, so halt thresholds and
    warn thresholds stay aligned without a shared format-string."""
    return f"{tool_name}|{args!r}"


def semantic_failure_signature(
    tool_name: str, args: Any, content: Any,
) -> str | None:
    """Return a stable signature for repeated tool *failures*, or None
    when the call succeeded.

    Exact (tool, args) matching misses loops where the model varies
    irrelevant args while hitting the same underlying error. This
    normalizes the action to ``tool | target | first error line``.
    """
    if not isinstance(content, dict) or content.get("ok") is True:
        return None
    error = (
        content.get("stderr")
        or content.get("syntax_error")
        or content.get("error")
        or content.get("reason")
        or ""
    )
    if not error:
        return None
    first_line = str(error).strip().splitlines()[0][:160]
    if isinstance(args, dict):
        target = (
            args.get("path") or args.get("file") or args.get("name")
            or content.get("path") or content.get("file") or ""
        )
        if not target and tool_name in ("execute_code", "run_python"):
            code = str(args.get("code") or "")
            target = f"code:{hash(code) & 0xffff:x}" if code else ""
    else:
        target = ""
    return f"{tool_name}|{target}|{first_line}"


def loop_warning(
    call_signatures: dict[str, int],
    failure_signatures: dict[str, int] | None = None,
    *,
    sig: str | None = None,
    fail_sig: str | None = None,
) -> str | None:
    """Return guidance text when the CURRENT call (identified by its
    ``sig`` / ``fail_sig``) is one step from tripping the backstop, else
    ``None``.

    The text is appended to the tool result so the model sees it in
    band. Phrasing matters: weak models that get warned about loops
    tend to abandon tools entirely and free-associate an answer — the
    guidance explicitly tells them to keep using tools, diagnose, and
    vary the approach (the Hermes recovery-hint lesson).
    """
    if fail_sig is not None:
        n = (failure_signatures or {}).get(fail_sig, 0)
        if n >= WARN_SEMANTIC_FAILURES:
            tool = fail_sig.split("|", 1)[0]
            return (
                f"[loop warning: {tool} hit the same failure {n} time(s) "
                f"this turn — one more identical failure halts the turn. "
                f"Do not abandon tools; inspect the error above, fix the "
                f"arguments or pick a different tool, and avoid retrying "
                f"the exact same call.]"
            )
    if sig is not None:
        n = call_signatures.get(sig, 0)
        if n >= WARN_IDENTICAL_CALLS:
            tool = sig.split("|", 1)[0]
            return (
                f"[loop warning: {tool} was called {n} times with "
                f"identical arguments — at {MAX_IDENTICAL_CALLS} the turn "
                f"halts. The result above is what this call produces; use "
                f"it, change the arguments, or choose a different tool.]"
            )
    return None


def loop_halt_reason(
    tool_calls_made: int,
    call_signatures: dict[str, int],
    failure_signatures: dict[str, int] | None = None,
) -> str | None:
    """Return a halt reason when the turn is spinning, else ``None``.

    Order matters: semantic failures first (the model is stuck on the
    same error), then identical-call loops (same tool/args), then the
    runaway-total ceiling. The first match wins so the most diagnostic
    message reaches the operator.
    """
    for sig, n in (failure_signatures or {}).items():
        if n >= MAX_SEMANTIC_FAILURES:
            return (
                f"hit the same {sig.split('|', 1)[0]} failure {n} times"
            )
    for sig, n in call_signatures.items():
        if n >= MAX_IDENTICAL_CALLS:
            return (
                f"called {sig.split('|', 1)[0]} with identical "
                f"arguments {n} times"
            )
    if tool_calls_made > MAX_TOOL_CALLS:
        return f"made {tool_calls_made} tool calls in a single turn"
    return None


__all__ = [
    "MAX_TOOL_CALLS",
    "MAX_IDENTICAL_CALLS",
    "MAX_SEMANTIC_FAILURES",
    "WARN_IDENTICAL_CALLS",
    "WARN_SEMANTIC_FAILURES",
    "call_signature",
    "semantic_failure_signature",
    "loop_halt_reason",
    "loop_warning",
]
