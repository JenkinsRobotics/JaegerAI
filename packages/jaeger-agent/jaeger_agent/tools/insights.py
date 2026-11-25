"""Attributed research records in the existing instance memory, with receipts.

Saving a claim does not verify it. Records live only in the local instance
memory (the Honcho mirror was retired 2026-11-15).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from jaeger_agent.memory import memory as mem
from jaeger_tools.tool_registry import register_tool_from_function


def _identity(topic: str, insight_id: str) -> tuple[str, str]:
    for value in (topic, insight_id):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", value):
            raise ValueError("topic and insight_id need lowercase letters, digits, dots, underscores or hyphens (1–96 characters)")
    return "research:" + topic, "insight:" + insight_id


@register_tool_from_function(name="record_insight")
def record_insight(topic: str, insight_id: str, claim: str,
                   epistemic_status: str, sources: list[str]) -> dict[str, Any]:
    """Persist an attributed research claim or open_question; read it back.

    Use a topic about the project/phenomenon, not the owner's identity.
    Status: supported, hypothesis, disputed, or open_question. Cite URLs.
    This records the author's assessment, not independently verified truth.
    IDs are
    immutable: use a new insight_id for a revision, citing the old one.
    """
    try:
        subject, key = _identity(topic, insight_id)
        if epistemic_status not in {"supported", "hypothesis", "disputed", "open_question"}:
            raise ValueError("Invalid epistemic_status")
        if not claim.strip() or len(claim) > 12000:
            raise ValueError("claim must contain 1–12000 characters")
        if not sources or len(sources) > 20 or any(
            not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}
            or not urlparse(url).netloc for url in sources
        ):
            raise ValueError("Supply 1–20 source URLs")
        payload = {"schema": 1, "topic": topic, "insight_id": insight_id,
                   "claim": claim.strip(), "epistemic_status": epistemic_status,
                   "sources": sources, "independently_verified": False}
        candidate = {**payload, "recorded_at": datetime.now(timezone.utc).isoformat()}
        raw = mem.remember_if_absent(key, json.dumps(candidate, sort_keys=True, ensure_ascii=False),
                                    subject=subject, category="research")
        record = json.loads(raw)
        if any(record.get(k) != v for k, v in payload.items()):
            return {"ok": False, "error": "insight_id already holds different content; use a revision ID"}
        # Exact lookup: ordinary recall() also permits fuzzy key matches.
        verified = json.loads(mem.list_facts(subject=subject).get(key, "null")) == record
        return {"ok": verified, "local_verified": verified, "subject": subject,
                "key": key, "record": record}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(name="recall_insight", side_effect="read")
def recall_insight(topic: str, insight_id: str, backend: str = "local") -> dict[str, Any]:
    """Retrieve an exact research record from local memory.

    The stored epistemic status is an attributed assessment.
    """
    try:
        subject, key = _identity(topic, insight_id)
        if backend == "local":
            raw = mem.list_facts(subject=subject).get(key)
            record = json.loads(raw) if raw else None
        else:
            raise ValueError("backend must be local")
        return {"ok": True, "found": record is not None, "backend": backend, "record": record}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "found": False, "error": str(exc)}
