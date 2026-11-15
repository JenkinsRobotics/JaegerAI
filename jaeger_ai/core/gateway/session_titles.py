"""Conversation-based chat titles, generated after the assistant replies.

The first user message still gets a provisional truncated title. Once the
first assistant reply lands, a cheap model call (Ollama Cloud, then Grok,
then truncation) produces a short topic label. Later turns can refresh it,
but a name the user set is never overwritten.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import threading
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

BACKFILL_META_KEY = "topic_title_backfill_v1"
MIN_USER_TURNS_BETWEEN = 3
MIN_EXTRA_TURNS_FOR_SHIFT = 2
MIN_SECONDS_FOR_SHIFT = 90.0
DEBOUNCE_SECONDS = 1.5
BACKFILL_DELAY_SECONDS = 3.0
CLOUD_TIMEOUT_S = 12.0
GROK_TIMEOUT_S = 25.0
MAX_TITLE_WORDS = 8
MIN_TITLE_WORDS = 1
MAX_TITLE_CHARS = 60
JACCARD_KEEP = 0.7

PREFERRED_CLOUD_MODELS = (
    "inkling-2-small",
    "glm-5.3-flash",
    "deepseek-v4.1-flash",
    "deepseek-v4-flash",
    "mimo-v2.6-flash",
    "minimax-m3.1-flash",
    "glm-5.3-flash:latest",
)

SYSTEM_SESSION_PREFIXES = ("task:", "specialist", "agent-native", "agent-na", "handoff")
SYSTEM_TITLE_PREFIXES = ("[skill-review", "handoff handoff_")

TITLE_SYSTEM_PROMPT = (
    "You name chat conversations. Return only a short 3-6 word topic title "
    "that describes the conversation as a whole, not just the first message. "
    "Use a noun phrase, not a sentence. No quotes, markdown, labels, or prefixes. "
    "If a current title is provided and the topic has not clearly changed, "
    "repeat that exact title. Do not mention that you are writing a title."
)


def is_system_session(session_id: str, title: str | None = None) -> bool:
    ident = (session_id or "").lower()
    if any(ident.startswith(prefix) for prefix in SYSTEM_SESSION_PREFIXES):
        return True
    lowered = (title or "").strip().lower()
    return any(lowered.startswith(prefix) for prefix in SYSTEM_TITLE_PREFIXES)


def conversation_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in messages or []:
        role = str(row.get("role") or "")
        kind = str(row.get("kind") or "message")
        if role not in {"user", "assistant"} or kind not in {"", "message"}:
            continue
        text = " ".join(str(row.get("content") or "").split()).strip()
        if not text:
            continue
        out.append({"role": role, "content": text})
    return out


def user_turn_count(messages: list[dict[str, str]]) -> int:
    return sum(1 for row in messages if row["role"] == "user")


def fingerprint_messages(messages: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for row in messages[-8:]:
        digest.update(row["role"].encode())
        digest.update(b"\0")
        digest.update(row["content"][:400].encode())
        digest.update(b"\n")
    return digest.hexdigest()[:16]


def sanitize_topic_title(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    text = re.sub(r"^[`*'\"“”]+|[`*'\"“”]+$", "", text).strip()
    text = re.sub(
        r"^(session\s+title|title|topic|name)\s*[:\-–—]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(r"\s+", " ", text).strip(" \t.-–—")
    if text.endswith(".") and text.count(" ") <= 7:
        text = text[:-1].rstrip()
    lowered = text.lower()
    if lowered.startswith((
        "the user", "this conversation", "the assistant", "here is", "here is a",
        "sure,", "okay", "ok,", "i'll", "i will", "i am", "i'm", "there isn't",
        "there is", "there isn’t", "listing the", "i can",
    )):
        return ""
    words = text.split()
    if len(words) < MIN_TITLE_WORDS or len(words) > MAX_TITLE_WORDS:
        if len(words) > MAX_TITLE_WORDS:
            text = " ".join(words[:MAX_TITLE_WORDS])
        else:
            return ""
    if len(text) > MAX_TITLE_CHARS:
        trimmed = text[:MAX_TITLE_CHARS].rsplit(" ", 1)[0].rstrip(".,;:")
        text = trimmed or text[:MAX_TITLE_CHARS]
    return text[:MAX_TITLE_CHARS]


def titles_equivalent(left: str, right: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    a, b = norm(left), norm(right)
    if not a or not b:
        return False
    if a == b:
        return True
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= JACCARD_KEEP


def _looks_like_first_message_title(title: str, first_user: str) -> bool:
    from jaeger_ai.core.gateway.session_store import title_from_user_text
    generated = title_from_user_text(first_user)
    return bool(generated) and titles_equivalent(title, generated)


def _session_source(session: dict[str, Any]) -> str:
    value = session.get("title_source")
    if value in {"auto", "user"}:
        return value
    meta = session.get("metadata") or {}
    org = meta.get("chat_organization") or {}
    if org.get("title_source") in {"auto", "user"}:
        return org["title_source"]
    return "user" if org.get("manual_title") else "auto"


def should_refresh(session: dict[str, Any], messages: list[dict[str, str]], *, force: bool = False) -> bool:
    if is_system_session(session.get("session_id") or "", session.get("title")):
        return False
    if _session_source(session) == "user" and not force:
        return False
    if _session_source(session) == "user":
        first = next((row["content"] for row in messages if row["role"] == "user"), "")
        if not _looks_like_first_message_title(session.get("title") or "", first):
            return False
    if user_turn_count(messages) < 1 or not any(row["role"] == "assistant" for row in messages):
        return False
    if force:
        return True
    meta = (session.get("metadata") or {}).get("title_auto") or {}
    if not meta.get("generated"):
        return True
    last_turns = int(meta.get("user_turns") or 0)
    turns = user_turn_count(messages)
    added = turns - last_turns
    if added < MIN_EXTRA_TURNS_FOR_SHIFT:
        return False
    if fingerprint_messages(messages) == str(meta.get("fingerprint") or ""):
        return False
    if added >= MIN_USER_TURNS_BETWEEN:
        return True
    last_at = float(meta.get("updated_at") or 0)
    return (time.time() - last_at) >= MIN_SECONDS_FOR_SHIFT


def _excerpt(messages: list[dict[str, str]], limit: int = 8) -> str:
    parts = []
    for row in messages[-limit:]:
        label = "User" if row["role"] == "user" else "Assistant"
        parts.append(f"{label}: {row['content'][:400]}")
    return "\n".join(parts)


def _title_prompt(messages: list[dict[str, str]], current_title: str) -> str:
    body = (
        "Write a 3-6 word topic title for this conversation.\n"
        f"Current title: {current_title or '(none)'}\n\n"
        f"{_excerpt(messages)}\n"
    )
    return body


def _openai_chat(base_url: str, api_key: str, model: str, user_text: str, timeout: float) -> str:
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url = url + "/v1"
    response = requests.post(
        f"{url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "temperature": 0.2,
            "max_tokens": 32,
            "messages": [
                {"role": "system", "content": TITLE_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return str((((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or "")


def _pick_cloud_model(names: list[str]) -> str | None:
    available = []
    for name in names:
        clean = str(name or "").strip()
        if clean:
            available.append(clean)
    if not available:
        return None
    lower = {name.lower(): name for name in available}
    for preferred in PREFERRED_CLOUD_MODELS:
        if preferred.lower() in lower:
            return lower[preferred.lower()]
    for name in available:
        token = name.lower()
        if any(tag in token for tag in ("flash", "small", "mini", "1b", "3b", "4b", "e4b")):
            return name
    return available[0]


def _ollama_cloud_title(prompt: str) -> str | None:
    from jaeger_ai.core.models.discovery import discover_ollama_cloud
    from jaeger_ai.core.models.router import OLLAMA_CLOUD_OPENAI, ollama_cloud_api_model
    from jaeger_ai.core.secrets_env import ollama_api_key

    key = ollama_api_key()
    if not key:
        return None
    discovered = discover_ollama_cloud(key) or {}
    names = []
    for row in discovered.get("models") or []:
        if isinstance(row, dict):
            names.append(str(row.get("name") or row.get("id") or ""))
        else:
            names.append(str(row))
    model = _pick_cloud_model(names)
    if not model:
        return None
    raw = _openai_chat(OLLAMA_CLOUD_OPENAI, key, ollama_cloud_api_model(model), prompt, CLOUD_TIMEOUT_S)
    title = sanitize_topic_title(raw)
    return title or None


def _text_from_cli_json(raw: str) -> str:
    text = (raw or "").strip()
    candidates = [text]
    candidates.extend(reversed([line.strip() for line in text.splitlines() if line.strip().startswith("{")]))
    for blob in candidates:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        for key in ("text", "output", "content", "response", "message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, dict):
                inner = value.get("content") or value.get("text")
                if isinstance(inner, str) and inner.strip():
                    return inner
    return text


def _grok_title(prompt: str) -> str | None:
    from jaeger_ai.features.cli_backends.discovery import KNOWN_BACKENDS, probe_backend

    spec = next((item for item in KNOWN_BACKENDS if item.id == "grok"), None)
    if spec is None:
        return None
    executable = probe_backend(spec)
    if not executable:
        return None
    args = [executable]
    for part in spec.args:
        args.append(prompt if part == "{prompt}" else part)
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=GROK_TIMEOUT_S,
    )
    if result.returncode != 0:
        logger.info("title model fallback: grok cli exited %s", result.returncode)
        return None
    title = sanitize_topic_title(_text_from_cli_json(result.stdout or ""))
    return title or None


def generate_topic_title(messages: list[dict[str, str]], current_title: str = "") -> tuple[str | None, str]:
    prompt = _title_prompt(messages, current_title)
    try:
        title = _ollama_cloud_title(prompt)
        if title:
            return title, "ollama-cloud"
    except Exception:
        logger.info("title model fallback: ollama cloud unavailable")
    try:
        title = _grok_title(prompt)
        if title:
            return title, "grok"
    except Exception:
        logger.info("title model fallback: grok unavailable")
    first = next((row["content"] for row in messages if row["role"] == "user"), "")
    from jaeger_ai.core.gateway.session_store import title_from_user_text
    fallback = title_from_user_text(first)
    return (fallback or None), "truncation"


def maybe_update_session_title(store: Any, session_id: str, *, event_bus: Any | None = None, force: bool = False) -> str | None:
    session = store.get_session(session_id)
    if session is None:
        return None
    messages = conversation_messages(session.get("messages") or [])
    if not should_refresh(session, messages, force=force):
        return None
    current = str(session.get("title") or "").strip()
    title, source = generate_topic_title(messages, current)
    if not title:
        return None
    if current and titles_equivalent(current, title) and source != "truncation":
        title = current
    elif current and titles_equivalent(current, title):
        store.apply_auto_title(
            session_id,
            current,
            user_turns=user_turn_count(messages),
            fingerprint=fingerprint_messages(messages),
            model=source,
            changed=False,
            allow_heal=_session_source(session) == "user",
        )
        return None
    changed = store.apply_auto_title(
        session_id,
        title,
        user_turns=user_turn_count(messages),
        fingerprint=fingerprint_messages(messages),
        model=source,
        changed=title != current,
        allow_heal=_session_source(session) == "user",
    )
    if not changed:
        return None
    if event_bus is not None:
        updated = store.get_session(session_id)
        if updated is not None:
            event_bus.publish(session_id, "session.updated", {"session": updated})
    logger.info("session title updated session=%s source=%s", session_id[:12], source)
    return title


def _backfill_marked(store: Any) -> bool:
    with store._get_conn() as conn:
        row = conn.execute("SELECT value FROM schema_meta WHERE key=?", (BACKFILL_META_KEY,)).fetchone()
        return bool(row)


def _mark_backfill(store: Any, payload: dict[str, Any]) -> None:
    with store._get_conn() as conn:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (BACKFILL_META_KEY, json.dumps(payload)),
        )


def backfill_topic_titles(store: Any, *, event_bus: Any | None = None) -> dict[str, int]:
    stats = {"updated": 0, "skipped": 0, "failed": 0}
    if _backfill_marked(store):
        return stats
    rows = store.list_sessions()
    for row in rows:
        session_id = row["session_id"]
        try:
            title = maybe_update_session_title(store, session_id, event_bus=event_bus, force=True)
            if title:
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        except Exception:
            stats["failed"] += 1
            logger.info("session title backfill failed session=%s", session_id[:12])
    stats["done"] = 1  # type: ignore[typeddict-item]
    _mark_backfill(store, {"done": True, "updated": stats["updated"], "skipped": stats["skipped"], "failed": stats["failed"]})
    logger.info(
        "session title backfill complete updated=%s skipped=%s failed=%s",
        stats["updated"], stats["skipped"], stats["failed"],
    )
    return stats


def install(app: Any) -> None:
    """Watch turn.finish and refresh titles off the event-bus thread."""
    timers: dict[str, threading.Timer] = {}
    lock = threading.Lock()

    def schedule(session_id: str) -> None:
        if not session_id or session_id == "*":
            return

        def run() -> None:
            with lock:
                timers.pop(session_id, None)
            try:
                maybe_update_session_title(app.store, session_id, event_bus=app.event_bus)
            except Exception:
                logger.info("session title refresh failed session=%s", session_id[:12])

        with lock:
            previous = timers.get(session_id)
            if previous is not None:
                previous.cancel()
            timer = threading.Timer(DEBOUNCE_SECONDS, run)
            timer.daemon = True
            timers[session_id] = timer
            timer.start()

    def observe(evt: Any) -> None:
        if getattr(evt, "event", None) == "turn.finish":
            schedule(getattr(evt, "session_id", "") or "")

    app.event_bus.add_observer(observe)

    def backfill() -> None:
        time.sleep(BACKFILL_DELAY_SECONDS)
        try:
            backfill_topic_titles(app.store, event_bus=app.event_bus)
        except Exception:
            logger.warning("session title backfill failed", exc_info=True)

    def repair() -> None:
        time.sleep(BACKFILL_DELAY_SECONDS + 1)
        try:
            for row in app.store.list_sessions():
                if row.get("title_source") == "user":
                    continue
                title = str(row.get("title") or "")
                if title and sanitize_topic_title(title):
                    continue
                generated = ((row.get("metadata") or {}).get("title_auto") or {}).get("generated")
                if not generated:
                    continue
                try:
                    maybe_update_session_title(app.store, row["session_id"], event_bus=app.event_bus, force=True)
                except Exception:
                    logger.info("session title repair failed session=%s", str(row["session_id"])[:12])
        except Exception:
            logger.warning("session title repair failed", exc_info=True)

    threading.Thread(target=backfill, name="topic-title-backfill", daemon=True).start()
    threading.Thread(target=repair, name="topic-title-repair", daemon=True).start()
