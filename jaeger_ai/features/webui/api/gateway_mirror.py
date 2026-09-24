"""Project the Gateway's conversations into the WebUI session store.

One source of truth: the Gateway's ``gateway_sessions.sqlite3`` owns every
conversation, its transcript and its title. The WebUI's per-session JSON files
are a read-through cache of that store, not a second copy that can drift. This
module is the only writer of that cache for Gateway-backed sessions:

* a conversation started in the IDE (or any other client) appears in the WebUI
  sidebar because :func:`mirror_all` upserts it;
* opening a session refreshes its transcript from the Gateway
  (:func:`mirror_session`);
* a finished WebUI turn re-reads the Gateway's transcript instead of appending
  its own copy;
* titles are set on the Gateway (:func:`push_title`) and mirrored back.

A session with a stream in flight is never touched: the WebUI owns its partial
state until the Gateway has the final message.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from jaeger_ai.contract.sessions import is_conversation_session

logger = logging.getLogger(__name__)

_GENERIC_TITLES = frozenset({"", "new conversation", "untitled", "new chat"})
_SWEEP_MIN_INTERVAL_S = 2.0
_TIMEOUT_S = 5.0

_lock = threading.Lock()
_fingerprints: dict[str, tuple[Any, int]] = {}
_last_sweep = 0.0


def _base() -> str:
    from api.jaeger_sessions import gateway_base

    return gateway_base()


def _request(method: str, path: str, body: dict | None = None) -> Any | None:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{_base()}{path}", data=data, method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # The Gateway being down is a normal state for a cache: keep serving it.
        logger.debug("gateway %s %s unavailable: %s", method, path, exc)
        return None


def _is_generic(title: str | None) -> bool:
    return str(title or "").strip().lower() in _GENERIC_TITLES


def _to_webui_messages(gateway_messages: list[dict], local: list[dict]) -> list[dict]:
    """Gateway transcript as WebUI rows, reusing a local row when it is the same message.

    A locally authored row can carry display extras (attachments, reasoning) the
    Gateway does not store; matching on (role, content) keeps them.
    """
    by_key: dict[tuple[str, str], list[dict]] = {}
    for row in local:
        if isinstance(row, dict):
            by_key.setdefault((str(row.get("role")), str(row.get("content"))), []).append(row)
    out: list[dict] = []
    for msg in gateway_messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        content = content if isinstance(content, str) else json.dumps(content)
        reuse = by_key.get((role, content))
        if reuse:
            out.append(reuse.pop(0))
        else:
            out.append({"role": role, "content": content, "timestamp": msg.get("timestamp")})
    return out


def list_gateway_conversations() -> list[dict] | None:
    """Conversation sessions the Gateway holds, or ``None`` if it is unreachable."""
    payload = _request("GET", "/v1/sessions")
    if not isinstance(payload, dict):
        return None
    return [s for s in payload.get("sessions", []) if is_conversation_session(s)]


def mirror_session(session_id: str, *, gateway_session: dict | None = None) -> bool:
    """Make the WebUI copy of ``session_id`` match the Gateway. True if it changed.

    Returns False when the Gateway is unreachable, the session is unknown to it,
    or a stream is in flight on the WebUI side.
    """
    from api import models

    gw = gateway_session
    if gw is None or "messages" not in gw:
        gw = _request("GET", f"/v1/sessions/{urllib.parse.quote(session_id, safe='')}")
    if not isinstance(gw, dict) or gw.get("error") or not is_conversation_session(gw):
        return False

    try:
        session = models.get_session(session_id)
    except Exception:  # not cached locally yet
        session = None
    if session is not None and getattr(session, "active_stream_id", None):
        return False

    local = list(getattr(session, "messages", None) or [])
    messages = _to_webui_messages(gw.get("messages") or [], local)
    gw_title = str(gw.get("title") or "")
    local_title = str(getattr(session, "title", "") or "")
    if _is_generic(gw_title) and not _is_generic(local_title) and session is not None:
        # The Gateway has no better name than the one the WebUI generated.
        push_title(session_id, local_title)
        gw_title = local_title
    title = gw_title if not _is_generic(gw_title) else (local_title or gw_title or "New conversation")
    updated = gw.get("updated_at") or time.time()
    last_ts = next((m.get("timestamp") for m in reversed(messages) if m.get("timestamp")), updated)

    if session is None:
        session = models.Session(
            session_id=session_id, title=title, workspace=gw.get("workspace") or models.DEFAULT_WORKSPACE,
            messages=messages, created_at=gw.get("created_at"), updated_at=updated,
            profile=gw.get("profile"),
        )
        changed = True
    else:
        changed = (session.messages != messages or session.title != title)
        session.messages = messages
        session.title = title
        if gw.get("workspace"):
            session.workspace = gw["workspace"]
        if gw.get("profile"):
            session.profile = gw["profile"]
        session.updated_at = updated
    session.last_message_at = last_ts
    session.save(touch_updated_at=False)
    with models.LOCK:
        models.SESSIONS[session.session_id] = session
    with _lock:
        _fingerprints[session_id] = (gw.get("updated_at"), len(messages))
    return changed


def mirror_all(*, force: bool = False) -> int:
    """Upsert every stale Gateway conversation into the WebUI store; return how many changed."""
    global _last_sweep
    now = time.monotonic()
    with _lock:
        if not force and now - _last_sweep < _SWEEP_MIN_INTERVAL_S:
            return 0
        _last_sweep = now
    listed = list_gateway_conversations()
    if listed is None:
        return 0
    changed = 0
    for entry in listed:
        sid = entry["session_id"]
        with _lock:
            seen = _fingerprints.get(sid)
        if not force and seen and seen[0] == entry.get("updated_at"):
            continue
        try:
            changed += bool(mirror_session(sid))
        except Exception:
            logger.warning("mirroring gateway session %s failed", sid, exc_info=True)
    return changed


def push_title(session_id: str, title: str) -> bool:
    """Rename on the Gateway, the owner of titles. True when it accepted."""
    result = _request(
        "PATCH", f"/v1/sessions/{urllib.parse.quote(session_id, safe='')}", {"title": title},
    )
    return isinstance(result, dict) and not result.get("error")
