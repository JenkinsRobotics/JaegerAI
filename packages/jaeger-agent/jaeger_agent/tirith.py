"""Tirith pre-exec content scanning.

Ported from hermes-agent ``tools/tirith_security.py``. hermes-agent is MIT
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

WHAT IT ADDS. Jaeger's ``command_guard`` and the destructive-command regex in
``safety.py`` match on the *shape* of a command. Tirith scans its *content* —
homograph/lookalike URLs, pipe-to-interpreter, terminal escape injection —
which is the class of thing a regex over command text keeps missing.

VERDICT CONTRACT, from the donor and unchanged::

    exit 0 → allow      exit 1 → block      exit 2 → warn

The exit code is the source of truth. JSON on stdout enriches findings and
summary but NEVER overrides the verdict, so a scanner that emits malformed
JSON still gets its block honoured.

THE CIRCUIT BREAKER IS NOT OPTIONAL. The donor added it for its issue #41400:
a missing or corrupted binary makes every tool call hit the same spawn
failure, fail open, and get retried, hanging the user for 20+ minutes. After
:data:`_CRASH_LIMIT` consecutive failures this module stops trying for the
rest of the process.

DELIBERATELY NOT PORTED: the donor's auto-installer, which downloads a
release tarball from GitHub and executes the binary it contains. Its checksum
and cosign verification are good, but "fetch and run a binary from the network
without being asked" is a supply-chain decision that belongs to the operator,
not to a security feature that is itself supposed to reduce risk. Here the
binary must already be on PATH or named by ``tirith.path``; when it is absent
the layer reports unavailable and (by default) fails open, exactly as the
donor does when its install has failed.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_MAX_FINDINGS = 20
_MAX_SUMMARY_LEN = 2000
_DEFAULT_TIMEOUT = 5
#: Consecutive failures before this process stops trying. See the module
#: docstring — without this a broken binary turns into a retry hang.
_CRASH_LIMIT = 3

ALLOW = "allow"
WARN = "warn"
BLOCK = "block"

_crash_count = 0
_circuit_open = False
_warned: set[str] = set()


@dataclass(frozen=True)
class ScanResult:
    action: str = ALLOW
    summary: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action == BLOCK


def reset_state() -> None:
    """Clear the circuit breaker and warning dedup. Test seam."""
    global _crash_count, _circuit_open
    _crash_count = 0
    _circuit_open = False
    _warned.clear()


def _warn_once(key: str, msg: str, *args: Any) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(msg, *args)


def _record_crash() -> None:
    global _crash_count, _circuit_open
    _crash_count += 1
    if _crash_count >= _CRASH_LIMIT and not _circuit_open:
        _circuit_open = True
        logger.warning(
            "tirith: %d consecutive failures — disabling scans for the rest "
            "of this process (circuit breaker)", _crash_count)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _cfg() -> Any:
    from jaeger_agent import instance_config

    return instance_config.section("tirith")


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def enabled() -> bool:
    block = _cfg()
    return _env_bool("JAEGER_TIRITH", bool(getattr(block, "enabled", False)))


def fail_open() -> bool:
    """Whether an unavailable scanner allows the command.

    Defaults to True, matching the donor: a security *enrichment* layer that
    is merely unavailable should not brick the agent. An operator running
    untrusted input can set it False to require a working scanner.
    """
    block = _cfg()
    return _env_bool("JAEGER_TIRITH_FAIL_OPEN",
                     bool(getattr(block, "fail_open", True)))


def binary_path() -> str | None:
    """Resolve the tirith binary, or None when it is not installed."""
    configured = str(getattr(_cfg(), "path", "") or
                     os.environ.get("JAEGER_TIRITH_PATH", "")).strip()
    if configured:
        return configured if os.path.isfile(configured) else None
    return shutil.which("tirith")


def _timeout() -> int:
    try:
        return max(1, int(getattr(_cfg(), "timeout_s", _DEFAULT_TIMEOUT)))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def _unavailable(reason: str) -> ScanResult:
    if fail_open():
        return ScanResult(ALLOW, f"tirith unavailable: {reason}")
    return ScanResult(BLOCK, f"tirith unavailable, failing closed: {reason}")


def scan_command(command: str) -> ScanResult:
    """Scan *command* for content-level threats.

    Returns a :class:`ScanResult`. Never raises for operational problems —
    a spawn failure, timeout or unknown exit code is resolved by the
    ``fail_open`` policy — so callers can treat this as a pure verdict.
    """
    global _crash_count

    if not enabled():
        return ScanResult()
    if _circuit_open:
        return ScanResult(ALLOW, "tirith disabled (circuit breaker)")
    if not (command or "").strip():
        return ScanResult()

    exe = binary_path()
    if not exe:
        _warn_once("tirith_missing",
                   "tirith is enabled but the binary was not found on PATH "
                   "(set tirith.path, or install it) — scans are inactive")
        _record_crash()
        return _unavailable("binary not found")

    timeout = _timeout()
    try:
        proc = subprocess.run(
            [exe, "scan", "--json", "-"],
            input=command, capture_output=True, text=True,
            timeout=timeout, shell=False,
        )
    except subprocess.TimeoutExpired:
        _warn_once(f"tirith_timeout:{timeout}",
                   "tirith timed out after %ds", timeout)
        _record_crash()
        return _unavailable(f"timed out after {timeout}s")
    except Exception as exc:
        _warn_once(f"tirith_spawn:{type(exc).__name__}",
                   "tirith spawn failed: %s", exc)
        _record_crash()
        return _unavailable(str(exc))

    code = proc.returncode
    if code == 0:
        action = ALLOW
        _crash_count = 0          # a clean run resets the breaker
    elif code == 1:
        action = BLOCK
        _crash_count = 0
    elif code == 2:
        action = WARN
        _crash_count = 0
    else:
        # Includes signal deaths (-11/SIGSEGV). Not a verdict — an operational
        # failure, so the fail_open policy decides.
        logger.warning("tirith returned unexpected exit code %d", code)
        _record_crash()
        return _unavailable(f"unexpected exit code {code}")

    # JSON enriches, never overrides. A scanner that blocks but emits garbage
    # still blocks — losing the reason is acceptable, losing the block is not.
    findings: list[dict[str, Any]] = []
    summary = ""
    try:
        data = json.loads(proc.stdout) if (proc.stdout or "").strip() else {}
        if isinstance(data, dict):
            raw = data.get("findings") or []
            if isinstance(raw, list):
                findings = [f for f in raw[:_MAX_FINDINGS] if isinstance(f, dict)]
            summary = str(data.get("summary") or "")[:_MAX_SUMMARY_LEN]
    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.debug("tirith: JSON parse failed; using exit code only")
        if action == BLOCK:
            summary = "security issue detected (details unavailable)"
        elif action == WARN:
            summary = "security warning detected (details unavailable)"

    return ScanResult(action, summary, findings)


__all__ = [
    "ALLOW", "BLOCK", "WARN", "ScanResult",
    "binary_path", "enabled", "fail_open", "reset_state", "scan_command",
]
