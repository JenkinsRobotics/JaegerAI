"""Auto-segment the Jaeger home chat into titled topics as the subject moves."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from jaeger_ai.core.gateway.session_titles import (
    conversation_messages,
    generate_topic_title,
    sanitize_topic_title,
    titles_equivalent,
)

logger = logging.getLogger(__name__)

HOME_AGENT_ID = "native:jaeger"
HOME_TITLE = "Jaeger"
DEBOUNCE_SECONDS = 2.0
MIN_MESSAGES_BEFORE_SPLIT = 2  # at least one user + one assistant in the current topic

SHIFT_PROMPT = (
    "You watch a continuous chat and decide whether the latest exchange started a new topic.\n"
    "Reply with JSON only, no markdown: {\"shift\": false, \"title\": \"Current or new 3-6 word title\"}\n"
    "shift=true only when the latest user message clearly changes the subject.\n"
    "If the topic is the same, set shift=false and you may refine the current title.\n"
    "Titles are noun phrases, 3-6 words, no quotes, no sentences."
)


def home_session_id() -> str:
    return f"agent-{HOME_AGENT_ID}"


def is_jaeger_home(session_id: str, metadata: dict[str, Any] | None = None) -> bool:
    if session_id == home_session_id():
        return True
    meta = metadata or {}
    return bool(meta.get("home") and meta.get("agent_id") == HOME_AGENT_ID)


def _memory_excerpt(query: str) -> str:
    try:
        from jaeger_ai.core.runtime.collaboration import memory_excerpt
        text = memory_excerpt(query, limit_chars=600)
        return str(text or "").strip()
    except Exception:
        return ""


def _prior_summaries(topics: list[dict[str, Any]], current_id: str | None) -> str:
    lines = []
    for topic in topics:
        if topic["topic_id"] == current_id or topic.get("archived"):
            continue
        summary = (topic.get("summary") or "").strip()
        title = topic.get("title") or "Untitled"
        lines.append(f"- {title}: {summary}" if summary else f"- {title}")
    return "\n".join(lines[-8:])


def _excerpt(messages: list[dict[str, str]], limit: int = 10) -> str:
    parts = []
    for row in messages[-limit:]:
        label = "User" if row["role"] == "user" else "Assistant"
        parts.append(f"{label}: {row['content'][:350]}")
    return "\n".join(parts)


def _parse_shift(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        title = sanitize_topic_title(text)
        return False, title
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return False, sanitize_topic_title(text)
    if not isinstance(data, dict):
        return False, ""
    title = sanitize_topic_title(str(data.get("title") or ""))
    return bool(data.get("shift")), title


def _topic_messages(store: Any, session_id: str, topic: dict[str, Any]) -> list[dict[str, str]]:
    page = store.list_messages(
        session_id,
        after=int(topic["start_message_id"]),
        until=int(topic["end_message_id"]) if topic.get("end_message_id") is not None else None,
        limit=200,
    )
    # list_messages is newest first
    return conversation_messages(list(reversed(page.get("messages") or [])))


def _ensure_current_topic(store: Any, session_id: str, session: dict[str, Any]) -> dict[str, Any] | None:
    current = store.current_topic(session_id)
    if current is not None:
        return current
    messages = session.get("messages") or []
    if not messages:
        return None
    first_id = int(messages[0]["id"])
    title = session.get("title") if not is_jaeger_home(session_id, session.get("metadata")) else ""
    if not title or title.strip().lower() in {"jaeger", "new chat", "new conversation"}:
        conv = conversation_messages(messages)
        generated, _ = generate_topic_title(conv, "")
        title = generated or "Conversation"
    return store.create_topic(session_id, title=title, start_message_id=first_id, close_open=False)


def _shift_decision(prompt: str) -> tuple[bool, str, str]:
    from jaeger_ai.core.gateway.session_titles import _ollama_cloud_title, _grok_title, sanitize_topic_title as _san

    try:
        from jaeger_ai.core.gateway import session_titles as titles
        from jaeger_ai.core.models.discovery import discover_ollama_cloud
        from jaeger_ai.core.models.router import OLLAMA_CLOUD_OPENAI, ollama_cloud_api_model
        from jaeger_ai.core.secrets_env import ollama_api_key
        text = None
        route = "none"
        key = ollama_api_key()
        if key:
            discovered = discover_ollama_cloud(key) or {}
            names = [str((row.get("name") if isinstance(row, dict) else row) or "") for row in (discovered.get("models") or [])]
            model = titles._pick_cloud_model(names)
            if model:
                text = titles._openai_chat(
                    OLLAMA_CLOUD_OPENAI, key, ollama_cloud_api_model(model),
                    SHIFT_PROMPT + "\n\n" + prompt, titles.CLOUD_TIMEOUT_S,
                )
                route = "ollama-cloud"
        if not text:
            from jaeger_ai.features.cli_backends.discovery import KNOWN_BACKENDS, probe_backend
            import subprocess
            spec = next((item for item in KNOWN_BACKENDS if item.id == "grok"), None)
            executable = probe_backend(spec) if spec else None
            if executable and spec:
                args = [executable]
                body = SHIFT_PROMPT + "\n\n" + prompt
                for part in spec.args:
                    args.append(body if part == "{prompt}" else part)
                result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=titles.GROK_TIMEOUT_S)
                if result.returncode == 0:
                    text = titles._text_from_cli_json(result.stdout or "")
                    route = "grok"
        shift, title = _parse_shift(text or "")
        return shift, title, route
    except Exception:
        logger.info("topic shift model unavailable")
        return False, "", "none"


def maybe_update_home_topics(store: Any, session_id: str, *, event_bus: Any | None = None) -> dict[str, Any] | None:
    session = store.get_session(session_id)
    if session is None or not is_jaeger_home(session_id, session.get("metadata")):
        return None
    current = _ensure_current_topic(store, session_id, session)
    if current is None:
        return None
    messages = _topic_messages(store, session_id, current)
    if len(messages) < MIN_MESSAGES_BEFORE_SPLIT:
        _maybe_refresh_topic_title(store, current, messages, event_bus)
        return current
    all_messages = conversation_messages(session.get("messages") or [])
    # Need ids of the latest user message to split on.
    raw_rows = list(session.get("messages") or [])
    user_ids = [int(row["id"]) for row in raw_rows if row.get("role") == "user" and (row.get("kind") in (None, "", "message"))]
    latest_user_id = user_ids[-1] if user_ids else None
    prior = store.list_topics(session_id)
    memory = _memory_excerpt(current.get("title") or "")
    prompt = (
        f"Current title: {current.get('title') or '(none)'}\n"
        f"Current topic messages:\n{_excerpt(messages)}\n"
    )
    summaries = _prior_summaries(prior, current["topic_id"])
    if summaries:
        prompt += f"\nPrior topics:\n{summaries}\n"
    if memory:
        prompt += f"\nMemory:\n{memory[:600]}\n"
    shift, title, route = _shift_decision(prompt)
    if shift and latest_user_id and latest_user_id > int(current["start_message_id"]):
        new_title = title or None
        if not new_title:
            new_title, route = generate_topic_title(all_messages[-4:], "")
        store.update_topic(current["topic_id"], end_message_id=latest_user_id - 1, summary=_summary_from_messages(messages[:-2] or messages))
        created = store.create_topic(
            session_id,
            title=new_title or "New conversation",
            start_message_id=latest_user_id,
            close_open=False,
        )
        _publish(event_bus, session_id, created)
        logger.info("home topic opened topic=%s source=%s", created["topic_id"][-8:], route)
        return created
    _maybe_refresh_topic_title(store, current, messages, event_bus, suggested=title)
    return current


def _summary_from_messages(messages: list[dict[str, str]]) -> str:
    if not messages:
        return ""
    bits = []
    for row in messages[:3]:
        bits.append(row["content"][:120])
    return " / ".join(bits)[:400]


def _maybe_refresh_topic_title(
    store: Any,
    topic: dict[str, Any],
    messages: list[dict[str, str]],
    event_bus: Any | None,
    suggested: str = "",
) -> None:
    if topic.get("title_source") == "user":
        return
    title = sanitize_topic_title(suggested) if suggested else ""
    if not title:
        title, _ = generate_topic_title(messages, topic.get("title") or "")
    if not title:
        return
    current = topic.get("title") or ""
    if current and titles_equivalent(current, title):
        return
    if current and current.lower() not in {"new conversation", "new chat", "conversation"} and titles_equivalent(current, title):
        return
    updated = store.update_topic(topic["topic_id"], title=title, title_source="auto")
    _publish(event_bus, topic["session_id"], updated)


def _publish(event_bus: Any | None, session_id: str, topic: dict[str, Any] | None) -> None:
    if event_bus is None or topic is None:
        return
    event_bus.publish(session_id, "session.updated", {"session_id": session_id, "topic": topic})
    event_bus.publish("*", "chat.organization.updated", {"session_id": session_id, "topic": topic})


def start_new_topic(store: Any, session_id: str, *, event_bus: Any | None = None) -> dict[str, Any]:
    """Close the current topic and open a fresh one (New conversation)."""
    start = store.next_message_id(session_id)
    current = store.current_topic(session_id)
    if current is not None and current["start_message_id"] == start:
        return current  # still empty; reuse
    if current is not None:
        last = start - 1
        if last >= int(current["start_message_id"]):
            messages = _topic_messages(store, session_id, current)
            store.update_topic(current["topic_id"], end_message_id=last, summary=_summary_from_messages(messages))
        elif not _topic_messages(store, session_id, current):
            # empty current topic — just keep it
            return current
    topic = store.create_topic(session_id, title="New conversation", start_message_id=start, close_open=False)
    _publish(event_bus, session_id, topic)
    return topic


def ensure_home(app: Any) -> str:
    sid, _ = app._ensure_agent_home(HOME_AGENT_ID, HOME_TITLE)
    session = app.store.get_session(sid)
    if session is not None and (session.get("title") or "").strip().lower() in {"", "native:jaeger", "new chat", "new conversation"}:
        if session.get("title_source") != "user":
            app.store.apply_auto_title(sid, HOME_TITLE, user_turns=0, fingerprint="home", model="home", changed=True)
    return sid


def install(app: Any) -> None:
    try:
        ensure_home(app)
    except Exception:
        logger.warning("could not ensure Jaeger home chat", exc_info=True)
    timers: dict[str, threading.Timer] = {}
    lock = threading.Lock()

    def schedule(session_id: str) -> None:
        if not session_id:
            return

        def run() -> None:
            with lock:
                timers.pop(session_id, None)
            try:
                maybe_update_home_topics(app.store, session_id, event_bus=app.event_bus)
            except Exception:
                logger.info("home topic refresh failed session=%s", session_id[:16])

        with lock:
            previous = timers.get(session_id)
            if previous is not None:
                previous.cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, run)
            timer.daemon = True
            timers[session_id] = timer
            timer.start()

    def observe(evt: Any) -> None:
        if getattr(evt, "event", None) != "turn.finish":
            return
        session_id = getattr(evt, "session_id", "") or ""
        session = app.store.get_session(session_id) if session_id else None
        if session and is_jaeger_home(session_id, session.get("metadata")):
            schedule(session_id)

    app.event_bus.add_observer(observe)
