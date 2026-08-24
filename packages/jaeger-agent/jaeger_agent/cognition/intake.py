"""Event intake — turn text becomes a TOLD claim, not a fact.

The loop still talks. This module records *that the user said it* with
explicit provenance so later belief revision can tell hearsay from
observation.
"""

from __future__ import annotations

import re
from typing import Protocol

from jaeger_agent.memory.models import Claim, Entity, ProvenanceKind


class ClaimWriter(Protocol):
    """The slice of KnowledgeStore intake needs."""

    def add_claim(self, claim: Claim) -> Claim: ...


def link_known_people_mentions(store: ClaimWriter, text: str, *, source_id: str) -> list[Entity]:
    """Record deterministic mentions of people already known to EntityStore.

    This deliberately does not guess novel names. Existing contacts/entities
    supply the ontology; word-boundary matching merely records that the person
    appeared in this intake event.
    """
    list_entities = getattr(store, "list_entities", None)
    save_entity = getattr(store, "save_entity", None)
    if not callable(list_entities) or not callable(save_entity):
        return []
    value = text or ""
    found: list[Entity] = []
    for entity in list_entities(kind="person"):
        names = [entity.name, *entity.aliases]
        if not any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", value, re.IGNORECASE) for name in names if name):
            continue
        entity.attributes["last_mentioned_source"] = source_id
        save_entity(entity)
        store.add_claim(Claim.create(
            subject="user", predicate="mentioned_person", value=entity.id,
            provenance=ProvenanceKind.TOLD, source_id=source_id,
            metadata={"entity_name": entity.name},
        ))
        found.append(entity)
    return found


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
    link_known_people_mentions(store, value, source_id=source_id)
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


__all__ = ["ClaimWriter", "extract_told_propositions", "link_known_people_mentions", "record_told"]
