"""Event intake — turn text becomes a TOLD claim, not a fact.

The loop still talks. This module records *that the user said it* with
explicit provenance so later belief revision can tell hearsay from
observation.
"""

from __future__ import annotations

import re
from typing import Protocol

from jaeger_agent.memory.models import Claim, ProvenanceKind


class ClaimWriter(Protocol):
    """The slice of KnowledgeStore intake needs."""

    def add_claim(self, claim: Claim) -> Claim: ...


# Conservative, deterministic. "my editor is neovim" → (user, editor, neovim).
_MY_IS = re.compile(
    r"\bmy\s+([a-z][a-z0-9_-]{1,32})\s+is\s+(.+?)(?:[.!?]|$)",
    re.IGNORECASE,
)


def extract_told_propositions(
    text: str, *, subject: str = "user"
) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for match in _MY_IS.finditer(text or ""):
        predicate = match.group(1).strip().lower()
        value = match.group(2).strip()
        if predicate and value:
            out.append((subject, predicate, value[:200]))
    return out


def record_told(
    store: ClaimWriter,
    text: str,
    *,
    source_id: str = "user",
    subject: str = "user",
) -> Claim | None:
    value = (text or "").strip()
    if not value:
        return None
    said = store.add_claim(
        Claim.create(
            subject=subject,
            predicate="said",
            value=value[:2000],
            provenance=ProvenanceKind.TOLD,
            source_id=source_id,
        )
    )
    for subj, predicate, extracted in extract_told_propositions(value, subject=subject):
        store.add_claim(
            Claim.create(
                subject=subj,
                predicate=predicate,
                value=extracted,
                provenance=ProvenanceKind.TOLD,
                source_id=source_id,
            )
        )
    return said


__all__ = ["ClaimWriter", "extract_told_propositions", "record_told"]
