"""Chief-of-staff glue: one primary session, workers for heavy jobs.

The operator always talks to a single persistent session. Long batch
work is ``delegate_task(background=True)`` — a worker runs the
autonomous goal loop in isolation and returns a summary on the
completion rail. This module is the small amount of routing that
lives on the parent turn: which sessions are "the main conversation",
and how a turn's user text is prepared (domain recall, ledger, compact).
"""

from __future__ import annotations

from typing import Any

from jaeger_ai.core.runtime.context_compactor import compact_agent
from jaeger_ai.core.runtime.domain_router import domain_block
from jaeger_ai.core.runtime.work_ledger import context_block

# Session keys that ARE the operator's primary conversation. Workers
# use ``delegate:<id>`` / ``worker`` / heartbeat names and must not
# pull domain routing into a sandbox.
PRIMARY_SESSIONS = frozenset({
    "", "cli", "desktop-app", "main", "voice", "tui",
})


def is_primary_session(session_key: str) -> bool:
    key = (session_key or "").strip().lower()
    if key in PRIMARY_SESSIONS:
        return True
    return not key.startswith((
        "delegate", "worker", "heartbeat", "cron", "kanban",
        "deepthink", "completions", "webhook",
    ))


def normalize_session_key(session_key: str | None, *, default: str) -> str:
    key = (session_key or "").strip() or default
    if key.lower() == "main":
        return default
    return key


def prepare_turn_text(
    agent: Any,
    user_text: str,
    *,
    session_key: str = "",
    domain: bool = True,
    ledger: bool = True,
    request: str | None = None,
) -> str:
    """Compact history if needed, then prepend domain + ledger blocks.

    The original ``user_text`` is unchanged for session transcripts —
    callers pass this prepared string only to the model loop.

    ``request`` is the operator's own words when ``user_text`` arrives
    already enriched (the Entity prefixes a ``<background>`` block of
    recalled turns). Every decision here — skill routing, ledger, domain
    recall, world admission — is about the request, so it reads
    ``request``; only the returned model text carries the enrichment.
    Routing on the enriched text auto-selected an 11 KB "Box" playbook and
    opened a ledger named "<background> Reference only…" for "My favorite
    color is teal" (live capture, 2026-09-22).
    """
    from jaeger_ai.core.runtime.continuation import is_continuation_prompt

    intent = user_text if request is None else request
    continuing = is_continuation_prompt(intent)
    # Skill selection sees the request, never ledger/world scaffolding.
    agent._skill_route_query = "" if continuing else intent
    if not continuing:
        agent._task_objective = intent
    compact_agent(agent)
    from jaeger_ai.core.runtime.autonomous_runner import conversation_only
    ledger = ledger and not conversation_only(intent)
    parts: list[str] = []
    if ledger:
        try:
            from jaeger_ai.core.runtime.autonomous_runner import (
                ACCEPTANCE_GUIDANCE,
                ensure_autonomous_ledger,
            )
            opened = ensure_autonomous_ledger(intent)
            if opened is not None:
                parts.append(ACCEPTANCE_GUIDANCE)
        except Exception:  # noqa: BLE001 — setup must never lose the request
            pass
    if domain and not continuing and is_primary_session(session_key):
        extra = domain_block(intent, session_key=session_key)
        if extra:
            parts.append(extra)
    if ledger:
        block = context_block()
        if block:
            parts.append(block)
    if continuing and getattr(agent, "_task_objective", ""):
        parts.append("Original user request still in force:\n" + agent._task_objective)
    parts.append(user_text)
    # World admission sees only the original utterance, never work-ledger or
    # domain prompt scaffolding. Conversation scope is a conservative fallback
    # until authenticated ingress supplies a stronger actor mapping.
    from jaeger_agent.memory import sqlite_store
    if sqlite_store.is_bound() and not continuing:
        from jaeger_agent.cognition.world import WorldEvent, WorldModel
        from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore
        event = WorldEvent.for_session(intent, session_key)
        agent._world_event = event
        world = WorldModel(SqliteKnowledgeStore())
        packet = world.prepare(event)
        if packet:
            parts.insert(0, packet)
    else:
        agent._world_event = None
    return "\n\n".join(parts)


__all__ = [
    "PRIMARY_SESSIONS",
    "is_primary_session",
    "normalize_session_key",
    "prepare_turn_text",
]
