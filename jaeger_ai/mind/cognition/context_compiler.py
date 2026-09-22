"""
ARES SI — Context Compiler.

Assembles the minimum useful context for each task.
Uses deterministic rules first (FTS5, temporal boost, decision boost),
with optional model-based reranking later.

The Context Compiler is the ONLY module that decides what Journal data
reaches a worker. Workers never see the full Journal.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from .types import (
    DataClassification,
    PERSONAL,
    ContextBriefing,
    ContextItem,
    MemoryItem,
    Constraint,
    OutputSpec,
    ManifestEntry,
    ManifestAction,
    SIIdentity,
)
from .trust_engine import classify_data, filter_briefing, log_disclosure


# ── Intent Classification (deterministic rules) ────────────────────────

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "code_generation": [
        "write code", "implement", "build", "create a", "refactor", "fix bug",
        "debug", "compile", "deploy", "script", "function", "class", "module",
        "test", "lint", "type check",
    ],
    "research": [
        "research", "find out", "look up", "search for", "what is", "explain",
        "how does", "compare", "evaluate", "analyze", "investigate",
    ],
    "action": [
        "run", "execute", "start", "stop", "restart", "install", "delete",
        "move", "copy", "send", "schedule", "automate",
    ],
    "memory": [
        "remember", "forget", "recall", "what did we", "what did you",
        "earlier", "last time", "previously", "before we", "our decision",
        "we decided", "what was the", "did we talk about",
    ],
    "conversation": [
        "hello", "hi", "hey", "thanks", "good", "bad", "tell me about",
        "what do you think", "opinion", "chat",
    ],
}

# Priority order: more specific intents checked first
_INTENT_PRIORITY = ["action", "memory", "code_generation", "research", "conversation"]


def classify_intent(message: str) -> tuple[str, float]:
    """Classify the user's intent using deterministic keyword matching.

    Returns (intent_type, confidence). Confidence is 1.0 for clear matches,
    0.5 for ambiguous, 0.3 for default fallback.
    """
    message_lower = message.lower()

    best_intent = "conversation"
    best_confidence = 0.3

    # Check intents in priority order — more specific intents win ties
    for intent in _INTENT_PRIORITY:
        keywords = _INTENT_KEYWORDS[intent]
        matches = sum(1 for kw in keywords if kw in message_lower)
        if matches > 0:
            confidence = min(1.0, 0.5 + (matches * 0.2))
            if confidence > best_confidence:
                best_intent = intent
                best_confidence = confidence

    return best_intent, best_confidence


# ── Context Retrieval ──────────────────────────────────────────────────

def _search_journal(
    query: str,
    limit: int = 10,
    source: str | None = None,
) -> list[dict]:
    """Search the Journal for relevant conversations and documents."""
    from api.journal.schema import get_db

    db = get_db()

    # Search conversations
    try:
        conv_results = db.execute("""
            SELECT c.id, c.title, c.source, c.updated_at,
                   snippet(messages_fts, 0, '⟫', '⟪', '...', 50) as snippet
            FROM messages_fts
            JOIN messages m ON messages_fts.rowid = m.id
            JOIN conversations c ON m.conversation_id = c.id
            WHERE messages_fts MATCH ?
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (query, limit)).fetchall()

        doc_results = db.execute("""
            SELECT d.id, d.title, d.source, d.updated_at,
                   snippet(documents_fts, 0, '⟫', '⟪', '...', 50) as snippet
            FROM documents_fts
            JOIN documents d ON documents_fts.rowid = d.id
            WHERE documents_fts MATCH ?
            ORDER BY d.updated_at DESC
            LIMIT ?
        """, (query, limit)).fetchall()

        results = []
        for r in conv_results:
            results.append({
                "type": "conversation",
                "id": r[0],
                "title": r[1],
                "source": r[2],
                "updated_at": r[3],
                "snippet": r[4],
            })
        for r in doc_results:
            results.append({
                "type": "document",
                "id": r[0],
                "title": r[1],
                "source": r[2],
                "updated_at": r[3],
                "snippet": r[4],
            })
        return results
    except Exception:
        return []


def _apply_temporal_boost(
    results: list[dict],
    now: float | None = None,
) -> list[dict]:
    """Boost recent results over old ones.

    Recency score: 1.0 for results from the last hour, decaying to 0.1
    for results older than 30 days.
    """
    if now is None:
        now = time.time()

    for r in results:
        age_seconds = now - (r.get("updated_at") or now)
        age_days = age_seconds / 86400

        if age_days < 1:
            recency = 1.0
        elif age_days < 7:
            recency = 0.8
        elif age_days < 30:
            recency = 0.5
        else:
            recency = 0.1

        r["recency"] = recency

    return results


def _apply_decision_boost(results: list[dict]) -> list[dict]:
    """Boost results that are final decisions over exploration drafts.

    For now, this checks the title and snippet for decision markers.
    Future: use the `tags` column when it's added.
    """
    decision_markers = {"decision", "decided", "final", "locked", "resolved", "fixed"}
    exploration_markers = {"exploration", "draft", "wip", "todo", "investigate", "maybe"}

    for r in results:
        title_lower = (r.get("title") or "").lower()
        snippet_lower = (r.get("snippet") or "").lower()
        combined = title_lower + " " + snippet_lower

        if any(m in combined for m in decision_markers):
            r["is_decision"] = True
            r["relevance_boost"] = 0.2
        elif any(m in combined for m in exploration_markers):
            r["is_decision"] = False
            r["relevance_boost"] = -0.1
        else:
            r["is_decision"] = False
            r["relevance_boost"] = 0.0

    return results


