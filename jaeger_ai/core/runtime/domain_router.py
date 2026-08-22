"""Topic shift → pull domain facts into the ONE primary session.

The user talks to a single persistent session. Switching from "general
chat" to "Project X" or "the notes" must not open a new window — it
must recall what this instance already knows about that domain and
park it in working context for the turn.

Fail-open: a memory miss or an unbound store yields no block, never an
error. The model still has the user's words.
"""

from __future__ import annotations

import re
import threading
from typing import Any

DOMAIN_TAG = "[Domain context:"

# Explicit "let's work on / switch to / talk about …"
_SHIFT = re.compile(
    r"(?is)(?:let'?s |i want to |can we )?"
    r"(?:talk about|work on|look at|switch(?:ing)? to|focus on|regarding)\s+"
    r"(.{2,80}?)(?:[.!?]|$)"
)
_PROJECT = re.compile(r"(?i)\bproject\s+([A-Za-z0-9][\w-]{0,40})")
_NOTES = re.compile(r"(?i)\b(?:apple\s+)?notes?\b")

_tls = threading.local()


def reset() -> None:
    _tls.domain = ""


def _normalize_topic(raw: str) -> str:
    text = " ".join((raw or "").strip().split())
    text = re.sub(r"^(the|my|our|this)\s+", "", text, flags=re.IGNORECASE)
    return text[:80].strip(" .,:;")


def detect_topic(text: str) -> str:
    """A domain label if this prompt is a topic shift, else ``""``."""
    body = (text or "").strip()
    if not body:
        return ""
    project = _PROJECT.search(body)
    if project:
        return _normalize_topic("project " + project.group(1))
    shift = _SHIFT.search(body)
    if shift:
        return _normalize_topic(shift.group(1))
    if _NOTES.search(body) and re.search(
        r"(?i)\b(?:let'?s|work on|look at|switch|consolidat|process|review)\b",
        body,
    ):
        return "notes"
    return ""


def _memory_hits(topic: str) -> list[str]:
    lines: list[str] = []
    try:
        from jaeger_agent import tools
        result = tools.memory(action="search", query=topic, limit=6)
    except Exception:  # noqa: BLE001 — memory is optional here
        return lines
    if not isinstance(result, dict) or not result.get("ok"):
        return lines
    hits = result.get("results") or result.get("items") or result.get("matches") or []
    if isinstance(hits, dict):
        hits = list(hits.values())
    for item in hits[:6]:
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("name") or "").strip()
            value = str(item.get("value") or item.get("text") or "").strip()
            if key and value:
                lines.append(f"{key}: {value[:240]}")
            elif value:
                lines.append(value[:240])
        elif item:
            lines.append(str(item)[:240])
    return lines


def _ledger_hits(topic: str) -> list[str]:
    lines: list[str] = []
    needle = (topic or "").lower()
    if not needle:
        return lines
    try:
        from jaeger_ai.core.runtime.work_ledger import all_ledgers
        ledgers = all_ledgers()
    except Exception:  # noqa: BLE001
        return lines
    for ledger in ledgers:
        name = (ledger.task_name or "").lower()
        if needle not in name and name not in needle:
            continue
        lines.append(
            f"ledger {ledger.task_id}: {ledger.task_name} "
            f"({ledger.done_count()}/{ledger.total()} "
            f"{'complete' if ledger.completed else 'in progress'})"
        )
    return lines


def recall_domain(topic: str) -> str:
    """Compact facts for ``topic`` from memory + work ledgers."""
    if not topic:
        return ""
    parts = _memory_hits(topic) + _ledger_hits(topic)
    if not parts:
        return ""
    return "\n".join(parts[:8])


def domain_block(user_text: str, *, session_key: str = "") -> str:
    """A context block when the prompt shifts domain in this session.

    Empty string when there is no shift, the domain has not changed, or
    nothing is on file for it.
    """
    topic = detect_topic(user_text)
    if not topic:
        return ""
    last = getattr(_tls, "domain", "") or ""
    key = f"{session_key}:{topic.lower()}"
    if last == key:
        return ""
    facts = recall_domain(topic)
    _tls.domain = key
    if not facts:
        return ""
    return f"{DOMAIN_TAG} {topic}]\n{facts}\n[end domain context]"


def prepend_domain_context(user_text: str, *, session_key: str = "") -> str:
    block = domain_block(user_text, session_key=session_key)
    if not block:
        return user_text
    return f"{block}\n\n{user_text}"


__all__ = [
    "DOMAIN_TAG",
    "detect_topic",
    "recall_domain",
    "domain_block",
    "prepend_domain_context",
    "reset",
]
