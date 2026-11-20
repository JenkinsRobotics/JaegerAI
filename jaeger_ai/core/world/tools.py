"""Agent tools for Truth's epistemic world-state store.

Uses ``operator_state_root() / "knowledge.sqlite3"`` so isolated tests and
scratch Gateways never touch the operator's live knowledge store.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jaeger_ai.core.instance.instance import operator_state_root
from jaeger_ai.core.world.model import EpistemicProvenance
from jaeger_ai.core.world.store import SqliteWorldStore


def _world_store(db_path: Path | str | None = None) -> SqliteWorldStore:
    target = Path(db_path) if db_path is not None else (operator_state_root() / "knowledge.sqlite3")
    return SqliteWorldStore(target)


def knowledge_record_claim(
    subject: str,
    predicate: str,
    value: str,
    provenance: str = "observed",
    confidence: float = 0.8,
    source_id: str = "truth_agent",
    evidence_snippet: str = "",
    evidence_uri: str = "",
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Record a typed epistemic claim and report any immediate contradictions."""
    subj = (subject or "").strip()
    pred = (predicate or "").strip()
    val = str(value or "").strip()
    if not subj or not pred or not val:
        return {"ok": False, "error": "subject, predicate, and value are required"}
    try:
        prov = EpistemicProvenance(str(provenance or "observed").strip().lower())
    except ValueError:
        valid = [p.value for p in EpistemicProvenance]
        return {"ok": False, "error": f"invalid provenance {provenance!r}; choose from {valid}"}

    store = _world_store(db_path)
    claim = store.record_claim(
        subj,
        pred,
        val,
        prov,
        confidence=float(confidence),
        source_id=(source_id or "truth_agent").strip(),
    )
    evidence_id: str | None = None
    if evidence_snippet.strip() or evidence_uri.strip():
        evi = store.link_evidence(
            claim.claim_id,
            source_type="tool_observation",
            source_id=(source_id or "truth_agent").strip(),
            snippet=evidence_snippet.strip(),
            uri=evidence_uri.strip() or None,
        )
        evidence_id = evi.evidence_id
    contradictions = store.find_contradictions(subject=subj, predicate=pred)
    return {
        "ok": True,
        "claim_id": claim.claim_id,
        "subject": claim.subject,
        "predicate": claim.predicate,
        "value": claim.value,
        "provenance": claim.provenance.value,
        "confidence": claim.confidence,
        "evidence_id": evidence_id,
        "contradictions": contradictions,
    }


def knowledge_query(
    query: str = "",
    subject: str = "",
    include_inactive: bool = False,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Search or inspect epistemic claims in Truth's knowledge store."""
    store = _world_store(db_path)
    subj = (subject or "").strip()
    if subj:
        rows = store.query_claims(subj, include_inactive=bool(include_inactive))
        return {
            "ok": True,
            "subject": subj,
            "count": len(rows),
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "subject": c.subject,
                    "predicate": c.predicate,
                    "value": c.value,
                    "provenance": c.provenance.value,
                    "confidence": c.confidence,
                    "source_id": c.source_id,
                    "active": c.valid_until is None,
                }
                for c in rows
            ],
        }
    res = store.search_claims(str(query or "")[:200], include_inactive=bool(include_inactive))
    return {"ok": True, "count": len(res.get("claims") or []), **res}


def knowledge_contradictions(
    subject: str = "",
    predicate: str = "",
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Detect active conflicting claims across the epistemic world store."""
    store = _world_store(db_path)
    conflicts = store.find_contradictions(
        subject=(subject or "").strip() or None,
        predicate=(predicate or "").strip() or None,
    )
    return {"ok": True, "count": len(conflicts), "contradictions": conflicts}


def knowledge_verify_claim(
    claim_id: str,
    source_type: str,
    source_id: str,
    snippet: str = "",
    uri: str = "",
    confidence: float = 1.0,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Attach empirical evidence and promote an active claim to VERIFIED."""
    store = _world_store(db_path)
    try:
        return store.verify_claim(
            (claim_id or "").strip(),
            source_type=source_type,
            source_id=source_id,
            snippet=snippet,
            uri=(uri or "").strip() or None,
            confidence=float(confidence),
            actor="truth_agent",
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
