"""
ARES SI — Trust and Privacy Engine.

Determines what data may be shared with which worker.
No LLM needed — this is pure deterministic policy.
"""

from __future__ import annotations

import time
from pathlib import Path

from .types import (
    DataClassification,
    PrivacyClass,
    PUBLIC, PERSONAL, PRIVATE, SENSITIVE, SECRET,
    ContextBriefing,
    ContextItem,
    MemoryItem,
    ManifestEntry,
    ManifestAction,
)


# ── Data classification rules ──────────────────────────────────────────

# Keywords that indicate sensitive data classification
_FINANCIAL_KEYWORDS = {
    "bank", "credit", "debit", "account number", "ssn", "social security",
    "tax", "income", "salary", "payment", "invoice", "receipt", "budget",
    "financial", "investment", "portfolio", "mortgage", "loan",
}

_MEDICAL_KEYWORDS = {
    "health", "medical", "diagnosis", "prescription", "medication", "doctor",
    "hospital", "therapy", "treatment", "symptom", "patient", "clinical",
}

_LEGAL_KEYWORDS = {
    "attorney", "lawyer", "legal", "lawsuit", "contract", "nda", "confidential",
    "privileged", "court", "patent", "trademark", "copyright",
}

_SECRET_KEYWORDS = {
    "api_key", "apikey", "api_key", "password", "passwd", "secret",
    "token", "access_key", "private_key", "credential", "auth",
}


def classify_data(content: str, metadata: dict | None = None) -> DataClassification:
    """Classify data sensitivity using deterministic rules.

    1. Check explicit tags (user-marked)
    2. Check source (secret vault = SECRET)
    3. Check keywords (financial, medical, legal → SENSITIVE)
    4. Default to PERSONAL
    """
    content_lower = content.lower()
    meta = metadata or {}

    # Explicit tags take priority
    if meta.get("sensitivity"):
        try:
            return DataClassification(meta["sensitivity"])
        except ValueError:
            pass

    # Source-based classification
    source = meta.get("source", "")
    if source in ("secret_vault", "api_key", "credential"):
        return SECRET

    # Keyword-based classification
    if any(kw in content_lower for kw in _SECRET_KEYWORDS):
        return SECRET
    if any(kw in content_lower for kw in _FINANCIAL_KEYWORDS):
        return SENSITIVE
    if any(kw in content_lower for kw in _MEDICAL_KEYWORDS):
        return SENSITIVE
    if any(kw in content_lower for kw in _LEGAL_KEYWORDS):
        return SENSITIVE

    # Check if content contains conversation that looks private
    if meta.get("source") == "conversation":
        return PRIVATE

    # Documents and preferences default to PERSONAL
    if meta.get("source") in ("document", "preference"):
        return PERSONAL

    # Default
    return PERSONAL


def filter_briefing(
    briefing: ContextBriefing,
    worker_privacy_class: PrivacyClass,
    local_only_mode: bool = False,
) -> ContextBriefing:
    """Remove items from a briefing that the worker is not eligible to see.

    Returns a new briefing with ineligible items removed and manifest entries
    added for every removal/redaction.
    """
    if local_only_mode:
        # In local-only mode, ALL data above PUBLIC goes to LOCAL_ONLY workers only
        worker_privacy_class = PrivacyClass.LOCAL_ONLY

    manifest_entries = list(briefing.context_manifest)
    filtered_user = []
    filtered_project = []
    filtered_conversation = []
    filtered_memories = []

    def _filter_items(
        items: list[ContextItem],
        item_type: str,
    ) -> list[ContextItem]:
        result = []
        for item in items:
            action = _check_eligibility(item.sensitivity, worker_privacy_class)
            if action == ManifestAction.INCLUDED:
                result.append(item)
            else:
                manifest_entries.append(ManifestEntry(
                    item_id=item.source_id,
                    action=action,
                    reason=_eligibility_reason(item.sensitivity, worker_privacy_class),
                    original_tokens=len(item.content) // 4,  # rough estimate
                    final_tokens=0,
                ))
        return result

    def _filter_memories(
        items: list[MemoryItem],
    ) -> list[MemoryItem]:
        result = []
        for item in items:
            action = _check_eligibility(item.sensitivity, worker_privacy_class)
            if action == ManifestAction.INCLUDED:
                result.append(item)
            else:
                manifest_entries.append(ManifestEntry(
                    item_id=item.memory_id,
                    action=action,
                    reason=_eligibility_reason(item.sensitivity, worker_privacy_class),
                    original_tokens=len(item.content) // 4,
                    final_tokens=0,
                ))
        return result

    filtered_user = _filter_items(briefing.user_context, "user_context")
    filtered_project = _filter_items(briefing.project_context, "project_context")
    filtered_conversation = _filter_items(briefing.recent_conversation, "recent_conversation")
    filtered_memories = _filter_memories(briefing.relevant_memories)

    return ContextBriefing(
        si_identity=briefing.si_identity,
        user_context=filtered_user,
        project_context=filtered_project,
        recent_conversation=filtered_conversation,
        relevant_memories=filtered_memories,
        constraints=briefing.constraints,
        privacy_policy=briefing.privacy_policy,
        tools=briefing.tools,
        output_requirements=briefing.output_requirements,
        context_manifest=manifest_entries,
        total_tokens=briefing.total_tokens,
    )


