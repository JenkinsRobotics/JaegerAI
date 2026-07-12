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
from jaeger_ai.agent.prompts._doc import load_prompt_doc

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


def safety_review(
    request: PermissionRequest,
    *,
    args: dict[str, Any] | None = None,
    world_state: dict[str, Any] | None = None,
) -> SafetyVerdict:
    """LLM-as-judge stub. Phase-1 placeholder — always allows.

    The real implementation invokes an independent agent with the Three Laws
    as system prompt, the proposed action, and the available world state
    (e.g. "human detected in workspace zone"), and returns
    ``SafetyVerdict(allow=False, reason=…)`` for any action it judges unsafe.

    Wiring this into the agent loop on tier 2-3 calls lands in a later phase
    chunk. Calling it now returns auto-approve so the interface is
    exercisable.
    """
    return SafetyVerdict(
        allow=True,
        reason=f"phase-1 stub: auto-approving {request.skill}.{request.operation}",
        reviewer="stub",
    )


__all__ = [
    "THREE_LAWS_PROMPT_BLOCK",
    "with_three_laws",
    "SafetyVerdict",
    "safety_review",
]