# ── Budget Packing ────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return len(text) // 4


def _pack_with_budget(
    items: list[dict],
    budget: int,
    snippet_field: str = "snippet",
) -> tuple[list[ContextItem], list[ManifestEntry]]:
    """Pack context items within a token budget.

    Priority: recent conversation > decisions > project context > background
    """
    packed = []
    manifest = []
    remaining = budget

    # Sort by relevance: recency * (1 + boost)
    sorted_items = sorted(
        items,
        key=lambda x: x.get("recency", 0.5) * (1 + x.get("relevance_boost", 0)),
        reverse=True,
    )

    for item in sorted_items:
        content = item.get(snippet_field, "")
        tokens = _estimate_tokens(content)

        if tokens <= remaining:
            packed.append(ContextItem(
                source=item.get("type", "unknown"),
                source_id=str(item.get("id", "")),
                content=content,
                sensitivity=DataClassification(item.get("sensitivity", "personal")),
                relevance=item.get("recency", 0.5) * (1 + item.get("relevance_boost", 0)),
                recency=item.get("recency", 0.5),
                is_decision=item.get("is_decision", False),
            ))
            remaining -= tokens
            manifest.append(ManifestEntry(
                item_id=str(item.get("id", "")),
                action=ManifestAction.INCLUDED,
                reason="relevant",
                original_tokens=tokens,
                final_tokens=tokens,
            ))
        else:
            manifest.append(ManifestEntry(
                item_id=str(item.get("id", "")),
                action=ManifestAction.EXCLUDED,
                reason="over_budget",
                original_tokens=tokens,
                final_tokens=0,
            ))

    return packed, manifest


# ── Main Compilation ───────────────────────────────────────────────────

def compile_context(
    user_message: str,
    conversation_id: str | None = None,
    target_worker_id: str | None = None,
    token_budget: int = 4000,
    local_only_mode: bool = False,
    si_identity: SIIdentity | None = None,
) -> ContextBriefing:
    """Assemble a briefing for a worker based on the user's message.

    This is the main entry point for the Context Compiler.
    It:
    1. Classifies the user's intent
    2. Retrieves relevant context from the Journal
    3. Applies temporal and decision boosts
    4. Packs context within the token budget
    5. Filters for privacy based on the target worker
    6. Returns a ContextBriefing with a manifest

    The briefing is the ONLY data structure that crosses the SI→Worker boundary.
    """
    # 1. Classify intent
    intent, confidence = classify_intent(user_message)

    # 2. Retrieve relevant context
    # Extract key terms from the message for search
    search_query = user_message
    search_results = _search_journal(search_query, limit=15)

    # 3. Apply boosts
    search_results = _apply_temporal_boost(search_results)
    search_results = _apply_decision_boost(search_results)

    # 4. Pack within budget (reserve 500 tokens for identity + constraints)
    context_budget = token_budget - 500
    packed_items, pack_manifest = _pack_with_budget(
        search_results, max(context_budget, 500)
    )

    # 5. Separate into categories
    conversation_items = [i for i in packed_items if i.source == "conversation"]
    document_items = [i for i in packed_items if i.source == "document"]

    # 6. Build the briefing — load persisted Companion identity (not generic defaults)
    if si_identity is None:
        try:
            from .identity import load_identity

            cfg = load_identity()
            si_identity = SIIdentity(
                name=cfg.name or "ARES",
                owner_name=cfg.owner_name or "User",
                mission=cfg.mission or "",
                principles=list(cfg.principles or []),
                loyalty=cfg.loyalty or "user",
            )
        except Exception:
            si_identity = SIIdentity(
                name="ARES",
                owner_name="User",
                mission="Assist the owner accurately, protect their data, and be honest about uncertainty.",
                principles=[
                    "Be honest about what you know and don't know",
                    "Protect the owner's private data",
                ],
                loyalty="user",
            )

    briefing = ContextBriefing(
        si_identity=si_identity,
        recent_conversation=conversation_items,
        relevant_memories=[MemoryItem(
            memory_id=i.source_id,
            content=i.content,
            source=i.source,
            sensitivity=i.sensitivity,
            importance=i.relevance,
        ) for i in document_items],
        context_manifest=pack_manifest,
        total_tokens=sum(_estimate_tokens(i.content) for i in packed_items),
    )

    # 7. Filter for privacy based on the target worker
    if target_worker_id:
        from .worker_registry import get_registry
        registry = get_registry()
        worker = registry.get(target_worker_id)
        if worker:
            briefing = filter_briefing(
                briefing,
                worker.privacy_class,
                local_only_mode=local_only_mode,
            )
            # Log disclosure for every item that was shared
            for item in briefing.recent_conversation + [
                MemoryItem(m.memory_id, m.content, m.source, m.sensitivity, m.importance)
                for m in briefing.relevant_memories
            ]:
                log_disclosure(
                    worker_id=target_worker_id,
                    data_class=item.sensitivity.value,
                    data_source=item.source,
                    reason=f"context_compilation:{intent}",
                )

    return briefing