def _check_eligibility(
    sensitivity: DataClassification,
    worker_privacy_class: PrivacyClass,
) -> ManifestAction:
    """Check if a data item can be shared with a worker."""
    if sensitivity == SECRET:
        return ManifestAction.EXCLUDED
    if sensitivity == SENSITIVE:
        if worker_privacy_class == PrivacyClass.LOCAL_ONLY:
            return ManifestAction.INCLUDED
        return ManifestAction.EXCLUDED
    if sensitivity == PRIVATE:
        if worker_privacy_class in (PrivacyClass.LOCAL_ONLY,):
            return ManifestAction.INCLUDED
        return ManifestAction.REDACTED
    if sensitivity == PERSONAL:
        if worker_privacy_class in (
            PrivacyClass.LOCAL_ONLY,
            PrivacyClass.APPROVED_PROVIDER,
        ):
            return ManifestAction.INCLUDED
        return ManifestAction.INCLUDED  # approved providers see personal data
    # PUBLIC
    return ManifestAction.INCLUDED


def _eligibility_reason(
    sensitivity: DataClassification,
    worker_privacy_class: PrivacyClass,
) -> str:
    """Human-readable reason for an eligibility decision."""
    reasons = {
        (SECRET, PrivacyClass.LOCAL_ONLY): "secret_data_never_leaves_device",
        (SECRET, PrivacyClass.APPROVED_PROVIDER): "secret_data_never_leaves_device",
        (SECRET, PrivacyClass.EXTERNAL_PROVIDER): "secret_data_never_leaves_device",
        (SENSITIVE, PrivacyClass.APPROVED_PROVIDER): "sensitive_data_requires_local_worker",
        (SENSITIVE, PrivacyClass.EXTERNAL_PROVIDER): "sensitive_data_requires_local_worker",
        (PRIVATE, PrivacyClass.APPROVED_PROVIDER): "private_data_requires_local_or_approved",
        (PRIVATE, PrivacyClass.EXTERNAL_PROVIDER): "private_data_requires_local_worker",
    }
    return reasons.get(
        (sensitivity, worker_privacy_class),
        f"{sensitivity.value}_data_eligible_for_{worker_privacy_class.value}",
    )


def check_approval_required(action: str, data_sensitivity: str) -> bool:
    """Check if an action requires explicit user approval.

    Approval is ALWAYS required for:
    - Sending sensitive data to any worker
    - Shell command execution
    - File deletion
    - External API calls that modify state
    - Spending above cost threshold
    """
    approval_always = {
        "shell_execute": True,
        "file_delete": True,
        "external_api_write": True,
    }

    # Action-based approval
    if approval_always.get(action):
        return True

    # Sensitivity-based approval
    if data_sensitivity in ("sensitive", "secret"):
        return True

    return False


# ── Disclosure Ledger ──────────────────────────────────────────────────

_LEDGER_DB = None


