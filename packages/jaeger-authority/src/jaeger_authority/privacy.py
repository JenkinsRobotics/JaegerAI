"""Deterministic Data Sensitivity & Privacy Routing Classifier (0 LLM tokens).

Adapted from ARES SI Trust & Privacy Engine (`core/si/trust_engine.py`).
Determines data sensitivity class (`PUBLIC`, `PERSONAL`, `PRIVATE`, `SENSITIVE`,
`SECRET`) using pure deterministic rules so Jaeger's Hybrid Cloud + Local routing
can guard financial, medical, legal, and credential data from leaving local models.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class DataSensitivity(str, Enum):
    PUBLIC = "public"
    PERSONAL = "personal"
    PRIVATE = "private"
    SENSITIVE = "sensitive"
    SECRET = "secret"


_ORDER: dict[DataSensitivity, int] = {
    DataSensitivity.PUBLIC: 0,
    DataSensitivity.PERSONAL: 1,
    DataSensitivity.PRIVATE: 2,
    DataSensitivity.SENSITIVE: 3,
    DataSensitivity.SECRET: 4,
}

_FINANCIAL_KEYWORDS = frozenset({
    "bank", "credit card", "debit card", "account number", "routing number",
    "ssn", "social security", "tax return", "salary", "mortgage", "bank statement",
})

_MEDICAL_KEYWORDS = frozenset({
    "medical record", "diagnosis", "prescription", "medication", "clinical",
    "blood test", "patient id", "therapy notes",
})

_LEGAL_KEYWORDS = frozenset({
    "attorney-client", "privileged", "lawsuit", "nda", "confidential agreement",
    "court filing",
})

_SECRET_KEYWORDS = frozenset({
    "api_key", "apikey", "private_key", "secret_key", "access_token",
    "refresh_token", "bearer ", "sk-", "ghp_", "-----begin ", "passwd",
})


@dataclass(frozen=True)
class PrivacyDecision:
    sensitivity: DataSensitivity
    cloud_allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensitivity": self.sensitivity.value,
            "cloud_allowed": self.cloud_allowed,
            "reason": self.reason,
        }


def classify_sensitivity(
    content: str,
    metadata: Mapping[str, Any] | None = None,
) -> DataSensitivity:
    """Classify content sensitivity deterministically without an LLM call."""
    meta = dict(metadata or {})
    explicit = str(meta.get("sensitivity") or "").strip().lower()
    if explicit:
        try:
            return DataSensitivity(explicit)
        except ValueError:
            pass

    source = str(meta.get("source") or "").strip().lower()
    if source in ("secret_vault", "api_key", "credential", "keychain"):
        return DataSensitivity.SECRET

    low = (content or "").lower()
    if any(kw in low for kw in _SECRET_KEYWORDS):
        return DataSensitivity.SECRET
    if any(kw in low for kw in _FINANCIAL_KEYWORDS):
        return DataSensitivity.SENSITIVE
    if any(kw in low for kw in _MEDICAL_KEYWORDS):
        return DataSensitivity.SENSITIVE
    if any(kw in low for kw in _LEGAL_KEYWORDS):
        return DataSensitivity.SENSITIVE

    if source == "conversation":
        return DataSensitivity.PRIVATE
    if source in ("document", "preference", "memory", "wiki"):
        return DataSensitivity.PERSONAL
    if source == "public":
        return DataSensitivity.PUBLIC
    return DataSensitivity.PERSONAL


def evaluate_cloud_egress(
    content: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    local_only_mode: bool = False,
    max_cloud_sensitivity: DataSensitivity = DataSensitivity.PRIVATE,
) -> PrivacyDecision:
    """Decide whether a text payload may be sent to a cloud model or must stay local."""
    sens = classify_sensitivity(content, metadata)
    if local_only_mode and _ORDER[sens] > _ORDER[DataSensitivity.PUBLIC]:
        return PrivacyDecision(
            sensitivity=sens,
            cloud_allowed=False,
            reason=f"local_only_mode blocks {sens.value} egress",
        )
    if _ORDER[sens] > _ORDER[max_cloud_sensitivity]:
        return PrivacyDecision(
            sensitivity=sens,
            cloud_allowed=False,
            reason=f"{sens.value} exceeds max cloud threshold ({max_cloud_sensitivity.value})",
        )
    return PrivacyDecision(
        sensitivity=sens,
        cloud_allowed=True,
        reason=f"{sens.value} allowed within cloud threshold",
    )


def filter_items_for_egress(
    items: Sequence[Mapping[str, Any]],
    *,
    local_only_mode: bool = False,
    max_cloud_sensitivity: DataSensitivity = DataSensitivity.PRIVATE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter context items into (allowed_items, redacted_manifest)."""
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        text = str(item.get("content") or item.get("text") or "")
        meta = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        decision = evaluate_cloud_egress(
            text,
            metadata=meta,
            local_only_mode=local_only_mode,
            max_cloud_sensitivity=max_cloud_sensitivity,
        )
        if decision.cloud_allowed:
            kept.append(dict(item))
        else:
            blocked.append({
                "index": idx,
                "sensitivity": decision.sensitivity.value,
                "reason": decision.reason,
            })
    return kept, blocked


__all__ = [
    "DataSensitivity",
    "PrivacyDecision",
    "classify_sensitivity",
    "evaluate_cloud_egress",
    "filter_items_for_egress",
]
