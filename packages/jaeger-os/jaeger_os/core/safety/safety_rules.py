"""Deterministic safety — the hash-chained audit log.

This module holds the safety pillar that fires WITHOUT a model in the
loop: an append-only, hash-chained audit log of every gated decision.

The 4-pillar safety stack splits by whether a pillar needs an agent:

  1. Identity prompt (Three Laws)  — :mod:`jaeger_os.agent.safety`  (agent)
  2. Tier gating                   — :mod:`.permissions`            (core)
  3. Safety review (LLM-as-judge)  — :mod:`jaeger_os.agent.safety`  (agent)
  4. Audit log                     — :class:`AuditLogger`, here     (core)

Pillars 1 & 3 require an LLM to interpret them, so they live in
``agent/safety.py``. Pillars 2 & 4 are deterministic enforcement and
stay in ``core/safety/``. See ``docs/unified_architecture.md`` §7.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_os.core.safety.permissions import PermissionRequest


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
]