def _get_ledger_db():
    """Get or create the disclosure ledger database."""
    global _LEDGER_DB
    if _LEDGER_DB is not None:
        return _LEDGER_DB

    import sqlite3
    from api.journal.paths import si_dir

    db_path = si_dir() / "disclosure_ledger.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _LEDGER_DB = sqlite3.connect(str(db_path))
    _LEDGER_DB.execute("""
        CREATE TABLE IF NOT EXISTS disclosure_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            session_id TEXT,
            worker_id TEXT NOT NULL,
            data_class TEXT NOT NULL,
            data_source TEXT,
            reason TEXT,
            user_approved INTEGER DEFAULT 0,
            manifest_entry TEXT
        )
    """)
    _LEDGER_DB.commit()
    return _LEDGER_DB


def log_disclosure(
    worker_id: str,
    data_class: str,
    data_source: str = "",
    reason: str = "",
    session_id: str = "",
    user_approved: bool = False,
    manifest_entry: str = "",
) -> None:
    """Log that data was shared with a worker."""
    db = _get_ledger_db()
    db.execute(
        """INSERT INTO disclosure_ledger
           (timestamp, session_id, worker_id, data_class, data_source, reason, user_approved, manifest_entry)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), session_id, worker_id, data_class, data_source, reason,
         int(user_approved), manifest_entry),
    )
    db.commit()


def get_disclosure_log(limit: int = 100) -> list[dict]:
    """Get recent disclosure entries for user inspection."""
    db = _get_ledger_db()
    rows = db.execute(
        """SELECT id, timestamp, session_id, worker_id, data_class, data_source,
                  reason, user_approved, manifest_entry
           FROM disclosure_ledger ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r[0], "timestamp": r[1], "session_id": r[2], "worker_id": r[3],
            "data_class": r[4], "data_source": r[5], "reason": r[6],
            "user_approved": bool(r[7]), "manifest_entry": r[8],
        }
        for r in rows
    ]


# ── Privacy Rules ───────────────────────────────────────────────────────

_privacy_rules: list[dict] = []
_local_only_mode: bool = False
_restricted_workers: set[str] = set()
_approved_workers: set[str] = set()


def get_privacy_rules() -> list[dict]:
    """Get all privacy rules."""
    rules = list(_privacy_rules)
    if _local_only_mode:
        rules.append({"type": "local_only", "target": "*", "reason": "Local-only mode is enabled"})
    for w in _restricted_workers:
        rules.append({"type": "restricted", "target": w, "reason": "Worker restricted by user"})
    for w in _approved_workers:
        rules.append({"type": "approved", "target": w, "reason": "Worker approved for sensitive data"})
    return rules


def add_privacy_rule(rule_type: str, target: str, reason: str = "") -> dict:
    """Add a privacy rule."""
    rule = {"type": rule_type, "target": target, "reason": reason, "created_at": time.time()}
    _privacy_rules.append(rule)
    return rule


def delete_privacy_rule(rule_id: str) -> bool:
    """Delete a privacy rule by its index or target match."""
    try:
        idx = int(rule_id)
        if 0 <= idx < len(_privacy_rules):
            _privacy_rules.pop(idx)
            return True
    except ValueError:
        pass
    # Try matching by target
    for i, r in enumerate(_privacy_rules):
        if r.get("target") == rule_id:
            _privacy_rules.pop(i)
            return True
    return False


def set_local_only_mode(enabled: bool) -> None:
    """Enable or disable local-only mode."""
    global _local_only_mode
    _local_only_mode = enabled


def is_local_only_mode() -> bool:
    """Check if local-only mode is enabled."""
    return _local_only_mode


def restrict_worker(worker_id: str) -> bool:
    """Restrict a worker from receiving data above PUBLIC."""
    _restricted_workers.add(worker_id)
    return True


def approve_worker(worker_id: str) -> bool:
    """Approve a worker for sensitive data access."""
    _approved_workers.add(worker_id)
    _restricted_workers.discard(worker_id)
    return True


def is_worker_restricted(worker_id: str) -> bool:
    """Check if a worker is restricted."""
    return worker_id in _restricted_workers


def is_worker_approved(worker_id: str) -> bool:
    """Check if a worker is approved for sensitive data."""
    return worker_id in _approved_workers