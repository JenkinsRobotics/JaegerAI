"""Tight budgets for scheduled (cron) and heartbeat turns.

OpenClaw- and Hermes-style check-ins: a short checklist, a small tool
grant, a low tool-call cap, and a time budget that is not the
interactive CLI cap. Does not loosen the privacy classifier.
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

# Heartbeat is a read-only look at standing work, not a work turn.
HEARTBEAT_TOOLS = ("board_view", "list_schedules", "list_background", "todo")
CRON_MAX_TOOL_CALLS = 8
CRON_MAX_STEPS = 1
# Distinct from the interactive CLI hard cap (120s). A check-in should
# finish in under a minute and a half; operators can raise this with
# JAEGER_CRON_TURN_TIMEOUT_S.
_DEFAULT_CRON_TURN_TIMEOUT_S = 90.0
_PREAMBLE_MARK = "[Heartbeat checklist]"

_cron_turn: ContextVar[bool] = ContextVar("jaeger_cron_turn", default=False)
_turn_timeout_s: ContextVar[float | None] = ContextVar("jaeger_turn_timeout_s", default=None)

_HEARTBEAT_NAME = re.compile(r"heartbeat", re.I)


def is_cron_source(source: str | None = "", *, session_id: str = "", options: dict[str, Any] | None = None) -> bool:
    src = str(source or (options or {}).get("source") or "").strip().lower()
    if src in {"cron", "heartbeat"}:
        return True
    sid = str(session_id or "")
    return sid.startswith("cron:") or sid.startswith("heartbeat")


def is_heartbeat_job(*, session_id: str = "", name: str = "", prompt: str = "") -> bool:
    return bool(_HEARTBEAT_NAME.search(f"{session_id} {name} {prompt[:400]}"))


def cron_turn_timeout_s() -> float:
    raw = os.environ.get("JAEGER_CRON_TURN_TIMEOUT_S", "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return _DEFAULT_CRON_TURN_TIMEOUT_S


def active_turn_timeout_s() -> float | None:
    """Wall-clock cap for the current spawn, or None to use the interactive cap."""
    return _turn_timeout_s.get()


def in_cron_turn() -> bool:
    return bool(_cron_turn.get())


def tighten_heartbeat_prompt(prompt: str) -> str:
    """Prefix a read-only checklist without dropping the operator's job text."""
    body = str(prompt or "").strip()
    if _PREAMBLE_MARK in body:
        return body
    tools = ", ".join(HEARTBEAT_TOOLS)
    return (
        f"{_PREAMBLE_MARK} This is a read-only check-in. "
        f"You may call at most {CRON_MAX_TOOL_CALLS} tools, and only these: {tools}. "
        "Do not start new work, edit files, or use a shell. Then stop. "
        "Reply HEARTBEAT_OK if nothing needs attention, or a short 3-line "
        "summary of what is pending, blocked, or finished.\n\n"
        + body
    )


def job_names_skill(query: str) -> bool:
    """True when the job prompt contains a skill's exact name or alias."""
    try:
        from jaeger_agent.skill_registry.playbook_skills import (
            _ROUTE_WORD,
            available_playbooks,
        )
    except Exception:  # noqa: BLE001 — routing stays off if discovery fails
        return False
    clean = " ".join(_ROUTE_WORD.findall((query or "").lower()))
    if not clean:
        return False
    padded = f" {clean} "
    try:
        skills = available_playbooks(None)
    except Exception:  # noqa: BLE001
        return False
    for skill in skills:
        for name in (skill.name, *skill.aliases):
            norm = " ".join(_ROUTE_WORD.findall((name or "").lower()))
            if norm and f" {norm} " in padded:
                return True
    return False


def cron_auto_route_allowed(query: str) -> bool:
    """Lexical auto-routing is off on cron/heartbeat unless the job names a skill."""
    if not in_cron_turn():
        return True
    return job_names_skill(query)


@contextmanager
def cron_turn_scope(options: dict[str, Any] | None = None, *, session_id: str = "") -> Iterator[None]:
    """Mark this turn as a scheduled check-in and apply its time budget."""
    cron = is_cron_source(options=options, session_id=session_id)
    timeout = None
    if cron:
        raw = (options or {}).get("turn_timeout_s")
        try:
            timeout = float(raw) if raw is not None else cron_turn_timeout_s()
        except (TypeError, ValueError):
            timeout = cron_turn_timeout_s()
        if timeout <= 0:
            timeout = cron_turn_timeout_s()
    token_cron = _cron_turn.set(cron)
    token_timeout = _turn_timeout_s.set(timeout)
    try:
        yield
    finally:
        _cron_turn.reset(token_cron)
        _turn_timeout_s.reset(token_timeout)


def apply_cron_turn(
    prompt: str,
    *,
    session_id: str = "",
    requested: dict[str, Any] | None = None,
    source: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fill cron/heartbeat budgets on an admission or execution dict.

    Heartbeat jobs also get the read-only tool grant and checklist
    preamble. Other cron jobs keep their tools but inherit the step cap
    and time budget.
    """
    requested = dict(requested or {})
    options = dict(requested.get("options") or {})
    src = str(source or options.get("source") or "").strip()
    if not is_cron_source(src, session_id=session_id, options=options):
        return str(prompt or ""), requested
    if not src:
        src = "cron"
    options["source"] = src
    options["background"] = True if options.get("background") is None else options["background"]
    try:
        options["max_tool_calls"] = max(1, int(options.get("max_tool_calls") or CRON_MAX_TOOL_CALLS))
    except (TypeError, ValueError):
        options["max_tool_calls"] = CRON_MAX_TOOL_CALLS
    try:
        options["max_steps"] = max(1, int(options.get("max_steps") or CRON_MAX_STEPS))
    except (TypeError, ValueError):
        options["max_steps"] = CRON_MAX_STEPS
    try:
        options["turn_timeout_s"] = float(options.get("turn_timeout_s") or cron_turn_timeout_s())
    except (TypeError, ValueError):
        options["turn_timeout_s"] = cron_turn_timeout_s()
    requested["options"] = options
    text = str(prompt or "")
    if is_heartbeat_job(session_id=session_id, prompt=text):
        if requested.get("allowed_tools") is None:
            requested["allowed_tools"] = list(HEARTBEAT_TOOLS)
        text = tighten_heartbeat_prompt(text)
    return text, requested
