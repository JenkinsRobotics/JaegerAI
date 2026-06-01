"""4-pillar safety stack — primitives.

The four pillars of the unified safety architecture, surfaced here
as the machinery later code paths reach for. Phase 1 ships the
primitives. Wiring (system-prompt prepend, audit-log writes on every
gated decision, safety-review-agent invocation on high-tier calls)
lands as later phase chunks reach the agent loop.

Pillar map:

  1. Identity prompt    — :data:`THREE_LAWS_PROMPT_BLOCK`
  2. Tier gating        — :mod:`.permissions` (the ``@requires_tier`` decorator)
  3. Safety review      — :func:`safety_review` (LLM-as-judge stub)
  4. Audit log          — :class:`AuditLogger` (append-only, hash-chained)

See ``docs/unified_architecture.md`` §7 Safety architecture for the
composition story and per-tier overhead expectations.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_os.core.safety.permissions import PermissionRequest, PermissionTier


# ── Pillar 1: identity prompt ─────────────────────────────────────────

THREE_LAWS_PROMPT_BLOCK = """\
SAFETY CONTRACT — read this before every decision.

You operate under three laws, in priority order:

  1. You will not, by action or inaction, cause harm to a human being.
  2. You will obey orders from your operator EXCEPT where those orders
     conflict with the First Law.
  3. You will protect your own continued operation EXCEPT where doing
     so would conflict with the First or Second Law.

These laws bind every tool call you make. When in doubt, refuse or
ask the operator. You may not edit, hide, or work around this
contract; an independent safety review will see your reasoning and
the audit log records every gated decision.
"""
"""Three Laws prepended to every system prompt at build time. Identity-
prompt pillar (#1) of the 4-pillar safety stack. Source of truth for
the safety contract surface the agent reads; the safety-review agent
(#3) uses the SAME text as its judging contract so the two are
guaranteed in sync."""


def with_three_laws(system_prompt: str) -> str:
    """Return ``system_prompt`` with the Three Laws block prepended.

    Idempotent — calling twice doesn't double the block. Callers in
    the system-prompt build path use this rather than concatenating
    by hand so a future edit to the laws lands everywhere at once.
    """
    if THREE_LAWS_PROMPT_BLOCK in system_prompt:
        return system_prompt
    return f"{THREE_LAWS_PROMPT_BLOCK}\n\n{system_prompt}"


# ── Pillar 3: safety review ───────────────────────────────────────────


@dataclass(frozen=True)
class SafetyVerdict:
    """Return shape from :func:`safety_review`.

    ``allow=True`` means the safety-review agent approved the call;
    ``allow=False`` means it refused, with ``reason`` populated for
    the audit log + the operator-visible explanation.
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

    The real implementation invokes an independent agent with the
    Three Laws as system prompt, the proposed action, and the
    available world state (e.g. "human detected in workspace zone"),
    and returns ``SafetyVerdict(allow=False, reason=...)`` for any
    action it judges unsafe.

    Wiring this into the agent loop on tier 2-3 calls lands in a
    later phase chunk. Calling it now returns auto-approve so the
    interface is exercisable.
    """
    return SafetyVerdict(
        allow=True,
        reason=f"phase-1 stub: auto-approving {request.skill}.{request.operation}",
        reviewer="stub",
    )


# ── Pillar 4: audit log (hash-chained, append-only) ───────────────────


@dataclass
class AuditLogger:
    """Append-only audit log with a hash chain.

    Every gated decision (allow / prompt / deny / safety-review-allow /
    safety-review-deny) writes one entry. Entries carry a SHA-256 of
    ``(prev_hash || payload)`` so a tampered or truncated file can be
    detected: re-walk the file from top, recomputing each entry's hash;
    a mismatch means someone wrote outside our API or deleted lines.

    Phase-1 surface — minimal. Wiring (calls from the agent loop on
    every tier check) lands in a later chunk. Tests can exercise the
    primitive directly today.

    Attributes:
        path: Target log file. Parent dir is created on first write.
        prev_hash: Hex digest of the previous entry, or ``"GENESIS"``
            on first write. Updated in-memory after each append.
    """

    path: Path
    prev_hash: str = "GENESIS"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append(
        self,
        *,
        kind: str,
        request: PermissionRequest,
        outcome: str,
        detail: dict[str, Any] | None = None,
    ) -> str:
        """Append one audit entry. Returns the entry's hash.

        ``kind`` is the gate that fired (``"tier_check"``,
        ``"safety_review"``, ``"confirmation_prompt"``, etc.).
        ``outcome`` is the result (``"allow"``, ``"deny"``,
        ``"prompt_approved"``, ``"prompt_refused"``, ...).

        Concurrent-safe via the internal lock: in-process writers see
        a consistent ``prev_hash`` chain. Cross-process safety needs an
        fcntl flock on top — wire that in when multi-process audit
        becomes a real use case.
        """
        with self._lock:
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "kind": kind,
                "skill": request.skill,
                "operation": request.operation,
                "tier": request.tier.name,
                "outcome": outcome,
                "detail": detail or {},
                "prev_hash": self.prev_hash,
            }
            encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
            entry_hash = hashlib.sha256(
                self.prev_hash.encode("utf-8") + encoded
            ).hexdigest()
            payload["hash"] = entry_hash

            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
            self.prev_hash = entry_hash
            return entry_hash

    def verify(self) -> bool:
        """Walk the log from top, recomputing hashes. Returns True iff
        every entry's recorded hash matches the recomputed value AND
        each ``prev_hash`` matches the previous entry's hash.

        A tampered or truncated file returns False. Useful in tests
        and as a periodic integrity check on production logs.
        """
        if not self.path.exists():
            return True  # nothing to verify yet
        expected_prev = "GENESIS"
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                stored_hash = entry.pop("hash")
                if entry.get("prev_hash") != expected_prev:
                    return False
                encoded = json.dumps(entry, ensure_ascii=True, sort_keys=True).encode("utf-8")
                recomputed = hashlib.sha256(
                    expected_prev.encode("utf-8") + encoded
                ).hexdigest()
                if recomputed != stored_hash:
                    return False
                expected_prev = stored_hash
        return True


# ── Public surface ────────────────────────────────────────────────────


__all__ = [
    "AuditLogger",
    "SafetyVerdict",
    "THREE_LAWS_PROMPT_BLOCK",
    "PermissionTier",
    "safety_review",
    "with_three_laws",
]
