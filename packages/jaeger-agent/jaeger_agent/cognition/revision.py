"""Deterministic belief revision. An LLM does not pick the truth.

Claims are authoritative events. Beliefs are a derived projection.
When evidence conflicts at the same provenance rank, the projection is
``contradicted`` — not last-write-wins.
"""

from __future__ import annotations

from collections.abc import Iterable

from jaeger_agent.memory.models import Belief, BeliefStatus, Claim, ProvenanceKind, utc_now_iso


# Higher wins. SYSTEM configuration outranks observation, which outranks
# what someone said, which outranks inference and forecasts.
PROVENANCE_RANK: dict[ProvenanceKind, int] = {
    ProvenanceKind.SYSTEM: 50,
    ProvenanceKind.OBSERVED: 40,
    ProvenanceKind.TOLD: 30,
    ProvenanceKind.INFERRED: 20,
    ProvenanceKind.PREDICTED: 10,
    ProvenanceKind.BELIEVED: 0,
}


def _rank(claim: Claim) -> int:
    prov = claim.provenance
    if isinstance(prov, str):
        prov = ProvenanceKind(prov)
    return PROVENANCE_RANK.get(prov, 0)


def revise_group(claims: Iterable[Claim]) -> Belief | None:
    """One belief for one (subject, predicate). None if no valid claims."""
    valid = [c for c in claims if c.status == "valid"]
    if not valid:
        return None
    subject, predicate = valid[0].subject, valid[0].predicate
    values = {c.value for c in valid}
    ids = [c.id for c in valid]
    now = utc_now_iso()

    if len(values) == 1:
        chosen = valid[0]
        return Belief.create(
            subject=subject,
            predicate=predicate,
            value=chosen.value,
            confidence=max(c.confidence for c in valid),
            status=BeliefStatus.ACTIVE,
            valid_from=min((c.valid_from or now) for c in valid),
            valid_until=None,
            evidence_ids=ids,
        )

    top = max(_rank(c) for c in valid)
    winners = [c for c in valid if _rank(c) == top]
    winner_values = {c.value for c in winners}
    if len(winner_values) == 1:
        chosen = winners[0]
        # Contested by weaker provenance: still hold the ranked value,
        # but drop confidence so the contradiction is visible.
        return Belief.create(
            subject=subject,
            predicate=predicate,
            value=chosen.value,
            confidence=min(0.7, max(c.confidence for c in winners)),
            status=BeliefStatus.ACTIVE,
            valid_from=chosen.valid_from,
            evidence_ids=ids,
        )

    # Same-rank conflict: do not pick a winner.
    sample = winners[0]
    belief = Belief.create(
        subject=subject,
        predicate=predicate,
        value="|".join(sorted(winner_values)),
        confidence=0.0,
        status=BeliefStatus.CONTRADICTED,
        valid_from=sample.valid_from,
        evidence_ids=ids,
    )
    return belief


def revise_all(claims: Iterable[Claim]) -> list[Belief]:
    grouped: dict[tuple[str, str], list[Claim]] = {}
    for claim in claims:
        grouped.setdefault((claim.subject, claim.predicate), []).append(claim)
    out: list[Belief] = []
    for group in grouped.values():
        belief = revise_group(group)
        if belief is not None:
            out.append(belief)
    return out


__all__ = ["PROVENANCE_RANK", "revise_all", "revise_group"]
