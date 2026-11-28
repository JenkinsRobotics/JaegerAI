"""Loop backstop — guarantees a turn terminates (standalone jaeger-loop module)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

MAX_TOOL_CALLS = 40
WARN_TOOL_CALLS = 34
MAX_IDENTICAL_CALLS = 4
MAX_SEMANTIC_FAILURES = 2

MAIL_TOOLS = frozenset({
    "list_mail", "list_mailboxes", "read_mail", "plan_mail_triage", "triage_all_accounts",
    "move_mail", "batch_move", "mark_mail", "scan_junk_mail",
    "block_sender", "unblock_sender", "list_blocked_senders", "sweep_mail",
})

WARN_IDENTICAL_CALLS = 2
WARN_SEMANTIC_FAILURES = 1


def collapse_generated_repetition(text: str) -> tuple[str, int]:
    """Collapse exact consecutive repetition of meaningful blocks (>=80 chars, 3+ repeats)."""
    raw = str(text or "")
    if len(raw) < 240:
        return raw, 1
    blocks = [part.strip() for part in re.split(r"\n\s*\n", raw) if part.strip()]
    if len(blocks) < 3:
        blocks = [part.strip() for part in raw.splitlines() if part.strip()]
    count = len(blocks)
    for unit_size in range(1, count // 3 + 1):
        if count % unit_size:
            continue
        repeats = count // unit_size
        if repeats < 3:
            continue
        unit = blocks[:unit_size]
        if len("\n\n".join(unit)) < 80:
            continue
        if all(blocks[index:index + unit_size] == unit for index in range(0, count, unit_size)):
            collapsed = "\n\n".join(unit)
            return (
                f"{collapsed}\n\n[repetition guard: collapsed {repeats} identical generated blocks]",
                repeats,
            )
    return raw, 1


def call_signature(tool_name: str, args: Any) -> str:
    return f"{tool_name}|{args!r}"


def semantic_failure_signature(
    tool_name: str,
    args: Any,
    content: Any,
) -> str | None:
    """Normalize repeated tool failures to ``tool | target | diagnostic line``."""
    if not isinstance(content, dict):
        return None
    if content.get("ok") is True and content.get("success") is not False:
        return None
    error = (
        content.get("stderr")
        or content.get("syntax_error")
        or content.get("error")
        or content.get("reason")
        or ""
    )
    timed_out = bool(content.get("timed_out")) or (
        "timed out" in str(error).lower() or "timeout" in str(error).lower()
    )
    if timed_out:
        if tool_name in ("web_extract", "web_search", "browser", "fetch") and isinstance(args, dict):
            raw_url = str(args.get("url") or "").strip()
            if raw_url:
                host = (urlparse(raw_url).netloc or raw_url)[:80].lower()
                return f"{tool_name}|timeout|{host}"
        return f"{tool_name}|timeout|timed out"
    if not error:
        return None
    lines = [ln for ln in str(error).strip().splitlines() if ln.strip()]
    _WARN_NOISE = (
        "Warning:",
        "warnings.warn(",
        "PytestDeprecationWarning",
        "DeprecationWarning",
        "Valid fixture loop scopes",
        "asyncio_default_fixture_loop_scope",
    )
    non_warn = [
        ln for ln in lines
        if not any(tok in ln for tok in _WARN_NOISE)
        and not ln.lstrip().startswith(("The event loop scope", "Future versions of", "icitly in order"))
    ]
    if not non_warn:
        out_text = str(content.get("stdout") or content.get("output") or "").strip()
        if out_text:
            out_lines = [ln.strip() for ln in out_text.splitlines() if ln.strip()]
            fail_lines = [
                ln for ln in out_lines
                if ln.startswith(("FAILED ", "ERROR ", "E   "))
                or re.match(r"^[\w.]+(?:Error|Exception)(?::|$)", ln)
            ]
            if fail_lines:
                non_warn = [fail_lines[-1]]
    eff_lines = non_warn or lines
    first_line = eff_lines[0][:160]
    if first_line.startswith("Traceback (most recent call last):"):
        diagnostics = [
            line.strip()
            for line in eff_lines
            if re.match(r"^[\w.]+(?:Error|Exception|Interrupt|Exit|Iteration)(?::|$)", line)
        ]
        first_line = (diagnostics[-1] if diagnostics else eff_lines[-1].strip())[:160]
    if tool_name in MAIL_TOOLS:
        account = str(args.get("account") or "") if isinstance(args, dict) else ""
        err_l = first_line.lower()
        if any(s in err_l for s in ("mailbox", "can't get", "can’t get", "not found")):
            return f"{tool_name}|{account}|mailbox-resolve"
        return f"{tool_name}|{account}|{first_line}"
    if isinstance(args, dict):
        target = (
            args.get("path") or args.get("file") or args.get("name")
            or args.get("account")
            or content.get("path") or content.get("file") or ""
        )
        if not target and args.get("url"):
            parsed = urlparse(str(args.get("url") or ""))
            target = (parsed.netloc + parsed.path)[:120] or str(args.get("url"))[:120]
        if not target and tool_name in ("execute_code", "run_python", "run_shell", "terminal"):
            code = str(args.get("code") or args.get("command") or "")
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
    *,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> str | None:
    for sig, n in (failure_signatures or {}).items():
        if n >= MAX_SEMANTIC_FAILURES:
            return f"hit the same {sig.split('|', 1)[0]} failure {n} times"
    for sig, n in call_signatures.items():
        if n >= MAX_IDENTICAL_CALLS:
            return f"called {sig.split('|', 1)[0]} with identical arguments {n} times"
    if tool_calls_made >= max_tool_calls:
        return f"made {tool_calls_made} tool calls in a single turn"
    return None


def tool_budget_warning(
    tool_calls_made: int,
    *,
    max_tool_calls: int = MAX_TOOL_CALLS,
    warning_fraction: float = WARN_TOOL_CALLS / MAX_TOOL_CALLS,
) -> str | None:
    warn_at = max(1, int(max_tool_calls * min(0.99, max(0.01, warning_fraction))))
    if warn_at <= tool_calls_made < max_tool_calls:
        remaining = max_tool_calls - tool_calls_made
        return (
            f"[tool budget: {remaining} call(s) remain this turn. "
            "Prioritize the next concrete implementation or verification step. "
            "If the limit is reached, checkpoint the same task accurately; do "
            "not redefine a repair as a report or claim completion. If the remaining "
            "work repeats one operation over many items, use execute_with_tools "
            "for the batch; otherwise call another tool only if essential.]"
        )
    return None


__all__ = [
    "MAIL_TOOLS",
    "MAX_IDENTICAL_CALLS",
    "MAX_SEMANTIC_FAILURES",
    "MAX_TOOL_CALLS",
    "WARN_IDENTICAL_CALLS",
    "WARN_SEMANTIC_FAILURES",
    "WARN_TOOL_CALLS",
    "call_signature",
    "collapse_generated_repetition",
    "loop_halt_reason",
    "loop_warning",
    "semantic_failure_signature",
    "tool_budget_warning",
]
