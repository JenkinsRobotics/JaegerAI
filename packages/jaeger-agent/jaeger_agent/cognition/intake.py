"""Event intake — turn text becomes a TOLD claim, not a fact.

The loop still talks. This module records *that the user said it* with
explicit provenance so later belief revision can tell hearsay from
observation.
"""

from __future__ import annotations

from typing import Protocol

from jaeger_agent.memory.models import Claim, ProvenanceKind


class ClaimWriter(Protocol):
    """The slice of KnowledgeStore intake needs."""

    def add_claim(self, claim: Claim) -> Claim: ...


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
    return store.add_claim(
        Claim.create(
            subject=subject,
            predicate="said",
            value=value[:2000],
            provenance=ProvenanceKind.TOLD,
            source_id=source_id,
        )
    )


__all__ = ["ClaimWriter", "record_told"]
