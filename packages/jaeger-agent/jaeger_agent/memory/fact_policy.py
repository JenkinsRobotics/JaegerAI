"""Persistent facts carry context, never authority over runtime safeguards.

This write-boundary check rejects common attempts to persist permission grants
or instruction overrides. It complements (and never replaces) the host's tool
permission checks; no memory value is a permission decision.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


class UnsafeMemoryFact(ValueError):
    """The proposed fact attempts to change the agent's authority."""


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    return re.sub(r"[\W_]+", " ", text).strip()


_OVERRIDE = re.compile(
    r"\b(?:ignore|override|disregard|bypass|disable|skip|waive)\b.{0,80}"
    r"\b(?:instructions|safeguards?|safety|review|logging|audit|permissions?|"
    r"confirmations?|approvals?)\b"
)
_AUTHORITY = re.compile(
    r"\b(?:pre ?authori[sz](?:ed|ation)|blanket|unrestricted|unconditional|"
    r"permanent permission|always (?:allow|approve)|allow all|auto approve)\b"
)
_DANGEROUS = re.compile(
    r"\b(?:delet\w*|remov\w*|wip\w*|execut\w*|commands?|tools?|files?|"
    r"permissions?|safety|safeguards?|logging|audit|access|actions?)\b"
)
_WITHOUT_CONSENT = re.compile(
    r"\b(?:without (?:ever )?(?:asking|confirm\w*|approval|permission)|"
    r"no (?:confirmation|approval|permission) (?:needed|required)|"
    r"never ask|do not ask|don t ask)\b"
)
_AUTHORITY_KEYS = {
    "permissions", "permission mode", "safety policy", "safety rules",
    "approval policy", "authorization", "authorisation", "allow all",
    "pre authorized", "preauthorized", "auto approve", "skip confirmation",
}


def validate_fact(key: str, value: str, *, category: str | None = None,
                  subject: str | None = None, tags: Any = None,
                  note: str = "") -> None:
    """Reject a policy override before any current/history row is written."""
    text = _normalize(" ".join(str(v or "") for v in
                               (key, value, category, subject, tags, note)))
    authority_key = _normalize(key) in _AUTHORITY_KEYS
    if (authority_key or _OVERRIDE.search(text)
            or (_AUTHORITY.search(text) and _DANGEROUS.search(text))
            or (_WITHOUT_CONSENT.search(text) and _DANGEROUS.search(text))):
        raise UnsafeMemoryFact(
            "Cannot store permission grants or safeguard overrides as facts. "
            "Memory never authorizes actions; the configured permission policy "
            "and approval for the actual operation still apply."
        )
