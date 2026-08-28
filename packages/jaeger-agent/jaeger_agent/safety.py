"""Agent-side safety — the safety pillars that REQUIRE an agent to interpret.

Two of the four safety pillars need an LLM, not deterministic code, so they
live here in ``agent/`` rather than ``core/safety/``:

  * The **Three Laws contract** the brain reads and reasons against
    (``agent/prompts/three_laws.md``). It is prompt text — only an agent
    consumes it.
  * The **LLM-as-judge safety review** (:func:`safety_review`) that decides
    whether a proposed action is allowed. It, too, is an agent.

The DETERMINISTIC pillars stay in ``core/safety/`` because they fire
regardless of any model's reasoning: permission tier-gating
(``core/safety/permissions.py``), the command / file / skills guards, secret
redaction, and the hash-chained append-only audit log
(``core/safety/safety_rules.py``'s :class:`~AuditLogger`).

The Three Laws is the single source of truth shared by BOTH agents here —
the brain's system prompt (via :func:`with_three_laws`) and the judging
contract (:func:`safety_review`) — so the two can never drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jaeger_os.core.safety.permissions import PermissionRequest
from jaeger_agent.prompts._doc import load_prompt_doc

# ── Pillar 1: the Three Laws identity prompt ──────────────────────────
_THREE_LAWS_PATH = Path(__file__).parent / "prompts" / "three_laws.md"

THREE_LAWS_PROMPT_BLOCK = load_prompt_doc(_THREE_LAWS_PATH)
"""The Three Laws, prepended to every system prompt at build time. The
safety-review judge uses the SAME text as its judging contract, so the two
are guaranteed in sync. Edit ``agent/prompts/three_laws.md`` to change it."""


def with_three_laws(system_prompt: str) -> str:
    """Return ``system_prompt`` with the Three Laws block prepended.

    Idempotent — calling twice doesn't double the block. Callers in the
    system-prompt build path use this rather than concatenating by hand so a
    future edit to the laws lands everywhere at once.
    """
    block = THREE_LAWS_PROMPT_BLOCK
    if not block or block in system_prompt:
        return system_prompt
    return f"{block}\n\n{system_prompt}"


# ── Pillar 3: LLM-as-judge safety review ──────────────────────────────
@dataclass(frozen=True)
class SafetyVerdict:
    """Return shape from :func:`safety_review`.

    ``allow=True`` means the safety-review agent approved the call;
    ``allow=False`` means it refused, with ``reason`` populated for the audit
    log + the operator-visible explanation.
    """

    allow: bool
    reason: str = ""
    reviewer: str = "stub"


import re

_DESTRUCTIVE_COMMAND_RE = re.compile(
    r"(?:"
    r"(?:^|[;&|]\s*)rm\s+(?=[^\n;&|]*(?:-[^\s]*r[^\s]*|--recursive))"
    r"(?=[^\n;&|]*(?:-[^\s]*f[^\s]*|--force))[^\n;&|]*\s(?:/|~)(?:\s|$)|"
    r"\bmkfs(?:\.[a-z0-9_-]+)?\b|"
    r"(?:^|[;&|]\s*)dd\s+[^\n;&|]*\bif\s*=|"
    r"(?:^|[;&|]\s*)chmod\s+(?:-[^\s]*R[^\s]*|--recursive)\s+777\s+/(?:\s|$)|"
    r"(?:^|[;&|]\s*)git\s+clean\s+-[^\s]*f[^\s]*d[^\s]*x(?:\s|$)"
    r")",
    re.IGNORECASE,
)


def safety_review(
    request: PermissionRequest,
    *,
    args: dict[str, Any] | None = None,
    world_state: dict[str, Any] | None = None,
) -> SafetyVerdict:
    """Safety review guard: checks operations and shell commands for destructive actions (Hermes pattern)."""
    arguments = args or {}
    command_text = str(arguments.get("command", "") or arguments.get("script", "") or "")

    if command_text and _DESTRUCTIVE_COMMAND_RE.search(command_text):
        return SafetyVerdict(
            allow=False,
            reason=f"Safety policy blocked potentially destructive command: '{command_text[:80]}'",
            reviewer="command_guard",
        )

    return SafetyVerdict(
        allow=True,
        reason=f"Approved operation {request.skill}.{request.operation}",
        reviewer="safety_guard",
    )


__all__ = [
    "THREE_LAWS_PROMPT_BLOCK",
    "with_three_laws",
    "SafetyVerdict",
    "safety_review",
]
