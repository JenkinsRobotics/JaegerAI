"""Explicit topic state for Jaeger's durable home conversation.

Conversation text never creates, closes, or renames a topic. Those mutations
come from explicit Gateway topic commands; the host only ensures an initial
container exists for older clients.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
HOME_AGENT_ID = "native:jaeger"
HOME_TITLE = "Jaeger"


def home_session_id() -> str:
    return f"agent-{HOME_AGENT_ID}"


def is_jaeger_home(session_id: str, metadata: dict[str, Any] | None = None) -> bool:
    meta = metadata or {}
    return session_id == home_session_id() or bool(
        meta.get("home") and meta.get("agent_id") == HOME_AGENT_ID
    )


def _publish(event_bus: Any | None, session_id: str, topic: dict[str, Any]) -> None:
    if event_bus is not None:
        event_bus.publish(session_id, "session.topic", {"session_id": session_id, "topic": topic})


def _initial_topic(store: Any, session_id: str, session: dict[str, Any]) -> dict[str, Any] | None:
    current = store.current_topic(session_id)
    if current is not None:
        return current
    messages = list(session.get("messages") or [])
    if not messages:
        return None
    return store.create_topic(
        session_id, title="Conversation",
        start_message_id=min(int(message["id"]) for message in messages),
        close_open=False,
    )


def maybe_update_home_topics(
    store: Any, session_id: str, *, event_bus: Any | None = None,
) -> dict[str, Any] | None:
    """Ensure compatibility state; never infer a topic transition."""
    session = store.get_session(session_id)
    if session is None or not is_jaeger_home(session_id, session.get("metadata")):
        return None
    return _initial_topic(store, session_id, session)


def start_new_topic(store: Any, session_id: str, *, event_bus: Any | None = None) -> dict[str, Any]:
    """Open a new topic only because an explicit Gateway command requested it."""
    session = store.get_session(session_id)
    if session is None:
        raise KeyError(session_id)
    rows = list(session.get("messages") or [])
    start = max((int(row["id"]) for row in rows), default=0) + 1
    current = store.current_topic(session_id)
    if current is not None and int(current.get("start_message_id") or 0) == start:
        return current
    if current is not None:
        end = max(start - 1, int(current["start_message_id"]))
        store.update_topic(current["topic_id"], end_message_id=end)
    topic = store.create_topic(
        session_id, title="New conversation", start_message_id=start, close_open=False,
    )
    _publish(event_bus, session_id, topic)
    return topic


def ensure_home(app: Any) -> str:
    sid, _ = app._ensure_agent_home(HOME_AGENT_ID, HOME_TITLE)
    session = app.store.get_session(sid)
    if session is not None and session.get("title_source") != "user":
        title = str(session.get("title") or "").strip().lower()
        if title in {"", "native:jaeger", "new chat", "new conversation"}:
            app.store.apply_auto_title(
                sid, HOME_TITLE, user_turns=0, fingerprint="home", model="home", changed=True,
            )
    return sid


def install(app: Any) -> None:
    """Install only the home-session invariant; no background model/timer."""
    try:
        ensure_home(app)
    except Exception:
        logger.warning("could not ensure Jaeger home chat", exc_info=True)
