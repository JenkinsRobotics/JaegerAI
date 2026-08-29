"""Operator-defined shell hooks, including a blocking pre-tool gate.

Ported from hermes-agent ``agent/shell_hooks.py``. hermes-agent is MIT
licensed:

    Copyright (c) 2025 Nous Research

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions: the above copyright notice and this
    permission notice shall be included in all copies or substantial
    portions of the Software.

WHY. Jaeger's permission model is richer than the donor's — six typed tiers
with a policy layer, versus 59 hand-maintained command regexes. But it is
*compiled in*: an operator who wants a site-specific rule ("never let it touch
this path", "log every external effect to our SIEM", "refuse writes during a
deploy freeze") has to edit Python. This module is the missing operator seam.

WIRE PROTOCOL, carried over from the donor unchanged so hooks are portable
between the two agents.

**stdin** — one JSON document::

    {
        "hook_event_name": "pre_tool_call",
        "tool_name":       "terminal",
        "tool_input":      {"command": "rm -rf /"},
        "session_id":      "sess_abc123",
        "cwd":             "/home/user/project",
        "extra":           {}
    }

**stdout** — optional JSON; anything else is ignored::

    {"decision": "block", "reason": "path is frozen during deploys"}

**exit code** — ``2`` blocks. Any other code allows.

BLOCKING IS NARROW BY DESIGN. Only ``pre_tool_call`` can veto, because it is
the only event that fires before anything has happened. A "block" from
``post_tool_call`` would be a lie — the side effect already occurred — so it
is logged and ignored rather than silently pretending the call did not happen.

SAFETY PROPERTIES, all inherited from the donor:

  - ``shlex.split`` + ``shell=False``. No shell, so no injection through a
    crafted tool argument. Operators who want pipes wrap them in a script.
  - **First-use consent.** Each ``(event, command)`` pair must be approved
    once and is recorded in ``<instance>/shell-hooks-allowlist.json``. A
    config file alone cannot make Jaeger execute a new program — this matters
    because config may be synced, restored from backup, or written by the
    agent itself.
  - **Non-interactive callers must opt in** via ``JAEGER_ACCEPT_HOOKS=1``, so
    the daemon does not silently self-approve new hooks at 3am.
  - **A hook that fails does not block**, except on ``pre_tool_call``, where a
    timeout or crash is treated as a *block*. That asymmetry is deliberate:
    for the one event whose purpose is to deny, an engine that cannot answer
    must not be read as consent.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Exit code a hook uses to veto. Donor-compatible.
BLOCK_EXIT_CODE = 2

# Only this event may veto — see module docstring.
BLOCKING_EVENTS: frozenset[str] = frozenset({"pre_tool_call"})

EVENTS: frozenset[str] = frozenset({
    "pre_tool_call",
    "post_tool_call",
    "on_session_start",
    "on_session_end",
})

_DEFAULT_TIMEOUT = 10
_ALLOWLIST_NAME = "shell-hooks-allowlist.json"


@dataclass(frozen=True)
class HookSpec:
    """One configured ``(event, command)`` pair."""

    event: str
    command: str
    timeout: int = _DEFAULT_TIMEOUT
    # Only fire for these tools (empty = all). Keeps a per-tool gate from
    # paying subprocess cost on every unrelated call.
    tools: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, tool_name: str) -> bool:
        return not self.tools or tool_name in self.tools


@dataclass(frozen=True)
class HookDecision:
    """The aggregate verdict for one event."""

    blocked: bool = False
    reason: str = ""

    def __bool__(self) -> bool:  # `if decision:` reads as "was it blocked"
        return self.blocked


# ---------------------------------------------------------------------------
# Config + consent
# ---------------------------------------------------------------------------

def _layout() -> Any:
    from jaeger_agent.workspace import get_layout

    return get_layout()


def hooks_enabled() -> bool:
    """Master switch. Off unless the instance config turns it on.

    Env override ``JAEGER_SHELL_HOOKS=0`` force-disables, which gives an
    operator a way to boot past a hook that is itself broken without editing
    config (the donor learned this the hard way — a blocking hook with a bug
    can lock the agent out of every tool call).
    """
    val = os.environ.get("JAEGER_SHELL_HOOKS", "").strip().lower()
    if val in ("0", "false", "no", "off"):
        return False
    if val in ("1", "true", "yes", "on"):
        return True
    try:
        cfg = _config()
        return bool(getattr(getattr(cfg, "hooks", None), "enabled", False))
    except Exception:
        return False


def _config() -> Any:
    """The instance config, via the mtime-cached reader (this runs before
    every tool call, so an uncached YAML parse here would be a real cost)."""
    from jaeger_agent import instance_config

    return instance_config.load()


def configured_hooks(event: str) -> list[HookSpec]:
    """Hook specs for *event*, from the instance config. Never raises."""
    if event not in EVENTS:
        return []
    try:
        block = getattr(_config(), "hooks", None)
        raw = list(getattr(block, event, None) or [])
    except Exception as exc:
        logger.debug("shell_hooks: config read failed (%s)", exc)
        return []

    out: list[HookSpec] = []
    for item in raw:
        if isinstance(item, str):
            out.append(HookSpec(event=event, command=item))
        elif isinstance(item, dict):
            cmd = str(item.get("command", "")).strip()
            if not cmd:
                continue
            try:
                timeout = max(1, int(item.get("timeout", _DEFAULT_TIMEOUT)))
            except (TypeError, ValueError):
                timeout = _DEFAULT_TIMEOUT
            tools = tuple(str(t) for t in (item.get("tools") or ()))
            out.append(HookSpec(event=event, command=cmd, timeout=timeout,
                                tools=tools))
    return out


def _allowlist_path() -> Path:
    return Path(_layout().root) / _ALLOWLIST_NAME


def _load_allowlist() -> dict[str, Any]:
    try:
        p = _allowlist_path()
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _entry_key(event: str, command: str) -> str:
    return f"{event}\x00{command}"


def is_allowlisted(event: str, command: str) -> bool:
    return _entry_key(event, command) in _load_allowlist()


def approve(event: str, command: str) -> None:
    """Record consent for one ``(event, command)`` pair."""
    from datetime import datetime, timezone

    data = _load_allowlist()
    data[_entry_key(event, command)] = {
        "event": event,
        "command": command,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    p = _allowlist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def revoke(command: str) -> int:
    """Drop every approval for *command*. Returns how many were removed."""
    data = _load_allowlist()
    doomed = [k for k, v in data.items()
              if isinstance(v, dict) and v.get("command") == command]
    for k in doomed:
        data.pop(k, None)
    if doomed:
        p = _allowlist_path()
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(p)
    return len(doomed)


def _auto_accept() -> bool:
    return os.environ.get("JAEGER_ACCEPT_HOOKS", "").strip().lower() in (
        "1", "true", "yes", "on")


def _consented(spec: HookSpec) -> bool:
    """Whether this hook may run. Unapproved hooks are skipped, not prompted:
    the dispatch path runs inside a tool call, which may be a daemon beat with
    nobody watching. ``jaeger hooks approve`` is the interactive route."""
    if is_allowlisted(spec.event, spec.command):
        return True
    if _auto_accept():
        approve(spec.event, spec.command)
        logger.info("shell_hooks: auto-approved %s → %s (JAEGER_ACCEPT_HOOKS)",
                    spec.event, spec.command)
        return True
    logger.warning(
        "shell_hooks: %s hook %r is not approved — skipped. Approve it with "
        "`jaeger hooks approve %s %r`, or set JAEGER_ACCEPT_HOOKS=1.",
        spec.event, spec.command, spec.event, spec.command)
    return False


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _payload(
    event: str,
    tool_name: str,
    tool_input: Any,
    extra: dict[str, Any] | None,
) -> str:
    from jaeger_agent.workspace import get_current_session, get_project_root

    try:
        session = get_current_session()
    except Exception:
        session = ""
    try:
        cwd = str(get_project_root() or Path.cwd())
    except Exception:
        cwd = ""
    return json.dumps({
        "hook_event_name": event,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session,
        "cwd": cwd,
        "extra": extra or {},
    }, default=str)


def _run_one(spec: HookSpec, payload: str) -> HookDecision:
    """Run one hook. Returns its decision for blocking events."""
    blocking = spec.event in BLOCKING_EVENTS
    try:
        argv = shlex.split(os.path.expanduser(spec.command))
    except ValueError as exc:
        logger.error("shell_hooks: unparseable command %r (%s)", spec.command, exc)
        # An unparseable blocking hook cannot answer, so it must not consent.
        return HookDecision(True, f"hook command is unparseable: {exc}") \
            if blocking else HookDecision()
    if not argv:
        return HookDecision()

    try:
        proc = subprocess.run(
            argv, input=payload, capture_output=True, text=True,
            timeout=spec.timeout, shell=False,
        )
    except subprocess.TimeoutExpired:
        logger.error("shell_hooks: %s hook %r timed out after %ss",
                     spec.event, spec.command, spec.timeout)
        return HookDecision(True, f"hook timed out after {spec.timeout}s") \
            if blocking else HookDecision()
    except Exception as exc:
        logger.error("shell_hooks: %s hook %r failed to run: %s",
                     spec.event, spec.command, exc)
        return HookDecision(True, f"hook failed to run: {exc}") \
            if blocking else HookDecision()

    reason = ""
    decision_block = False
    out = (proc.stdout or "").strip()
    if out:
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict):
                reason = str(parsed.get("reason", "") or "")
                decision_block = str(
                    parsed.get("decision", "")).lower() == "block"
        except json.JSONDecodeError:
            # Free-form stdout is allowed and ignored — a hook that just logs
            # should not need to speak JSON.
            pass

    if proc.returncode == BLOCK_EXIT_CODE or decision_block:
        if not blocking:
            logger.warning(
                "shell_hooks: %s hook %r asked to block, but %s cannot veto "
                "(the call already happened) — ignoring the block",
                spec.event, spec.command, spec.event)
            return HookDecision()
        return HookDecision(True, reason or
                            f"blocked by {spec.event} hook: {spec.command}")
    return HookDecision()


def fire(
    event: str,
    *,
    tool_name: str = "",
    tool_input: Any = None,
    extra: dict[str, Any] | None = None,
) -> HookDecision:
    """Run every approved hook for *event*.

    Returns the first block for a blocking event; otherwise a clean decision.
    Never raises — a hook layer that can break the agent is worse than no
    hook layer, with the single exception that a blocking hook which cannot
    produce an answer counts as a block.
    """
    if not hooks_enabled():
        return HookDecision()
    try:
        specs = [s for s in configured_hooks(event) if s.matches(tool_name)]
    except Exception as exc:
        logger.debug("shell_hooks: spec lookup failed (%s)", exc)
        return HookDecision()
    if not specs:
        return HookDecision()

    payload = _payload(event, tool_name, tool_input, extra)
    for spec in specs:
        if not _consented(spec):
            continue
        decision = _run_one(spec, payload)
        if decision.blocked:
            return decision
    return HookDecision()


__all__ = [
    "BLOCKING_EVENTS", "BLOCK_EXIT_CODE", "EVENTS",
    "HookDecision", "HookSpec",
    "approve", "configured_hooks", "fire", "hooks_enabled",
    "is_allowlisted", "revoke",
]
