"""Topic-aware session titling for the Jaeger gateway.

The gateway used to leave every chat session at the placeholder title
"New Conversation" (only ``task:`` sessions got real names from the
dispatcher). This module ports the provenance contract of the vendored
Hermes titler (``vendor/hermes_agent/agent/title_generator.py``) to the
gateway store, in two stages, both off the critical path:

* **Stage 1 — instant derived title** (deterministic, cannot fail):
  written the moment the first user message lands, so the sidebar never
  shows "New Conversation" past the first message.
* **Stage 2 — LLM upgrade** (one cheap background call): replaces the
  derived title with a 3–7 word topical title once the model is reachable.

Provenance is stored in session metadata as ``title_provenance`` and
enforces ``derived < llm < user``: stage 2 only replaces stage 1, and a
title the user typed (or renamed to) is never overwritten. Placeholder
titles ("New Conversation" / "New chat") are always fair game.

The LLM call targets the same OpenAI-compatible endpoint the runtime
already uses (read from ``~/.hermes/config.yaml``), so no new provider
setup is required. Every failure path is silent-by-design: titling must
never break message persistence.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Titles that mean "nobody named this yet" — always safe to replace.
PLACEHOLDER_TITLES = frozenset({"new conversation", "new chat", "new_conversation"})

# Provenance ladder: higher wins; a lower-provenance writer never clobbers.
_PROV_RANK = {"derived": 0, "llm": 1, "user": 2}

# Stage-1 cap: a raw fragment reads worse the longer it runs (mirrors the
# vendored titler's MAX_DERIVED_TITLE_CHARS).
MAX_DERIVED_TITLE_CHARS = 48
# Stage-2 input budget (Claude Code / OpenClaw converged on 1000).
MAX_TITLE_INPUT_CHARS = 1000
# A title is 3-7 words; >12 means the small model answered instead of titling.
_MAX_TITLE_WORDS = 12
# LLM call budget: room for a reasoning model that thinks despite the
# thinking-off request, without letting a runaway reply hang the thread.
_TITLE_TIMEOUT_S = 25.0

# Control-tag wrappers around machine-authored content inside a nominal
# "user" message (kept in sync with the vendored titler's list).
_CONTROL_WRAPPER_RE = re.compile(
    r"<(?:command-message|command-name|command-args|local-command-caveat|"
    r"local-command-stderr|local-command-stdout|task-notification|"
    r"system-reminder|ide_opened_file|ide_selection)>.*?</\1>\s*",
    re.DOTALL,
)
# Machine-authored openers that must never name a session.
_MACHINE_PREFIXES = (
    "[CONTEXT COMPACTION", "[Runtime note:", "[System note:", "[SYSTEM]",
    "[System: The active model for this chat has changed to ",
)
# Footers appended below the typed text by the @-reference expander / paste
# preview: strip everything from these markers on.
_CONTEXT_FOOTER_RE = re.compile(r"\n+--- (?:Context Warnings|Attached Context) ---\n.*", re.DOTALL)
_PASTE_PREVIEW_LABEL = "\n\nPasted content:\n"

# Echo guard: the prompt's examples must never come back as a real title
# (a small model sometimes parrots them verbatim). "Friendly greeting" is
# deliberately absent — it is the *requested* output for bare greetings,
# handled as a provisional title instead of a settled one.
_PROMPT_GOOD_EXAMPLES = (
    "Fix login button on mobile",
    "Postgres connection pool exhaustion",
)
_ECHO_REJECT = frozenset(t.lower() for t in _PROMPT_GOOD_EXAMPLES)
# Predictable placeholder for openers with no topic yet: persisted at
# ``derived`` authority so the next substantive turn upgrades it.
_PROVISIONAL_GREETING_TITLE = "friendly greeting"

_TITLE_PROMPT = (
    "You name chat sessions. Given the user's message, write a title "
    "that lets them find this conversation again in a list.\n\n"
    "Rules:\n"
    "- 3 to 7 words, sentence case (capitalize only the first word and proper nouns).\n"
    "- Name what the user wants DONE, not that they asked a question.\n"
    "- Keep technical terms, filenames, numbers, and error codes exact.\n"
    "- Drop filler words: the, this, my, a, an.\n"
    "- No trailing punctuation, no quotes, no tool names, no 'Title:' prefix.\n"
    "- Never answer the message. Name it.\n"
    "- Always produce something, even for a bare greeting.\n"
    + "".join(f'Good: {{"title": "{t}"}}\n' for t in _PROMPT_GOOD_EXAMPLES)
    + 'Too vague: {"title": "Code changes"}\n'
    'Too long: {"title": "Investigate and fix the issue where the login button '
    'does not respond on mobile devices"}\n\n'
    'Reply with JSON only: {"title": "..."}'
)

# In-flight stage-2 upgrades, deduped per session.
_INFLIGHT: set[str] = set()
_INFLIGHT_LOCK = threading.Lock()


def is_placeholder_title(title: str | None) -> bool:
    return bool(title) and title.strip().lower() in PLACEHOLDER_TITLES


def _clean_opener(text: str) -> str:
    """Reduce a user message to the human-typed opener, best effort."""
    if not text:
        return ""
    for prefix in _MACHINE_PREFIXES:
        if text.startswith(prefix):
            return ""
    cleaned = _CONTROL_WRAPPER_RE.sub(" ", text)
    cleaned = _CONTEXT_FOOTER_RE.sub("", cleaned)
    idx = cleaned.find(_PASTE_PREVIEW_LABEL)
    if idx != -1:
        cleaned = cleaned[:idx]
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def derive_instant_title(text: str) -> str:
    """Deterministic stage-1 title from the user's opening text.

    Returns "" when the opener carries no usable signal (machine wrapper,
    empty) — the caller then leaves the existing title alone.
    """
    cleaned = _clean_opener(text)
    if not cleaned:
        return ""
    if len(cleaned) <= MAX_DERIVED_TITLE_CHARS:
        title = cleaned
    else:
        cut = cleaned[:MAX_DERIVED_TITLE_CHARS]
        # Prefer a clean word boundary over a mid-word slice.
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        title = cut.rstrip(" ,.;:!?-—")
    if not title:
        return ""
    return title[0].upper() + title[1:]


def _title_model_config() -> tuple[str, str]:
    """(model, base_url) for the title call — the runtime's own route.

    Read from ``~/.hermes/config.yaml`` (model.default / model.base_url),
    falling back to the local Ollama defaults this deployment uses.
    """
    default_model, default_base = "glm-5.3-flash:cloud", "http://127.0.0.1:11434/v1"
    path = Path.home() / ".hermes" / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return default_model, default_base
    model, base = "", ""
    try:
        import yaml  # type: ignore[import-untyped]
        cfg = yaml.safe_load(text) or {}
        m = cfg.get("model") or {}
        model = str(m.get("default") or "").strip()
        base = str(m.get("base_url") or "").strip()
    except Exception:
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("default:") and not model:
                model = s.split(":", 1)[1].strip()
            elif s.startswith("base_url:") and not base:
                base = s.split(":", 1)[1].strip()
    return (model or default_model, (base or default_base).rstrip("/"))


def _parse_llm_title(raw: str) -> str:
    """Extract + guard the model's title reply. "" means reject."""
    raw = (raw or "").strip()
    # Tolerate a fenced reply or prose around the JSON object.
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            raw = str(data.get("title") or "").strip()
        except Exception:
            pass
    title = re.sub(r"\s+", " ", raw).strip().strip('"').rstrip(".!?:;,")
    if not title:
        return ""
    if len(title.split()) > _MAX_TITLE_WORDS:
        return ""  # answer-shaped output, not a title
    if title.lower() in _ECHO_REJECT:
        return ""
    return title


