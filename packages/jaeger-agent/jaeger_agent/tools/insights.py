"""Attributed research records in the existing instance memory, with receipts.

Saving a claim does not verify it. Public research may explicitly be copied to
Honcho; that receipt is separate from local durability and never inferred from
the presence of a client or from generated prose.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from jaeger_agent.memory import memory as mem
from jaeger_os.core.tools.tool_registry import register_tool_from_function


def _identity(topic: str, insight_id: str) -> tuple[str, str]:
    for value in (topic, insight_id):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", value):
            raise ValueError("topic and insight_id need lowercase letters, digits, dots, underscores or hyphens (1–96 characters)")
    return "research:" + topic, "insight:" + insight_id


def _remote_session(topic: str) -> str:
    return "research-" + hashlib.sha256(topic.encode()).hexdigest()[:32]


def _honcho():
    from jaeger_ai.features.shared_memory.honcho_client import HonchoClient
    return HonchoClient()


def _messages(payload: Any):
    """Inspect message bodies only; summaries and model answers are not receipts."""
    if isinstance(payload, list):
        for item in payload:
            yield from _messages(item)
    elif isinstance(payload, dict):
        if isinstance(payload.get("content"), str):
            yield payload
        for key in ("items", "messages", "data"):
            if key in payload:
                yield from _messages(payload[key])


def _share(record: dict[str, Any]) -> dict[str, Any]:
    client = _honcho()
    session = _remote_session(record["topic"])
    if not client.health():
        return {"status": "unavailable", "verified": False, "session_id": session}
    # Check before creating; never blindly retry a possibly accepted write.
    peer = client.get_peer("jaeger-research")
    if peer.get("error"):
        if "HTTP 404" not in str(peer["error"]):
            return {"status": "unconfirmed", "verified": False, "error": peer["error"]}
        peer = client.create_peer("jaeger-research", {"kind": "research_archive"})
    if peer.get("error"):
        return {"status": "unconfirmed", "verified": False, "error": peer["error"]}
    existing = client.get_session(session)
    if existing.get("error"):
        if "HTTP 404" not in str(existing["error"]):
            return {"status": "unconfirmed", "verified": False, "error": existing["error"]}
        existing = client.create_session(session, {"jaeger-research": {}})
    if existing.get("error"):
        return {"status": "unconfirmed", "verified": False, "error": existing["error"]}
    body = json.dumps(record, sort_keys=True, ensure_ascii=False)
    before = client.list_messages(session)
    if before.get("error"):
        return {"status": "unconfirmed", "verified": False, "error": before["error"]}
    found = next((m for m in _messages(before) if m["content"] == body), None)
    if found is None:
        write = client.add_message(session, "jaeger-research", body)
        if write.get("error"):
            return {"status": "unconfirmed", "verified": False, "session_id": session, "error": write["error"]}
        found = next((m for m in _messages(client.list_messages(session)) if m["content"] == body), None)
    return {"status": "verified" if found else "unconfirmed", "verified": found is not None,
            "session_id": session, "message_id": found.get("id") if found else None}


@register_tool_from_function(name="record_insight")
def record_insight(topic: str, insight_id: str, claim: str,
                   epistemic_status: str, sources: list[str],
                   share_publicly_with_honcho: bool = False) -> dict[str, Any]:
    """Persist an attributed research claim or open_question; read it back.

    Use a topic about the project/phenomenon, not the owner's identity.
    Status: supported, hypothesis, disputed, or open_question. Cite URLs.
    This records the author's assessment, not independently verified truth.
    Set share_publicly_with_honcho only for public material the user asked
    to archive there. Local success never implies remote success. IDs are
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
        remote: dict[str, Any] = {"status": "not_requested", "verified": False}
        if verified and share_publicly_with_honcho:
            try:
                remote = _share(record)
            except Exception as exc:
                remote = {"status": "unconfirmed", "verified": False, "error": str(exc)}
        return {"ok": verified, "local_verified": verified, "subject": subject,
                "key": key, "record": record, "honcho": remote}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(name="recall_insight", side_effect="read")
def recall_insight(topic: str, insight_id: str, backend: str = "local") -> dict[str, Any]:
    """Retrieve an exact research record from local memory or Honcho.

    Honcho reads never fall back to the local cache. A missing/failed read
    is explicit. The stored epistemic status is an attributed assessment.
    """
    try:
        subject, key = _identity(topic, insight_id)
        if backend == "local":
            raw = mem.list_facts(subject=subject).get(key)
            record = json.loads(raw) if raw else None
        elif backend == "honcho":
            response = _honcho().list_messages(_remote_session(topic))
            if response.get("error"):
                return {"ok": False, "found": False, "backend": backend, "error": response["error"]}
            records = []
            for message in _messages(response):
                try:
                    candidate = json.loads(message["content"])
                    if isinstance(candidate, dict) and candidate.get("topic") == topic and candidate.get("insight_id") == insight_id:
                        records.append(candidate)
                except ValueError:
                    continue
            record = records[-1] if records else None
        else:
            raise ValueError("backend must be local or honcho")
        return {"ok": True, "found": record is not None, "backend": backend, "record": record}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "found": False, "error": str(exc)}
