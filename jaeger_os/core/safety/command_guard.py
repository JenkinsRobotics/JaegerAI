"""Hardline command blocklist — the unconditional floor under run_shell.

``run_shell`` is gated at tier-4 (PRIVILEGED): a human approves every
command. But the tier prompt is the *only* gate — nothing inspects what
the command actually does, and a human approver cannot always parse a
long command. This module is the floor *below* that prompt: a short list
of catastrophic, no-legitimate-use commands refused **unconditionally**,
before the tier check even runs.

It is the one idea worth taking from hermes-agent's much larger
``tools/approval.py`` (see ``docs/hermes_internals_audit.md`` A9). JROS's
6-tier permission model stays the foundation; this is defence-in-depth
under it, in the same spirit as the OSV malware check on package installs.

Deliberately tiny and conservative. Only patterns with **zero**
legitimate use belong here — everything merely risky is the tier
system's job. A false positive (blocking a real command) is worse than
a miss (the human still sees the tier prompt), so when in doubt it is
left out. This is a safety *floor*, not a sandbox: it is not hardened
against an adversary deliberately obfuscating a command.

Scope: ``run_shell`` only. ``run_python`` / ``run_in_venv`` execute
Python, not shell — a shell-pattern blocklist does not apply to them.
"""

from __future__ import annotations

import functools
import re
from typing import Any, Callable

# A command is "in command position" at the start of the line or right
# after a separator / a wrapper like sudo — as opposed to being a mere
# argument. This is what keeps ``echo shutdown`` from tripping the
# shutdown rule: there, ``shutdown`` is an argument, not a command.
_CMD_POS = (
    r"(?:^|[;&|({]|\bsudo\s+|\bdoas\s+|\bxargs\s+(?:-\S+\s+)*"
    r"|\benv\s+(?:\S+=\S+\s+)*|\bnice\s+|\btime\s+)\s*"
)

# Catastrophic targets for a recursive rm — root, home, a top-level
# system directory. /tmp and deep subpaths like /usr/local/<x> are
# deliberately absent: deleting them is bad but not machine-ending, so
# the tier prompt owns those.
_RM_TARGET = re.compile(
    r"(?:^|\s)"
    r"(?:"
    r"/|/\*|~|~/\*?|\$HOME"
    r"|/(?:bin|boot|dev|etc|lib|lib64|opt|proc|root|sbin|srv|sys|usr|var|home)"
    r"|/(?:System|Library|Applications|Users)"
    r")"
    r"(?:/\*?)?"
    r"(?=\s|$)",
    re.IGNORECASE,
)
_RM_CMD = re.compile(_CMD_POS + r"rm\b([^;&|\n]*)", re.IGNORECASE)
_RM_RECURSIVE = re.compile(r"(?:^|\s)-{1,2}\w*r\w*\b", re.IGNORECASE)


def _hardline_rm(norm: str) -> str | None:
    """A recursive ``rm`` aimed at root / home / a system directory.

    Each ``rm`` *segment* (up to the next command separator) is checked
    on its own, so ``rm -rf ./x && cat /etc/hosts`` is not flagged by the
    ``/etc`` in the unrelated ``cat``."""
    for m in _RM_CMD.finditer(norm):
        seg = m.group(1)
        if _RM_RECURSIVE.search(seg) and _RM_TARGET.search(seg):
            return "recursive delete of a root / home / system directory"
    return None


# (compiled pattern, human reason). Checked against the normalised string.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(_CMD_POS + r"mkfs(?:\.\w+)?\b", re.IGNORECASE),
     "format a filesystem (mkfs)"),
    (re.compile(_CMD_POS + r"dd\b[^;&|\n]*\bof=\s*/dev/"
                r"(?:sd|hd|disk|rdisk|nvme|mmcblk|vd|loop)", re.IGNORECASE),
     "dd writing directly to a disk device"),
    (re.compile(r">\s*/dev/(?:sd|hd|disk|rdisk|nvme|mmcblk|vd)\w*",
                re.IGNORECASE),
     "redirect into a raw disk device"),
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
     "fork bomb"),
    (re.compile(_CMD_POS + r"(?:shutdown|reboot|halt|poweroff)\b",
                re.IGNORECASE),
     "shut down or reboot the machine"),
]


def check_hardline(command: str) -> str | None:
    """Return a human reason if ``command`` is hardline-blocked, else None.

    Conservative by design — a return of ``None`` means "not obviously
    catastrophic", **not** "safe": the tier prompt is still the gate."""
    if not command or not command.strip():
        return None
    # Normalise: neutralise quotes / backslashes (defeats trivial
    # `rm -rf "/"` evasion) and collapse whitespace.
    norm = command.strip()
    for ch in ('"', "'", "\\"):
        norm = norm.replace(ch, " ")
    norm = re.sub(r"\s+", " ", norm)

    hit = _hardline_rm(norm)
    if hit:
        return hit
    for pat, reason in _PATTERNS:
        if pat.search(norm):
            return reason
    return None


def hardline_guard(arg_name: str = "command") -> Callable[[Callable], Callable]:
    """Decorator: refuse a hardline-blocked command before the wrapped
    function — and, applied *outside* ``@requires_tier``, before the tier
    prompt — ever runs.

    Apply it OUTERMOST so the hardline check is the very first thing::

        @hardline_guard("command")
        @requires_tier(PermissionTier.PRIVILEGED, ...)
        def run_shell(command: str, ...): ...

    On a hit it returns a tool-result dict (``hardline_blocked: True``)
    and writes the refusal to the audit trail; the wrapped function — and
    the permission prompt it carries — is never reached."""
    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrap(*args: Any, **kwargs: Any) -> Any:
            cmd = kwargs.get(arg_name)
            if cmd is None and args:
                cmd = args[0]
            reason = check_hardline(str(cmd or ""))
            if reason:
                try:
                    from jaeger_os.agent.tools._common import _audit
                    _audit("hardline_block",
                           {"command": str(cmd)[:500], "reason": reason})
                except Exception:  # noqa: BLE001 — audit is best-effort
                    pass
                return {
                    "ok": False,
                    "error": (f"refused — hardline safety block: {reason}. "
                              "This command is catastrophic and is blocked "
                              "unconditionally, below the permission prompt."),
                    "hardline_blocked": True,
                    "command": str(cmd),
                }
            return fn(*args, **kwargs)
        return wrap
    return decorate


__all__ = ["check_hardline", "hardline_guard"]