def llm_title(text: str) -> str:
    """Stage-2: one cheap chat-completion call → guarded topical title.

    Returns "" on any failure (unreachable endpoint, bad JSON, guard
    rejection) — callers keep the stage-1 title.
    """
    cleaned = _clean_opener(text)[:MAX_TITLE_INPUT_CHARS]
    if not cleaned:
        return ""
    model, base_url = _title_model_config()
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _TITLE_PROMPT},
            {"role": "user", "content": cleaned},
        ],
        "stream": False,
        "think": False,
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TITLE_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        content = str(((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    except Exception:
        logger.debug("title LLM call failed", exc_info=True)
        return ""
    return _parse_llm_title(content)


def _current_provenance(store: Any, session_id: str) -> str:
    try:
        sess = store.get_session(session_id)
    except Exception:
        return "user"  # fail closed: never overwrite what we cannot read
    if not sess:
        return "user"
    meta = sess.get("metadata") or {}
    prov = str(meta.get("title_provenance") or "").strip().lower()
    if prov in _PROV_RANK:
        return prov
    # Legacy rows: a placeholder title counts as derived; anything else
    # (client-supplied at creation) counts as user-authored.
    return "derived" if is_placeholder_title(sess.get("title")) else "user"


def _set_title(store: Any, session_id: str, title: str, provenance: str) -> None:
    try:
        store.set_title(session_id, title, provenance)
    except Exception:
        logger.debug("failed to persist title for %s", session_id, exc_info=True)


def on_user_message(store: Any, session_id: str, text: str) -> None:
    """Titling hook: call after a user message is persisted.

    Stage 1 runs inline (one short UPDATE); stage 2 runs on a daemon
    thread so the turn is never delayed. Every path is exception-guarded:
    titling must never break message persistence.
    """
    try:
        prov = _current_provenance(store, session_id)
        if prov == "user":
            return  # a title the user chose is final
        if prov == "derived":
            instant = derive_instant_title(text)
            if instant:
                _set_title(store, session_id, instant, "derived")
        _spawn_llm_upgrade(store, session_id, text)
    except Exception:
        logger.debug("titling hook failed for %s", session_id, exc_info=True)


def _spawn_llm_upgrade(store: Any, session_id: str, text: str) -> None:
    with _INFLIGHT_LOCK:
        if session_id in _INFLIGHT:
            return
        _INFLIGHT.add(session_id)

    def _run() -> None:
        try:
            title = llm_title(text)
            if not title:
                return
            prov = _current_provenance(store, session_id)
            if _PROV_RANK.get(prov, 2) >= _PROV_RANK["llm"]:
                return  # user renamed (or a newer llm title) meanwhile
            if title.lower() == _PROVISIONAL_GREETING_TITLE:
                # Bare greeting: keep it provisional so the next substantive
                # turn upgrades the title to the real topic.
                _set_title(store, session_id, title.title(), "derived")
                return
            _set_title(store, session_id, title, "llm")
        except Exception:
            logger.debug("llm title upgrade failed for %s", session_id, exc_info=True)
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.discard(session_id)

    thread = threading.Thread(target=_run, name=f"title-upgrade-{session_id[:8]}", daemon=True)
    thread.start()