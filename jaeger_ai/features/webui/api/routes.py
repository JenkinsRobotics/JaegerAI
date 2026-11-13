"""
Hermes Web UI -- Route handlers for GET and POST endpoints.
Extracted from server.py (Sprint 11) so server.py is a thin shell.
"""

import html as _html
import copy
import hashlib
import inspect
import errno
import io
import gzip
import json
from api.sse_chunked import end_sse_headers
import logging
import os
import queue
import re
import platform
import shlex
import shutil
import sqlite3
import stat as _stat
import subprocess
import sys
import threading
import time
import uuid
import http.client
import socket as _socket
from collections import defaultdict, deque, OrderedDict
from pathlib import Path
from contextlib import closing
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from api.agent_runtime import (AgentRuntimeChangedError, ensure_agent_runtime_current)
from api.agent_sessions import (MESSAGING_SOURCES, is_cli_session_row, is_cli_session_row_visible)
from api.compression_anchor import visible_messages_for_anchor
from api.compression_recovery import (clear_compression_recovery, compression_recovery_payload_for_session, is_generic_continuation_intent)
from api.session_events import (add_session_list_changed_listener, publish_session_list_changed)

logger = logging.getLogger(__name__)


def _publish_session_list_changed(
    reason: str,
    *,
    profile: str | None = None,
    session_id: str | None = None,
) -> None:
    """Invalidate the route cache and publish a scoped sidebar change."""
    # The event bus also owns a cache listener, but an import-order failure or
    # a replaced listener must never leave the HTTP response cache stale. The
    # mutation route is the authoritative producer, so invalidate here before
    # notifying browser subscribers.
    try:
        _clear_session_list_cache(profile)
    except Exception:
        logger.debug("Failed to invalidate session-list cache", exc_info=True)
    if not profile and not session_id:
        publish_session_list_changed(reason)
        return
    try:
        publish_session_list_changed(reason, profile=profile, session_id=session_id)
    except TypeError:
        # Some focused tests monkeypatch the route-level publisher with the
        # historical one-argument or profile-only shape. Preserve the old signal instead of
        # turning unrelated session mutations into 500s.
        if profile:
            try:
                publish_session_list_changed(reason, profile=profile)
                return
            except TypeError:
                pass
        publish_session_list_changed(reason)








def _on_session_list_changed(profile: str | None = None) -> None:
    """Invalidate in-process /api/sessions cache when sidebar state mutates."""
    _clear_session_list_cache(profile)
    # #4842: also drop the inner CLI/cron projection cache. While a turn streams
    # that cache is frozen on a stable streaming marker (so per-token message
    # writes don't bust it), which means it no longer self-invalidates via the
    # state.db content fingerprint mid-stream. In-app structural mutations
    # (session create/rename/archive/delete/branch/pin/move/import, attention)
    # fire this listener — and never fire per streamed token — so clearing here
    # restores prompt freshness for those without reintroducing the per-poll
    # rebuild the freeze removed. Note: externally-driven changes that do NOT go
    # through this listener (a scheduled cron job completing, or an external CLI
    # writing rows directly) are not cleared here mid-stream; for those the 30s
    # streaming TTL is the backstop — they surface within one streaming-TTL
    # window (≤30s) rather than instantly. That bound is the deliberate
    # latency/CPU trade-off of the freeze.
    try:
        from api.models import clear_cli_sessions_cache
        clear_cli_sessions_cache()
    except Exception:
        logger.debug("Failed to clear CLI sessions cache on session list change", exc_info=True)


try:
    add_session_list_changed_listener(_on_session_list_changed)
except Exception:
    logger.debug("Failed to register session list cache invalidation listener", exc_info=True)


# ── Cron run tracking ────────────────────────────────────────────────────────
# Track job IDs currently being executed so the frontend can poll status.
_RUNNING_CRON_JOBS: dict[str, float] = {}  # job_id → start_timestamp
_RUNNING_CRON_LOCK = threading.Lock()
_MESSAGING_RAW_SOURCES = {str(s).strip().lower() for s in MESSAGING_SOURCES}
_MESSAGING_SESSION_METADATA_CACHE: dict[str, object] = {
    "path": None,
    "mtime": None,
    "identity": {},
}
_MESSAGING_SESSION_METADATA_LOCK = threading.Lock()
_STALE_MESSAGING_END_REASONS = {"session_reset", "session_switch"}
_CSP_REPORT_LOGGER = logging.getLogger("csp_report")
_CSP_REPORT_RATE_LIMIT: dict[str, list[float]] = {}
_CSP_REPORT_RATE_LIMIT_LOCK = threading.Lock()
_CSP_REPORT_RATE_LIMIT_WINDOW_SECONDS = 60
_CSP_REPORT_RATE_LIMIT_MAX = 100
_CSP_REPORT_MAX_BODY_BYTES = 64 * 1024
_EXTENSION_SIDECAR_PROXY_MAX_RESPONSE_BYTES = 512 * 1024















# ── Profile-scoped session/project filtering (#1611, #1614) ────────────────
#
# Sessions and projects are stored in the WebUI sidecar without per-row
# isolation by default — they're tagged with a `profile` field but every
# query saw all rows. The fix scopes both endpoints to the active profile
# by default, with `?all_profiles=1` opting into aggregate mode.
#
# Renamed-root profile handling (#1612): a row tagged `profile='default'`
# matches the active root regardless of the root's display name, and a row
# tagged with the renamed-root display name (e.g. 'kinni') likewise matches
# when the active profile is `'default'`. _is_root_profile() is the
# canonical check.

# Canonical helper now lives in api.profiles so out-of-process consumers
# (mcp_server.py) can import it without duplicating the visibility model.
# Re-exported here so existing `_profiles_match(...)` call sites in this
# module keep resolving without per-call-site refactors.
from api.profiles import (_profiles_match, _is_isolated_profile_mode, _is_root_profile, get_active_profile_name, get_active_profile_name as _get_active_profile_name, get_active_hermes_home, list_profiles_api, profile_scope_for_detached_worker)










def _session_visible_to_active_profile(session_profile, handler=None) -> bool:
    """Return whether a detail-load session belongs to the active profile.

    Real request handlers must enforce the same profile boundary as
    /api/sessions, even when the request has no hermes_profile cookie and the
    process-level active profile is the default/root profile. Direct unit-callers
    without a request handler keep the historical metadata-load behavior.
    """
    if handler is None:
        return True
    active_profile = _get_active_profile_name()
    if not isinstance(session_profile, str):
        session_profile = None
    return _profiles_match(session_profile, active_profile)


def _is_profile_agnostic_foreign_session(cli_meta) -> bool:
    """Return whether a foreign-session row lives outside the Hermes profile tree.

    Claude Code transcripts are scanned straight out of ``~/.claude/projects``
    by ``get_claude_code_sessions()``, which stamps ``profile: None`` on every
    row because the JSONL files belong to no Hermes profile at all. The sidebar
    lists them under whichever profile is active, but ``_profiles_match``
    coerces ``None`` to ``'default'``, so the detail-load profile gate 404s
    every one of them as soon as the active profile is a named (non-root) one —
    the session shows in the list and then renders "Session not available in
    web UI." when clicked.

    Exempt these profile-less external-agent rows from the gate so opening one
    behaves identically on the root profile and on named profiles. Rows that
    DO carry a profile (every state.db-backed CLI/messaging/cron session) stay
    fully scoped.
    """
    if not isinstance(cli_meta, dict):
        return False
    if cli_meta.get("profile"):
        return False
    sources = {
        str(cli_meta.get("source_tag") or "").strip().lower(),
        str(cli_meta.get("raw_source") or "").strip().lower(),
    }
    # Profile-less external-agent rows that live outside the Hermes profile tree.
    # Claude Code: scanned from ~/.claude/projects; Codex: scanned from ~/.codex/
    profile_agnostic_sources = {CLAUDE_CODE_SOURCE}
    try:
        from api.codex_sessions import CODEX_SOURCE
        profile_agnostic_sources.add(CODEX_SOURCE)
    except ImportError:
        pass
    return bool(sources & profile_agnostic_sources)


def _session_visible_in_profile_sidebar(session: dict, active_profile: str | None) -> bool:
    """Keep profile-owned rows and global read-only external-agent transcripts."""
    return _profiles_match(session.get("profile"), active_profile) or (
        _is_profile_agnostic_foreign_session(session)
    )


def _request_session_visibility_exempt(method: str, path: str | None) -> bool:
    if not path:
        return False
    if method == "GET" and path == "/api/session":
        # Detail-load owns profile mismatch handling so the frontend can switch
        # to the session's profile instead of treating a valid cross-profile
        # deep link as a deleted/stale session.
        return True
    if method != "POST":
        return False
    # Import routes create/claim sessions before normal ownership exists, and
    # chat/start has inline placeholder-retag rules that must run before the
    # generic request-session guard.
    return path in {
        "/api/session/import",
        "/api/session/import_cli",
        "/api/chat/start",
    }


def _session_id_visible_to_request_profile(handler, sid, *, emit_error: bool = True) -> bool:
    """Return whether ``sid`` belongs to the active profile."""
    if not isinstance(sid, str) or not sid:
        return True
    if not is_safe_session_id(sid):
        return True
    try:
        session = get_session(sid, metadata_only=True)
    except KeyError:
        cli_meta = _lookup_cli_session_metadata(sid) or {}
        session_profile = cli_meta.get("profile")
        if not session_profile:
            return True
    else:
        session_profile = getattr(session, "profile", None)
        if not session_profile:
            cli_meta = _lookup_cli_session_metadata(sid) or {}
            session_profile = cli_meta.get("profile")
    if not _session_visible_to_active_profile(session_profile, handler):
        if emit_error:
            bad(handler, "Session not found", 404)
        return False
    return True






def _guard_request_session_visibility(handler, parsed, body=None, method="GET") -> bool:
    """Apply request session-profile visibility check to request-supplied IDs.

    Covers top-level `session_id` in the query/body. Routes that accept session
    IDs under other keys must enforce their own visibility checks.
    """
    method = str(method).upper()
    if _request_session_visibility_exempt(method, getattr(parsed, "path", "")):
        return True
    sid = parse_qs(getattr(parsed, "query", "") or "").get("session_id", [None])[0]
    if not _session_id_visible_to_request_profile(handler, sid):
        return False
    if isinstance(body, dict) and not _session_id_visible_to_request_profile(handler, body.get("session_id")):
        return False
    return True



































# ── SSE app-level heartbeat (#1623) ────────────────────────────────────────
#
# Kernel TCP keepalive (server.py setsockopt block) declares a peer dead at
# KEEPIDLE (10s) + KEEPINTVL (5s) * KEEPCNT (3) = 25s in the worst case. The
# app-level SSE heartbeat must fire well below that window so flaky-network
# probes never get the chance to kill an idle stream during long LLM thinking
# phases. 5s gives the kernel ~5x headroom: probe at 10s, heartbeat byte at
# every 5s of idle keeps the socket warm.
#
# Cost: ~12 bytes per heartbeat * 12 extra heartbeats/min = ~150B/min idle.
# Trivial; many production SSE deployments run 5-15s heartbeats specifically
# to handle proxies and mobile NAT.
_SSE_HEARTBEAT_INTERVAL_SECONDS = 5
_SESSION_SSE_SENT_EVENT_ID_LIMIT = 4096


def _normalize_messaging_source(raw_source) -> str:
    return str(raw_source or "").strip().lower()


def _is_known_messaging_source(raw_source) -> bool:
    return _normalize_messaging_source(raw_source) in _MESSAGING_RAW_SOURCES


def _safe_first(*values):
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _gateway_session_metadata_path():
    try:
        from api.profiles import get_active_hermes_home
        hermes_home = Path(get_active_hermes_home()).expanduser().resolve()
    except Exception:
        hermes_home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".jaeger" / "hermes"))).expanduser().resolve()
    return hermes_home / "sessions" / "sessions.json"


def _load_gateway_session_identity_map() -> dict[str, dict]:
    path = _gateway_session_metadata_path()
    if not path.exists():
        return {}

    try:
        st = path.stat()
        cache = _MESSAGING_SESSION_METADATA_CACHE
        with _MESSAGING_SESSION_METADATA_LOCK:
            if cache["path"] == str(path) and cache["mtime"] == st.st_mtime:
                return cache["identity"].copy()
    except Exception:
        return {}

    try:
        raw_sessions = json.loads(path.read_text(encoding="utf-8"))
    except Exception as _json_err:
        logger.debug("Failed to parse gateway sessions metadata from %s: %s", path, _json_err)
        return {}

    mapping: dict[str, dict] = {}
    if isinstance(raw_sessions, dict):
        for _entry in raw_sessions.values():
            if not isinstance(_entry, dict):
                continue
            session_id = _safe_first(_entry.get("session_id"))
            if not session_id:
                continue
            origin = _entry.get("origin") if isinstance(_entry.get("origin"), dict) else {}
            platform = _safe_first(origin.get("platform"), _entry.get("platform"))
            mapping[session_id] = {
                "session_key": _safe_first(_entry.get("session_key"), _entry.get("key")),
                "chat_id": _safe_first(origin.get("chat_id"), _entry.get("chat_id")),
                "thread_id": _safe_first(origin.get("thread_id"), _entry.get("thread_id")),
                "chat_type": _safe_first(origin.get("chat_type"), _entry.get("chat_type")),
                "user_id": _safe_first(origin.get("user_id"), _entry.get("user_id")),
                "platform": platform,
                "raw_source": platform,
            }

    with _MESSAGING_SESSION_METADATA_LOCK:
        _MESSAGING_SESSION_METADATA_CACHE["path"] = str(path)
        _MESSAGING_SESSION_METADATA_CACHE["mtime"] = st.st_mtime
        _MESSAGING_SESSION_METADATA_CACHE["identity"] = mapping
    return mapping.copy()











def _mark_cron_running(job_id: str):
    with _RUNNING_CRON_LOCK:
        _RUNNING_CRON_JOBS[job_id] = time.time()


def _mark_cron_done(job_id: str):
    with _RUNNING_CRON_LOCK:
        _RUNNING_CRON_JOBS.pop(job_id, None)



































_PROVIDER_ALIASES = {
    "claude": "anthropic",
    "gpt": "openai",
    "gemini": "google",
    "openai-codex": "openai",
    "openai-api": "openai",
    "google-gemini": "google",
    "google-ai-studio": "google",
    "claude-code": "anthropic",
}













from api import route_session_list_cache as _route_session_list_cache

_SESSIONS_CACHE = _route_session_list_cache._SESSIONS_CACHE
_SESSIONS_CACHE_LOCK = _route_session_list_cache._SESSIONS_CACHE_LOCK
_SESSIONS_CACHE_PROFILE_INVALIDATION_VERSION = (
    _route_session_list_cache._SESSIONS_CACHE_PROFILE_INVALIDATION_VERSION
)
_SESSIONS_CACHE_TTL_SECONDS = _route_session_list_cache._SESSIONS_CACHE_TTL_SECONDS
_clear_session_list_cache = _route_session_list_cache._clear_session_list_cache
_session_list_cache_clear = _route_session_list_cache._session_list_cache_clear
_session_list_cache_path_stamp = _route_session_list_cache._session_list_cache_path_stamp
_session_list_cache_profile_scope = _route_session_list_cache._session_list_cache_profile_scope
_session_list_cache_source_stamp = _route_session_list_cache._session_list_cache_source_stamp
_session_list_cache_state_db_fingerprint = _route_session_list_cache._session_list_cache_state_db_fingerprint
_session_list_cache_streaming_freeze_marker = _route_session_list_cache._session_list_cache_streaming_freeze_marker


def _callable_accepts_kwarg(callable_obj, kwarg_name: str) -> bool:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    if kwarg_name in signature.parameters:
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )



_ROUTE_SESSION_LIST_CACHE_DYNAMIC_EXPORTS = {
    "_SESSIONS_CACHE_ALL_PROFILES_INVALIDATION_VERSION",
    "_SESSIONS_CACHE_GLOBAL_INVALIDATION_VERSION",
    "_session_list_cache_settings_write_version",
}


def __getattr__(name):
    if name in _ROUTE_SESSION_LIST_CACHE_DYNAMIC_EXPORTS:
        return getattr(_route_session_list_cache, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _prune_orphaned_webui_zero_message_sessions(rows, *, diag_stage=None):
    """#4985 second-pass orphan prune for native-WebUI rows whose ``state.db.messages`` is empty.

    Takes the post-``#3238`` ``webui_sessions`` list (i.e. rows that already
    survived the #3238/#4591 CLI/API-server prune) and returns a NEW list with
    any row whose backing ``state.db.messages`` table is empty removed.
    Removed sids are also persisted to the tombstone via
    ``_record_webui_zero_message_orphan_tombstone`` so
    ``recover_missing_index_sidecars`` does not re-add them to the sidebar
    index on the next poll (avoids the cache-thrash loop where every poll
    does one fsync'd index write + one state.db probe per orphan, forever).

    Invariants preserved:

    - Rows with ``active_stream_id`` / ``has_pending_user_message`` /
      ``worktree_path`` set are NEVER pruned — the inflight / worktree-bound
      / pending safety contract from ``IC_kwDOR1LuPM8AAAABHrkF1Q``.
    - Rows whose ``state.db.messages`` is empty AND that survived the
      upstream ``all_sessions()`` ``#1171`` keep-filter (i.e. titled OR has
      positive ``message_count``) ARE pruned — the post-#1171-survivor
      shape #4985 actually describes (a row that lingers VISIBLY in the
      sidebar because of a stale positive ``message_count`` or a title set
      before the first turn committed).

    This helper is intentionally extracted out of the ``if show_cli_sessions:``
    branch so the prune fires in BOTH branches of
    ``_build_session_list_cache_payload``. Established installs have
    ``settings.show_cli_sessions`` pinned to ``False`` (per
    ``api/config.py:7637-7648``) and those are exactly the long-time users
    who have accumulated the #4985 404 orphans — without hoisting, the
    ``else:`` branch silently skipped the prune and the sidebar kept
    dangling rows that 404 on click (review
    ``IC_kwDOR1LuPM8AAAABHsyFGg``).
    """
    if not rows:
        return list(rows) if rows is not None else []
    _diag = diag_stage if callable(diag_stage) else (lambda *_a, **_k: None)
    # #4985 self-healing: the tombstone is NOT a blind-drop filter at the
    # top of the helper. A row whose sid is in the tombstone is allowed
    # into the gate predicate like any other row — and the post-probe
    # logic below explicitly distinguishes four cases:
    #
    #   1. probe says NOT empty AND sid IS tombstoned → SELF-HEAL: the row
    #      has actually gained messages, so clear the tombstone and keep
    #      the row (do NOT add to missing_webui_orphan_ids). This is the
    #      primary fix for review IC_kwDOR1LuPM8AAAABHvY-dw.
    #   2. probe says empty AND sid IS tombstoned → tombstone persists
    #      (orphan shape unchanged), but the row is excluded from the
    #      returned list so the tombstone continues to suppress it on
    #      this poll too. Do NOT redundantly prune+tombstone (would
    #      cycle).
    #   3. probe says empty AND sid is NOT tombstoned → new orphan: prune
    #      from index, record tombstone, diag_stage.
    #   4. probe says NOT empty AND sid is NOT tombstoned → row has
    #      messages, retain (gate already passes anyway).
    #
    # A blind-drop at the top (the previous behavior) is strictly worse
    # than the orphan it suppresses — it would silently swallow a
    # legitimately-resurfaced row forever, even after the user actually
    # sent messages. The self-healing case is what makes the tombstone a
    # recoverable "this sid is currently empty" signal rather than a
    # permanent hide-list.
    if not rows:
        return []
    # Gate predicate mirrors the inline block that lived here before the
    # helper extract. The (title!='Untitled' OR count>0) clause is what makes
    # this gate actually reach a row #1171 kept — without it, the gate is a
    # no-op because ``all_sessions()`` at ``api/models.py:3892-3898`` (and
    # its full-scan fallback at 3946-3952) has already stripped every
    # (Untitled ∧ count==0 ∧ ¬active_stream_id ∧ ¬has_pending_user_message ∧
    # ¬worktree_path) row before our prune block runs.
    from api.gateway_chat import webui_gateway_chat_enabled
    from api import gateway_mirror

    _gw_enabled = False
    try:
        _gw_enabled = bool(webui_gateway_chat_enabled(get_config()))
    except Exception:
        _gw_enabled = False

    _webui_orphan_probe_rows = [
        s for s in rows
        if _session_source_is_webui(s)
        and not s.get("active_stream_id")
        and not s.get("has_pending_user_message")
        and not s.get("worktree_path")
        and not str(s.get("session_id") or "").startswith("agent-")
        and not bool((s.get("metadata") or {}).get("home"))
        and not (_gw_enabled and gateway_mirror.is_mirrored_gateway_session(str(s.get("session_id") or "")))
        and (
            s.get("title", "Untitled") not in ("Untitled", "New conversation", "New Chat")
            or _numeric_count(s.get("message_count")) > 0
        )
    ]
    if not _webui_orphan_probe_rows:
        return list(rows)
    rows_by_profile_webui: dict[object, list[dict]] = defaultdict(list)
    for row in _webui_orphan_probe_rows:
        rows_by_profile_webui[row.get("profile")].append(row)
    _tombstoned = _load_webui_zero_message_orphan_tombstone()
    self_healed_ids: set[str] = set()
    missing_webui_orphan_ids: set[str] = set()
    still_hidden_ids: set[str] = set()
    for profile_key, profile_rows in rows_by_profile_webui.items():
        probe_ids = [
            str(row.get("session_id")).strip()
            for row in profile_rows
            if str(row.get("session_id") or "").strip()
        ]
        zero_message_sids = agent_session_zero_message_sids(
            probe_ids,
            profile=profile_key if isinstance(profile_key, str) and profile_key else None,
        )
        # Iterate over the actual rows (not just probe_ids) so each sid
        # decision can probe the sidecar for real ``messages``. The r5
        # signal keyed off the row's cached ``message_count`` (which is
        # stale-positive on the very phantom rows #4985 exists to prune:
        # sidecar ``messages`` empty but cached count > 0), so the r5
        # retain branch kept the phantom and re-opened the bug (maintainer
        # review 4584722701, supersedes the r5 cached-count signal). The
        # r6 signal probes ``Session.load(sid).messages`` directly — but
        # ONLY for ``state.db``-empty candidates (the small set; the
        # common live-row path takes the ``else`` branch and pays
        # nothing). Full ``Session.load`` is intentional (vs
        # ``load_metadata_only`` which zeroes the messages array at
        # ``api/models.py:1210``).
        for row in profile_rows:
            sid = str(row.get("session_id") or "").strip()
            if not sid:
                continue
            is_empty = sid in zero_message_sids
            is_tombstoned = sid in _tombstoned
            if is_empty:
                # ``state.db.messages`` is empty. Probe the sidecar JSON
                # for real messages — the cached ``message_count`` alone
                # is stale-positive on phantom rows (sidecar ``messages``
                # empty but cached count > 0) and would retain the very
                # phantom this feature exists to prune (maintainer review
                # 4584722701, supersedes the r5 cached-count signal).
                # Full ``Session.load`` is intentional (vs
                # ``load_metadata_only`` which zeros the messages array
                # at ``api/models.py:1210``); the common live-row path
                # pays nothing because it skips the load via the
                # ``else`` branch below.
                try:
                    from api.models import Session as _Session
                    _loaded = _Session.load(sid)
                    sidecar_has_messages = bool(
                        _loaded is not None and len(_loaded.messages or []) > 0
                    )
                except Exception:
                    logger.debug(
                        "Failed to load sidecar for webui orphan decision %s; "
                        "treating as empty for prune purposes",
                        sid,
                        exc_info=True,
                    )
                    sidecar_has_messages = False
            else:
                # ``state.db.messages`` is non-empty — the conversation is real.
                sidecar_has_messages = True
            if sidecar_has_messages:
                # Real transcript (state.db OR loaded sidecar). Retain; if
                # tombstoned, self-heal so it stops thrashing on recovery.
                if is_tombstoned:
                    self_healed_ids.add(sid)
                continue
            if not is_empty and is_tombstoned:
                # Case 1: SELF-HEAL — clear tombstone, keep row.
                self_healed_ids.add(sid)
            elif is_empty and is_tombstoned:
                # Case 2: still-empty tombstoned row stays hidden this
                # poll (do not add to missing_webui_orphan_ids — would
                # cycle through prune_session_from_index + record).
                still_hidden_ids.add(sid)
            elif is_empty and not is_tombstoned:
                # Case 3: new orphan.
                missing_webui_orphan_ids.add(sid)
            # Case 4 (not empty + not tombstoned): row has messages, retain.
    if self_healed_ids:
        for _sid in self_healed_ids:
            try:
                _clear_webui_zero_message_orphan_tombstone(_sid)
                logger.debug(
                    "self-heal: cleared webui zero-message orphan tombstone "
                    "for %s (state.db.messages now non-empty)",
                    _sid,
                )
            except Exception:
                logger.debug(
                    "Failed to clear webui zero-message orphan tombstone for %s",
                    _sid,
                    exc_info=True,
                )
        _diag("self_heal_webui_zero_message_orphan")
    if missing_webui_orphan_ids:
        for _sid in missing_webui_orphan_ids:
            try:
                prune_session_from_index(_sid)
                _diag("prune_orphaned_webui_zero_message")
            except Exception:
                logger.debug(
                    "Failed to prune orphaned webui zero-message row %s",
                    _sid,
                    exc_info=True,
                )
            # Tombstone the sid in a SECOND step so a tombstone-write failure
            # never blocks the prune itself (the prune still removes the row
            # from the sidebar; only the re-prune avoidance would degrade).
            try:
                _record_webui_zero_message_orphan_tombstone(_sid)
            except Exception:
                logger.debug(
                    "Failed to tombstone webui zero-message orphan %s",
                    _sid,
                    exc_info=True,
                )
    # Return rows excluding both the freshly-pruned orphans AND the
    # tombstoned rows that the probe confirmed are still empty (case 2).
    # Self-healed rows (case 1) and live rows (case 4) stay in the result.
    _hidden = missing_webui_orphan_ids | still_hidden_ids
    return [
        s for s in rows
        if str(s.get("session_id") or "").strip() not in _hidden
    ]


def _build_session_list_cache_payload(
    active_profile: str | None,
    all_profiles: bool,
    show_cli_sessions: bool,
    show_previous_messaging_sessions: bool,
    show_cron_sessions: bool,
    show_claude_code_sessions: bool = True,
    include_archived: bool = False,
    exclude_hidden: bool = False,
    visible_only: bool = False,
    show_webhook_sessions: bool = False,
    show_kanban_sessions: bool = False,
    source_filter: str | None = None,
    sidebar_source: str | None = None,
    archived_limit: int | None = None,
    archived_offset: int = 0,
    diag=None,
) -> dict:
    diag_stage = diag.stage if diag is not None else lambda *_a, **_k: None

    def _session_has_server_visible_messages(session: dict) -> bool:
        """Return True when a non-active sidebar row has a visibility signal.

        Keep this mirror of the non-active server filter narrow and local to
        route behavior so model-layer behavior remains unchanged.
        """
        if not isinstance(session, dict):
            return False
        if _numeric_count(session.get("message_count")) > 0:
            return True

        attention = session.get("attention")
        if not (isinstance(attention, dict) and attention.get("kind")):
            attention = _session_attention_summary(str(session.get("session_id") or ""))
        if isinstance(attention, dict) and attention.get("kind"):
            if _numeric_count(attention.get("count")) > 0:
                return True

        return bool(
            session.get("is_streaming")
            or session.get("active_stream_id")
            or session.get("pending_user_message")
            or session.get("has_pending_user_message")
        )

    def _all_sessions_for_sidebar():
        if _callable_accepts_kwarg(all_sessions, "include_lineage_metadata"):
            return all_sessions(diag=diag, include_lineage_metadata=False)
        # Focused tests and third-party callers sometimes monkeypatch
        # routes.all_sessions with the historical diag-only signature.
        return all_sessions(diag=diag)

    diag_stage("all_sessions")
    webui_sessions = _all_sessions_for_sidebar()
    diag_stage("reconcile_stale_stream_state")
    if _reconcile_stale_stream_state_for_session_rows(webui_sessions):
        diag_stage("all_sessions_after_stale_stream_reconcile")
        webui_sessions = _all_sessions_for_sidebar()
    diag_stage("normalize_cli_rows")
    show_cli_sessions = bool(show_cli_sessions)
    show_previous_messaging_sessions = bool(show_previous_messaging_sessions)
    show_cron_sessions = bool(show_cron_sessions)
    show_webhook_sessions = bool(show_webhook_sessions)
    show_kanban_sessions = bool(show_kanban_sessions)
    webui_sessions = [_normalize_sidebar_source_flags(s) for s in webui_sessions]
    if show_cli_sessions:
        diag_stage("get_cli_sessions")
        if _callable_accepts_kwarg(get_cli_sessions, "include_claude_code"):
            cli = get_cli_sessions(
                source_filter=source_filter,
                all_profiles=all_profiles,
                include_claude_code=show_claude_code_sessions,
            )
        else:
            # Focused tests sometimes monkeypatch routes.get_cli_sessions with
            # the historical two-keyword signature.
            cli = get_cli_sessions(
                source_filter=source_filter,
                all_profiles=all_profiles,
            )
        diag_stage("merge_cli_sessions")
        cli_by_id = {s["session_id"]: s for s in cli}
        # #3238/#4591: reconcile orphaned imported sidecars. When a CLI or
        # API-server session is clicked in WebUI it gets a WebUI-owned sidecar
        # that all_sessions() returns independently of state.db. If the user
        # later deletes the backing agent session outside WebUI, the sidecar is
        # never pruned and the stale row lingers in the sidebar forever (there
        # is no WebUI delete affordance for read-only imported rows).
        # Drop rows whose backing agent row is genuinely gone. We probe
        # state.db directly (agent_session_rows_existing) rather than trust
        # cli_by_id absence, because get_cli_sessions() caps at
        # CLI_VISIBLE_SESSION_LIMIT (20) — an existing session can fall
        # out of that window and look deleted. Native WebUI sessions
        # (source == "webui") that merely have a CLI ancestor are never
        # pruned by this path.
        #
        # #4985: parallel pass for native-WebUI rows that have a backing
        # agent row in state.db but zero messages (a `+`-click that opened a
        # row but the first turn never committed, or a sidebar nav that
        # opened then closed before any message landed). The same #3238
        # helper doesn't catch these because source == "webui" is excluded
        # above, and the WebUI delete affordance isn't exposed for them,
        # so they would otherwise linger forever. Inflight first-turn
        # safety is preserved by gating on `active_stream_id` (after
        # _reconcile_stale_stream_state has cleared stale stream ids).
        _orphan_probe_rows = []
        _kept_after_orphan_prune = []
        for s in webui_sessions:
            _sid = s.get("session_id")
            if (
                _sid
                and (is_cli_session_row(s) or _is_api_server_sidecar_row(s))
                and not _session_source_is_webui(s)
                and _sid not in cli_by_id
            ):
                _orphan_probe_rows.append(s)
            else:
                _kept_after_orphan_prune.append(s)
        if _orphan_probe_rows:
            rows_by_profile: dict[object, list[dict]] = defaultdict(list)
            for row in _orphan_probe_rows:
                rows_by_profile[row.get("profile")].append(row)
            missing_orphan_ids: set[str] = set()
            for profile_key, rows in rows_by_profile.items():
                probe_ids = [
                    str(row.get("session_id")).strip()
                    for row in rows
                    if str(row.get("session_id") or "").strip()
                ]
                existing = agent_session_rows_existing(
                    probe_ids,
                    profile=profile_key if isinstance(profile_key, str) and profile_key else None,
                )
                for row in rows:
                    _sid = str(row.get("session_id") or "").strip()
                    if _sid and _sid not in existing:
                        missing_orphan_ids.add(_sid)
            for s in _orphan_probe_rows:
                _sid = str(s.get("session_id") or "").strip()
                if _sid in missing_orphan_ids:
                    try:
                        prune_session_from_index(_sid)
                    except Exception:
                        logger.debug(
                            "Failed to prune orphaned agent sidecar %s",
                            _sid,
                            exc_info=True,
                        )
                    diag_stage("prune_orphaned_agent_sidecar")
                    continue
                _kept_after_orphan_prune.append(s)
        # #4985 second pass — probe state.db.messages for native-WebUI rows
        # that *survived* the upstream all_sessions() #1171 keep-filter (so
        # the row is TITLED or has a POSITIVE message_count, meaning it IS
        # shown in the sidebar — and the 404 click reported in #4985 happens),
        # BUT whose actual state.db.messages table is empty (the ground-truth
        # probe). This is the orphan shape #4985 actually describes: a row
        # that lingers VISIBLY in the sidebar because of a stale positive
        # message_count or a title set before the first turn committed.
        #
        # The (title!='Untitled' OR count>0) clause is the part that makes
        # this gate actually reach a row #1171 kept. Without it, the gate is
        # a no-op because all_sessions() at api/models.py:3892-3898 and
        # 3946-3952 has already stripped every (Untitled ∧ count==0 ∧
        # ¬active_stream_id ∧ ¬has_pending_user_message ∧ ¬worktree_path)
        # row before this point — making the earlier 6-condition gate a
        # no-op against the real pipeline (review IC_kwDOR1LuPM8AAAABHrkF1Q).
        #
        # Implementation lives in ``_prune_orphaned_webui_zero_message_sessions``
        # above so the prune runs in BOTH branches of this function
        # (``if show_cli_sessions:`` AND ``else:``). Established installs
        # have ``settings.show_cli_sessions`` pinned to False (per
        # api/config.py:7637-7648) and those are exactly the long-time
        # users who accumulated the #4985 404 orphans — without hoisting,
        # the ``else:`` branch silently skipped the prune
        # (review IC_kwDOR1LuPM8AAAABHsyFGg).
        #
        # Inflight / worktree / pending safety: same as before — any row
        # still carrying active_stream_id / has_pending_user_message /
        # worktree_path is never pruned, even if its messages table is
        # momentarily empty. _reconcile_stale_stream_state_for_session_rows
        # at line 2224 has already cleared stale stream ids above this point.
        webui_sessions = _prune_orphaned_webui_zero_message_sessions(
            _kept_after_orphan_prune,
            diag_stage=diag_stage,
        )
        for s in webui_sessions:
            meta = cli_by_id.get(s.get("session_id"))
            if not meta:
                continue
            if _is_messaging_session_record(meta):
                s.update(_merge_cli_sidebar_metadata(s, meta))
                if s.get("session_id") != meta.get("session_id"):
                    s["session_id"] = meta.get("session_id")
            else:
                for key in ("source_tag", "raw_source", "session_source", "source_label"):
                    if not s.get(key) and meta.get(key):
                        s[key] = meta[key]
        webui_sessions = [_normalize_sidebar_source_flags(s) for s in webui_sessions]
        # Apply the same CLI visibility semantics to imported local copies so
        # low-value imported artifacts do not leak into the sidebar.
        webui_sessions = [s for s in webui_sessions if is_cli_session_row_visible(s)]
        represented_webui_ids = set()
        for s in webui_sessions:
            represented_webui_ids.update(_session_lineage_ids(s))
        deduped_cli = _dedupe_cli_sidebar_sessions_for_api(
            cli,
            represented_webui_ids,
            show_cron_sessions=show_cron_sessions,
            show_webhook_sessions=show_webhook_sessions,
            show_kanban_sessions=show_kanban_sessions,
            source_filter=source_filter,
        )
    else:
        diag_stage("filter_webui_sessions")
        webui_sessions = [s for s in webui_sessions if not _is_cli_session_for_settings(s)]
        # #4985 second pass — see _prune_orphaned_webui_zero_message_sessions
        # for the gate predicate and the post-#1171-survivor rationale. The
        # prune MUST run here too: established installs have
        # ``settings.show_cli_sessions`` pinned to False
        # (api/config.py:7637-7648) and those are exactly the long-time
        # users who accumulated the 404 orphans — review
        # IC_kwDOR1LuPM8AAAABHsyFGg. Without this call the else branch
        # silently skipped the prune and the sidebar kept dangling rows.
        webui_sessions = _prune_orphaned_webui_zero_message_sessions(
            webui_sessions,
            diag_stage=diag_stage,
        )
        deduped_cli = []
    diag_stage("sort_sessions")
    merged = webui_sessions + deduped_cli
    merged.sort(
        key=lambda s: s.get("last_message_at") or s.get("updated_at", 0) or 0,
        reverse=True,
    )
    # ── Profile scoping (#1611) ────────────────────────────────────────
    # Default: filter to the active profile. ?all_profiles=1 opts into
    # the aggregate view used by the "All profiles" sidebar toggle.
    # The other_profile_count is always returned so the UI can render
    # the "Show N from other profiles" affordance without sending the
    # cross-profile rows by default.
    #
    # IMPORTANT: scope BEFORE _keep_latest_messaging_session_per_source.
    # _messaging_source_key is profile-blind (#1614 follow-up): if the
    # same Slack/Telegram identity has sessions in profiles A and B, a
    # profile-blind dedupe would discard the older one even when scoped
    # to its own profile, leaving that profile with zero rows for that
    # source. Filter first so the dedupe operates only within the active
    # profile's rows.
    diag_stage("profile_scope")
    if all_profiles:
        scoped = merged
        other_profile_count = 0
    else:
        scoped = [
            s for s in merged
            if _session_visible_in_profile_sidebar(s, active_profile)
        ]
        other_profile_count = 0 if _is_isolated_profile_mode() else len(merged) - len(scoped)
    diag_stage("messaging_dedupe")
    archived_scoped = _keep_latest_messaging_session_per_source(
        list(scoped),
        show_previous_messaging_sessions=show_previous_messaging_sessions,
    )
    visible_scoped = _keep_latest_messaging_session_per_source(
        [s for s in scoped if not s.get("archived")],
        show_previous_messaging_sessions=show_previous_messaging_sessions,
    )
    if show_cli_sessions:
        diag_stage("cli_cap")
        archived_scoped = _cap_recent_cli_sessions(archived_scoped, cli_cap=CLI_VISIBLE_SESSION_CAP)
        visible_scoped = _cap_recent_cli_sessions(visible_scoped, cli_cap=CLI_VISIBLE_SESSION_CAP)
    if visible_only:
        archived_scoped = [
            s for s in archived_scoped if _session_has_server_visible_messages(s)
        ]
        visible_scoped = [
            s for s in visible_scoped if _session_has_server_visible_messages(s)
        ]
    if exclude_hidden:
        archived_scoped = [s for s in archived_scoped if not s.get("default_hidden")]
        visible_scoped = [s for s in visible_scoped if not s.get("default_hidden")]
    archived_webui_count = sum(
        1 for s in archived_scoped
        if s.get("archived") and not _is_cli_session_for_settings(s)
    )
    archived_cli_count = sum(
        1 for s in archived_scoped
        if s.get("archived") and _is_cli_session_for_settings(s)
    )
    archived_count = archived_webui_count + archived_cli_count
    def _filter_sidebar_source(rows: list[dict]) -> list[dict]:
        if sidebar_source == "webui":
            return [s for s in rows if not _is_cli_session_for_settings(s)]
        if sidebar_source == "cli":
            return [s for s in rows if _is_cli_session_for_settings(s)]
        return list(rows)

    full_scoped_all_sources = archived_scoped if include_archived else visible_scoped
    webui_session_count = sum(
        1 for s in full_scoped_all_sources
        if not _is_cli_session_for_settings(s)
    )
    cli_session_count = sum(
        1 for s in full_scoped_all_sources
        if _is_cli_session_for_settings(s)
    )
    visible_scoped_filtered = _filter_sidebar_source(visible_scoped)
    archived_scoped_filtered = _filter_sidebar_source(archived_scoped)
    scoped = _filter_sidebar_source(full_scoped_all_sources)
    if include_archived and archived_limit is not None:
        try:
            normalized_archived_limit = max(0, int(archived_limit))
        except (TypeError, ValueError):
            normalized_archived_limit = None
        try:
            normalized_archived_offset = max(0, int(archived_offset or 0))
        except (TypeError, ValueError):
            normalized_archived_offset = 0
        if normalized_archived_limit is not None:
            visible_rows_for_page = [s for s in visible_scoped_filtered if not s.get("archived")]
            archived_rows_for_page = [s for s in archived_scoped_filtered if s.get("archived")]
            scoped = visible_rows_for_page + archived_rows_for_page[
                normalized_archived_offset: normalized_archived_offset + normalized_archived_limit
            ]
    sidebar_reference_sessions: list[dict] = []
    if not include_archived:
        sidebar_reference_sessions = _hidden_archived_sidebar_reference_sessions(
            visible_scoped_filtered,
            archived_scoped_filtered,
        )
    if not include_archived:
        diag_stage("filter_archived_sessions")
    diag_stage("visible_lineage_metadata")
    _enrich_sidebar_lineage_metadata(scoped)
    # Delegated subagent children (#5307) are view-only, owned by the delegate
    # runner. The model-layer batch overlay above has already applied the
    # authoritative source and view-only flags before this route runs.
    def _coerce_subagent_rows(_rows):
        for _r in _rows:
            if not isinstance(_r, dict):
                continue
            _src = (
                str(_r.get("source_tag") or _r.get("raw_source")
                    or _r.get("session_source") or _r.get("source") or "").strip().lower()
            )
            if _src == "subagent":
                _r["read_only"] = True
                _r["is_cli_session"] = False
    _coerce_subagent_rows(scoped)
    _coerce_subagent_rows(sidebar_reference_sessions)
    return {
        "sessions": [
            dict(s) if isinstance(s, dict) else {}
            for s in scoped
        ],
        "sidebar_reference_sessions": [
            dict(s) if isinstance(s, dict) else {}
            for s in sidebar_reference_sessions
        ],
        "cli_count": len(deduped_cli),
        "archived_count": archived_count,
        "archived_webui_count": archived_webui_count,
        "archived_cli_count": archived_cli_count,
        "webui_session_count": webui_session_count,
        "cli_session_count": cli_session_count,
        "include_archived": include_archived,
        "archived_limit": archived_limit,
        "archived_offset": archived_offset,
        "all_profiles": all_profiles,
        "active_profile": active_profile,
        "other_profile_count": other_profile_count,
        "settings": {
            "show_cli_sessions": show_cli_sessions,
            "show_previous_messaging_sessions": show_previous_messaging_sessions,
            "show_cron_sessions": show_cron_sessions,
            "show_claude_code_sessions": show_claude_code_sessions if show_cli_sessions else False,
            "show_webhook_sessions": show_webhook_sessions,
            "show_kanban_sessions": show_kanban_sessions,
        },
    }




def _hidden_archived_sidebar_reference_sessions(
    visible_rows: list[dict],
    archived_rows: list[dict],
) -> list[dict]:
    """Return hidden archived ancestors needed for client-side sidebar nesting.

    The default sidebar payload intentionally omits archived sessions. The
    browser still needs a tiny reference row for an archived parent/ancestor so
    `_attachChildSessionsToSidebarRows()` can suppress its visible child rows
    instead of rendering them as orphan top-level conversations (#4293).
    """
    archived_by_id = {
        str(row.get("session_id")): row
        for row in archived_rows
        if isinstance(row, dict) and row.get("archived") and row.get("session_id")
    }
    if not archived_by_id:
        return []

    references: list[dict] = []
    added: set[str] = set()
    visible_ids = {
        str(row.get("session_id"))
        for row in visible_rows
        if isinstance(row, dict) and row.get("session_id")
    }

    for row in visible_rows:
        if not isinstance(row, dict):
            continue
        parent_id = str(row.get("parent_session_id") or "").strip()
        seen: set[str] = set()
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            if parent_id in visible_ids:
                break
            parent = archived_by_id.get(parent_id)
            if not parent:
                break
            if parent_id not in added:
                references.append(parent)
                added.add(parent_id)
            parent_id = str(parent.get("parent_session_id") or "").strip()

    return references



from api.config import (STATE_DIR, SESSION_DIR, DEFAULT_WORKSPACE, DEFAULT_MODEL, SESSIONS, SESSIONS_MAX, LOCK, STREAMS, STREAMS_LOCK, CANCEL_FLAGS, STREAM_LAST_EVENT_ID, SERVER_START_TIME, _resolve_cli_toolsets, get_available_models, get_available_models_for_session_visit, _provider_is_known_or_configured, MIME_MAP, ACTIVE_RUNS, ACTIVE_RUNS_LOCK, register_stream_owner, register_session_writeback_owner, clear_session_writeback_owner_if_owned, stream_owner_session_id, unregister_stream_owner, _get_session_agent_lock, load_settings, persisted_speech_settings_keys, save_settings, SETTINGS_FILE, set_hermes_default_model, canonical_model_provider_lane, model_with_provider_context, create_stream_channel, get_config, get_webui_session_save_mode, get_config_snapshot, STREAM_GOAL_RELATED, PENDING_GOAL_CONTINUATION, _get_config_path, _load_yaml_config_file, get_config_for_profile_home, PENDING_BG_TASK_COMPLETIONS, _parse_provider_qualified_model_id)
from api import config as api_config
from api.helpers import (require, bad, safe_resolve, j, t, read_body, MAX_BODY_BYTES, _security_headers, _sanitize_error, redact_session_data, _redact_text, _CLIENT_DISCONNECT_ERRORS)
from api.request_diagnostics import RequestDiagnostics




# A cancelled worker that stays in ACTIVE_RUNS longer than this is treated as
# stuck (e.g. blocked in C-level provider I/O and never reaching its finally).
# Once the cancel has been outstanding past this grace window, the run row can
# no longer protect the session's active_stream_id/pending_* from stale
# cleanup: _clear_stale_stream_state() clears them, and every delayed cancel
# finalizer (api/streaming.py _finalize_cancelled_turn) is generation-guarded
# under the session lock — it no-ops unless the session still points at the
# cancelled stream — so clearing early cannot clobber a newer turn (#6623).
_STALE_CANCELLED_RUN_GRACE_SECONDS = 60.0


def _cancelled_run_is_stale(run_entry) -> bool:
    """Return True when an ACTIVE_RUNS row belongs to a cancel that has been
    outstanding longer than the stale grace window.

    ``cancelled_at`` is stamped by cancel_stream() when it flips the run to
    phase="cancelling". ``started_at`` is accepted as a fallback anchor so runs
    cancelled before the stamp was introduced are still reclaimed eventually.
    """
    try:
        from api import config as _live_config

        return _live_config.active_run_cancel_is_stale(
            run_entry,
            grace_seconds=_STALE_CANCELLED_RUN_GRACE_SECONDS,
        )
    except Exception:
        return False


_RUNNER_WRITEBACK_LOCK = threading.Lock()
_RUNNER_WRITEBACK_STARTED: set[str] = set()


def _clear_stale_stream_state(session) -> bool:
    """Clear persisted streaming flags when the in-memory stream no longer exists.

    A server restart or worker crash can leave active_stream_id/pending_* in the
    session JSON while STREAMS is empty. The frontend then keeps reconnecting to
    a dead stream and shows a permanent running/thinking state.

    SAFETY (#1558): If ``session`` was loaded with ``metadata_only=True``, its
    ``messages`` array is empty by design and calling ``save()`` would
    atomically overwrite the on-disk JSON, wiping the conversation. In that
    case we re-load the full session before mutating, so the persisted
    write carries the real messages forward.
    """
    stream_id = getattr(session, "active_stream_id", None)
    if not stream_id:
        return False
    with STREAMS_LOCK:
        stream_alive = stream_id in STREAMS
    if stream_alive:
        return False
    try:
        from api import config as _live_config
        with _live_config.ACTIVE_RUNS_LOCK:
            worker_alive = stream_id in (_live_config.ACTIVE_RUNS or {})
    except Exception:
        worker_alive = False
    if not worker_alive:
        try:
            with _RUNNER_WRITEBACK_LOCK:
                if stream_id in _RUNNER_WRITEBACK_STARTED:
                    worker_alive = True
        except Exception:
            pass
    if worker_alive:
        # #6623: a worker stuck in C-level I/O may never reach its finally to
        # unregister the run, so ACTIVE_RUNS could hold the row forever and
        # block stale cleanup indefinitely. A *cancelled* run (cancel_stream()
        # stamped phase="cancelling" + cancelled_at) that has not unwound past
        # the grace window is treated as stale — clear the session anyway. The
        # _stream_writeback_is_current() guard rejects any eventual writeback
        # from the stuck worker, so this cannot clobber a newer turn.
        try:
            with _live_config.ACTIVE_RUNS_LOCK:
                run_entry = dict((_live_config.ACTIVE_RUNS or {}).get(stream_id) or {})
        except Exception:
            run_entry = {}
        if not _cancelled_run_is_stale(run_entry):
            logger.debug(
                "_clear_stale_stream_state: stream %s for session %s missing SSE channel "
                "but worker bookkeeping is still active; deferring stale cleanup",
                stream_id,
                getattr(session, "session_id", "?"),
            )
            return False
        logger.info(
            "_clear_stale_stream_state: stream %s for session %s missing SSE channel and "
            "cancelled run is stale (cancelled_at=%s); clearing stale stream state (#6623)",
            stream_id,
            getattr(session, "session_id", "?"),
            run_entry.get("cancelled_at"),
        )
    grace_seconds = 30.0
    try:
        from api.models import _REPAIR_STALE_PENDING_GRACE_SECONDS
        grace_seconds = float(_REPAIR_STALE_PENDING_GRACE_SECONDS)
        pending_started_at = getattr(session, "pending_started_at", None)
        pending_age = time.time() - float(pending_started_at) if pending_started_at else None
    except Exception:
        pending_age = None
    if (
        getattr(session, "pending_user_message", None)
        and pending_age is not None
        and pending_age < grace_seconds
    ):
        logger.debug(
            "_clear_stale_stream_state: stream %s for session %s missing SSE channel "
            "but pending turn is %.1fs old; waiting for %.1fs stale-repair grace",
            stream_id,
            getattr(session, "session_id", "?"),
            pending_age,
            grace_seconds,
        )
        return False

    # ── #1558 P0 safety: if we were handed a metadata-only stub, reload the
    # full session before touching persisted state. The original
    # metadata-only object is left untouched so the caller's read path is
    # unaffected.
    original_stub = session  # SHOULD-FIX #1 (Opus): keep reference so we can
                             # patch the caller's in-memory copy after a
                             # successful clear, avoiding one ghost SSE
                             # reconnect on the very next /api/session GET.
    if getattr(session, "_loaded_metadata_only", False):
        try:
            from api.models import get_session as _get_session
            session = _get_session(session.session_id, metadata_only=False)
        except Exception:
            # If we cannot upgrade to a full load (file gone, decode error,
            # etc.) bail without clearing — better to leave a stale
            # active_stream_id than to wipe the conversation.
            logger.warning(
                "_clear_stale_stream_state: refused to clear stale stream %s "
                "for session %s — full reload failed and we will not save a "
                "metadata-only stub. See #1558.",
                stream_id, getattr(session, "session_id", "?"),
            )
            return False
        if session is None:
            return False
        # The full-load path may have already repaired stale pending fields
        # via _repair_stale_pending(); only re-assert if still set.
        if not getattr(session, "active_stream_id", None):
            # Patch the caller's stub so its read path also sees the cleared
            # field (matches the Opus SHOULD-FIX #1 — without this, /api/session
            # would briefly return the stale active_stream_id and the frontend
            # would attempt one ghost SSE reconnect before recovering).
            try:
                original_stub.active_stream_id = None
                if hasattr(original_stub, "pending_user_message"):
                    original_stub.pending_user_message = None
                if hasattr(original_stub, "pending_attachments"):
                    original_stub.pending_attachments = []
                if hasattr(original_stub, "pending_started_at"):
                    original_stub.pending_started_at = None
                if hasattr(original_stub, "pending_user_source"):
                    original_stub.pending_user_source = None
            except Exception:
                pass
            return False

    # ── #1533 race fix: acquire the per-session lock and re-read
    # active_stream_id under it. A concurrent chat_start may have already
    # registered a new stream after our STREAMS_LOCK check above; in that
    # case we must NOT clobber its session.active_stream_id.
    with _get_session_agent_lock(session.session_id):
        if getattr(session, "active_stream_id", None) != stream_id:
            return False
        if getattr(session, "pending_user_message", None):
            try:
                from api.models import _apply_core_sync_or_error_marker, _get_profile_home
                profile_home = _get_profile_home(getattr(session, "profile", None))
                core_path = profile_home / "sessions" / f"session_{session.session_id}.json"
                repaired = _apply_core_sync_or_error_marker(
                    session,
                    core_path,
                    stream_id_for_recheck=stream_id,
                    touch_updated_at=False,
                )
            except Exception:
                logger.exception(
                    "_clear_stale_stream_state: failed to repair stale pending stream %s "
                    "for session %s",
                    stream_id, getattr(session, "session_id", "?"),
                )
                repaired = False
            if repaired:
                if original_stub is not session:
                    try:
                        original_stub.active_stream_id = None
                        if hasattr(original_stub, "pending_user_message"):
                            original_stub.pending_user_message = None
                        if hasattr(original_stub, "pending_attachments"):
                            original_stub.pending_attachments = []
                        if hasattr(original_stub, "pending_started_at"):
                            original_stub.pending_started_at = None
                        if hasattr(original_stub, "pending_user_source"):
                            original_stub.pending_user_source = None
                    except Exception:
                        pass
                return True
            if getattr(session, "active_stream_id", None) != stream_id:
                return False
        _materialize_pending_user_turn_before_error(session)
        session.active_stream_id = None
        if hasattr(session, "pending_user_message"):
            session.pending_user_message = None
        if hasattr(session, "pending_attachments"):
            session.pending_attachments = []
        if hasattr(session, "pending_started_at"):
            session.pending_started_at = None
        if hasattr(session, "pending_user_source"):
            session.pending_user_source = None
        try:
            # Runtime cleanup is not user activity; do not bubble old sessions
            # to the top of the sidebar just because a stale stream flag was
            # repaired during a read/list path.
            session.save(touch_updated_at=False)
        except Exception:
            logger.exception(
                "_clear_stale_stream_state: save() failed for session %s",
                getattr(session, "session_id", "?"),
            )
    # Patch the caller's stub (if different from the full-load object) so
    # its in-memory active_stream_id matches what just got persisted.
    if original_stub is not session:
        try:
            original_stub.active_stream_id = None
            if hasattr(original_stub, "pending_user_message"):
                original_stub.pending_user_message = None
            if hasattr(original_stub, "pending_attachments"):
                original_stub.pending_attachments = []
            if hasattr(original_stub, "pending_started_at"):
                original_stub.pending_started_at = None
            if hasattr(original_stub, "pending_user_source"):
                original_stub.pending_user_source = None
        except Exception:
            pass
    return True
























def _ensure_full_session_before_mutation(sid: str, session):
    """Reload cached metadata-only sessions before mutating persisted fields.

    Session.save() intentionally refuses metadata-only stubs (#1558) because
    their messages list is empty by design. Mutation routes that save session
    metadata must upgrade the cached stub first so they do not trip that guard
    or risk writing an incomplete object.
    """
    if not getattr(session, "_loaded_metadata_only", False):
        return session
    full_session = Session.load(sid)
    if full_session is None:
        raise KeyError(sid)
    with LOCK:
        SESSIONS[sid] = full_session
        SESSIONS.move_to_end(sid)
        _evict_sessions_over_cap()  # #4765: safe LRU eviction (never active/unsaved)
    return full_session
















































































































def _get_or_materialize_session(sid: str, *, refresh_cli_messages: bool = False):
    """Get a session, materializing from CLI/agent metadata if not in WebUI store.

    Mirrors the fallback logic in /api/session/archive (routes.py:~8530).
    Raises:
        KeyError: session not found in any store
        PermissionError: session is read-only (messaging/Claude Code)
    """
    try:
        s = get_session(sid)
        s = _ensure_full_session_before_mutation(sid, s)
        # Read-only guard on the happy path too: an already-stored read-only /
        # imported session must not be mutated via rename/update/move
        # (Session.save() does not enforce this). Scope this to the explicit
        # read_only flag — a stored messaging session already owns its sidecar,
        # so the messaging-fork concern only applies to the materialize fallback
        # below (and the heuristic record-check would mis-trip on mock sessions).
        if getattr(s, "read_only", False):
            raise PermissionError("read-only imported session")
        # A previously-persisted subagent sidecar (#5307) is view-only and
        # owned by the delegate runner — even if it was stored with
        # read_only=False (e.g. materialized before this fix), it must not be
        # mutated / used as a writable chat session. This mirrors the
        # missing-sidecar subagent guard below on the happy path.
        if (
            (getattr(s, "source_tag", "") or getattr(s, "raw_source", "") or "").strip().lower() == "subagent"
            or _is_subagent_child_session_id(sid)
        ):
            raise PermissionError("read-only subagent child session")
        if refresh_cli_messages and getattr(s, "is_cli_session", False):
            latest_messages = get_cli_session_messages(
                sid,
                profile=getattr(s, "profile", None),
            )
            current_messages = list(getattr(s, "messages", None) or [])
            if (
                latest_messages
                and len(latest_messages) >= len(current_messages)
                and _session_messages_have_prefix(latest_messages, current_messages)
            ):
                # Keep the stitched CLI transcript authoritative on the first
                # WebUI continuation path without clobbering later divergent
                # WebUI-owned turns.
                s.messages = list(latest_messages)
        return s
    except KeyError:
        pass

    # Fallback: try to materialize from CLI/agent session metadata
    cli_meta = _lookup_cli_session_metadata(sid)

    # Delegated subagent children (#5307) are view-only: their transcript lives
    # in state.db and ownership belongs to the delegate runner, not WebUI. They
    # must never be materialized as a writable sidecar here — this is the shared
    # chokepoint reached by POST /api/chat/start (_get_or_materialize_session),
    # so gating it closes the write path that bypasses the GET/import_cli guards.
    # Checked via state.db source (independent of cli_meta, which is often empty
    # for a server-side subagent child).
    _mat_source_tag = (
        (cli_meta or {}).get("source_tag") or (cli_meta or {}).get("raw_source") or ""
    ).strip().lower()
    if _mat_source_tag == "subagent" or _is_subagent_child_session_id(sid):
        raise PermissionError("read-only subagent child session")

    if not cli_meta:
        raise KeyError(sid)

    # Read-only guard: messaging sessions and Claude Code imports cannot be
    # mutated. Reject BOTH an explicit read_only flag AND any messaging-source
    # record — agent rows normalize messaging sources without setting read_only,
    # and state.db (not a WebUI sidecar) is the source of truth for them, so
    # materializing a writable sidecar would fork the title/state.
    if cli_meta.get("read_only") or _is_messaging_session_record(cli_meta):
        raise PermissionError("read-only imported session")

    # Preserve source metadata fields
    def _apply_source_meta(s):
        s.is_cli_session = is_cli_session_row(cli_meta)
        s.source_tag = cli_meta.get("source_tag")
        s.raw_source = cli_meta.get("raw_source") or cli_meta.get("source_tag")
        s.session_source = cli_meta.get("session_source")
        s.source_label = cli_meta.get("source_label")
        s.user_id = cli_meta.get("user_id")
        s.chat_id = cli_meta.get("chat_id")
        s.chat_type = cli_meta.get("chat_type")
        s.thread_id = cli_meta.get("thread_id")
        s.session_key = cli_meta.get("session_key")
        s.platform = cli_meta.get("platform")

    if _is_messaging_session_record(cli_meta):
        # Messaging sessions: lightweight Session with no messages (state.db is source of truth)
        s = Session(
            session_id=sid,
            title=cli_meta.get("title") or title_from(get_cli_session_messages(sid), "CLI Session"),
            workspace=get_last_workspace(),
            model=cli_meta.get("model") or "unknown",
            created_at=cli_meta.get("created_at"),
            updated_at=cli_meta.get("updated_at"),
        )
        _apply_source_meta(s)
        s.save(touch_updated_at=False)
    else:
        # Regular CLI/agent sessions: import full message history
        msgs = get_cli_session_messages(sid)
        if not msgs:
            raise KeyError(sid)
        s = import_cli_session(
            sid,
            cli_meta.get("title") or title_from(msgs, "CLI Session"),
            msgs,
            cli_meta.get("model") or "unknown",
            profile=cli_meta.get("profile"),
            created_at=cli_meta.get("created_at"),
            updated_at=cli_meta.get("updated_at"),
        )
        _apply_source_meta(s)

    return s








def _reconcile_stale_stream_state_for_session_rows(session_rows) -> bool:
    """Clear stale persisted stream fields before /api/sessions serializes rows."""
    changed = False
    for row in session_rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("session_id")
        if not sid or not row.get("active_stream_id"):
            continue
        if row.get("is_streaming") is True:
            continue
        try:
            session = get_session(sid, metadata_only=True)
        except Exception:
            logger.debug(
                "Failed to load session %s while reconciling stale stream state",
                sid,
                exc_info=True,
            )
            continue
        if session is None:
            continue
        changed = _clear_stale_stream_state(session) or changed
    return changed

# ── CSRF: validate Origin/Referer on POST ────────────────────────────────────
import re as _re


def _normalize_host_port(value: str) -> tuple[str, str | None]:
    """Split a host or host:port string into (hostname, port|None).
    Handles IPv6 bracket notation, e.g. [::1]:8080."""
    value = value.strip().lower()
    if not value:
        return '', None
    if value.startswith('['):
        end = value.find(']')
        if end != -1:
            host = value[1:end]
            rest = value[end + 1 :]
            if rest.startswith(':') and rest[1:].isdigit():
                return host, rest[1:]
            return host, None
    if value.count(':') == 1:
        host, port = value.rsplit(':', 1)
        if port.isdigit():
            return host, port
    return value, None


def _ports_match(origin_scheme: str, origin_port: str | None, allowed_port: str | None) -> bool:
    """Return True when two ports should be considered equivalent, scheme-aware.

    Treats an absent port as the scheme default: port 80 for http, port 443 for https.
    Port 80 is NOT treated as equivalent to 443 (different protocols = different origins).
    """
    if origin_port == allowed_port:
        return True
    # Determine the default port for the origin's scheme
    default = '443' if origin_scheme == 'https' else '80'
    if not origin_port and allowed_port == default:
        return True
    if not allowed_port and origin_port == default:
        return True
    return False


def _allowed_public_origins() -> set[str]:
    """Parse HERMES_WEBUI_ALLOWED_ORIGINS env var (comma-separated) into a set.

    Each entry must include the scheme, e.g. https://myapp.example.com:8000.
    Entries without a scheme are silently skipped and a warning is printed.
    """
    raw = os.getenv('HERMES_WEBUI_ALLOWED_ORIGINS', '')
    result = set()
    for value in raw.split(','):
        value = value.strip().rstrip('/').lower()
        if not value:
            continue
        if not (value.startswith('http://') or value.startswith('https://')):
            import sys
            print(
                f"[webui] WARNING: HERMES_WEBUI_ALLOWED_ORIGINS entry {value!r} is missing "
                f"the scheme (expected https://hostname or http://hostname). Entry ignored.",
                flush=True, file=sys.stderr,
            )
            continue
        result.add(value)
    return result


def _is_browser_unsafe_request(handler) -> bool:
    """Return True when request headers identify a browser unsafe request.

    Non-browser API clients, including the MCP bridge and curl-style scripts,
    normally send no Origin/Referer and remain compatible with the existing
    same-machine API contract. Browsers send Origin for unsafe fetch/form POSTs;
    Referer is retained for older paths and proxies.
    """
    return bool(handler.headers.get("Origin") or handler.headers.get("Referer"))


def _check_same_origin_browser_request(handler, *, require_provenance: bool = False) -> bool:
    _clear_csrf_failure_reason(handler)
    origin = handler.headers.get("Origin", "")
    referer = handler.headers.get("Referer", "")
    host = handler.headers.get("Host", "")
    sec_fetch_site = handler.headers.get("Sec-Fetch-Site", "").strip().lower()
    if not (origin or referer or sec_fetch_site):
        return not require_provenance or _set_csrf_failure_reason(handler, "origin_mismatch")
    if sec_fetch_site == "cross-site":
        return _set_csrf_failure_reason(handler, "origin_mismatch")
    target = origin or referer
    if not target:
        if sec_fetch_site == "none":
            return True
        if sec_fetch_site == "same-origin":
            return not require_provenance or _set_csrf_failure_reason(
                handler, "origin_mismatch"
            )
        return _set_csrf_failure_reason(handler, "origin_mismatch")
    m = _re.match(r"^https?://([^/]+)", target)
    if not m:
        return _set_csrf_failure_reason(handler, "origin_mismatch")
    origin_host = m.group(1)
    origin_scheme = m.group(0).split('://')[0].lower()
    origin_name, origin_port = _normalize_host_port(origin_host)
    origin_allowed = False
    origin_value = m.group(0).rstrip('/').lower()
    if origin_value in _allowed_public_origins():
        origin_allowed = True
    if not origin_allowed:
        allowed_hosts = [h.strip() for h in [host] if h.strip()]
        trust_forwarded_host = os.getenv("HERMES_WEBUI_TRUST_FORWARDED_HOST", "").strip().lower()
        if trust_forwarded_host in ("1", "true", "yes", "on"):
            allowed_hosts.extend(
                h.strip()
                for h in [
                    handler.headers.get("X-Forwarded-Host", ""),
                    handler.headers.get("X-Real-Host", ""),
                ]
                if h.strip()
            )
        for allowed in allowed_hosts:
            allowed_name, allowed_port = _normalize_host_port(allowed)
            if origin_name == allowed_name and _ports_match(origin_scheme, origin_port, allowed_port):
                origin_allowed = True
                break
    if not origin_allowed:
        return _set_csrf_failure_reason(handler, "origin_mismatch")
    return True


def apply_cors_preflight_headers(handler) -> None:
    """Emit CORS preflight headers on ``handler`` for a same-origin/allowlisted
    request; emit nothing for a disallowed origin (browser treats the header-less
    200 as a preflight denial).

    Echoes the request Origin only when it is same-origin or explicitly
    allowlisted via HERMES_WEBUI_ALLOWED_ORIGINS — the exact policy the CSRF gate
    enforces for real requests. Reuses _check_same_origin_browser_request so the
    preflight can never advertise wider access (`*`) than an actual request would
    be granted. A wildcard here would let any site read authenticated responses
    on a deployment with no password set. Kept in api/ so server.py stays a thin
    dispatcher.
    """
    origin = handler.headers.get("Origin", "").strip()
    if not origin or not _check_same_origin_browser_request(handler):
        return
    handler.send_header("Access-Control-Allow-Origin", origin)
    handler.send_header("Vary", "Origin")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")


def _csrf_exempt_path(path: str) -> bool:
    """Paths that cannot or must not carry a session CSRF token."""
    return path in {
        "/api/auth/login",
        "/api/auth/passkey/options",
        "/api/auth/passkey/login",
        "/api/csp-report",
        "/api/remote/pair",
        "/api/process-complete-ack",
    }


_CSRF_FAILURE_ATTR = "_hermes_csrf_failure_reason"


def _set_csrf_failure_reason(handler, reason: str) -> bool:
    try:
        setattr(handler, _CSRF_FAILURE_ATTR, reason)
    except Exception:
        pass
    return False


def _clear_csrf_failure_reason(handler) -> None:
    try:
        if hasattr(handler, _CSRF_FAILURE_ATTR):
            delattr(handler, _CSRF_FAILURE_ATTR)
    except Exception:
        pass


def _csrf_rejection_error(handler) -> str:
    reason = getattr(handler, _CSRF_FAILURE_ATTR, "")
    if reason == "origin_mismatch":
        return "Cross-origin mismatch - check reverse proxy headers"
    if reason == "token_mismatch":
        return "Session expired - reload the page"
    return "Cross-origin request rejected"


def _check_csrf(handler) -> bool:
    """Reject cross-origin or tokenless authenticated cookie mutations.

    Cookie-authenticated browser and cookie-authenticated curl both need a
    CSRF token. Bearer-only infrastructure calls (no session cookie) follow
    the existing bearer policy and are not this gate.
    """
    if not _check_same_origin_browser_request(handler):
        return False

    from api.auth import (
        CSRF_HEADER_NAME,
        is_auth_enabled,
        parse_cookie,
        verify_csrf_token,
        verify_session,
    )

    cookie_val = parse_cookie(handler)
    has_cookie_session = bool(cookie_val and verify_session(cookie_val))
    authorization = (handler.headers.get("Authorization") or "").strip()
    bearer_only = authorization.lower().startswith("bearer ") and not has_cookie_session
    if bearer_only:
        return True
    if not has_cookie_session and not _is_browser_unsafe_request(handler):
        return True
    if not is_auth_enabled():
        return True
    submitted = handler.headers.get(CSRF_HEADER_NAME) or handler.headers.get("X-CSRF-Token")
    if verify_csrf_token(cookie_val or "", submitted or ""):
        return True
    return _set_csrf_failure_reason(handler, "token_mismatch")


_EXTENSION_SIDECAR_PROXY_RE = _re.compile(
    r"^/api/extensions/(?P<extension_id>[^/]+)/sidecar(?:/(?P<proxy_path>.*))?$"
)
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-connection",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _connection_bound_header_names(headers) -> set[str]:
    names = set(_HOP_BY_HOP_HEADERS)
    if not headers or not hasattr(headers, "items"):
        return names
    connection_values = []
    if hasattr(headers, "get_all"):
        connection_values.extend(headers.get_all("Connection", []))
    else:
        for name, value in headers.items():
            if str(name).lower() == "connection":
                connection_values.append(value)
    for value in connection_values:
        for token in str(value).split(","):
            normalized = token.strip().lower()
            if normalized:
                names.add(normalized)
    return names


def _match_extension_sidecar_proxy_path(path: str) -> tuple[str, str] | None:
    match = _EXTENSION_SIDECAR_PROXY_RE.match(path or "")
    if not match:
        return None
    return match.group("extension_id"), match.group("proxy_path") or ""


def _read_body_bytes(handler) -> bytes:
    raw_length = handler.headers.get("Content-Length", 0)
    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        try:
            handler.close_connection = True
        except Exception:
            pass
        raise ValueError(f"Invalid Content-Length: {raw_length!r}") from None
    if length < 0:
        try:
            handler.close_connection = True
        except Exception:
            pass
        raise ValueError(f"Invalid Content-Length: {length}")
    if length > MAX_BODY_BYTES:
        try:
            handler.close_connection = True
        except Exception:
            pass
        raise ValueError(f"Request body too large ({length} bytes, max {MAX_BODY_BYTES})")
    raw = handler.rfile.read(length) if length else b""
    try:
        from api.helpers import mark_request_body_consumed
        mark_request_body_consumed(handler)
    except Exception:
        pass
    return raw


def _extension_sidecar_proxy_request_headers(handler) -> dict[str, str]:
    headers = {}
    raw_headers = getattr(handler, "headers", None)
    if not raw_headers or not hasattr(raw_headers, "items"):
        return headers
    blocked_headers = _connection_bound_header_names(raw_headers)
    for name, value in raw_headers.items():
        lower = str(name).lower()
        if (
            lower in blocked_headers
            or lower in {"authorization", "cookie", "content-length", "host", "origin", "referer"}
            or lower.startswith("x-csrf")
            or lower.startswith("x-hermes-")
        ):
            continue
        headers[str(name)] = str(value)
    return headers


def _send_extension_sidecar_proxy_response(handler, status: int, body: bytes, headers) -> bool:
    handler.send_response(status)
    sent_content_type = False
    blocked_headers = _connection_bound_header_names(headers)
    if headers and hasattr(headers, "items"):
        for name, value in headers.items():
            lower = str(name).lower()
            if (
                lower in blocked_headers
                or lower in {"content-length", "set-cookie"}
                or lower.startswith("x-hermes-")
            ):
                continue
            if lower == "content-type":
                sent_content_type = True
            handler.send_header(str(name), str(value))
    if not sent_content_type:
        handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    _security_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _read_extension_sidecar_proxy_body(stream) -> bytes:
    body = stream.read(_EXTENSION_SIDECAR_PROXY_MAX_RESPONSE_BYTES + 1)
    if len(body) > _EXTENSION_SIDECAR_PROXY_MAX_RESPONSE_BYTES:
        raise ValueError("Extension sidecar response too large")
    return body


def _extension_sidecar_proxy_redirect_url(
    allowed_origin: str,
    request_url: str,
    redirect_url: str,
) -> str | None:
    resolved = urljoin(request_url, redirect_url or "")
    allowed = urlsplit(allowed_origin or "")
    parts = urlsplit(resolved)
    if not allowed.scheme or not allowed.netloc or not parts.scheme or not parts.netloc:
        return None
    allowed_scheme = allowed.scheme.lower()
    redirect_scheme = parts.scheme.lower()
    if redirect_scheme != allowed_scheme:
        return None
    allowed_name, allowed_port = _normalize_host_port(allowed.netloc)
    redirect_name, redirect_port = _normalize_host_port(parts.netloc)
    if redirect_name != allowed_name or not _ports_match(
        allowed_scheme,
        redirect_port,
        allowed_port,
    ):
        return None
    return resolved


def _extension_sidecar_proxy_same_origin_opener(allowed_origin: str):
    class _SameOriginRedirectHandler(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            resolved = _extension_sidecar_proxy_redirect_url(
                allowed_origin,
                req.full_url,
                newurl,
            )
            if not resolved:
                raise URLError("Extension sidecar redirect crossed declared origin")
            return super().redirect_request(req, fp, code, msg, headers, resolved)

    return build_opener(ProxyHandler({}), _SameOriginRedirectHandler)


def _handle_extension_sidecar_proxy(
    handler,
    parsed,
    method: str,
    *,
    read_request_body: bool = False,
):
    matched = _match_extension_sidecar_proxy_path(parsed.path)
    if matched is None:
        return False
    # Require same-origin browser provenance on EVERY proxied method, not just
    # GET. Browser extensions (the only legitimate caller) always send Origin/
    # Referer/Sec-Fetch-Site, so this costs nothing on the real path while
    # closing the GET-vs-unsafe-method asymmetry: without it, POST/PATCH/PUT/
    # DELETE fell through the CSRF compatibility path that intentionally admits
    # non-browser clients, giving unsafe methods weaker provenance than GET.
    if not _check_same_origin_browser_request(handler, require_provenance=True):
        return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
    try:
        request_body = _read_body_bytes(handler) if read_request_body else None
    except ValueError as exc:
        status = 413 if "too large" in str(exc).lower() else 400
        return bad(handler, str(exc), status=status)
    from api.extensions import (
        ExtensionSidecarProxyError,
        resolve_extension_sidecar_proxy_target,
    )

    extension_id, proxy_path = matched
    try:
        target = resolve_extension_sidecar_proxy_target(
            extension_id,
            proxy_path,
            query=parsed.query,
        )
        proxied_headers = _extension_sidecar_proxy_request_headers(handler)
        # token-v1: inject the per-extension shared secret core minted. The
        # inbound x-hermes-* strip above guarantees the client cannot have
        # forged this header.
        _auth_token = target.get("auth_token")
        if _auth_token:
            proxied_headers["X-Hermes-Sidecar-Token"] = _auth_token
        request = Request(
            target["upstream_url"],
            data=request_body,
            headers=proxied_headers,
            method=method,
        )
        opener = _extension_sidecar_proxy_same_origin_opener(target["origin"])
        with opener.open(request, timeout=10) as response:
            body = _read_extension_sidecar_proxy_body(response)
            return _send_extension_sidecar_proxy_response(
                handler,
                getattr(response, "status", 200),
                body,
                response.headers,
            )
    except ExtensionSidecarProxyError as exc:
        return bad(handler, str(exc), status=exc.status)
    except ValueError as exc:
        return bad(handler, str(exc), status=502)
    except HTTPError as exc:
        try:
            body = _read_extension_sidecar_proxy_body(exc)
        except ValueError as read_exc:
            return bad(handler, str(read_exc), status=502)
        return _send_extension_sidecar_proxy_response(
            handler,
            exc.code,
            body,
            exc.headers,
        )
    except (TimeoutError, URLError, OSError):
        logger.warning(
            "extension sidecar proxy failed for %s %s",
            method,
            parsed.path,
            exc_info=True,
        )
        return bad(handler, "Failed to reach extension sidecar", status=502)


def _client_ip_for_rate_limit(handler) -> str:
    try:
        address = getattr(handler, "client_address", None)
        if address:
            return str(address[0])
    except Exception:
        pass
    return "unknown"


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _request_client_ip(handler) -> str:
    try:
        address = getattr(handler, "client_address", None)
        if address:
            return str(address[0] or "")
    except Exception:
        pass
    return ""


def _ip_is_loopback_or_private(raw: str):
    """Parse an IP string; return (parsed_ok, is_loopback_or_private).

    Returns (False, False) for empty/malformed input so callers fail closed.
    """
    import ipaddress

    raw = (raw or "").strip()
    if not raw:
        return (False, False)
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return (False, False)
    return (True, bool(addr.is_loopback or addr.is_private))


def _trusted_proxy_networks():
    """Networks whose socket peer is allowed to assert a forwarded client IP.

    Loopback is ALWAYS trusted implicitly (the common same-host reverse-proxy
    deployment). Operators fronting the WebUI with a LAN/remote proxy add its
    address(es) via HERMES_WEBUI_TRUSTED_PROXY_CIDRS (comma-separated CIDRs or
    bare IPs). Malformed entries are skipped, never widening trust.
    """
    import ipaddress

    nets = [
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("::ffff:127.0.0.0/104"),
    ]
    raw = os.getenv("HERMES_WEBUI_TRUSTED_PROXY_CIDRS", "") or ""
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            # Invalid CIDR/IP → skip (fail closed: never widens trust).
            continue
    return nets


def _ip_in_networks(addr, networks) -> bool:
    """Family-aware membership test.

    Checks the parsed address against each network, and — for an IPv4-mapped
    IPv6 address (e.g. ``::ffff:10.9.9.9``) — ALSO checks its embedded IPv4 form
    against IPv4 networks. Without this, a mapped-IPv6 proxy peer would never
    match an IPv4 CIDR allowlist: the trusted proxy would be treated as
    untrusted (locking out legitimate clients behind it) and, inside an XFF
    chain, a mapped trusted hop would be mis-returned as the client (admitting a
    public client that preceded it). See #5764.
    """
    candidates = [addr]
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)
    for cand in candidates:
        for net in networks:
            try:
                if cand in net:
                    return True
            except TypeError:
                # IPv4/IPv6 family mismatch between candidate and net → skip.
                continue
    return False


def _raw_peer_is_trusted_proxy(handler) -> bool:
    """True when the immediate socket peer is loopback or an allowlisted proxy.

    Only such a peer is allowed to assert a forwarded client IP. Judged on the
    RAW socket address (never a header), so it cannot be spoofed.
    """
    import ipaddress

    raw = _request_client_ip(handler)
    if not raw:
        return False
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return _ip_in_networks(addr, _trusted_proxy_networks())


def _forwarded_client_ip_from_trusted_proxy(handler):
    """Resolve the real client IP from a chain fronted by a trusted proxy.

    Precondition: the caller has verified the raw socket peer is a trusted proxy.
    Consumes ALL X-Forwarded-For values (across repeated headers), preserves wire
    order, walks RIGHT-TO-LEFT skipping hops that are themselves trusted-proxy
    addresses, and returns the first non-trusted (i.e. real-client) hop. Falls
    back to X-Real-IP, then the raw socket peer. Returns None when the chain is
    present-but-empty / malformed so the caller fails closed.
    """
    import ipaddress

    try:
        xff_values = handler.headers.get_all("X-Forwarded-For") or []
    except AttributeError:
        single = handler.headers.get("X-Forwarded-For", "")
        xff_values = [single] if single else []

    hops: list[str] = []
    for header_value in xff_values:
        for token in str(header_value or "").split(","):
            hops.append(token.strip())

    if xff_values:
        # A present-but-empty / all-blank XFF is malformed → fail closed.
        if not any(hops):
            return None
        trusted_nets = _trusted_proxy_networks()

        def _is_trusted_hop(ip_str: str) -> bool:
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                return False
            return _ip_in_networks(addr, trusted_nets)

        for hop in reversed(hops):
            if not hop:
                # An empty hop inside the chain is malformed → fail closed
                # rather than skip past it (an attacker could inject blanks).
                return None
            try:
                ipaddress.ip_address(hop)
            except ValueError:
                # Non-IP token in the chain → malformed → fail closed.
                return None
            if _is_trusted_hop(hop):
                continue
            return hop
        # Every hop was a trusted proxy → no distinct client; treat as the proxy
        # tier itself (loopback/private), i.e. resolve to the raw peer below.
        return _request_client_ip(handler)

    real_ip = handler.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    # No forwarded header at all → the trusted proxy is speaking for itself.
    return _request_client_ip(handler)


def _onboarding_request_is_local(handler) -> bool:
    """Return True when an unauthenticated onboarding request is local/private.

    Trust model (single, symmetric — see the full truth table in
    tests/test_cvd3_terminal_local_origin_gate.py):

    * Forwarded client-IP headers are honored ONLY when the RAW socket peer is a
      trusted proxy (loopback, or an address in HERMES_WEBUI_TRUSTED_PROXY_CIDRS).
      This is checked on the un-spoofable socket address, so a direct client
      cannot promote itself to "local" by sending X-Forwarded-For: 127.0.0.1.
    * When the peer is NOT a trusted proxy, forwarded headers are ignored and the
      request is classified by the raw socket peer directly. A direct loopback or
      private/LAN client (no proxy) is therefore still correctly local — so
      onboarding, first-password/passkey setup, and passwordless embedded-terminal
      access keep working on the common direct-LAN deployment.
    * HERMES_WEBUI_TRUST_FORWARDED_FOR=1 is the opt-in that makes us CONSULT the
      forwarded chain at all; without it the raw peer is authoritative. Either
      way the classification fails closed on malformed/empty chains.
    """
    trust_forwarded = _truthy_env("HERMES_WEBUI_TRUST_FORWARDED_FOR")
    peer_is_trusted_proxy = _raw_peer_is_trusted_proxy(handler)

    if trust_forwarded and peer_is_trusted_proxy:
        client_ip = _forwarded_client_ip_from_trusted_proxy(handler)
        if client_ip is None:
            # Malformed/empty forwarded chain from a trusted proxy → fail closed.
            return False
        parsed_ok, is_local = _ip_is_loopback_or_private(client_ip)
        return parsed_ok and is_local

    # Not consulting the forwarded chain (either the opt-in is off, or the raw
    # peer is not a trusted proxy). Classify by the raw socket peer — it cannot
    # be spoofed by a header. A public peer sending X-Forwarded-For: 127.0.0.1 is
    # therefore correctly rejected (its raw peer is public).
    raw = _request_client_ip(handler)
    parsed_ok, is_local = _ip_is_loopback_or_private(raw)
    if not parsed_ok:
        return False

    import ipaddress

    addr = ipaddress.ip_address(raw.strip())
    if addr.is_loopback:
        # A loopback TCP source is genuinely same-host and unspoofable → local
        # even if a (ignored) forwarded header is present.
        return True

    # Non-loopback raw peer. A forwarded header being PRESENT here means the
    # request most likely arrived through a proxy we have NOT been told to trust
    # (no trusted-proxy env, or the peer isn't in the allowlist) — so a
    # private/LAN raw peer could be an untrusted proxy relaying an arbitrary
    # (public) client we can't see. Deny in that case; require the operator to
    # opt in via HERMES_WEBUI_TRUST_FORWARDED_FOR (+ HERMES_WEBUI_TRUSTED_PROXY_CIDRS
    # for a non-loopback proxy). With NO forwarded header, a direct private/LAN
    # client (the common direct-LAN deployment) stays local so onboarding,
    # first-password/passkey setup, and passwordless terminal keep working.
    forwarded_present = bool(
        (handler.headers.get("X-Forwarded-For", "") or "").strip()
        or (handler.headers.get("X-Real-IP", "") or "").strip()
    )
    if forwarded_present:
        return False
    return bool(is_local)


def _onboarding_gate_allows(handler, auth_enabled: bool | None = None) -> bool:
    from api.auth import is_auth_enabled

    auth_enabled = is_auth_enabled() if auth_enabled is None else auth_enabled
    if auth_enabled or _truthy_env("HERMES_WEBUI_ONBOARDING_OPEN"):
        return True
    return _onboarding_request_is_local(handler)


# Operator-facing copy reused by every embedded-terminal endpoint refusal.
_EMBEDDED_TERMINAL_GATE_DENIED_MESSAGE = (
    "Embedded terminal is only available from local networks when authentication "
    "is not configured. Configure a password/passkey, or set "
    "HERMES_WEBUI_ONBOARDING_OPEN=1 to allow it on a deliberately-exposed server."
)


def _embedded_terminal_gate_allows(handler) -> bool:
    """Local-origin gate for the embedded-terminal endpoints.

    The embedded terminal spawns a PTY shell that runs arbitrary commands as the
    server-process user, so admitting an unauthenticated remote caller is remote
    code execution. When auth is enabled, ``check_auth()`` has already verified
    the session cookie before the request reaches these handlers, so this returns
    True. When auth is DISABLED (the default out-of-the-box state) ``check_auth()``
    admits every caller unconditionally, so restrict the terminal to local/private
    origins — the same trust model the onboarding/bootstrap endpoints use, ignoring
    spoofable forwarded headers unless an operator has opted into trusting them.
    A deliberately-exposed passwordless server (access secured at another layer)
    opts out with ``HERMES_WEBUI_ONBOARDING_OPEN=1``.
    """
    return _onboarding_gate_allows(handler)


# Above this many distinct client keys, sweep out entries whose timestamps have
# all aged past the window on the next update. Behind a reverse proxy the map
# holds a single key (the proxy IP) and never trips this; a directly-exposed
# deployment would otherwise keep one entry forever for every IP that ever hit
# the endpoint, since a key is only revisited when that same IP calls again.
_RATE_LIMIT_MAP_SWEEP_THRESHOLD = 4096


def _prune_stale_rate_limit_keys(mapping: dict, cutoff: float) -> None:
    """Drop keys whose newest timestamp has aged out of the window. Caller holds
    the map's lock. Size-gated so the common (few-key) path stays O(1)."""
    if len(mapping) <= _RATE_LIMIT_MAP_SWEEP_THRESHOLD:
        return
    stale = [k for k, ts in mapping.items() if not ts or ts[-1] < cutoff]
    for k in stale:
        del mapping[k]


def _csp_report_rate_limited(handler, *, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    key = _client_ip_for_rate_limit(handler)
    cutoff = now - _CSP_REPORT_RATE_LIMIT_WINDOW_SECONDS
    with _CSP_REPORT_RATE_LIMIT_LOCK:
        _prune_stale_rate_limit_keys(_CSP_REPORT_RATE_LIMIT, cutoff)
        timestamps = [ts for ts in _CSP_REPORT_RATE_LIMIT.get(key, []) if ts >= cutoff]
        if len(timestamps) >= _CSP_REPORT_RATE_LIMIT_MAX:
            _CSP_REPORT_RATE_LIMIT[key] = timestamps
            return True
        timestamps.append(now)
        _CSP_REPORT_RATE_LIMIT[key] = timestamps
    return False




def _send_no_content(handler, status: int = 204) -> bool:
    handler.send_response(status)
    handler.send_header("Content-Length", "0")
    handler.end_headers()
    return True


def _safe_content_length(handler, max_bytes: int) -> int:
    raw_length = handler.headers.get("Content-Length", 0)
    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        try:
            handler.close_connection = True
        except Exception:
            pass
        raise ValueError(f"Invalid Content-Length: {raw_length!r}") from None
    if length < 0:
        try:
            handler.close_connection = True
        except Exception:
            pass
        raise ValueError(f"Invalid Content-Length: {length}")
    if length > max_bytes:
        try:
            handler.close_connection = True
        except Exception:
            pass
        raise OverflowError(f"Request body too large ({length} bytes, max {max_bytes})")
    return length


def _read_csp_report_payload(handler):
    try:
        length = _safe_content_length(handler, _CSP_REPORT_MAX_BODY_BYTES)
    except OverflowError as exc:
        try:
            handler.rfile.read(_CSP_REPORT_MAX_BODY_BYTES)
        except Exception:
            pass
        return {"discarded": "body_too_large", "error": str(exc)}
    except ValueError as exc:
        return {"discarded": "invalid_content_length", "error": str(exc)}
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        from api.helpers import mark_request_body_consumed
        mark_request_body_consumed(handler)
    except Exception:
        pass
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {"invalid": True, "bytes": len(raw)}


def _handle_csp_report(handler) -> bool:
    """Collect browser CSP report-only violations without requiring auth."""
    if _csp_report_rate_limited(handler):
        _CSP_REPORT_LOGGER.warning(
            "Dropped CSP report from %s: rate limit exceeded",
            _client_ip_for_rate_limit(handler),
        )
        return _send_no_content(handler)

    payload = _read_csp_report_payload(handler)
    _CSP_REPORT_LOGGER.info("CSP report from %s: %s", _client_ip_for_rate_limit(handler), payload)
    return _send_no_content(handler)












def _starts_token(raw: str, prefix: str) -> bool:
    if not raw.startswith(prefix):
        return False
    rest = raw[len(prefix):]
    return rest == "" or rest[0] in ":/"


def _normalize_provider_id(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[raw]
    for prefix, normalized in (
        ("openai-codex", "openai"),
        ("openai", "openai"),
        ("anthropic", "anthropic"),
        ("claude", "anthropic"),
        ("google", "google"),
        ("gemini", "google"),
        ("openrouter", "openrouter"),
        ("custom", "custom"),
    ):
        if _starts_token(raw, prefix):
            return normalized
    # Unknown prefix — return empty so callers treat it as "no match" and pass
    # the model through unchanged rather than incorrectly stripping it.
    return ""


def _catalog_provider_id_sets(catalog: dict) -> tuple[set[str], set[str]]:
    raw_provider_ids: set[str] = set()
    normalized_provider_ids: set[str] = set()
    for group in catalog.get("groups") or []:
        raw = str(group.get("provider_id") or "").strip().lower()
        if not raw:
            continue
        raw_provider_ids.add(raw)
        normalized = _normalize_provider_id(raw)
        if normalized:
            normalized_provider_ids.add(normalized)
    return raw_provider_ids, normalized_provider_ids


def _catalog_has_provider(
    provider_raw: str,
    provider_normalized: str,
    raw_provider_ids: set[str],
    normalized_provider_ids: set[str],
) -> bool:
    return (
        provider_raw in raw_provider_ids
        or (provider_normalized and provider_normalized in raw_provider_ids)
        or (provider_normalized and provider_normalized in normalized_provider_ids)

    )


def _model_matches_active_provider_family(
    model: str,
    active_provider: str,
) -> bool:
    model_lower = model.lower()
    for bare_prefix in ("gpt", "claude", "gemini"):
        if model_lower.startswith(bare_prefix):
            return _normalize_provider_id(bare_prefix) == active_provider
    return False


def _catalog_model_id_matches(candidate: str, model: str) -> bool:
    candidate = str(candidate or "").strip()
    if candidate.startswith("@") and ":" in candidate:
        candidate = candidate.rsplit(":", 1)[1]
    if "/" in candidate:
        candidate = candidate.split("/", 1)[1]
    return candidate.replace("-", ".").lower() == model.replace("-", ".").lower()


def _catalog_group_owns_exact_model(group: dict, model: str) -> bool:
    provider_id = str(group.get("provider_id") or "").strip()
    wrapper = f"@{provider_id}:"
    for bucket in ("models", "extra_models"):
        for entry in group.get(bucket) or []:
            if not isinstance(entry, dict):
                continue
            candidate = str(entry.get("id") or "").strip()
            if candidate.lower().startswith(wrapper.lower()):
                candidate = candidate[len(wrapper):]
            if candidate == model or _catalog_model_id_matches(candidate, model):
                return True
    return False


def _repair_foreign_session_model_provider(
    session,
    *,
    requested_model: str,
    requested_provider: str | None,
    resolved_model: str,
    resolved_provider: str | None,
    explicit_model_pick: bool,
    profile_provider: str | None,
) -> str | None:
    """Repair a stale provider only when the cached catalog names one owner."""
    stored_model = str(getattr(session, "model", "") or "").strip()
    stored_provider = _clean_session_model_provider(getattr(session, "model_provider", None))
    requested_provider = _clean_session_model_provider(requested_provider)
    resolved_provider = _clean_session_model_provider(resolved_provider)
    profile_provider = _clean_session_model_provider(profile_provider)
    _, qualified_provider = _split_provider_qualified_model(requested_model)
    if (
        explicit_model_pick
        or qualified_provider
        or not stored_model
        or not stored_provider
        or (
            str(requested_model or "").strip() != stored_model
            and not _catalog_model_id_matches(str(requested_model or "").strip(), stored_model)
        )
        or requested_provider != stored_provider
        or (
            resolved_model != stored_model
            and not _catalog_model_id_matches(resolved_model, stored_model)
        )
        or resolved_provider != stored_provider
        or not profile_provider
        or profile_provider == stored_provider
    ):
        return resolved_provider

    try:
        catalog = get_available_models(prefer_cache=True)
    except Exception:
        return resolved_provider
    groups = [group for group in catalog.get("groups") or [] if isinstance(group, dict)]
    stored_groups = [
        group
        for group in groups
        if str(group.get("provider_id") or "").strip().lower() == stored_provider
    ]
    if (
        not stored_groups
        or any(group.get("models_endpoint_error") for group in stored_groups)
        or any(_catalog_group_owns_exact_model(group, stored_model) for group in stored_groups)
    ):
        return resolved_provider
    owners = [
        group
        for group in groups
        if str(group.get("provider_id") or "").strip().lower() != stored_provider
        and _catalog_group_owns_exact_model(group, stored_model)
    ]
    if len(owners) != 1:
        return resolved_provider
    return str(owners[0].get("provider_id") or "").strip() or resolved_provider


def _clean_session_model_provider(value: str | None) -> str | None:
    """Normalize a stored/requested provider value to a bare provider ID.

    An ``@``-prefixed value is a provider-qualified *model* hint, so the
    provider is resolved with the shared
    ``config._parse_provider_qualified_model_id()`` grammar rather than a
    positional colon split — that keeps multi-segment custom provider IDs
    (``custom:<slug>``, ``custom:<host>:<port>``) whole while still dropping a
    trailing model segment (#6722). Values without the ``@`` marker are already
    plain provider IDs, whose colons belong to the ID itself, so they are
    preserved verbatim.
    """
    provider = str(value or "").strip().lower()
    if not provider or provider == "default":
        return None
    if provider.startswith("@"):
        parsed = _parse_provider_qualified_model_id(provider)
        provider = parsed[1].strip() if parsed else provider[1:]
    return provider or None


def _split_provider_qualified_model(model: str) -> tuple[str, str | None]:
    """Split an ``@provider:model`` hint into ``(bare_model, provider)``.

    Delegates the grammar to ``config._parse_provider_qualified_model_id()``,
    the shared parser that already knows how to keep a multi-segment custom
    provider ID (``custom:<slug>``, ``custom:<host>:<port>``) intact while
    still letting the model segment carry its own colons for tags such as
    ``:free``. Keeping one parser here means every caller in this module and
    the gateway request path resolve the same provider/model pair (#6722).
    """
    model = str(model or "").strip()
    parsed = _parse_provider_qualified_model_id(model)
    if parsed:
        bare_model, provider_hint = parsed
        provider = _clean_session_model_provider(provider_hint)
        bare = str(bare_model or "").strip()
        if provider and bare:
            return bare, provider
    return model, None


def _model_matches_configured_default(
    session_model: str | None,
    cfg_default: str | None,
    provider: str | None = None,
) -> bool:
    """Return True when ``session_model`` refers to the configured ``model.default``.

    The global ``model.context_length`` cap applies ONLY to the default model
    (#3256/#3263). An exact string compare is not enough because ``model.default``
    and the session model can be stored in different but equivalent shapes:
      - bare:            ``claude-opus-4.8``
      - slash-prefixed:  ``anthropic/claude-opus-4.8``  (OpenRouter-style)
      - @provider:model: ``@anthropic:claude-opus-4.8``

    Matching rule (correct in both directions):
      1. Identical strings → match.
      2. Otherwise compare BARE model ids — BUT only after a provider-compatibility
         check: if BOTH sides carry an identifiable provider (from a ``provider/``
         prefix, an ``@provider:`` qualifier, or the explicit ``provider`` arg for
         the session side) and those providers DIFFER, it is NOT a match. This
         stops a non-default model on a different provider that happens to share a
         bare name (``openai/gpt-4o`` vs default ``openrouter/gpt-4o``) from being
         treated as the default and wrongly receiving its cap.
      3. When a provider can't be identified on one side, fall through to the bare
         comparison (lenient-when-unknown — a bare default config still matches a
         bare/prefixed session model).
    Empty default → no match.
    """
    sess = str(session_model or "").strip()
    default = str(cfg_default or "").strip()
    if not sess or not default:
        return False
    if sess == default:
        return True

    def _split(value: str) -> tuple[str, str | None]:
        """Return (bare_model, provider_or_None) for any of the 3 shapes."""
        value = str(value or "").strip()
        # @provider:model
        unq, q_prov = _split_provider_qualified_model(value)
        if q_prov:
            return unq.strip(), str(q_prov).strip().lower()
        # provider/model (single leading slash segment)
        if "/" in value:
            prefix, rest = value.split("/", 1)
            return rest.strip(), prefix.strip().lower()
        return value, None

    sess_bare, sess_prov = _split(sess)
    default_bare, default_prov = _split(default)
    # The explicit provider arg is the session side's provider when the model
    # string itself didn't carry one.
    if not sess_prov and provider:
        sess_prov = str(provider).strip().lower() or None

    if not sess_bare or not default_bare or sess_bare != default_bare:
        return False
    # Bare ids match. Reject only when both sides name DIFFERENT providers.
    if sess_prov and default_prov and sess_prov != default_prov:
        return False
    return True


class _ContextLengthLookupInputs:
    __slots__ = ("config_context_length", "custom_providers", "base_url", "provider", "api_key")

    def __init__(
        self,
        *,
        config_context_length: int | None = None,
        custom_providers: list | None = None,
        base_url: str = "",
        provider: str = "",
        api_key: str = "",
    ) -> None:
        self.config_context_length = config_context_length
        self.custom_providers = custom_providers
        self.base_url = base_url
        self.provider = provider
        self.api_key = api_key


def _positive_context_length(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _model_lookup_candidates(model: str) -> tuple[str, ...]:
    raw = str(model or "").strip()
    candidates = []
    for candidate in (raw, _split_provider_qualified_model(raw)[0]):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
        if "/" in candidate:
            bare = candidate.split("/", 1)[1].strip()
            if bare and bare not in candidates:
                candidates.append(bare)
    return tuple(candidates)


def _models_config_context_length(models_cfg, model: str) -> int | None:
    candidates = _model_lookup_candidates(model)
    if isinstance(models_cfg, dict):
        for candidate in candidates:
            entry = models_cfg.get(candidate)
            raw_ctx = entry.get("context_length") if isinstance(entry, dict) else entry
            ctx = _positive_context_length(raw_ctx)
            if ctx is not None:
                return ctx
    if isinstance(models_cfg, list):
        for entry in models_cfg:
            if not isinstance(entry, dict):
                continue
            entry_model = str(entry.get("id") or entry.get("model") or entry.get("name") or "").strip()
            if entry_model in candidates:
                ctx = _positive_context_length(entry.get("context_length"))
                if ctx is not None:
                    return ctx
    return None


def _canonical_context_provider(value: str | None) -> str:
    provider = _clean_session_model_provider(value) or ""
    if not provider:
        return ""
    try:
        from api.config import _resolve_provider_alias

        provider = _resolve_provider_alias(provider)
    except Exception:
        pass
    return str(provider or "").strip().lower()


def _custom_provider_slug_for_context(name: object) -> str:
    try:
        from api.config import _custom_provider_slug_from_name

        return _custom_provider_slug_from_name(name)
    except Exception:
        raw = str(name or "").strip().lower()
        if not raw:
            return ""
        if raw.startswith("custom:"):
            return raw
        slug = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)
        return f"custom:{slug}" if slug else ""


def _providers_match_for_context(config_key: object, requested_provider: str) -> bool:
    if not requested_provider:
        return False
    raw_key = str(config_key or "").strip().lower()
    key = _canonical_context_provider(raw_key)
    requested = _canonical_context_provider(requested_provider)
    return bool(
        requested
        and (
            raw_key == requested
            or key == requested
            or raw_key == str(requested_provider or "").strip().lower()
        )
    )


def _custom_provider_api_key_for_context(entry: dict, provider: str) -> str:
    """Resolve the API key for a matched ``custom_providers`` entry.

    Static session hydration/update routes already have a per-profile config
    snapshot. Resolve from the matched entry instead of re-reading global config,
    while preserving the same literal, ``${ENV_VAR}``, ``key_env``, and
    sanitized-env shapes used by streaming/provider resolution.
    """
    raw_api_key = entry.get("api_key")
    if raw_api_key is not None:
        api_key_text = str(raw_api_key).strip()
        if api_key_text.startswith("${") and api_key_text.endswith("}") and len(api_key_text) > 3:
            env_name = api_key_text[2:-1]
            resolved = os.getenv(env_name, "").strip()
            if resolved:
                return resolved
            logger.debug(
                "Custom provider %s api_key references %s, but the environment variable is unset or empty",
                provider,
                api_key_text,
            )
        elif api_key_text:
            return api_key_text

    key_env = str(entry.get("key_env") or "").strip()
    if key_env:
        resolved = os.getenv(key_env, "").strip()
        if resolved:
            return resolved

    try:
        from api.config import _lookup_custom_api_key_env

        return _lookup_custom_api_key_env(provider) or ""
    except Exception:
        return ""


def _context_length_config_api_key_for_provider(
    provider: str | None,
    cfg: dict | None,
) -> str:
    """Return a config/env API key usable for context-window metadata lookup."""
    cfg = cfg if isinstance(cfg, dict) else {}
    provider = _canonical_context_provider(provider)

    def _resolve_key(raw_api_key, raw_key_env=None) -> str:
        api_key_text = str(raw_api_key or "").strip()
        if (
            api_key_text.startswith("${")
            and api_key_text.endswith("}")
            and len(api_key_text) > 3
        ):
            resolved = os.getenv(api_key_text[2:-1], "").strip()
            if resolved:
                return resolved
        elif api_key_text:
            return api_key_text
        key_env = str(raw_key_env or "").strip()
        if key_env:
            resolved = os.getenv(key_env, "").strip()
            if resolved:
                return resolved
        return ""

    providers_cfg = cfg.get("providers") or {}
    if isinstance(providers_cfg, dict):
        for provider_key, provider_cfg in providers_cfg.items():
            if not isinstance(provider_cfg, dict):
                continue
            if not _providers_match_for_context(provider_key, provider):
                continue
            api_key = _resolve_key(provider_cfg.get("api_key"), provider_cfg.get("key_env"))
            if api_key:
                return api_key

    model_cfg = cfg.get("model", {})
    if isinstance(model_cfg, dict):
        model_provider = _canonical_context_provider(model_cfg.get("provider"))
        if not provider or _providers_match_for_context(model_provider, provider):
            api_key = _resolve_key(model_cfg.get("api_key"), model_cfg.get("key_env"))
            if api_key:
                return api_key
    return ""


def _context_length_lookup_inputs_for_model(
    model: str | None,
    provider: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    cfg: dict | None = None,
) -> _ContextLengthLookupInputs:
    """Return the effective metadata resolver inputs for a WebUI model.

    ``agent.model_metadata.get_model_context_length`` understands global
    ``config_context_length`` and custom-provider overrides, but only when the
    matching base URL is supplied. WebUI also owns ``providers.<provider>.models``
    overrides, so normalize those here and keep route/session-save/SSE aligned.
    """
    model_for_lookup = str(model or "").strip()
    if not model_for_lookup:
        return _ContextLengthLookupInputs()

    if cfg is None:
        try:
            from api.config import get_config as _get_config_for_cl

            cfg = _get_config_for_cl()
        except Exception:
            cfg = {}
    cfg = cfg if isinstance(cfg, dict) else {}

    bare_model, explicit_provider = _split_provider_qualified_model(model_for_lookup)
    effective_provider = _canonical_context_provider(provider or explicit_provider)
    effective_base_url = str(base_url or "").strip()

    model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}
    if isinstance(model_cfg, dict):
        if not effective_provider:
            effective_provider = _canonical_context_provider(model_cfg.get("provider"))
        if not effective_base_url:
            effective_base_url = str(model_cfg.get("base_url") or "").strip()

    custom_providers = cfg.get("custom_providers") if isinstance(cfg, dict) else None
    if not isinstance(custom_providers, list):
        custom_providers = None

    provider_context_length = None
    providers_cfg = (cfg.get("providers") or {}) if isinstance(cfg, dict) else {}
    if isinstance(providers_cfg, dict):
        for provider_key, provider_cfg in providers_cfg.items():
            if not isinstance(provider_cfg, dict):
                continue
            if not _providers_match_for_context(provider_key, effective_provider):
                continue
            if not effective_base_url:
                effective_base_url = str(provider_cfg.get("base_url") or "").strip()
            provider_context_length = _models_config_context_length(
                provider_cfg.get("models"),
                bare_model or model_for_lookup,
            )
            break

    custom_context_length = None
    effective_api_key = str(api_key or "").strip()
    if custom_providers:
        target_base = effective_base_url.rstrip("/")
        model_candidates = set(_model_lookup_candidates(bare_model or model_for_lookup))
        for entry in custom_providers:
            if not isinstance(entry, dict):
                continue
            entry_name = str(entry.get("name") or "").strip()
            entry_slug = _custom_provider_slug_for_context(entry_name)
            entry_base = str(entry.get("base_url") or "").strip()
            entry_base_norm = entry_base.rstrip("/")
            provider_matches = bool(
                effective_provider
                and (
                    effective_provider == entry_slug
                    or effective_provider == entry_name.lower()
                    or (effective_provider == "custom" and len(custom_providers) == 1)
                )
            )
            base_matches = bool(target_base and entry_base_norm and target_base == entry_base_norm)
            model_matches = bool(model_candidates.intersection(set(_model_lookup_candidates(entry.get("model")))))
            models_cfg = entry.get("models")
            if isinstance(models_cfg, dict):
                model_matches = model_matches or any(candidate in models_cfg for candidate in model_candidates)
            if not (provider_matches or base_matches or (not effective_provider and model_matches)):
                continue
            if not effective_provider and entry_slug:
                effective_provider = entry_slug
            if not effective_base_url and entry_base:
                effective_base_url = entry_base
            if not effective_api_key:
                effective_api_key = _custom_provider_api_key_for_context(entry, effective_provider or entry_slug)
            custom_context_length = _models_config_context_length(models_cfg, bare_model or model_for_lookup)
            break

    global_context_length = None
    if isinstance(model_cfg, dict):
        cfg_default_model = str(model_cfg.get("default") or "").strip()
        raw_cfg_ctx = model_cfg.get("context_length")
        if raw_cfg_ctx is not None and (
            not cfg_default_model
            or _model_matches_configured_default(
                model_for_lookup,
                cfg_default_model,
                effective_provider,
            )
        ):
            global_context_length = _positive_context_length(raw_cfg_ctx)

    if not effective_api_key:
        effective_api_key = _context_length_config_api_key_for_provider(effective_provider, cfg)

    return _ContextLengthLookupInputs(
        config_context_length=provider_context_length or custom_context_length or global_context_length,
        custom_providers=custom_providers,
        base_url=effective_base_url,
        provider=effective_provider,
        api_key=effective_api_key,
    )



def _should_attach_codex_provider_context(model: str, raw_active_provider: str, catalog: dict) -> bool:
    """Return True when a bare Codex model needs separate provider context.

    OpenAI, OpenAI Codex, Copilot, and OpenRouter can all expose GPT-looking
    bare names. If a session stores only ``gpt-...`` while Codex is active, a
    later provider-list/default-model round trip can lose the user's Codex
    choice. Store the provider separately instead of converting the persisted
    model to ``@openai-codex:model``.
    """
    if raw_active_provider != "openai-codex":
        return False
    if not model.lower().startswith("gpt"):
        return False
    for group in catalog.get("groups") or []:
        if str(group.get("provider_id") or "").strip().lower() != "openai-codex":
            continue
        return any(
            _catalog_model_id_matches(entry.get("id"), model)
            for entry in group.get("models", [])
            if isinstance(entry, dict)
        )
    return False

def _read_profile_model_config(
    session,
    requested_provider: str | None,
) -> tuple[str | None, str | None, dict | None]:
    """Read model.provider, model.default, and the full profile config dict.

    Returns (profile_provider, profile_default_model, profile_config_dict).
    The first two are None when the session has no profile or the profile config
    is unreadable; profile_config_dict is None in the same cases so callers only
    pay for one YAML parse.

    When the session already has an explicit ``requested_provider``, the profile
    ``model.provider`` is not returned (first tuple element is None) so profile
    does not override the session provider. ``profile_default_model`` is still
    returned for suffix repair (#5127) only when the profile's configured
    provider matches ``requested_provider`` after normalization.

    perf(webui/session-load-latency) tier2a: the parse is wrapped in a
    per-process LRU keyed by (profile_name, config_mtime, size). The
    function fires on every chat-open for sessions under a named
    profile (resolve_model=1 path), and the YAML parse alone is
    hundreds of µs to single-digit ms on the Chromebook. Cache TTL
    60s is a backstop in case mtime resolution is poor on a given
    filesystem; under normal edits the mtime changes and invalidates
    immediately.
    """
    if not getattr(session, "profile", None):
        return None, None, None

    try:
        from api.profiles import get_hermes_home_for_profile

        _profile_name = str(session.profile or "")
        _profile_home = get_hermes_home_for_profile(_profile_name)
        _profile_cfg_path = os.path.join(str(_profile_home), "config.yaml")
        if not os.path.isfile(_profile_cfg_path):
            return None, None, None
        _pcfg = _read_profile_config_cached(_profile_name, _profile_cfg_path)
        if _pcfg is None:
            return None, None, None
        _model_cfg = _pcfg.get("model") or {}
        if not isinstance(_model_cfg, dict):
            return None, None, _pcfg
        _provider = (_model_cfg.get("provider") or "").strip() or None
        _default = (_model_cfg.get("default") or "").strip() or None
    except Exception:
        logger.warning(
            "profile provider read failed for %r",
            getattr(session, "profile", None),
            exc_info=True,
        )
        return None, None, None

    _requested = _clean_session_model_provider(requested_provider)
    if _requested:
        _profile_prov = _clean_session_model_provider(_provider)
        if _profile_prov != _requested:
            return None, None, _pcfg
        return None, _default, _pcfg
    return _provider, _default, _pcfg


# perf(webui/session-load-latency) tier2a: process-wide cache for parsed
# profile config.yaml. Key = (profile_name, inode, mtime, size); value = parsed
# dict. inode tracks atomic-rename edits (most editors replace files, giving a
# new inode on Linux). mtime+size auto-invalidates on in-place edits; a 60s TTL
# is the backstop in case of coarse mtime resolution (some network filesystems
# round mtime to whole seconds — the size guard catches a write of equal-length
# bytes within the same second). On cache hit, a full-content comparison catches
# any in-place rewrite that inode+mtime+size missed (Greptile P1, PR#5803
# discussion_r3548477915). Reading and comparing the full file content (~1-10KB)
# is much cheaper than yaml.safe_load(). Reads are guarded by a single Lock to
# keep the hot path simple; the underlying yaml.safe_load is the slow step, not
# the lock, so contention is bounded.
_PROFILE_CONFIG_CACHE: "dict[tuple, tuple[float, str, dict]]" = {}
_PROFILE_CONFIG_CACHE_TTL_SECONDS = 60.0
_PROFILE_CONFIG_CACHE_LOCK = threading.Lock()


def _read_profile_config_cached(profile_name: str, cfg_path: str) -> dict | None:
    """Return parsed profile config, caching by (inode, mtime, size) with
    TTL backstop and full-content verification.

    The full-content comparison reads the current file and compares it to a
    copy stored in the cache entry. This catches any in-place rewrite where
    inode+mtime+size are identical, regardless of where in the file the change
    occurs — unlike a fixed-length prefix comparison, edits to fields after the
    first N characters are always detected. Reading and comparing the full file
    content (~1-10KB for a typical config.yaml) is much cheaper than
    yaml.safe_load().

    NOTE: The cache key uses inode+mtime+size to handle the common cases
    (atomic-rename editors -> new inode; in-place editors -> mtime/size
    change). The full-content comparison is a backstop for the rare case where
    all three collide (e.g., sed -i on a filesystem with coarse mtime
    resolution, writing the same byte count).
    """
    try:
        st = os.stat(cfg_path)
    except OSError:
        return None
    mtime = float(getattr(st, "st_mtime", 0.0) or 0.0)
    size = int(getattr(st, "st_size", 0) or 0)
    inode = int(getattr(st, "st_ino", 0) or 0)
    key = (str(profile_name or ""), inode, mtime, size)
    now = time.monotonic()
    with _PROFILE_CONFIG_CACHE_LOCK:
        cached = _PROFILE_CONFIG_CACHE.get(key)
        if cached is not None:
            cached_at, cached_content, cached_dict = cached
            if (now - cached_at) <= _PROFILE_CONFIG_CACHE_TTL_SECONDS:
                # Full content comparison catches any in-place rewrite where
                # inode+mtime+size are identical but the file content changed.
                # Reading and comparing the full file (~1-10KB) is cheaper than
                # yaml.safe_load(). Unlike a fixed-length prefix, this detects
                # edits anywhere in the file. Greptile P1 (PR#5803).
                _current_content = None
                try:
                    with open(cfg_path, "r", encoding="utf-8") as _f:
                        _current_content = _f.read()
                except Exception:
                    pass
                if _current_content == cached_content:
                    return cached_dict
                # Content changed while key collided — fall through to re-parse
    import yaml
    try:
        with open(cfg_path, encoding="utf-8") as _f:
            content = _f.read()
            parsed = yaml.safe_load(content) or {}
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    with _PROFILE_CONFIG_CACHE_LOCK:
        _PROFILE_CONFIG_CACHE[key] = (now, content, parsed)
        # Cap the cache at 32 entries; profiles are bounded in practice
        # and unbounded growth would be a leak.
        if len(_PROFILE_CONFIG_CACHE) > 32:
            # Drop the oldest entry by insertion order (dict is ordered).
            for old_key in list(_PROFILE_CONFIG_CACHE.keys())[:max(0, len(_PROFILE_CONFIG_CACHE) - 32)]:
                _PROFILE_CONFIG_CACHE.pop(old_key, None)
    return parsed




def _ordered_custom_provider_model_ids(entry: dict) -> list[str]:
    """Model ids from a custom_providers entry (default model + dict/list models)."""
    ordered: list[str] = []
    _cp_model = str(entry.get("model") or "").strip()
    if _cp_model:
        ordered.append(_cp_model)
    _cp_models = entry.get("models")
    if isinstance(_cp_models, dict):
        for _key in _cp_models.keys():
            if isinstance(_key, str):
                _kid = _key.strip()
                if _kid and _kid not in ordered:
                    ordered.append(_kid)
    elif isinstance(_cp_models, list):
        for _item in _cp_models:
            if isinstance(_item, str):
                _mid = _item.strip()
                if _mid and _mid not in ordered:
                    ordered.append(_mid)
            elif isinstance(_item, dict):
                _mid = str(
                    _item.get("id") or _item.get("model") or _item.get("name") or ""
                ).strip()
                if _mid and _mid not in ordered:
                    ordered.append(_mid)
    return ordered


def _repair_bare_custom_provider_model(
    bare_model: str,
    provider: str | None,
    *,
    config_obj: dict | None = None,
) -> str | None:
    """Re-qualify a bare model ID using the named custom provider's config (#5314).

    Returns the fully namespaced model id when ``bare_model`` matches the suffix
    of a registered id on ``custom_providers``; otherwise None. Model ids are
    scanned in config declaration order (default ``model`` first, then
    ``models`` dict keys or list entries) so repair is deterministic when
    suffixes collide.

    When ``config_obj`` is set (typically the session profile's config.yaml),
    only that object's ``custom_providers`` are scanned. Otherwise uses
    ``get_config()`` for the active global config (not the raw ``cfg`` alias).
    """
    try:
        model = str(bare_model or "").strip()
        prov = _clean_session_model_provider(provider)
        if not model or "/" in model or not prov:
            return None
        if prov != "custom" and not str(prov).startswith("custom:"):
            return None
        from api.config import (
            _custom_provider_entries,
            _custom_provider_slug_from_name,
            get_config,
        )

        if isinstance(config_obj, dict):
            _entries = _custom_provider_entries(config_obj)
        else:
            _cfg = get_config()
            _entries = _custom_provider_entries(
                _cfg if isinstance(_cfg, dict) else None
            )
        prov_norm = str(prov).strip().lower()
        raw_suffix = prov_norm.removeprefix("custom:")
        _matching_cp = None
        for _entry in _entries:
            entry_name = str(_entry.get("name") or "").strip().lower()
            slug = _custom_provider_slug_from_name(_entry.get("name"))
            if not slug:
                continue
            if (
                prov_norm in {entry_name, slug}
                or raw_suffix == slug.removeprefix("custom:")
            ):
                _matching_cp = _entry
                break
        if not _matching_cp:
            return None
        for _id in _ordered_custom_provider_model_ids(_matching_cp):
            if "/" in _id and _id.rsplit("/", 1)[-1] == model:
                return _id
        return None
    except Exception:
        return None


def _moa_fast_path_model_state(model: str) -> tuple[str, str, bool]:
    """Strip an optional ``@moa:``/``moa/`` prefix from an MoA-routed model.

    Split out of ``_resolve_compatible_session_model_state`` so the MoA
    fast-path stays a single-line call in that function body (see
    ``test_issue1855_resolve_model_provider_fast_path.py``, the fast-path/
    catalog-call ordering check scans a bounded window of that function's
    source, and inlining this here previously pushed the catalog call just
    past that window).
    """
    if model.startswith("@moa:"):
        return model.split(":", 1)[1].strip(), "moa", True
    if model.lower().startswith("moa/"):
        return model.split("/", 1)[1].strip(), "moa", True
    return model, "moa", False


def _resolve_compatible_session_model_state(
    model_id: str | None,
    model_provider: str | None = None,
    *,
    profile_provider: str | None = None,
    profile_default_model: str | None = None,
    profile_config: dict | None = None,
    explicit_model_pick: bool = False,
    prefer_cached_catalog: bool = False,
) -> tuple[str, str | None, bool]:
    """Return (effective_model, effective_provider, model_was_normalized).

    Sessions can outlive provider changes. When an older session still points at
    a different provider namespace (for example `gemini/...` after switching the
    agent to OpenAI Codex), reusing that stale model causes chat startup to hit
    the wrong backend and fail. Normalize only obvious cross-provider mismatches.
    When a model has an explicit provider context, keep the model string itself
    in its picker/API shape and carry the provider as separate state.

    Fast path (#1855): when the caller supplies both a model and an explicit
    ``model_provider`` AND the model is not itself ``@provider:model``-qualified,
    we can return the inputs verbatim without calling ``get_available_models()``.
    The slow path below would arrive at the same answer via
    ``if requested_provider and not explicit_provider: return model, requested_provider, False``
    after paying the full catalog-build cost. Avoiding the catalog here keeps
    ``POST /api/chat/start`` snappy even when the model catalog is cold and the
    rebuild has to make network calls (custom OpenAI-compat endpoints,
    OpenRouter ``/models``, LM Studio ``/models``, credential pool refresh),
    those used to wedge the handler for >100s and trigger 502s on default-60s
    reverse proxies, even though the WebUI itself eventually responded.

    ``prefer_cached_catalog=True`` (ours-original) makes the catalog lookup
    non-blocking: it resolves from the warm/disk cache or a network-free
    minimal catalog and NEVER triggers a live per-provider rebuild (the
    Copilot token-exchange HTTPS call that hangs a server-initiated wakeup
    turn, see rebase report §1/§3/model-resolve-hang). Human-initiated
    chat/start leaves this False to keep full live discovery; a session that
    already has a persisted model still resolves correctly because the
    persisted model wins over the catalog and the catalog is only consulted
    for the default-model backstop.
    """
    model = str(model_id or "").strip()
    requested_provider = _clean_session_model_provider(model_provider)
    if model and requested_provider == "moa":
        return _moa_fast_path_model_state(model)
    if model and requested_provider and model.startswith(f"@{requested_provider}:"):
        try:
            from api.config import cfg as _active_cfg

            providers_cfg = _active_cfg.get("providers") if isinstance(_active_cfg, dict) else {}
        except Exception:
            providers_cfg = {}
        if isinstance(providers_cfg, dict) and requested_provider in providers_cfg:
            return model, requested_provider, False
    if model and requested_provider:
        # Only safe when the model itself does not carry an ``@provider:model``
        # qualifier — qualified strings require the catalog to decide whether
        # the qualifier matches the active provider (see slow path below).
        bare_model, explicit_provider = _split_provider_qualified_model(model)
        model_prefix = model.split("/", 1)[0].strip().lower() if "/" in model else ""
        stale_codex_openai_slash_id = (
            requested_provider == "openai-codex"
            and model_prefix == "openai"
        )
        if not explicit_provider and not stale_codex_openai_slash_id:
            _profile_default = str(profile_default_model or "").strip()
            _profile_prov = _clean_session_model_provider(profile_provider)
            _providers_match_for_repair = (
                _profile_prov is None or _profile_prov == requested_provider
            )
            if (
                _profile_default
                and "/" in _profile_default
                and "/" not in model
                and _profile_default.rsplit("/", 1)[-1] == model
                and _providers_match_for_repair
                and (
                    requested_provider == "custom"
                    or str(requested_provider).startswith("custom:")
                )
            ):
                return _profile_default, requested_provider, True

            _repaired_model = _repair_bare_custom_provider_model(
                model,
                requested_provider,
                config_obj=profile_config,
            )
            if _repaired_model:
                return _repaired_model, requested_provider, True

            return model, requested_provider, False

    # Default (human chat/start) path calls get_available_models() with NO
    # kwargs so it stays signature-compatible with the many tests that stub
    # get_available_models as a zero-arg callable. Only the server-side wakeup
    # path (prefer_cached_catalog=True) opts into the cache-only mode. Some
    # tests monkeypatch get_available_models as a zero-arg callable, so probe
    # the (possibly monkeypatched) signature for ``prefer_cache`` rather than
    # catching TypeError — a blanket ``except TypeError`` would also swallow a
    # genuine TypeError raised *inside* get_available_models(prefer_cache=True)
    # and silently fall back to the slow live provider rebuild that
    # prefer_cached_catalog=True is meant to avoid.
    if prefer_cached_catalog:
        import inspect as _inspect

        try:
            _gam_accepts_prefer_cache = (
                "prefer_cache" in _inspect.signature(get_available_models).parameters
            )
        except (TypeError, ValueError):
            # Builtins / C-callables can refuse introspection; assume the
            # zero-arg stub shape in that case.
            _gam_accepts_prefer_cache = False
        if _gam_accepts_prefer_cache:
            catalog = get_available_models(prefer_cache=True)
        else:
            catalog = get_available_models()
    else:
        catalog = get_available_models()
    default_model = str(catalog.get("default_model") or DEFAULT_MODEL or "").strip()

    # Profile-aware resolution: when the caller supplies profile context
    # (not an explicit per-chat override), use the profile's provider and
    # default model as the resolution context instead of the catalog's
    # active_provider / default_model. This preserves the repair path
    # (stale models still get normalized) but normalizes to the profile's
    # default model under the profile's provider rather than the global default.
    bare_model, explicit_provider = _split_provider_qualified_model(model) if model else ("", None)
    if profile_provider and not explicit_provider:
        _profile_provider_normalized = _normalize_provider_id(profile_provider)
        _profile_default = str(profile_default_model or "").strip()
        if not model:
            _fallback = _profile_default or default_model
            return _fallback, profile_provider, bool(_fallback)

        model_prefix = model.split("/", 1)[0].strip().lower() if "/" in model else ""
        model_provider_from_name = _normalize_provider_id(model_prefix) if "/" in model else ""

        model_family = ""
        if "/" not in model:
            model_lower = model.lower()
            for bare_prefix in ("gpt", "claude", "gemini"):
                if model_lower.startswith(bare_prefix):
                    model_family = _normalize_provider_id(bare_prefix)
                    break

        if model_family and model_family != _profile_provider_normalized:
            if explicit_model_pick:
                # User explicitly chose a cross-family model; honor it (#3737)
                return model, profile_provider, False
            _target = _profile_default or default_model
            return _target, profile_provider, True

        if (
            "/" in model
            and str(profile_provider).strip().lower() == "openai-codex"
            and model_provider_from_name == "openai"
        ):
            _target = _profile_default or default_model
            return _target, profile_provider, True

        # Slash-qualified models (e.g. openai/gpt-5.4-mini) are native IDs on
        # OpenRouter and custom providers, not cross-provider artifacts. Only
        # repair when the profile provider actually requires a different family.
        if "/" in model and _profile_provider_normalized in {"openrouter", "custom", ""}:
            return model, profile_provider, False

        if "/" in model and model_provider_from_name and model_provider_from_name != _profile_provider_normalized:
            _target = _profile_default or default_model
            return _target, profile_provider, True

        # Async server-side continuations (for example delegate_task completion
        # re-entry) can arrive here with profile context but without a usable
        # requested_provider, bypassing the fast-path custom-provider repair
        # above. If the profile's configured custom-provider default is a
        # slash-qualified model whose suffix matches the bare session model,
        # repair back to the profile default before the provider call (#5225).
        if (
            "/" not in model
            and _profile_default
            and "/" in _profile_default
            and _profile_default.rsplit("/", 1)[-1] == model
            and (
                _profile_provider_normalized == "custom"
                or str(profile_provider).startswith("custom:")
            )
        ):
            return _profile_default, profile_provider, True

        _repaired_model = _repair_bare_custom_provider_model(
            model,
            profile_provider,
            config_obj=profile_config,
        )
        if _repaired_model:
            return _repaired_model, profile_provider, True

        return model, profile_provider, False

    if not model:
        return default_model, requested_provider, bool(default_model)

    active_provider = _normalize_provider_id(catalog.get("active_provider"))
    # Also keep the raw active_provider slug for cross-provider detection with
    # non-listed providers (ollama-cloud, deepseek, xai, etc.) that _normalize_provider_id
    # returns "" for. If the raw provider is set but normalization returned "", we still
    # want to detect that a session model from a known provider (e.g. openai/gpt-5.4-mini)
    # is stale relative to this unknown active provider. (#1023)
    raw_active_provider = str(catalog.get("active_provider") or "").strip().lower()
    if not active_provider and not raw_active_provider:
        bare_model, explicit_provider = _split_provider_qualified_model(model)
        return model, explicit_provider or requested_provider, False

    bare_for_context, explicit_provider = _split_provider_qualified_model(model)
    if requested_provider and not explicit_provider:
        model_prefix = model.split("/", 1)[0].strip().lower() if "/" in model else ""
        stale_codex_openai_slash_id = (
            raw_active_provider == "openai-codex"
            and requested_provider == "openai-codex"
            and model_prefix == "openai"
        )
        if not stale_codex_openai_slash_id:
            return model, requested_provider, False

    if model.startswith("@") and ":" in model:
        provider_raw = explicit_provider or ""
        provider_normalized = _normalize_provider_id(provider_raw)
        bare_model = bare_for_context.strip()
        if not provider_raw or not bare_model:
            return model, requested_provider, False

        # A fresh, explicit user pick is by definition not a stale artifact, so
        # honor the @provider:model exactly as chosen — never reroute it via the
        # active-provider family repair or the cold-catalog fallback below (a bare
        # id like "gpt-oss-120b" under an OpenAI-active agent would otherwise get
        # pulled to OpenAI by the family-match branch). If the named provider is
        # unreachable the user sees a clear run-time error rather than a silent
        # model swap. Must sit above the family-match repair (#3737 principle).
        if explicit_model_pick:
            return model, provider_raw, False

        raw_provider_ids, normalized_provider_ids = _catalog_provider_id_sets(catalog)
        hint_matches_active = (
            provider_raw == raw_active_provider
            or provider_raw == active_provider
            or (provider_normalized and provider_normalized == active_provider)
        )
        if hint_matches_active:
            # The @provider:model hint explicitly names the active provider, so this
            # selection is intentional — not a stale cross-provider artifact. Return
            # the full @provider:model string unchanged so downstream (resolve_model_provider
            # in config.py) can route through the correct provider. Stripping the prefix
            # here would collapse duplicate model IDs from different providers back to the
            # bare ID, causing the first matching provider to win on the next UI render
            # and the wrong provider to be used for the agent run. (#1253)
            return model, provider_raw, False

        if _catalog_has_provider(
            provider_raw,
            provider_normalized,
            raw_provider_ids,
            normalized_provider_ids,
        ):
            return model, provider_raw, False

        if _model_matches_active_provider_family(bare_model, active_provider):
            provider_context = (
                raw_active_provider
                if _should_attach_codex_provider_context(bare_model, raw_active_provider, catalog)
                else None
            )
            return bare_model, provider_context, True
        # On NON-explicit resolves (2nd+ turn, chat switch — explicit picks already
        # returned above), preserve the selection only when all three hold:
        #
        #   * provider_normalized == "" — a non-first-party provider hint
        #     (ollama-cloud / deepseek / xai / a named custom proxy). First-party
        #     families fall through to the stale-cross-provider repair below.
        #
        #   * the BARE model is not a first-party family id (does not start with
        #     gpt/claude/gemini), i.e. not a misrouted first-party model that a
        #     vanished provider used to host (e.g. "@copilot:claude-opus-4.6").
        #
        #   * the provider is KNOWN or CONFIGURED. This is the load-bearing
        #     distinction: catalog-absence has two causes —
        #       (a) a cold live-discovery provider (ollama-cloud is configured; its
        #           group just isn't in this cached snapshot yet) → preserve, and
        #       (b) a genuinely removed/unknown provider ("@removed:mistral-large"
        #           configured nowhere) → fall through to the default so chat/start
        #           doesn't route to an unreachable provider.
        #     _provider_is_known_or_configured() decides this from the static
        #     provider registry + config state, NOT from the cold catalog snapshot
        #     (re-deriving that live would defeat the prefer_cached_catalog win).
        #
        # DELIBERATE: the registry test treats a KNOWN built-in (deepseek, minimax,
        # ollama-cloud, …) as preservable even when the user has no key configured
        # for it. We accept this on purpose. The only fully-reliable "is this
        # provider authenticated" signal is the live auth store / catalog rebuild —
        # exactly the cost this hot path avoids — and a cheap config/env-only check
        # would mis-classify providers configured via OAuth/auth-store (ollama-cloud
        # among them), re-introducing the original silent-revert bug for them. So a
        # known-but-unconfigured pick is kept; the user gets a clear run-time auth
        # error instead of a silent swap to the default. Pinned by
        # test_at_provider_known_unconfigured_builtin_is_intentionally_preserved.
        #
        # KNOWN LIMITATION: the first-party-family test is a bare-name prefix match
        # (the same approximation _model_matches_active_provider_family uses). A
        # genuine third-party model whose name merely *starts* with gpt/claude/
        # gemini (e.g. "@ollama:gpt4all-mini") is therefore still mis-classified as
        # first-party and reverted on non-explicit paths. A name-based check cannot
        # disambiguate that; the behavior is pinned by
        # test_at_provider_first_party_named_third_party_model_known_limitation.
        _bare_is_first_party_family = any(
            bare_model.lower().startswith(_p) for _p in ("gpt", "claude", "gemini")
        )
        if (
            not provider_normalized
            and not _bare_is_first_party_family
            and _provider_is_known_or_configured(provider_raw)
        ):
            return model, provider_raw, False
        if default_model:
            provider_context = (
                raw_active_provider
                if _should_attach_codex_provider_context(default_model, raw_active_provider, catalog)
                else None
            )
            return default_model, provider_context, True
        return model, provider_raw, False

    slash = model.find("/")
    if slash < 0:
        if explicit_model_pick:
            # User explicitly chose this model; don't second-guess (#3737)
            return model, requested_provider, False
        model_lower = model.lower()
        for bare_prefix in ("gpt", "claude", "gemini"):
            if model_lower.startswith(bare_prefix):
                model_provider = _normalize_provider_id(bare_prefix)
                if model_provider and model_provider != active_provider and default_model:
                    provider_context = (
                        raw_active_provider
                        if _should_attach_codex_provider_context(default_model, raw_active_provider, catalog)
                        else None
                    )
                    return default_model, provider_context, True
                provider_context = (
                    raw_active_provider
                    if _should_attach_codex_provider_context(model, raw_active_provider, catalog)
                    else requested_provider
                )
                return model, provider_context, False
        return model, requested_provider, False

    model_provider = _normalize_provider_id(model[:slash])

    # For custom/openrouter active providers: only skip normalization when the
    # model's namespace prefix is actually routable by a group in the catalog.
    # A user who only has custom_providers configured (active_provider="custom")
    # with a stale session model like "openai/gpt-5.4-mini" would otherwise
    # never get cleaned up, causing "(unavailable)" to appear in the picker.
    if active_provider in {"custom", "openrouter"}:
        # These namespaces are always routable as-is — preserve them.
        if model_provider in {"", "custom", "openrouter"}:
            return model, requested_provider, False
        # Check if any catalog group can actually route this model's prefix.
        groups = catalog.get("groups") or []
        routable_provider_ids = {
            _normalize_provider_id(g.get("provider_id") or "") for g in groups
        }
        # openrouter group can route any provider/model namespace
        has_openrouter_group = any(
            (g.get("provider_id") or "") == "openrouter" for g in groups
        )
        if model_provider in routable_provider_ids or has_openrouter_group:
            return model, requested_provider, False
        # Model prefix is not routable — stale cross-provider reference, clear it.
        if default_model:
            return default_model, requested_provider, True
        return model, requested_provider, False

    # Skip normalization for models on custom/openrouter namespaces — these are
    # user-controlled and should never be silently replaced.
    #
    # OpenAI Codex is intentionally normalized to the OpenAI family above so bare
    # GPT IDs survive provider switches. Slash-qualified OpenAI IDs are different:
    # ``openai/gpt-...`` is the OpenRouter shape for OpenAI models, and
    # resolve_model_provider() routes that through OpenRouter when Codex is the
    # configured provider. Legacy sessions can carry that stale slash ID without
    # a saved model_provider, so repair it to the active Codex default unless the
    # session/request explicitly says it is an OpenRouter selection. (#1734)
    if (
        raw_active_provider == "openai-codex"
        and model_provider == "openai"
        and requested_provider in {None, "openai-codex"}
        and default_model
    ):
        # Persist provider_context = "openai-codex" unconditionally on this
        # repair path so the resolved shape is stable across resolutions
        # (Opus stage-303 SHOULD-FIX: avoid redundant repair-writes per
        # chat-start when the catalog-coverage check fails — e.g. if a
        # future Codex default is itself slash-prefixed). Once we've
        # decided the session belongs to Codex, persist that decision.
        return default_model, raw_active_provider, True

    # Also normalize when the model is from a known provider but the active provider
    # is an unlisted one (e.g. ollama-cloud) — active_provider is "" in that case
    # but raw_active_provider is set. If model_provider doesn't start with the raw
    # active provider name, the session model is stale. (#1023)
    _active_for_compare = active_provider or raw_active_provider
    if model_provider and model_provider not in {"", "custom", "openrouter"} and model_provider != _active_for_compare and default_model:
        return default_model, requested_provider, True
    return model, requested_provider, False









def _resolve_context_length_for_session_model(
    model: str | None,
    provider: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> int:
    """Best-effort current context window for a session model.

    Persisted session context metadata is a snapshot from a prior model call.
    During session hydration/model switching, the current model metadata should
    be allowed to replace that stale snapshot.
    """
    model_for_lookup = str(model or "").strip()
    if not model_for_lookup:
        return 0
    try:
        from agent.model_metadata import get_model_context_length as _get_cl
        from api.config import get_config as _get_config_for_cl

        _cfg_for_cl = _get_config_for_cl()
        _ctx_lookup = _context_length_lookup_inputs_for_model(
            model_for_lookup,
            provider,
            base_url=base_url,
            api_key=api_key,
            cfg=_cfg_for_cl if isinstance(_cfg_for_cl, dict) else {},
        )
        try:
            return _get_cl(
                model_for_lookup,
                _ctx_lookup.base_url,
                api_key=_ctx_lookup.api_key,
                config_context_length=_ctx_lookup.config_context_length,
                provider=_ctx_lookup.provider or provider or "",
                custom_providers=_ctx_lookup.custom_providers,
            ) or 0
        except TypeError:
            # Older hermes-agent builds: legacy 2-arg form.
            return _get_cl(model_for_lookup, _ctx_lookup.base_url) or 0
    except Exception:
        return 0






def _should_accept_session_context_length_refresh(
    persisted: int,
    resolved: int,
    *,
    model_changed: bool = False,
) -> bool:
    if not resolved:
        return False
    if not persisted:
        return True
    # #4248: an anonymous reload resolver can still fall through to the agent
    # metadata default fallback. Do not let that lower-confidence 256k value
    # clobber a larger context window persisted by the streaming path. If the
    # effective model changed, though, a 256k result may be the real new model
    # window and should replace the old snapshot.
    return model_changed or not (resolved == 256_000 and persisted > resolved)








def _lookup_gateway_session_identity(session_id: str) -> dict:
    if not session_id:
        return {}
    metadata = _load_gateway_session_identity_map().get(str(session_id))
    return metadata if isinstance(metadata, dict) else {}


def _gateway_base_url() -> str:
    """The Gateway is the single store of record; this is where it lives."""
    from jaeger_ai.contract.ports import resolve_gateway_url
    return resolve_gateway_url().rstrip("/")








def _lookup_cli_session_metadata(session_id: str, *, all_profiles: bool = False) -> dict:
    if not session_id:
        return {}
    try:
        for row in get_cli_sessions(all_profiles=all_profiles):
            if row.get("session_id") == session_id:
                return row
    except Exception:
        pass
    # The normal CLI projection is capped to the 20 newest interactive rows.
    # Mutation/profile guards need an exact, uncapped ownership lookup or an
    # older CLI-only session falls through as profile-less and can be deleted
    # from the wrong profile. Probe the active profile first, then the remaining
    # configured profiles, and synthesize only the metadata those guards need.
    active_profile = _get_active_profile_name()
    profile_names = [active_profile]
    try:
        from api.profiles import list_profiles_api

        profile_names.extend(
            str(row.get("name") or "").strip()
            for row in list_profiles_api()
            if isinstance(row, dict)
        )
    except Exception:
        pass
    seen = set()
    for profile_name in profile_names:
        if not profile_name or profile_name in seen:
            continue
        seen.add(profile_name)
        try:
            if session_id in agent_session_rows_existing(
                [session_id], profile=profile_name
            ):
                return {
                    "session_id": session_id,
                    "profile": profile_name,
                    "source_tag": "cli",
                    "raw_source": "cli",
                }
        except Exception:
            continue
    return {}


def _session_index_marks_was_webui(sid: str) -> bool:
    """Return True iff ``sid`` is in the WebUI session index as a WebUI- or
    fork-origin row whose sidecar is now gone.

    The WebUI session index (``SESSION_INDEX_FILE``) is the canonical registry
    of sessions the WebUI ever owned. A row there tagged with ``webui`` or
    ``fork`` means the session once had a sidecar that has since been deleted
    (or never materialised on this profile). Returning 404 to the client on
    these ids is what lets the browser self-heal: strip the stale
    ``/session/<id>`` URL and clear localStorage instead of silently
    re-attaching to a now-empty session (#2782).

    Foreign-origin rows (CLI, TUI, Desktop, claude_code, gateway, telegram,
    etc.) — those with explicit non-webui source tags, OR blank sources with
    ``is_cli_session``/``read_only`` markers — are NOT treated as deleted
    WebUI sessions, even when the sidecar is absent.
    """
    if not SESSION_INDEX_FILE.exists():
        return False
    try:
        entries = json.loads(SESSION_INDEX_FILE.read_bytes())
    except Exception:
        return False
    for entry in entries if isinstance(entries, list) else []:
        if entry.get("session_id") != sid:
            continue
        # Classify per source field, not on a collapsed `a or b or c` — a
        # legacy CLI/imported row can carry is_cli_session:true with BLANK
        # source fields, and collapsing-then-defaulting-to-WebUI would wrongly
        # 404 it (it should keep its read-only CLI stub).
        srcs = [
            str(entry.get("source_tag") or "").strip().lower(),
            str(entry.get("raw_source") or "").strip().lower(),
            str(entry.get("session_source") or "").strip().lower(),
        ]
        explicit = [s for s in srcs if s]
        if any(s in ("webui", "fork") for s in explicit):
            # Explicit WebUI-origin (incl. forks, which /api/session/branch
            # stamps session_source="fork") — a deleted sidecar bricks
            # identically. 404.
            return True
        if explicit:
            # Explicit non-WebUI source (cli, telegram, claude_code, ...) —
            # genuine foreign session, keep the existing CLI/read-only stub.
            return False
        # All source fields blank: WebUI-origin UNLESS the row is a legacy
        # CLI/imported session marked only by is_cli_session / read_only.
        is_cli = entry.get("is_cli_session") is True
        is_read_only = bool(entry.get("read_only") or entry.get("is_read_only"))
        return not (is_cli or is_read_only)
    return False


def _session_deleted_tombstone_marks_was_webui(sid: str) -> bool:
    try:
        return sid in _load_webui_deleted_session_tombstone()
    except Exception:
        return False


def _state_db_session_source(sid: str) -> str:
    """Return the lowercased ``sessions.source`` for ``sid`` from state.db.

    Cheap single-row lookup used to distinguish delegated ``subagent`` children
    (which have a recoverable state.db transcript) from genuinely-deleted WebUI
    sessions.  Returns "" on any error / missing row so callers fall back to
    their existing behaviour.
    """
    if not sid or not is_safe_session_id(sid):
        return ""
    try:
        from api.models import _active_state_db_path
        db_path = _active_state_db_path()
        if not db_path or not Path(db_path).exists():
            return ""
        import sqlite3 as _sqlite
        with closing(_sqlite.connect(str(db_path))) as _conn:
            row = _conn.execute(
                "SELECT source FROM sessions WHERE id = ?", (sid,)
            ).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    return str(row[0] or "").strip().lower()


def _is_subagent_child_session_id(sid: str) -> bool:
    """Return True when ``sid`` is a delegated subagent child in state.db.

    Delegated ``delegate_task`` children are recorded in Hermes state.db with
    ``source='subagent'`` and a ``parent_session_id``. They frequently have no
    WebUI sidecar (they ran server-side), so opening one from the sidebar must
    recover the transcript from state.db rather than 404 as a deleted WebUI
    session (#5307).
    """
    return _state_db_session_source(sid) == "subagent"




def _is_claimable_cli_source(cli_meta: dict, state_db_source: str = "") -> tuple[bool, str]:
    """Decide whether a foreign-origin session is safe to claim writeable
    in WebUI. Returns ``(claimable, reason_if_not)``.

    Policy mirrors ``/api/session/import_cli``:
    sessions explicitly marked ``read_only`` in their foreign store are
    surfaced as read-only stubs but never materialised as writable
    WebUI sidecars. We extend that with a denylist of foreign-source
    families whose ownership belongs to a non-WebUI process
    (messaging channels, external agents, Claude Code, scheduled
    cron runs, and platformless gateway fallbacks), so a WebUI POST
    cannot accidentally turn them into writable sidecars and violate
    their ownership boundary (#4911 review + the residual
    gateway/unknown gap flagged in the follow-up + the cron-claim
    policy flagged in the Greptile 4/5 review).

    The check is denylist-based: if a source is in any of the
    refused families below, it is non-claimable. Everything else
    (CLI, TUI, Desktop, plus future local agent sources) is allowed.
    TUI/Desktop sessions whose cli_meta is empty (they don't appear
    in ``get_cli_sessions()`` due to the CLI cap) fall through to
    ``state_db_source``; state.db has a ``source`` column with values
    like ``tui``, ``desktop``, ``cli``, ``cron``, ``claude_code``,
    ``messaging``, ``external_agent``, ``gateway`` (platform-tagged
    gateways land in ``_MESSAGING_RAW_SOURCES`` and are caught by
    the messaging check above; bare ``"gateway"`` / ``"unknown"``
    literals are caught here).
    """
    cm = cli_meta or {}
    if bool(cm.get("read_only")):
        return False, "explicit_readonly"
    session_source = (cm.get("session_source") or "").strip().lower()
    if session_source in {"messaging", "external_agent"}:
        return False, f"session_source={session_source}"
    # Track cli_meta-sourced and state.db-sourced source_tag values
    # separately so the diagnostic reason string never mislabels a
    # cli_meta-sourced denial as a state.db-sourced one (Greptile P2,
    # #4911 follow-up).  The reason is currently discarded by the
    # caller, but it is exported in the return tuple and may surface
    # in a future log / user-visible diagnostic.
    cli_meta_source_tag = (cm.get("source_tag") or cm.get("raw_source") or "").strip().lower()
    if cli_meta_source_tag in {"claude_code", "cron", "external_agent",
                                "gateway", "messaging", "subagent", "unknown"}:
        # gateway/unknown are the platformless gateway fallbacks
        # (gateway/run.py, gateway/slash_commands.py) — they own the
        # conversation in the gateway, not in WebUI.
        # cron sessions are scheduled and owned by the cron runner
        # process; claiming them into a writable WebUI sidecar would
        # let a stray POST break the next scheduled run.
        # messaging / external_agent can be supplied by the foreign
        # store directly in source_tag (in addition to the
        # session_source / messaging-record checks above), and they
        # need the same provenance-correct refusal.
        return False, f"cli_meta_source={cli_meta_source_tag}"
    if _is_messaging_session_record(cm):
        return False, "messaging_record"
    # Empty cli_meta is the common case for TUI/Desktop; fall through
    # to state.db's source column.  Refuse known-foreign state.db sources.
    if not cli_meta_source_tag and state_db_source:
        state_db_source_tag = state_db_source.strip().lower()
        if state_db_source_tag in {"claude_code", "cron", "messaging",
                                    "external_agent", "gateway", "subagent", "unknown"}:
            return False, f"state_db_source={state_db_source_tag}"
    return True, ""


def _claim_or_synthesize_cli_session(sid: str, cli_meta: dict = None):
    """Resolve a session_id that has no WebUI sidecar.

    Returns ``(session_or_None, reason)``. Reasons:

      ``'materialized'``
        A state.db row with messages exists AND the foreign source is
        claimable per :func:`_is_claimable_cli_source` (CLI / TUI /
        Desktop, no explicit read_only, not a messaging / claude_code
        session). ``session`` is a fully populated
        :class:`api.models.Session` ready for writeable use; the caller
        MUST call ``session.save()`` to persist a WebUI-owned sidecar
        before the first write.  The Session carries the source-tag
        metadata from the CLI/state.db lookup (``is_cli_session=True``,
        ``read_only=False``) so the sidebar still renders the original
        source badge.

      ``'not_claimable'``
        The sid has recoverable state.db messages but the foreign
        source is owned by a non-WebUI process (messaging channel,
        claude_code, external_agent, or explicit read_only). ``session``
        is still returned, but with ``read_only=True`` preserved and
        the foreign source tag intact, so the GET stub continues to
        render the original badge and the read-only banner. The POST
        path must return 403 (not 404) so the user sees a clear
        refusal instead of the empty-state self-heal that the 404
        handler triggers (#4911 review).

      ``'was_webui'``
        The sid is in the WebUI session index as a webui/fork origin row but
        its sidecar is gone.  Callers MUST return 404 so the browser clears
        its stale ``/session/<id>`` URL and localStorage instead of silently
        re-attaching to a now-empty session (#2782).

      ``'no_foreign_state'``
        The sid has no WebUI sidecar AND no recoverable messages in
        state.db.  Callers MUST return 404.

      ``'invalid_sid'``
        ``sid`` failed :func:`is_safe_session_id`.  Callers MUST return 404.

    ``cli_meta`` is an optional pass-through.  Callers that already
    computed ``_lookup_cli_session_metadata(sid)`` (e.g. the GET path
    building a sidebar dict) can pass it in to avoid the redundant
    lookup; callers without it (POST path, tests) pass nothing and the
    helper does the lookup itself.

    Closing the GET-vs-POST asymmetry for foreign-origin sessions: GET
    ``/api/session`` and POST ``/api/chat/start`` both call this helper
    on a missing-sidecar KeyError, so a TUI/Desktop/CLI session can be
    loaded read-only AND continued writeable from the WebUI.
    """
    def build_workspace(sid, cli_meta):
        """Coalesce workspace with sane fallbacks so _start_run doesn't
        trip on a missing field. state.db's cwd is the canonical workspace for
        agent sessions; CLI metadata is the fallback (handles Telegram/etc).
        """
        workspace = (cli_meta or {}).get("workspace") or (cli_meta or {}).get("cwd")
        if not workspace:
            try:
                from api.workspace import get_last_workspace
                workspace = get_last_workspace()
            except Exception:
                workspace = None
        if not workspace:
            try:
                from api.models import DEFAULT_WORKSPACE
                workspace = DEFAULT_WORKSPACE
            except Exception:
                workspace = "/"
        return workspace

    def build_session(sid, cli_meta, msgs, read_only_flag, is_cli_flag=True):
        return Session(
            session_id=sid,
            title=(cli_meta or {}).get("title") or "CLI Session",
            workspace=build_workspace(sid, cli_meta),
            model=(cli_meta or {}).get("model") or "unknown",
            model_provider=(cli_meta or {}).get("model_provider"),
            messages=msgs,
            created_at=(cli_meta or {}).get("created_at") or 0,
            updated_at=(cli_meta or {}).get("updated_at") or 0,
            profile=(cli_meta or {}).get("profile"),
            # ``is_cli_flag`` is True for genuine CLI/TUI/Desktop sessions so the
            # sidebar renders the source badge and the client's external-session
            # gating applies. It is False for delegated subagent children (#5307):
            # they are recovered read-only and must NOT be CLI-classified, or they
            # would pass the frontend ``_isExternalSession`` poll-skip /
            # active-refresh gates that #3603 keeps narrow.
            is_cli_session=is_cli_flag,
            source_tag=(cli_meta or {}).get("source_tag"),
            raw_source=(cli_meta or {}).get("raw_source"),
            session_source=(cli_meta or {}).get("session_source"),
            source_label=(cli_meta or {}).get("source_label"),
            # ``read_only_flag`` is True for not_claimable sources (foreign
            # store marked them read-only / messaging / claude_code) and
            # False for genuine CLI / TUI / Desktop sessions.  Only the
            # POST claim path with a verified-claimable source can
            # actually write; the GET stub always reflects whatever the
            # helper returns so the read-only banner stays accurate.
            read_only=read_only_flag,
        )

    if not is_safe_session_id(sid):
        return None, "invalid_sid"
    if (
        (
            _session_index_marks_was_webui(sid)
            or (
                _session_deleted_tombstone_marks_was_webui(sid)
                and _state_db_session_source(sid) in ("", "webui", "fork")
            )
        )
        and not _is_subagent_child_session_id(sid)
    ):
        # A delegated subagent child (source='subagent' in state.db) can be
        # registered in the WebUI index as a webui/fork/blank-source row (it
        # shares the parent's lineage) yet have no WebUI sidecar of its own.
        # Those must recover their transcript from state.db below rather than
        # 404 as a genuinely-deleted WebUI session (#5307). Every other
        # index-marked-WebUI id keeps the #2782 self-heal 404 contract.
        #
        # The durable delete tombstone only 404s a row that is WebUI-owned
        # (source webui/fork, or blank = a stale URL with no surviving row).
        # A foreign-source row (messaging/cli/tui/desktop) that happens to
        # carry a tombstone — e.g. a WebUI delete of an imported session whose
        # state.db row the external writer later re-created — must still
        # materialize its transcript, never be self-healed to a 404 (#5504).
        return None, "was_webui"
    if cli_meta is None:
        cli_meta = _lookup_cli_session_metadata(sid) or {}
    msgs = get_cli_session_messages(sid)
    if not msgs:
        return None, "no_foreign_state"
    # TUI/Desktop sessions often have empty cli_meta (they don't appear in
    # get_cli_sessions() because of the cap).  Fall back to the state.db
    # ``source`` column to make the claim-eligibility check robust and to
    # populate the Session's source-tag metadata so the sidebar still
    # renders the correct badge for these sessions.
    state_db_source = ""
    state_db_row = None
    try:
        from api.models import _active_state_db_path
        db_path = _active_state_db_path()
        if db_path and Path(db_path).exists():
            import sqlite3 as _sqlite
            with closing(_sqlite.connect(str(db_path))) as _conn:
                _conn.row_factory = _sqlite.Row
                _row = _conn.execute(
                    "SELECT source, title, model, cwd, started_at, ended_at "
                    "FROM sessions WHERE id = ?", (sid,)
                ).fetchone()
                if _row is not None:
                    state_db_row = dict(_row)
                    state_db_source = str(_row["source"] or "").strip().lower()
    except Exception:
        state_db_source = ""
    # Populate source metadata from state.db when cli_meta is empty so the
    # synthesized Session carries the right source_tag/source_label.  Only
    # fill fields that are actually missing from cli_meta; the foreign store
    # always wins when both are present.
    #
    # No-mutation contract (Greptile #4911 follow-up): the GET path passes
    # a pre-computed cli_meta dict and expects it to be unchanged after
    # this helper returns.  We use a single copy-on-write rebind at the
    # top of the block and then plain subscript assignment so the
    # caller's dict is never touched in place.
    if state_db_row:
        cli_meta = dict(cli_meta or {})
        if not cli_meta.get("source_tag") and state_db_source:
            cli_meta["source_tag"] = state_db_source
        if not cli_meta.get("raw_source") and state_db_source:
            cli_meta["raw_source"] = state_db_source
        if not cli_meta.get("title") and state_db_row.get("title"):
            cli_meta["title"] = state_db_row["title"]
        if not cli_meta.get("model") and state_db_row.get("model"):
            cli_meta["model"] = state_db_row["model"]
        if not cli_meta.get("workspace") and state_db_row.get("cwd"):
            cli_meta["workspace"] = state_db_row["cwd"]
        # Map state.db timestamps to created_at/updated_at on the
        # synthesized Session.  Without this, the first POST writes
        # epoch (0) timestamps into the permanent sidecar and the
        # sidebar sorts/dates the session as "Jan 1 1970" (Greptile
        # #4911 follow-up, P1).  created_at always comes from
        # started_at; Session.save() never touches created_at (it's
        # not in the metadata touch list), so the mapping is
        # load-bearing on both the GET stub and the POST claim path.
        # updated_at prefers ended_at (last activity) and falls back
        # to started_at — note that on the POST claim path
        # Session.save() defaults to touch_updated_at=True and stamps
        # updated_at to wall-clock now, so this value is only the
        # GET-stub display value; the claimed sidecar's updated_at
        # reflects the moment of claim (the desired "just now" UX).
        if not cli_meta.get("created_at") and state_db_row.get("started_at"):
            cli_meta["created_at"] = state_db_row["started_at"]
        if not cli_meta.get("updated_at"):
            _ended = state_db_row.get("ended_at")
            _started = state_db_row.get("started_at")
            if _ended or _started:
                cli_meta["updated_at"] = _ended or _started
    claimable, _reason = _is_claimable_cli_source(cli_meta, state_db_source)
    if not claimable:
        # The session is real and viewable, but the foreign source forbids
        # the WebUI from taking write ownership.  Build the Session with
        # readonly=True so the GET stub keeps rendering the original
        # read-only badge, and return 'not_claimable' so the POST path
        # 403s instead of bare-404ing.
        #
        # Delegated subagent children (#5307) additionally must NOT be
        # CLI-classified: they are recovered read-only for viewing, but
        # is_cli_session=True would let them pass the frontend
        # _isExternalSession poll-skip / active-refresh gates that #3603
        # keeps narrow. Every other non-claimable foreign source keeps the
        # CLI classification so its source badge renders.
        _sa_child = _is_subagent_child_session_id(sid)
        return (
            build_session(sid, cli_meta, msgs, read_only_flag=True,
                          is_cli_flag=not _sa_child),
            "not_claimable",
        )
    return build_session(sid, cli_meta, msgs, read_only_flag=False), "materialized"










def _messaging_session_identity(session: dict, raw_source: str) -> str:
    sid = _safe_first(session.get("session_id"))
    if sid and _is_pre_compression_continuation_row(session):
        return f"{raw_source}|session_id:{sid}"

    metadata = _lookup_gateway_session_identity(session.get("session_id"))
    session_key = _safe_first(
        metadata.get("session_key"),
        session.get("session_key"),
        session.get("gateway_session_key"),
    )
    if session_key:
        return f"{raw_source}|session_key:{session_key}"

    chat_id = _safe_first(
        metadata.get("chat_id"),
        session.get("chat_id"),
        session.get("origin_chat_id"),
    )
    thread_id = _safe_first(metadata.get("thread_id"), session.get("thread_id"))
    chat_type = _safe_first(metadata.get("chat_type"), session.get("chat_type"))
    user_id = _safe_first(
        metadata.get("user_id"),
        session.get("user_id"),
        session.get("origin_user_id"),
    )

    identity_parts = []
    if chat_type:
        identity_parts.append(f"chat_type:{chat_type}")
    if chat_id:
        identity_parts.append(f"chat_id:{chat_id}")
    if thread_id:
        identity_parts.append(f"thread_id:{thread_id}")
    if user_id:
        identity_parts.append(f"user_id:{user_id}")

    if identity_parts:
        return f"{raw_source}|" + "|".join(identity_parts)

    return raw_source


def _is_pre_compression_snapshot_id(session_id: str) -> bool:
    sid = _safe_first(session_id)
    if not sid or not all(c in "0123456789abcdefghijklmnopqrstuvwxyz_" for c in sid):
        return False
    try:
        path = SESSION_DIR / f"{sid}.json"
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("pre_compression_snapshot"))
    except Exception:
        return False


def _is_pre_compression_continuation_row(session: dict) -> bool:
    parent_sid = _safe_first(session.get("parent_session_id"))
    return bool(parent_sid and _is_pre_compression_snapshot_id(parent_sid))


def _session_messaging_raw_source(session: dict) -> str:
    raw = _safe_first(
        session.get("raw_source"),
        session.get("source_tag"),
        session.get("source"),
        session.get("platform"),
    )
    if not raw:
        raw = session.get("source_label") or "messaging"
    return _normalize_messaging_source(raw)


def _has_durable_messaging_identity(session: dict) -> bool:
    metadata = _lookup_gateway_session_identity(session.get("session_id"))
    return bool(_safe_first(
        metadata.get("session_key"),
        session.get("session_key"),
        session.get("gateway_session_key"),
        metadata.get("chat_id"),
        session.get("chat_id"),
        session.get("origin_chat_id"),
        metadata.get("thread_id"),
        session.get("thread_id"),
    ))


def _numeric_count(value) -> int:
    try:
        return int(float(_safe_first(value, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _should_hide_stale_messaging_session(
    session: dict,
    active_gateway_session_ids: set[str],
    active_gateway_sources: set[str],
) -> bool:
    """Hide stale Gateway-owned internal rows after an external chat moved on.

    Hermes Gateway keeps the external conversation identity in sessions.json.
    Compression/session-reset can leave old Agent state.db rows behind; those
    rows are implementation segments, not distinct conversations users chose.
    Only apply this aggressive hiding when Gateway is currently advertising an
    active session for the same messaging source. Without that source-of-truth
    file we keep the old fallback behavior.
    """
    raw_source = _session_messaging_raw_source(session)
    if not _is_known_messaging_source(raw_source):
        return False
    if not active_gateway_session_ids or raw_source not in active_gateway_sources:
        return False

    sid = _safe_first(session.get("session_id"))
    if sid and sid in active_gateway_session_ids:
        return False

    if _safe_first(session.get("end_reason")) in _STALE_MESSAGING_END_REASONS:
        return True

    if not _has_durable_messaging_identity(session):
        if _is_pre_compression_continuation_row(session):
            return False
        parent_sid = _safe_first(session.get("parent_session_id"))
        if parent_sid and parent_sid in active_gateway_session_ids:
            return True
        return True

    if session.get("parent_session_id") and not _is_pre_compression_continuation_row(session):
        return True

    message_count = _numeric_count(session.get("message_count"))
    actual_count = _numeric_count(session.get("actual_message_count"))
    if message_count <= 0 and actual_count <= 0:
        return True

    return False


def _is_messaging_session_record(session) -> bool:
    """Return true for sessions backed by external messaging channels."""
    if not session:
        return False
    if (
        (getattr(session, "session_source", None) if not isinstance(session, dict) else session.get("session_source")) == "messaging"
    ):
        return True
    raw = _safe_first(
        getattr(session, "raw_source", None) if not isinstance(session, dict) else session.get("raw_source"),
        getattr(session, "source_tag", None) if not isinstance(session, dict) else session.get("source_tag"),
        getattr(session, "source", None) if not isinstance(session, dict) else session.get("source"),
        session.get("source_label") if isinstance(session, dict) else None,
    )
    return _is_known_messaging_source(raw)


















# If a sidecar JSON file exceeds this threshold, the display-path tail
# optimization fires regardless of message count.  Sessions with few messages
# but large tool outputs (multi-MB JSON) should not force a full-scan merge.
_SIDECAR_BYTE_TAIL_THRESHOLD = 500_000  # 500 KB












def _display_merge_session_is_active(session) -> bool:
    """Return whether any canonical in-memory projection is active/pending."""
    if getattr(session, "active_stream_id", None) or getattr(
        session, "pending_user_message", None
    ):
        return True
    sid = str(getattr(session, "session_id", "") or "")
    if not sid:
        return True
    with LOCK:
        live = SESSIONS.get(sid)
    if live is None or live is session:
        return False
    if str(getattr(live, "session_id", "") or "") != sid:
        return True
    return bool(
        getattr(live, "active_stream_id", None)
        or getattr(live, "pending_user_message", None)
    )














def _evict_lineage_display_cache_entry(sid, expected_entry) -> None:
    """Evict only the lineage entry that this caller validated as stale."""
    with _lineage_display_cache_lock:
        if _lineage_display_cache.get(sid) is expected_entry:
            _lineage_display_cache.pop(sid, None)














def _sidecar_file_exceeds_threshold(session_id, threshold_bytes) -> bool:
    """Check if the sidecar JSON file for ``session_id`` exceeds ``threshold_bytes``."""
    from api.config import SESSION_DIR
    try:
        p = SESSION_DIR / f"{session_id}.json"
        return os.path.isfile(p) and os.path.getsize(p) > threshold_bytes
    except Exception:
        return False


def _state_db_since_timestamp_for_limited_display(session, msg_limit, msg_before=None):
    """Return (timestamp floor, sidecar messages) for bounded state.db tail reads.

    The display window limit counts visible transcript rows after WebUI sidecar
    and state.db reconciliation, so this deliberately does not SQL ``LIMIT`` raw
    rows.  Instead, for the common initial tail load, keep the full sidecar
    coordinate space and read a conservative recent state.db superset.  Older
    page loads and edit/truncation recovery shapes stay on the full state.db
    path because their correctness depends on older reconciliation rows.
    """
    if msg_limit is None or msg_before is not None:
        return None, None
    if getattr(session, "truncation_watermark", None) not in (None, ""):
        return None, None
    if getattr(session, "truncation_boundary", None) not in (None, ""):
        return None, None

    sidecar_messages = _webui_sidecar_lineage_messages_for_display(session)
    if not sidecar_messages:
        return None, sidecar_messages
    sidecar_timestamps = [_message_timestamp_as_float(msg) for msg in sidecar_messages]
    if any(ts is None for ts in sidecar_timestamps):
        return None, sidecar_messages

    try:
        limit = max(1, int(msg_limit))
    except (TypeError, ValueError):
        return None, sidecar_messages
    raw_budget = max(300, limit * 10)
    if len(sidecar_messages) <= raw_budget:
        _sid = getattr(session, "session_id", "") or ""
        if not _sid or not _sidecar_file_exceeds_threshold(_sid, _SIDECAR_BYTE_TAIL_THRESHOLD):
            return None, sidecar_messages

    floor = min(sidecar_timestamps[-raw_budget:])
    sidecar_before_count = sum(1 for ts in sidecar_timestamps if ts < floor)
    prefix_summary = get_state_db_session_message_prefix_summary(
        getattr(session, "session_id", None),
        floor,
        profile=getattr(session, "profile", None) or None,
    )
    if prefix_summary is None:
        return None, sidecar_messages
    try:
        state_before_count = int(prefix_summary["count"])
        null_timestamp_count = int(prefix_summary["null_timestamp_count"])
    except (KeyError, TypeError, ValueError):
        return None, sidecar_messages
    if null_timestamp_count or state_before_count != sidecar_before_count:
        return None, sidecar_messages
    if sidecar_before_count == 0:
        return floor, sidecar_messages

    sidecar_before_keys = [
        _session_message_visible_key(msg)
        for msg, ts in zip(sidecar_messages, sidecar_timestamps, strict=True)
        if ts < floor
    ]
    state_before_keys = get_state_db_session_message_keys_before_timestamp(
        getattr(session, "session_id", None),
        floor,
        profile=getattr(session, "profile", None) or None,
    )
    if state_before_keys is None or state_before_keys != sidecar_before_keys:
        return None, sidecar_messages
    return floor, sidecar_messages


def _messages_start_with_visible_prefix(messages, prefix) -> bool:
    """Return True when ``messages`` already replays ``prefix`` in display order."""
    messages = list(messages or [])
    prefix = list(prefix or [])
    if not prefix:
        return True
    if len(messages) < len(prefix):
        return False
    try:
        return all(
            _session_message_visible_key(messages[idx]) == _session_message_visible_key(prefix_msg)
            for idx, prefix_msg in enumerate(prefix)
        )
    except Exception:
        return False


# perf: memoized lineage-stitch results for GET /api/session. Keyed by session
# id; validity = exact stat signature of the child sidecar AND every snapshot
# parent involved in the stitch. Any write to any involved sidecar changes its
# signature and invalidates the entry. Bounded LRU — historical lineages are
# few but their merges cost seconds each.
_LINEAGE_DISPLAY_CACHE_MAX = 16
_lineage_display_cache: "OrderedDict[str, dict]" = OrderedDict()
_lineage_display_cache_lock = threading.Lock()


def _webui_sidecar_lineage_messages_for_display(session, *, max_hops: int = 20) -> list:
    """Return WebUI sidecar messages stitched across compression snapshots.

    WebUI compression continuations persist the archived transcript in a parent
    sidecar marked ``pre_compression_snapshot`` and keep subsequent turns in the
    child sidecar. Opening the child alone makes older turns look lost. Stitch
    only those snapshot parents for display; ordinary forks also carry
    ``parent_session_id`` but must remain independent conversations.

    perf: the stitched merge is O(total messages) with expensive per-row keys
    (json.dumps of tool_calls, loose-content regex). For multi-thousand-message
    lineages it costs seconds per request, and GET /api/session re-runs it on
    every open/poll. The result is cached per session id, keyed by the stat
    signature of every sidecar involved (child + each snapshot parent), so an
    idle historical lineage merges once and any write to any involved sidecar
    invalidates naturally. Cache hits return shallow-copied rows so callers can
    attach display metadata without corrupting the cache.
    """
    from api.models import _sidecar_stat_signature

    cache_allowed = not _display_merge_session_is_active(session)
    sid = str(getattr(session, "session_id", "") or "")
    self_sig = None
    if sid and is_safe_session_id(sid):
        self_sig = _sidecar_stat_signature(SESSION_DIR / f"{sid}.json")
    if cache_allowed and self_sig is not None:
        with _lineage_display_cache_lock:
            entry = _lineage_display_cache.get(sid)
        if (
            entry is not None
            and entry.get("provenance_complete") is True
            and entry.get("self_sig") == self_sig
        ):
            stale = False
            for parent_path, parent_sig in entry.get("parent_sigs") or []:
                if _sidecar_stat_signature(Path(parent_path)) != parent_sig:
                    stale = True
                    break
            if not stale:
                with _lineage_display_cache_lock:
                    current_entry = _lineage_display_cache.get(sid)
                    if current_entry is entry:
                        _lineage_display_cache.move_to_end(sid, last=True)
                        return [
                            dict(m) if isinstance(m, dict) else m
                            for m in entry["messages"]
                        ]
            else:
                _evict_lineage_display_cache_entry(sid, entry)

    segments = []
    current = session
    session_messages = list(getattr(session, "messages", []) or [])
    source = str(getattr(session, "session_source", "") or "").strip().lower()
    root_is_fork = source == "fork"
    seen = {str(getattr(session, "session_id", "") or "")}
    parent_sigs: list[tuple[str, tuple]] = []
    parent_signatures_complete = True
    for _ in range(max(0, int(max_hops))):
        parent_id = str(getattr(current, "parent_session_id", "") or "").strip()
        if not parent_id:
            break
        if parent_id in seen or not is_safe_session_id(parent_id):
            parent_signatures_complete = False
            break
        parent_path = SESSION_DIR / f"{parent_id}.json"
        parent_sig_before = _sidecar_stat_signature(parent_path)
        parent = Session.load(parent_id)
        if not parent:
            parent_signatures_complete = False
            break
        if not getattr(parent, "pre_compression_snapshot", False):
            break
        parent_sig = _sidecar_stat_signature(parent_path)
        if (
            parent_sig_before is None
            or parent_sig is None
            or parent_sig_before != parent_sig
        ):
            parent_signatures_complete = False
        else:
            parent_sigs.append((str(parent_path), parent_sig))
        parent_source = str(getattr(parent, "session_source", "") or "").strip().lower()
        if root_is_fork and parent_source != "fork":
            break
        if not segments and _messages_start_with_visible_prefix(
            session_messages,
            getattr(parent, "messages", []) or [],
        ):
            return session_messages
        segments.append(parent)
        seen.add(parent_id)
        current = parent
    else:
        # Exhausting max_hops means the declared ancestry may continue beyond
        # the signatures captured above. Never publish partial provenance.
        parent_signatures_complete = False

    if not segments:
        return list(getattr(session, "messages", []) or [])

    merged = []
    for segment in reversed(segments):
        merged = merge_session_messages_append_only(
            merged,
            getattr(segment, "messages", []) or [],
            truncation_watermark=getattr(segment, "truncation_watermark", None),
            truncation_boundary=getattr(segment, "truncation_boundary", None),
        )
    merged = merge_session_messages_append_only(
        merged,
        getattr(session, "messages", []) or [],
        truncation_watermark=None,
    )
    if (
        cache_allowed
        and self_sig is not None
        and parent_sigs
        and parent_signatures_complete
    ):
        with _lineage_display_cache_lock:
            _lineage_display_cache[sid] = {
                "self_sig": self_sig,
                "parent_sigs": parent_sigs,
                "provenance_complete": True,
                "messages": merged,
            }
            _lineage_display_cache.move_to_end(sid, last=True)
            while len(_lineage_display_cache) > _LINEAGE_DISPLAY_CACHE_MAX:
                _lineage_display_cache.popitem(last=False)
        # Hand out copies so caller-side metadata mutation cannot corrupt
        # the cached rows (same contract as the cache-hit path).
        return [dict(m) if isinstance(m, dict) else m for m in merged]
    return merged















def _session_sort_timestamp(session: dict) -> float:
    return float(
        _safe_first(
            session.get("last_message_at"),
            session.get("updated_at"),
            session.get("created_at"),
            session.get("started_at"),
            0,
        ) or 0
    ) or 0.0


def _is_cli_session_for_settings(session: dict) -> bool:
    """Return True for importable CLI sessions that are safe to classify for settings."""
    if not isinstance(session, dict):
        return False
    if is_cli_session_row(session):
        return True

    # Fallback for legacy local copies that had weak/empty metadata:
    # keep this conservative so messaging sessions do not collapse incorrectly.
    if not session.get("is_cli_session"):
        return False
    source = str(session.get("source") or "").strip().lower()
    if source in MESSAGING_SOURCES:
        return False
    title = str(session.get("title") or "").strip().lower()
    return title in ("", "untitled", "cli", "cli session") or title.endswith(" session") and (
        not source or source == "cli"
    )


def _normalize_sidebar_source_flags(session: dict) -> dict:
    """Return a sidebar row with the frontend CLI flag matching source metadata."""
    if not isinstance(session, dict):
        return session
    normalized = dict(session)
    normalized["is_cli_session"] = is_cli_session_row(normalized)
    return normalized




def _session_source_is_webui(session: dict) -> bool:
    """Return True for state.db/sidebar rows that describe WebUI-origin sessions."""
    if not isinstance(session, dict):
        return False
    for key in ("source_tag", "raw_source", "session_source", "source"):
        if str(session.get(key) or "").strip().lower() == "webui":
            return True
    return False


def _normalized_source_marker(value) -> str:
    marker = str(value or "").strip().lower()
    if marker.endswith(" session"):
        marker = marker[:-len(" session")].strip()
    return marker.replace("-", "_").replace(" ", "_")


def _is_api_server_sidecar_row(session: dict) -> bool:
    """Return True for API-server imported sidecars that need orphan pruning."""
    if not isinstance(session, dict) or _session_source_is_webui(session):
        return False
    markers = {
        _normalized_source_marker(session.get(key))
        for key in ("source", "source_tag", "raw_source", "session_source", "source_label")
    }
    return bool(markers & {"api", "api_server"})


def _session_lineage_ids(session: dict) -> set[str]:
    """Return known ids that identify one logical sidebar lineage."""
    if not isinstance(session, dict):
        return set()
    ids: set[str] = set()
    for key in ("session_id", "_lineage_root_id", "_lineage_tip_id"):
        value = session.get(key)
        if value:
            ids.add(str(value))
    return ids


def _is_duplicate_webui_state_projection(session: dict, represented_webui_ids: set[str]) -> bool:
    """Return True when a state.db row is only a duplicate WebUI-origin projection.

    The "Show non-WebUI sessions" toggle should add external/agent-owned
    conversations, not make WebUI compression continuations appear only when the
    external-session bridge is enabled. WebUI-origin state.db rows are still
    useful metadata sidecars, but if any id in their compression lineage is
    already represented by WebUI session JSON, they should not be injected as an
    additive external row.
    """
    if not _session_source_is_webui(session):
        return False
    return bool(_session_lineage_ids(session) & represented_webui_ids)


def _dedupe_cli_sidebar_sessions_for_api(
    cli: list[dict],
    represented_webui_ids: set[str],
    *,
    show_cron_sessions: bool = False,
    show_webhook_sessions: bool = False,
    show_kanban_sessions: bool = False,
    source_filter: str | None = None,
) -> list[dict]:
    """Return state sidebar rows while preserving project-hidden background rows.

    Agent-side cron and webhook sessions come from state.db rather than the WebUI
    session store. They should stay hidden from the default sidebar, but
    project-assigned messageful rows must remain in the `/api/sessions` payload
    with `default_hidden` so the matching project chip can reveal them (#3134).

    An explicit ``source_filter`` for a background source (cron/webhook/kanban)
    is a deliberate request to view those rows, so it overrides the default
    hide for that source only — the user asked for them.
    """
    from api.models import (
        _hide_from_default_sidebar as _hide_background,
        _include_project_hidden_background_sidebar_sessions,
    )

    # An explicit background source filter reveals that source (override the hide).
    # Normalize to match how the loader canonicalizes source_filter (strip+lower).
    _sf = str(source_filter or '').strip().lower()
    if _sf == 'cron':
        show_cron_sessions = True
    elif _sf == 'webhook':
        show_webhook_sessions = True
    elif _sf == 'kanban':
        show_kanban_sessions = True

    candidates = [
        s for s in cli
        if s["session_id"] not in represented_webui_ids
        and not _is_duplicate_webui_state_projection(s, represented_webui_ids)
        and is_cli_session_row_visible(s)
    ]
    visible = [
        s for s in candidates
        if not _hide_background(
            s,
            show_cron=show_cron_sessions,
            show_webhook=show_webhook_sessions,
            show_kanban=show_kanban_sessions,
        )
    ]
    return _include_project_hidden_background_sidebar_sessions(candidates, visible)


CLI_VISIBLE_SESSION_CAP = 20


def _cap_recent_cli_sessions(sessions: list[dict], cli_cap: int = CLI_VISIBLE_SESSION_CAP) -> list[dict]:
    """Keep only the most recent CLI-visible sessions after filtering."""
    if cli_cap <= 0:
        return sessions
    kept = []
    cli_seen = 0
    for session in sessions:
        if _is_cli_session_for_settings(session):
            cli_seen += 1
            if cli_seen > cli_cap:
                continue
        kept.append(session)
    return kept


def _merge_cli_sidebar_metadata(ui_session: dict, cli_meta: dict) -> dict:
    """Merge source-of-truth CLI metadata into a sidebar session row.

    Preserve UI-owned state (archived/pinned) while replacing metadata that can
    legitimately drift in WebUI snapshots.
    """
    if not ui_session:
        return ui_session
    if not cli_meta:
        return dict(ui_session)
    merged = dict(ui_session)
    # Only preserve the CLI flag when the imported metadata is actually a CLI
    # row. WebUI sessions are also mirrored into state.db; treating every
    # matching state row as CLI hides long WebUI continuations from the default
    # sidebar source tab.
    merged["is_cli_session"] = is_cli_session_row(cli_meta)
    for key in (
        "source_tag",
        "raw_source",
        "session_source",
        "source_label",
        "user_id",
        "chat_id",
        "chat_type",
        "thread_id",
        "session_key",
        "platform",
        "parent_session_id",
        "end_reason",
        "actual_message_count",
        "_lineage_root_id",
        "_lineage_tip_id",
        "_compression_segment_count",
    ):
        value = _safe_first(cli_meta.get(key))
        if value:
            merged[key] = value

    if cli_meta.get("created_at") is not None:
        merged["created_at"] = cli_meta["created_at"]
    if cli_meta.get("updated_at") is not None:
        merged["updated_at"] = cli_meta["updated_at"]
    if cli_meta.get("last_message_at") is not None:
        merged["last_message_at"] = cli_meta["last_message_at"]
    if cli_meta.get("message_count") is not None:
        merged["message_count"] = max(
            _numeric_count(merged.get("message_count")),
            _numeric_count(cli_meta.get("message_count")),
        )
    elif cli_meta.get("actual_message_count") is not None:
        merged["message_count"] = max(
            _numeric_count(merged.get("message_count")),
            _numeric_count(cli_meta.get("actual_message_count")),
        )

    if cli_meta.get("title"):
        current_title = merged.get("title")
        if not current_title or current_title == "Untitled":
            merged["title"] = cli_meta["title"]

    if cli_meta.get("model"):
        if not merged.get("model") or merged.get("model") == "unknown":
            merged["model"] = cli_meta["model"]
    return merged


def _messaging_source_key(session: dict) -> str | None:
    raw = _session_messaging_raw_source(session)
    if not _is_known_messaging_source(raw):
        return None
    return _messaging_session_identity(session, raw)


def _keep_latest_messaging_session_per_source(
    sessions: list[dict],
    *,
    show_previous_messaging_sessions: bool = False,
) -> list[dict]:
    """Keep only the newest sidebar row per messaging session identity."""
    if show_previous_messaging_sessions:
        return sorted(sessions, key=_session_sort_timestamp, reverse=True)

    gateway_metadata = _load_gateway_session_identity_map()
    active_gateway_session_ids = {str(sid) for sid in gateway_metadata.keys() if sid}
    session_ids = {
        _safe_first(session.get("session_id"))
        for session in sessions
        if isinstance(session, dict)
    }
    visible_active_gateway_session_ids = active_gateway_session_ids & session_ids
    active_gateway_sources = {
        _normalize_messaging_source(_safe_first(meta.get("raw_source"), meta.get("platform")))
        for sid, meta in gateway_metadata.items()
        if sid in visible_active_gateway_session_ids and isinstance(meta, dict)
    }
    active_gateway_sources = {source for source in active_gateway_sources if _is_known_messaging_source(source)}

    kept_sources: set[str] = set()
    best_by_source: dict[str, dict] = {}
    kept: list[dict] = []
    for session in sessions:
        key = _messaging_source_key(session)
        if not key:
            kept.append(session)
            continue
        if _should_hide_stale_messaging_session(session, visible_active_gateway_session_ids, active_gateway_sources):
            continue
        if key in kept_sources:
            kept_sources.add(key)
            current = best_by_source.get(key)
            if current is None or _session_sort_timestamp(session) > _session_sort_timestamp(current):
                best_by_source[key] = session
            continue
        kept_sources.add(key)
        best_by_source[key] = session

    kept.extend(best_by_source.values())
    kept.sort(key=_session_sort_timestamp, reverse=True)
    return kept


from api.models import (
    Session,
    get_session,
    get_session_for_scan,
    find_compression_recovery_session,
    get_session_for_file_ops,
    persist_recovered_workspace_binding,
    WorkspaceBindingPersistenceError,
    new_session,
    all_sessions,
    title_from,
    _write_session_index,
    SESSION_INDEX_FILE,
    _active_state_db_path,
    load_projects,
    save_projects,
    import_cli_session,
    CLAUDE_CODE_SOURCE,
    get_cli_sessions,
    get_cli_session_messages,
    get_state_db_session_messages,
    get_state_db_session_message_prefix_summary,
    get_state_db_session_message_keys_before_timestamp,
    get_state_db_session_summary,
    merge_session_messages_append_only,
    _reconcile_api_content_sidecars,
    _enrich_sidebar_lineage_metadata,
    _active_stream_ids,
    _evict_sessions_over_cap,
    _merge_session_display_metadata,
    _session_message_merge_key,
    _session_messages_have_prefix,
    _session_message_visible_key,
    _message_timestamp_as_float,
    _is_empty_partial_activity_message,
    _hide_from_default_sidebar,
    prune_session_from_index,
    agent_session_rows_existing,
    agent_session_zero_message_sids,
    _load_webui_zero_message_orphan_tombstone,
    _record_webui_zero_message_orphan_tombstone,
    _clear_webui_zero_message_orphan_tombstone,
    _load_webui_deleted_session_tombstone,
    _record_webui_deleted_session_tombstone,
    ensure_cron_project,
    _profile_has_user_projects,
    is_cron_session,
    is_safe_session_id,
    PROCESS_WAKEUP_PAUSE_ERROR,
    clear_process_wakeup_pause,
    clear_process_wakeup_pause_if_model_changed,
    process_wakeup_pause_matches,
    process_wakeup_credential_state_fingerprint,
    process_wakeup_pause_credential_state_changed,
    suppress_process_wakeup_for_provider_pause,
)





from api.workspace import (get_last_workspace, set_last_workspace, list_dir, serialize_workspace_entries_for_browser, dir_signature, read_file_content, resolve_trusted_workspace, resolve_implicit_workspace_with_recovery, open_anchored_fd, _is_remote_terminal_backend)
from api.upload import (handle_upload, handle_upload_extract, handle_workspace_upload)
from api.streaming import (
    _sse,
    _sse_set_write_deadline,
    _run_agent_streaming,
    cancel_stream,
    _materialize_pending_user_turn_before_error,
    generate_session_title_for_session,
    _compact_for_echo_compare,
    _strip_compact_echo_suffix,
)
from api.gateway_chat import _run_gateway_chat_streaming, webui_gateway_chat_enabled
from api.run_journal import (_parse_run_journal_event_id as _shared_parse_run_journal_event_id, read_run_events, read_session_run_events, session_journal_fingerprint, SSE_RELAY_CLOSE_EVENTS)
from api.todo_state import attach_todo_state
from api.providers import (get_providers, provider_has_process_wakeup_recovery_credential, set_provider_key)

# Approval system -- state and helpers live in api.route_approvals; imported
# here for backward compatibility so existing call sites continue to resolve.
from api.route_approvals import (approve_session, approve_permanent, save_permanent_allowlist, _pending, _lock, _permanent_approved, _gateway_queues, resolve_gateway_approval, is_session_yolo_enabled, _approval_sse_notify_locked, _GATEWAY_AGENT_IDENTITY_V1, _GATEWAY_MIRROR_FLAG, _GATEWAY_MIRROR_TOKEN, _gateway_mirror_entry_token, gateway_yolo_handoff, begin_session_yolo_transition, claim_gateway_approval_relay_owner, finish_session_yolo_transition, gateway_pending_mirror, gateway_pending_mirrors, release_gateway_approval_relay_owner, retire_gateway_pending_mirror, reconcile_gateway_pending_mirror_locked, resolve_gateway_pending_local, resolve_gateway_pending_local_all, resolve_gateway_pending_local_no_run_mirror, set_session_yolo_enabled, submit_pending)

# Clarify prompts (optional -- graceful fallback if agent not available)
try:
    from api.clarify import (
        submit_pending as submit_clarify_pending,
        get_pending as get_clarify_pending,
        pending_count as get_clarify_pending_count,
        resolve_clarify,
        resolve_clarify_by_id,
        sse_subscribe as clarify_sse_subscribe,
        sse_unsubscribe as clarify_sse_unsubscribe,
    )
except ImportError:
    submit_clarify_pending = lambda *a, **k: None
    get_clarify_pending = lambda *a, **k: None
    get_clarify_pending_count = lambda *a, **k: 0
    clarify_sse_subscribe = None
    resolve_clarify = lambda *a, **k: 0
    resolve_clarify_by_id = lambda *a, **k: False


def _session_attention_summary(session_id: str) -> dict | None:
    """Return sidebar attention metadata for pending approval/clarify work."""
    approval_count = 0
    with _lock:
        reconcile_gateway_pending_mirror_locked(session_id)
        queue_list = _pending.get(session_id)
        if isinstance(queue_list, list):
            approval_count = len(queue_list)
        elif queue_list:
            approval_count = 1
    if approval_count > 0:
        return {
            "kind": "approval",
            "count": approval_count,
            "severity": "critical",
        }

    clarify_count = int(get_clarify_pending_count(session_id) or 0)
    if clarify_count > 0:
        return {
            "kind": "clarify",
            "count": clarify_count,
            "severity": "question",
        }
    return None







# ── Login page HTML generation & locale handling (extracted to api.route_login) ──
from api.route_login import (_safe_login_redirect_path, _request_base_url, handle_login_page)

# ── Logs endpoint (extracted to api.route_logs) ───────────────────────────────



# ── Insights, LLM-Wiki, and Project-OS endpoints (extracted to api.route_insights)

# ── MCP and Notes endpoints (extracted to api.route_mcp and api.route_notes) ──
from api.route_notes import (handle_notes_sources_list as _handle_notes_sources_list, handle_notes_search as _handle_notes_search, handle_notes_item as _handle_notes_item)

# ── TTS endpoint (extracted to api.route_tts) ─────────────────────────────────

# ── Folder download endpoint (extracted to api.route_folder_download) ─────────

# ── Git workspace endpoints (extracted to api.route_git) ──────────────────────
from api.route_git import (handle_git_status as _handle_git_status, handle_git_branches as _handle_git_branches, handle_git_diff as _handle_git_diff, handle_git_stage as _handle_git_stage, handle_git_unstage as _handle_git_unstage, handle_git_discard as _handle_git_discard, handle_git_commit_message as _handle_git_commit_message, handle_git_commit_message_selected as _handle_git_commit_message_selected, handle_git_commit as _handle_git_commit, handle_git_commit_selected as _handle_git_commit_selected, handle_git_remote_action as _handle_git_remote_action, handle_git_checkout as _handle_git_checkout, handle_git_stash_checkout as _handle_git_stash_checkout)

# ── Terminal endpoints (extracted to api.route_terminal) ──────────────────────
from api.route_terminal import (
    handle_terminal_start as _handle_terminal_start,
    handle_terminal_input as _handle_terminal_input,
    handle_terminal_resize as _handle_terminal_resize,
    handle_terminal_close as _handle_terminal_close,
    handle_terminal_output as _handle_terminal_output,
    _terminal_session_lookup,
    _terminal_remote_backend_enabled,
    _REMOTE_TERMINAL_BACKEND_UNSUPPORTED_ERROR,
    _REMOTE_TERMINAL_BACKEND_UNSUPPORTED_MESSAGE,
)

# ── GET routes ────────────────────────────────────────────────────────────────


def _accept_loop_health(handler) -> dict:
    server = getattr(handler, "server", None)
    return {
        "requests_total": int(getattr(server, "accept_loop_requests_total", 0) or 0),
        "last_request_at": round(float(getattr(server, "accept_loop_last_request_at", 0.0) or 0.0), 3),
    }


def _streams_lock_health(timeout_seconds: float = 0.5) -> dict:
    t0 = time.time()
    acquired = STREAMS_LOCK.acquire(timeout=timeout_seconds)
    elapsed_ms = round((time.time() - t0) * 1000, 1)
    if not acquired:
        return {
            "status": "blocked",
            "timeout_seconds": timeout_seconds,
            "ms": elapsed_ms,
        }
    try:
        return {
            "status": "ok",
            "active_streams": len(STREAMS),
            "ms": elapsed_ms,
        }
    finally:
        STREAMS_LOCK.release()


def _stream_runtime_diagnostics() -> dict:
    """Return non-sensitive SSE stream diagnostics for health/deep status.

    The WebUI chat path can feel slow or stuck when streams are alive but no
    browser is attached, or when many events are buffering offline. This helper
    exposes counts only — stream ids plus subscriber/buffer sizes — and avoids
    event payloads, prompts, tool arguments, or paths.
    """
    streams = []
    total_subscribers = 0
    total_offline_buffered_events = 0
    with STREAMS_LOCK:
        items = list(STREAMS.items())
    for stream_id, stream in items:
        snapshot = {}
        diagnostic_snapshot = getattr(stream, "diagnostic_snapshot", None)
        if callable(diagnostic_snapshot):
            try:
                raw_snapshot = diagnostic_snapshot()
                if isinstance(raw_snapshot, dict):
                    snapshot = raw_snapshot
            except Exception:
                snapshot = {}
        subscriber_count = int(snapshot.get("subscriber_count") or 0)
        offline_buffered_events = int(snapshot.get("offline_buffered_events") or 0)
        total_subscribers += subscriber_count
        total_offline_buffered_events += offline_buffered_events
        streams.append({
            "stream_id": str(stream_id),
            "subscriber_count": subscriber_count,
            "offline_buffered_events": offline_buffered_events,
        })
    streams.sort(key=lambda item: item["stream_id"])
    return {
        "active_streams": len(streams),
        "total_subscribers": total_subscribers,
        "total_offline_buffered_events": total_offline_buffered_events,
        "streams": streams,
    }


def _run_lifecycle_health() -> dict:
    """Return active worker-run state independent of SSE stream presence."""
    # Import the module rather than relying only on imported scalar aliases so
    # LAST_RUN_FINISHED_AT stays fresh after unregister_active_run() updates it.
    from api import config as _live_config

    now = time.time()
    with _live_config.ACTIVE_RUNS_LOCK:
        runs = []
        for _stream_id, raw in (_live_config.ACTIVE_RUNS or {}).items():
            item = dict(raw or {})
            item.pop("session_id", None)
            item.pop("stream_id", None)
            item.pop("workspace", None)
            started_at = item.get("started_at")
            try:
                age = max(0.0, now - float(started_at))
            except Exception:
                age = 0.0
            item["age_seconds"] = round(age, 1)
            runs.append(item)
        last_finished = _live_config.LAST_RUN_FINISHED_AT
    runs.sort(key=lambda item: float(item.get("started_at") or 0.0))
    payload = {
        "active_runs": len(runs),
        "runs": runs,
        "last_run_finished_at": last_finished,
    }
    if runs:
        payload["oldest_run_age_seconds"] = runs[0].get("age_seconds", 0.0)
    elif last_finished:
        payload["idle_seconds_since_last_run"] = round(max(0.0, now - float(last_finished)), 1)
    return payload


def _deep_health_checks(stream_check: dict | None = None) -> tuple[dict, bool]:
    """Run cheap probes that exercise the state paths used by the UI shell.

    Plain /health intentionally stays tiny. /health?deep=1 is for supervisors
    and watchdogs that need to know whether the process can still touch the
    shared stream map, sidebar/session path, project state, and Hermes state.db
    without hitting the RST-before-write failure mode from #1458.

    `stream_check` is the result from a prior `_streams_lock_health()` call;
    if provided, it's reused so we don't acquire `STREAMS_LOCK` twice on the
    same /health?deep=1 request (per Opus advisor on stage-297).
    """
    checks: dict[str, dict] = {}

    checks["streams_lock"] = stream_check if stream_check is not None else _streams_lock_health()
    checks["stream_runtime"] = {
        "status": "ok",
        **_stream_runtime_diagnostics(),
    }
    if checks["streams_lock"].get("status") != "ok":
        return checks, False

    t0 = time.time()
    try:
        sessions = all_sessions()
        checks["sessions"] = {
            "status": "ok",
            "count": len(sessions),
            "ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as exc:
        checks["sessions"] = {
            "status": "error",
            "error": type(exc).__name__,
            "ms": round((time.time() - t0) * 1000, 1),
        }

    t0 = time.time()
    try:
        projects = load_projects(_migrate=False)
        checks["projects"] = {
            "status": "ok",
            "count": len(projects),
            "ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as exc:
        checks["projects"] = {
            "status": "error",
            "error": type(exc).__name__,
            "ms": round((time.time() - t0) * 1000, 1),
        }

    t0 = time.time()
    try:
        db_path = _active_state_db_path()
        if not db_path.exists():
            checks["state_db"] = {
                "status": "missing",
                "ms": round((time.time() - t0) * 1000, 1),
            }
        else:
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.execute("PRAGMA schema_version").fetchone()
            checks["state_db"] = {
                "status": "ok",
                "ms": round((time.time() - t0) * 1000, 1),
            }
    except Exception as exc:
        checks["state_db"] = {
            "status": "error",
            "error": type(exc).__name__,
            "ms": round((time.time() - t0) * 1000, 1),
        }

    healthy = all(
        check.get("status") in {"ok", "missing"}
        for check in checks.values()
    )
    return checks, healthy


def _handle_health(handler, parsed):
    deep = parse_qs(parsed.query or "").get("deep", [""])[0].lower() in {"1", "true", "yes", "on"}
    stream_check = _streams_lock_health()
    run_check = _run_lifecycle_health()
    payload = {
        "status": "ok" if stream_check.get("status") == "ok" else "degraded",
        "sessions": len(SESSIONS),
        "active_streams": int(stream_check.get("active_streams") or 0),
        "active_runs": int(run_check.get("active_runs") or 0),
        "runs": run_check.get("runs", []),
        "last_run_finished_at": run_check.get("last_run_finished_at"),
        "server_started_at": SERVER_START_TIME,
        "uptime_seconds": round(time.time() - SERVER_START_TIME, 1),
        "accept_loop": _accept_loop_health(handler),
    }
    if "oldest_run_age_seconds" in run_check:
        payload["oldest_run_age_seconds"] = run_check["oldest_run_age_seconds"]
    if "idle_seconds_since_last_run" in run_check:
        payload["idle_seconds_since_last_run"] = run_check["idle_seconds_since_last_run"]
    if deep:
        if stream_check.get("status") != "ok":
            payload["checks"] = {"streams_lock": stream_check}
            return j(handler, payload, status=503)
        checks, healthy = _deep_health_checks(stream_check=stream_check)
        payload["checks"] = checks
        if not healthy:
            payload["status"] = "degraded"
            return j(handler, payload, status=503)
    if payload["status"] != "ok":
        return j(handler, payload, status=503)
    return j(handler, payload)














# WebUI dashboard plugins (from manifest.json discovery)
def _dashboard_plugin_enabled(plugin_name: str) -> bool:
    """True if a dashboard plugin is enabled in settings.

    Dashboard plugins are opt-in (default off). Enforced server-side so a
    disabled plugin's page + asset URLs are fully 404'd, not merely hidden in
    the Settings UI.
    """
    try:
        from api.config import load_settings
        prefs = (load_settings() or {}).get("dashboard_plugins", {}) or {}
        return bool(prefs.get(plugin_name, False))
    except Exception:
        return False










_SHUTDOWN_LOG_VALUE_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _shutdown_log_value(value, *, default: str = "unknown", max_len: int = 160) -> str:
    """Return a bounded single-line value safe for shutdown diagnostics."""
    if value is None:
        return default
    try:
        text = str(value)
    except Exception:
        return default
    text = _SHUTDOWN_LOG_VALUE_RE.sub("?", text).strip()
    if not text:
        return default
    if len(text) > max_len:
        text = f"{text[:max_len]}…"
    return text






def _serve_manifest(handler) -> bool:
    """Serve the canonical shared UI manifest, never an archived static file."""
    from api.ui_shell import dist_root
    root = dist_root()
    manifest = root / "manifest.webmanifest" if root else None
    if manifest is None or not manifest.is_file():
        return j(handler, {"error": "not found"}, status=404)
    data = manifest.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/manifest+json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)
    return True








def _jaeger_gateway_bases() -> list[str]:
    import os
    bases: list[str] = []
    for key in ("JAEGER_GATEWAY_URL", "HERMES_WEBUI_GATEWAY_URL"):
        raw = (os.environ.get(key) or "").strip().rstrip("/")
        if raw:
            bases.append(raw)
    from jaeger_ai.contract.ports import resolve_gateway_url
    # The loopback Gateway (contract.ports), after any explicitly configured URL above.
    implicit = {k: v for k, v in os.environ.items() if k != "JAEGER_GATEWAY_URL"}
    bases.append(resolve_gateway_url(implicit))
    runner = (
        os.environ.get("HERMES_WEBUI_RUNNER_BASE_URL")
        or os.environ.get("JAEGER_RUNNER_BASE_URL")
        or "http://127.0.0.1:8791"
    ).rstrip("/")
    if runner:
        bases.append(runner)
    out: list[str] = []
    for b in bases:
        if b and b not in out:
            out.append(b)
    return out


def _proxy_jaeger_gateway(handler, method: str, path: str, body: bytes | None = None):
    """Server-side proxy so browser clients on :8790 reach the loopback Gateway."""
    import json as _json
    import http.client
    from urllib.parse import urlparse

    last_err = "no gateway bases"
    for base in _jaeger_gateway_bases():
        parsed_base = urlparse(base)
        host = parsed_base.hostname or "127.0.0.1"
        port = parsed_base.port or (443 if parsed_base.scheme == "https" else 80)
        try:
            conn = http.client.HTTPConnection(host, port, timeout=3)
            from jaeger_ai.core.gateway.caller_auth import client_headers
            headers = {"Accept": "application/json", **client_headers("webui")}
            if body is not None:
                headers["Content-Type"] = "application/json"
            conn.request(method.upper(), path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            status = int(resp.status)
            conn.close()
            try:
                parsed_json = _json.loads(payload.decode("utf-8") or "null")
            except _json.JSONDecodeError:
                last_err = "gateway returned non-JSON"
                continue
            return j(handler, parsed_json, status=status)
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue
    return bad(handler, f"gateway unreachable: {last_err}", 503)



def handle_get(handler, parsed) -> bool:
    """Handle all GET routes. Returns True if handled, False for 404."""
    from api.jaeger_browser import route as browser_route
    if browser_route(handler, parsed, "GET"):
        return True
    from api.character_scenes import route as character_scene_route
    if character_scene_route(handler, parsed):
        return True
    from api.native_panel_context import check_profile as check_native_panel_profile
    try:
        from api.jaeger_agents import route as jaeger_agents_route
        if jaeger_agents_route(handler, parsed, "GET"):
            return True
    except Exception:
        pass
    from api.jaeger_conversation import route as conversation_route
    if conversation_route(handler, parsed, "GET"):
        return True
    proxy_result = _handle_extension_sidecar_proxy(handler, parsed, "GET")
    if proxy_result is not False:
        return proxy_result

    if parsed.path.startswith("/session/static/"):
        # Strip the leading "/session" so _serve_static() sees a path that
        # starts with "/static/" (its required prefix). _serve_static enforces
        # its own path-traversal sandbox via Path.resolve()+relative_to().
        stripped = parsed._replace(path=parsed.path[len("/session"):])
        return _serve_static(handler, stripped)

    # Firefox Android resolves <link rel="manifest"> against the page URL
    # before the dynamic <base href> script runs when installing from
    # /session/<id>, producing requests like /session/manifest.json.
    # Without this guard the catch-all below returns index.html instead of
    # the manifest, and Firefox falls back to a generated letter icon.
    # See #2226.
    if parsed.path in ("/session/manifest.json", "/session/manifest.webmanifest"):
        from api.ui_shell import serve
        return serve(handler, parsed._replace(path="/manifest.json"))

    # Canonical shared UI only; no legacy shell or source fallback.
    from api.ui_shell import serve as _serve_ui_shell
    if _serve_ui_shell(handler, parsed):
        return True
    if parsed.path == "/share" or parsed.path.startswith("/share/"):
        return j(handler, {"error": "Legacy share presentation archived; shared UI replacement unavailable"}, status=503)

    if parsed.path == "/login":
        return handle_login_page(handler, parsed, load_settings_fn=load_settings, render_html_fn=t)

    if parsed.path == "/api/auth/oidc/start":
        from api.auth_oidc import OIDCAuthError, OIDCConfigError, build_authorization_redirect

        next_path = _safe_login_redirect_path(
            parse_qs(parsed.query or "").get("next", [""])[0]
        )
        try:
            location = build_authorization_redirect(
                _request_base_url(handler), next_path
            )
        except OIDCConfigError as exc:
            return j(handler, {"error": str(exc)}, status=404)
        except OIDCAuthError as exc:
            return j(handler, {"error": str(exc)}, status=exc.status_code)
        handler.send_response(302)
        handler.send_header("Location", location)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", "0")
        _security_headers(handler)
        handler.end_headers()
        return True

    if parsed.path == "/api/auth/oidc/callback":
        from api.auth import create_session, set_auth_cookie
        from api.auth_oidc import OIDCAuthError, OIDCConfigError, complete_authorization_code_flow

        query = parse_qs(parsed.query or "")
        error = str(query.get("error", [""])[0] or "").strip()
        if error:
            description = str(query.get("error_description", [""])[0] or "").strip()
            return j(handler, {"error": description or error}, status=401)
        state = str(query.get("state", [""])[0] or "").strip()
        code = str(query.get("code", [""])[0] or "").strip()
        if not state or not code:
            return j(handler, {"error": "Missing OIDC callback state or code"}, status=400)
        try:
            result = complete_authorization_code_flow(
                _request_base_url(handler), state, code
            )
        except OIDCConfigError as exc:
            return j(handler, {"error": str(exc)}, status=404)
        except OIDCAuthError as exc:
            return j(handler, {"error": str(exc)}, status=exc.status_code)
        cookie_val = create_session()
        handler.send_response(302)
        handler.send_header(
            "Location",
            _safe_login_redirect_path(result.get("next_path")),
        )
        handler.send_header("Cache-Control", "no-store")
        _security_headers(handler)
        set_auth_cookie(handler, cookie_val)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return True

    if parsed.path == "/api/auth/status":
        from api.auth import (
            _passkey_feature_flag_enabled,
            ensure_trusted_auth_session,
            get_password_hash,
            is_auth_enabled,
            is_oidc_auth_enabled,
            is_trusted_auth_enabled,
        )
        from api.passkeys import registered_credentials

        logged_in = False
        session_info = None
        auth_enabled = is_auth_enabled()
        oidc_enabled = is_oidc_auth_enabled()
        if auth_enabled:
            session_info = ensure_trusted_auth_session(handler)
            logged_in = bool(session_info)
        passkey_flag = _passkey_feature_flag_enabled()
        passkeys = registered_credentials() if passkey_flag else []
        password_auth_enabled = get_password_hash() is not None
        payload = {
            "auth_enabled": auth_enabled,
            "logged_in": logged_in,
            "oidc_enabled": oidc_enabled,
            "password_auth_enabled": password_auth_enabled,
            "passwordless_enabled": bool(passkeys) and not password_auth_enabled,
            "passkeys_enabled": bool(passkeys),
            "passkeys_count": len(passkeys),
            "passkey_feature_flag": passkey_flag,
            "auth_disabled_acknowledged": bool(load_settings().get("auth_disabled_acknowledged")) if not auth_enabled else False,
        }
        if is_trusted_auth_enabled() or (session_info and session_info.get("auth_type") == "trusted"):
            payload["trusted_auth_enabled"] = True
        if session_info and session_info.get("auth_type") == "trusted":
            payload["auth_type"] = session_info.get("auth_type")
            payload["user"] = session_info.get("username")
            payload["bound_profile"] = session_info.get("bound_profile")
        return j(handler, payload)


    if parsed.path in ("/manifest.json", "/manifest.webmanifest"):
        return _serve_manifest(handler)

    if parsed.path == "/sw.js":
        static_root = api_config.get_static_root()
        sw_path = (static_root / "sw.js").resolve()
        if sw_path.exists():
            # Inject the current git-derived version as the cache name so the
            # service worker cache busts automatically on every new deploy.
            from urllib.parse import quote
            from api.updates import WEBUI_VERSION
            version_token = quote(WEBUI_VERSION, safe="")
            text = sw_path.read_text(encoding="utf-8").replace(
                "__WEBUI_VERSION__", version_token
            )
            data = text.encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/javascript; charset=utf-8")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Service-Worker-Allowed", "/")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return True
        return j(handler, {"error": "not found"}, status=404)

    if parsed.path == "/favicon.ico":
        static_root = api_config.get_static_root()
        ico_path = (static_root / "favicon.ico").resolve()
        if ico_path.exists() and ico_path.is_file():
            data = ico_path.read_bytes()
            handler.send_response(200)
            handler.send_header("Content-Type", "image/x-icon")
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "public, max-age=86400")
            handler.end_headers()
            handler.wfile.write(data)
        else:
            handler.send_response(204)
            handler.end_headers()
        return True

    if parsed.path.startswith("/api/") and not _guard_request_session_visibility(handler, parsed, method="GET"):
        return True



    if parsed.path == "/health":
        return _handle_health(handler, parsed)



    if parsed.path == "/api/models":
        # Profile-scoping for non-default profiles (#3957) is handled INSIDE
        # get_available_models() — it binds the active profile's env + TLS on
        # the detached rebuild worker (and the legacy synchronous rebuild),
        # which the request-thread wrapper could not reach. See
        # api.config.get_available_models cold path + profile_scope_for_detached_worker.
        freshness = parse_qs(parsed.query or "").get("freshness", [""])[0].strip().lower()
        diag = RequestDiagnostics.maybe_start("GET", parsed.path, logger=logger, print_fn=getattr(handler, '_safe_webui_print', None))
        try:
            diag.stage(f"enter:freshness={freshness or 'default'}") if diag else None
            if freshness == "session_visit":
                result = get_available_models_for_session_visit()
                diag.stage("response_serialize") if diag else None
                return j(handler, result)
            if freshness:
                return bad(handler, f"unknown models freshness: {freshness}", status=400)
            return j(handler, get_available_models())
        finally:
            if diag:
                diag.finish()





    # ── Providers (GET) ──
    if parsed.path == "/api/providers":
        # Apply the active per-request profile's env so provider auth probes
        # resolve against that profile's credentials, not the process-default
        # profile's (#3957). Without this, get_auth_status() probes on a
        # non-default profile resolve the wrong/empty creds and can stall past
        # the 30s frontend timeout. No-op for the default profile.
        from api.profiles import profile_env_for_active_request_readonly
        with profile_env_for_active_request_readonly("/api/providers", logger_override=logger):
            return j(handler, get_providers())



    if parsed.path == "/api/settings":
        settings = load_settings()
        settings["persisted_speech_keys"] = persisted_speech_settings_keys()
        # Never expose the stored password hash to clients
        settings.pop("password_hash", None)
        settings.setdefault("max_tokens", None)
        settings.setdefault("max_tokens_effective", None)
        settings.setdefault("max_tokens_fallback", None)
        try:
            from api.config import get_max_tokens_status
            settings.update(get_max_tokens_status())
        except Exception:
            settings["max_tokens"] = None
            settings["max_tokens_effective"] = None
            settings["max_tokens_fallback"] = None
        # Surface env-var precedence so the UI can disable the password field
        # instead of silently no-oping the save (#1560). The setting takes
        # precedence in api.auth.get_password_hash(), but until now the UI
        # had no way to know — see issue #1139 / #1560.
        settings["password_env_var"] = bool(
            os.getenv("HERMES_WEBUI_PASSWORD", "").strip()
        )
        # Auth-state fields for frontend safety badge / confirmation flows
        from api.auth import get_password_hash, is_auth_enabled
        settings["auth_enabled"] = is_auth_enabled()
        settings["password_auth_enabled"] = get_password_hash() is not None
        try:
            from api.auth import _passkey_feature_flag_enabled as _pffe
            from api.passkeys import registered_credentials as _rc
            if _pffe():
                settings["passkeys_enabled"] = bool(_rc())
                settings["passwordless_enabled"] = bool(_rc()) and not settings["password_auth_enabled"]
            else:
                settings["passkeys_enabled"] = False
                settings["passwordless_enabled"] = False
        except Exception:
            pass
        # Inject the running version so the UI badge stays in sync with git tags
        # without any manual release step.
        try:
            from api.updates import AGENT_VERSION, WEBUI_VERSION
            settings["webui_version"] = WEBUI_VERSION
            settings["agent_version"] = AGENT_VERSION
        except Exception:
            pass
        # Channel-scoped display badge — SEPARATE from webui_version (which is
        # load-bearing for asset cache-busting / SW cache / skew detection and
        # must stay channel-neutral). update_channel_version is display-only.
        try:
            from api.updates import channel_version_badge, _read_update_channel
            channel = _read_update_channel()
            settings["update_channel"] = channel
            settings["update_channel_version"] = channel_version_badge(channel)
        except Exception:
            pass
        return j(handler, settings)






    if parsed.path.startswith("/extensions/"):
        from api.extensions import serve_extension_static

        return serve_extension_static(handler, parsed)

    if parsed.path.startswith("/static/"):
        return _serve_static(handler, parsed)


















    if parsed.path == "/api/list":
        return _handle_list_dir(handler, parsed)


    if parsed.path in ("/api/checkpoints/list", "/api/checkpoints/diff"):
        from api.route_checkpoints import handle_checkpoints_get
        return handle_checkpoints_get(handler, parsed)

    if parsed.path == "/api/git/status":
        return _handle_git_status(handler, parsed)

    if parsed.path == "/api/git/branches":
        return _handle_git_branches(handler, parsed)

    if parsed.path == "/api/git/diff":
        return _handle_git_diff(handler, parsed)










    if parsed.path == "/api/terminal/output":
        return _handle_terminal_output(handler, parsed)



    session_events_session_id = _session_events_path_session_id(parsed.path)
    if session_events_session_id is not None:
        return _handle_session_sse_stream_for_session(handler, parsed, session_events_session_id)


    if parsed.path == "/api/file/raw":
        return _handle_file_raw(handler, parsed)



    if parsed.path == "/api/file":
        return _handle_file_read(handler, parsed)






















    # ── Unified UI: workspace layout + gateway liveness (WebUI-owned, minimal) ──
    from api import unified_api
    if unified_api.route(handler, parsed, "GET", read_body, j):
        return True
    if parsed.path == "/v1/dashboard":
        from api import dashboard_store
        return j(handler, dashboard_store.read())
    if parsed.path == "/v1/system/metrics":
        from api import system_metrics
        return j(handler, system_metrics.metrics())
    if parsed.path == "/v1/system/status":
        from api import system_metrics
        return j(handler, system_metrics.status())
    if parsed.path == "/v1/first-run":
        return _proxy_jaeger_gateway(handler, "GET", "/v1/first-run")
    if parsed.path == "/v1/gateway-health":
        return _proxy_jaeger_gateway(handler, "GET", "/health")

    # ── AppControl (Machine tab "Agent Apps"): reads proxied to the Gateway ──
    if parsed.path == "/v1/apps" or parsed.path.startswith("/v1/apps/"):
        qs = ("?" + parsed.query) if parsed.query else ""
        return _proxy_jaeger_gateway(handler, "GET", parsed.path + qs)

    # ── Jaeger Gateway agents (GET) — Surfaces spine parity with the Gateway ──
    if parsed.path in {"/api/agents", "/v1/agents"}:
        qs = ("?" + parsed.query) if parsed.query else ""
        return _proxy_jaeger_gateway(handler, "GET", f"/v1/agents{qs}")

    if parsed.path.startswith("/api/agents/") or parsed.path.startswith("/v1/agents/"):
        suffix = parsed.path.split("/agents/", 1)[-1]
        if suffix and not suffix.endswith("/activate"):
            return _proxy_jaeger_gateway(handler, "GET", f"/v1/agents/{suffix}")







    if parsed.path == "/api/notes/sources":
        return _handle_notes_sources_list(handler)
    if parsed.path == "/api/notes/search":
        return _handle_notes_search(handler, parsed)
    if parsed.path == "/api/notes/item":
        return _handle_notes_item(handler, parsed)



    # ── Plugin shared assets (e.g. /plugins/plugin.css) ──
    # Restricted to shared plugin assets only — no cross-plugin file access.
    if parsed.path.startswith("/plugins/"):
        from api.plugins import _get_plugin_base
        plugin_base = _get_plugin_base()
        rel = parsed.path[len("/plugins/"):]
        allowed = {"plugin.css"}
        if rel not in allowed:
            return False  # 404
        safe = (plugin_base / rel).resolve()
        try:
            safe.relative_to(plugin_base.resolve())
        except ValueError:
            return False  # path traversal — 404
        if safe.is_file():
            import os as _os
            data = safe.read_bytes()
            ext = _os.path.splitext(rel.lower())[1]
            ct = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".png": "image/png",
                ".svg": "image/svg+xml",
            }.get(ext, "application/octet-stream")
            handler.send_response(200)
            handler.send_header("Content-Type", ct)
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return True

    # ── Plugin static assets ──
    if parsed.path.startswith("/dashboard-plugins/"):
        parts = parsed.path.split("/", 3)
        if len(parts) >= 3:
            plugin_name = parts[2]
            rel_path = parts[3] if len(parts) > 3 else ""
            # Server-side enable-gate: a plugin disabled in Settings must have its
            # entire URL surface shut off, not merely hidden in the UI.
            if not _dashboard_plugin_enabled(plugin_name):
                return False  # 404 — disabled plugins serve nothing
            from api.plugins import serve_plugin_static
            result = serve_plugin_static(plugin_name, rel_path)
            if result:
                data, content_type = result
                handler.send_response(200)
                handler.send_header("Content-Type", content_type)
                # Defense-in-depth: plugin-controlled assets are served from the
                # WebUI's own origin. Sandbox them (null origin) so a plugin's
                # .html/.svg can't run privileged same-origin script if navigated
                # to directly (the in-panel iframe sandbox doesn't cover direct
                # navigation). nosniff prevents content-type confusion.
                handler.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms allow-popups")
                handler.send_header("X-Content-Type-Options", "nosniff")
                handler.send_header("Content-Length", str(len(data)))
                handler.end_headers()
                handler.wfile.write(data)
                return True

    # ── Plugin pages (HTML shell) ──
    from api.plugins import PLUGIN_MANIFESTS, _PLUGIN_STATIC_ROOTS
    for name, manifest in PLUGIN_MANIFESTS.items():
        tab = manifest.get("tab", {})
        tab_path = tab.get("path", f"/{name}")
        if parsed.path == tab_path:
            # Server-side enable-gate (opt-in): a disabled plugin's page 404s.
            if not _dashboard_plugin_enabled(name):
                return False
            dashboard_dir = _PLUGIN_STATIC_ROOTS.get(name)
            if dashboard_dir:
                # 1) dashboard/dist/index.html (full SPA build)
                index_html = dashboard_dir / "dist" / "index.html"
                if index_html.is_file():
                    data = index_html.read_bytes()
                    handler.send_response(200)
                    handler.send_header("Content-Type", "text/html; charset=utf-8")
                    handler.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms allow-popups")
                    handler.send_header("Content-Length", str(len(data)))
                    handler.end_headers()
                    handler.wfile.write(data)
                    return True
                # 2) static/index.html in plugin root (content page for IIFE loader)
                plugin_root = dashboard_dir.parent
                static_html = plugin_root / "static" / "index.html"
                if static_html.is_file():
                    data = static_html.read_bytes()
                    handler.send_response(200)
                    handler.send_header("Content-Type", "text/html; charset=utf-8")
                    handler.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms allow-popups")
                    handler.send_header("Content-Length", str(len(data)))
                    handler.end_headers()
                    handler.wfile.write(data)
                    return True
                # 3) Fallback: generate shell that loads the IIFE bundle
                index_js = dashboard_dir / "dist" / "index.js"
                if index_js.is_file():
                    import html
                    label = html.escape(manifest.get("label") or name)
                    css = html.escape(manifest.get("css", ""))
                    name_escaped = html.escape(name)
                    css_tag = f'<link rel="stylesheet" href="/dashboard-plugins/{name_escaped}/{css}">' if css else ""
                    html_content = (
                        f"<!doctype html>\n"
                        f"<html lang=\"en\">\n"
                        f"<head>\n"
                        f"  <meta charset=\"utf-8\">\n"
                        f"  <title>{label}</title>\n"
                        f"  {css_tag}\n"
                        f"</head>\n"
                        f"<body>\n"
                        f'  <div id="pluginPageContainer"></div>\n'
                        f'  <script src="/dashboard-plugins/{name_escaped}/dist/index.js"></script>\n'
                        f"</body>\n"
                        f"</html>\n"
                    ).encode("utf-8")
                    handler.send_response(200)
                    handler.send_header("Content-Type", "text/html; charset=utf-8")
                    handler.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms allow-popups")
                    handler.send_header("Content-Length", str(len(html_content)))
                    handler.end_headers()
                    handler.wfile.write(html_content)
                    return True

    return False  # 404


# ── POST auth helpers

def _require_passkey_registration_auth(handler) -> tuple[bool, str, int]:
    """Require auth, or the existing local-only first-run bootstrap gate.

    Registering additional passkeys is an auth-factor enrollment action and
    requires a valid WebUI session.  The first passkey can still bootstrap a
    passkey-only instance, but only through the same local/private-network
    onboarding gate used for first password setup.
    """
    from api.auth import is_auth_enabled, parse_cookie, verify_session

    auth_enabled = is_auth_enabled()
    if not auth_enabled:
        if _onboarding_gate_allows(handler, auth_enabled):
            return True, "", 200
        return False, "Authentication required", 401
    cookie_val = parse_cookie(handler)
    if not cookie_val or not verify_session(cookie_val):
        return False, "Authentication required", 401
    return True, "", 200




def handle_post(handler, parsed) -> bool:
    """Handle all POST routes. Returns True if handled, False for 404."""
    from api.jaeger_browser import route as browser_route
    if browser_route(handler, parsed, "POST"):
        return True
    if not _csrf_exempt_path(parsed.path) and not _check_csrf(handler):
        return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
    from api import unified_api
    if unified_api.route(handler, parsed, "POST", read_body, j):
        return True
    try:
        from api.jaeger_agents import route as jaeger_agents_route
        if jaeger_agents_route(handler, parsed, "POST"):
            return True
    except Exception:
        pass
    from api.jaeger_conversation import route as conversation_route
    if conversation_route(handler, parsed, "POST"):
        return True
    diag = RequestDiagnostics.maybe_start("POST", parsed.path, logger=logger, print_fn=getattr(handler, '_safe_webui_print', None))
    if parsed.path == "/api/csp-report":
        if diag:
            diag.stage("csp_report")
        try:
            return _handle_csp_report(handler)
        finally:
            if diag:
                diag.finish()
    # CSRF: reject cross-origin or tokenless authenticated browser requests.
    # /api/auth/login has no authenticated session token yet, and /api/csp-report
    # is intentionally unauthenticated for browser-generated violation reports.
    if diag:
        diag.stage("csrf")
    if not _csrf_exempt_path(parsed.path) and not _check_csrf(handler):
        try:
            return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
        finally:
            if diag:
                diag.finish()
    proxy_result = _handle_extension_sidecar_proxy(
        handler,
        parsed,
        "POST",
        read_request_body=True,
    )
    if proxy_result is not False:
        if diag:
            diag.finish()
        return proxy_result







    if diag:
        diag.stage("read_body")
    try:
        body = read_body(handler)
    except ValueError as exc:
        if diag:
            diag.finish()
        status = 413 if "too large" in str(exc).lower() else 400
        return bad(handler, str(exc), status=status)
    except Exception:
        if diag:
            diag.finish()
        raise
    if not _guard_request_session_visibility(handler, parsed, body=body, method="POST"):
        if diag:
            diag.finish()
        return True















    if parsed.path == "/api/default-model":
        try:
            advanced = body.get("advanced") if isinstance(body, dict) else None
            provider = body.get("provider") if isinstance(body, dict) else None
            if str(provider or "").strip().lower() == "auto":
                provider = None
            return j(handler, set_hermes_default_model(body.get("model"), provider=provider, advanced=advanced))
        except ValueError as e:
            return bad(handler, str(e))
        except RuntimeError as e:
            return bad(handler, str(e), 500)


    # ── Providers (POST) ──
    if parsed.path == "/api/providers":
        provider_id = (body.get("provider") or "").strip().lower()
        api_key = body.get("api_key")
        if not provider_id:
            return bad(handler, "provider is required")
        if api_key is not None:
            api_key = str(api_key).strip() or None
        result = set_provider_key(provider_id, api_key)
        if not result.get("ok"):
            return bad(handler, result.get("error", "Unknown error"))
        return j(handler, result)


































    if parsed.path == "/api/terminal/start":
        return _handle_terminal_start(handler, body)

    if parsed.path == "/api/terminal/input":
        return _handle_terminal_input(handler, body)

    if parsed.path == "/api/terminal/resize":
        return _handle_terminal_resize(handler, body)

    if parsed.path == "/api/terminal/close":
        return _handle_terminal_close(handler, body)







    # ── Git workspace ops (POST) ──
    if parsed.path == "/api/git/stage":
        return _handle_git_stage(handler, body)

    if parsed.path == "/api/git/unstage":
        return _handle_git_unstage(handler, body)

    if parsed.path == "/api/git/discard":
        return _handle_git_discard(handler, body)

    if parsed.path == "/api/git/commit-message":
        return _handle_git_commit_message(handler, body)

    if parsed.path == "/api/git/commit-message-selected":
        return _handle_git_commit_message_selected(handler, body)

    if parsed.path == "/api/git/commit":
        return _handle_git_commit(handler, body)

    if parsed.path == "/api/git/commit-selected":
        return _handle_git_commit_selected(handler, body)

    if parsed.path == "/api/git/fetch":
        return _handle_git_remote_action(handler, body, "fetch")

    if parsed.path == "/api/git/pull":
        return _handle_git_remote_action(handler, body, "pull")

    if parsed.path == "/api/git/push":
        return _handle_git_remote_action(handler, body, "push")

    if parsed.path == "/api/git/checkout":
        return _handle_git_checkout(handler, body)

    if parsed.path == "/api/git/stash-checkout":
        return _handle_git_stash_checkout(handler, body)
























    if parsed.path in {"/v1/first-run/setup", "/v1/first-run/skip"}:
        import json as _json
        return _proxy_jaeger_gateway(handler, "POST", parsed.path, _json.dumps(body or {}).encode("utf-8"))

    # ── AppControl: proposals and Matthew's decisions (webui caller; CSRF-checked page) ──
    if parsed.path.startswith("/v1/apps/") and (parsed.path.endswith("/proposals") or parsed.path.endswith("/decision")
                                                or parsed.path.endswith("/rollback")):
        import json as _json
        return _proxy_jaeger_gateway(handler, "POST", parsed.path, _json.dumps(body or {}).encode("utf-8"))

    # ── Profile API (POST) ──
    # ── Jaeger Gateway handoff + approvals (POST) ──
    if parsed.path.endswith("/handoff") and (
        parsed.path.startswith("/api/agents/") or parsed.path.startswith("/v1/agents/")
    ):
        import json as _json
        suffix = parsed.path.split("/agents/", 1)[-1]
        raw = _json.dumps(body or {}).encode("utf-8")
        return _proxy_jaeger_gateway(handler, "POST", f"/v1/agents/{suffix}", raw)

    if parsed.path.startswith("/api/approvals/") or parsed.path.startswith("/v1/approvals/"):
        import json as _json
        suffix = parsed.path.split("/approvals/", 1)[-1]
        raw = _json.dumps(body or {}).encode("utf-8")
        return _proxy_jaeger_gateway(handler, "POST", f"/v1/approvals/{suffix}", raw)

    if parsed.path.endswith("/handoff") and (
        parsed.path.startswith("/api/sessions/") or parsed.path.startswith("/v1/sessions/")
    ):
        import json as _json
        suffix = parsed.path.split("/sessions/", 1)[-1]
        raw = _json.dumps(body or {}).encode("utf-8")
        return _proxy_jaeger_gateway(handler, "POST", f"/v1/sessions/{suffix}", raw)

    # ── Jaeger Gateway agents (POST) ──
    if parsed.path in {"/api/agents", "/v1/agents"}:
        import json as _json
        raw = _json.dumps(body or {}).encode("utf-8")
        return _proxy_jaeger_gateway(handler, "POST", "/v1/agents", raw)

    if parsed.path.endswith("/activate") and (
        parsed.path.startswith("/api/agents/") or parsed.path.startswith("/v1/agents/")
    ):
        suffix = parsed.path.split("/agents/", 1)[-1]
        return _proxy_jaeger_gateway(handler, "POST", f"/v1/agents/{suffix}")




    # ── Settings (POST) ──
    if parsed.path == "/api/settings":
        from api.auth import (
            create_session,
            get_password_hash,
            is_auth_enabled,
            parse_cookie,
            set_auth_cookie,
            verify_password,
            verify_session,
        )

        if "bot_name" in body:
            body["bot_name"] = (str(body["bot_name"]) or "").strip() or "Hermes"

        auth_enabled_before = is_auth_enabled()
        password_auth_enabled_before = auth_enabled_before and get_password_hash() is not None
        current_cookie = parse_cookie(handler)
        logged_in_before = bool(current_cookie and verify_session(current_cookie))
        requested_password = bool(
            isinstance(body.get("_set_password"), str)
            and body.get("_set_password", "").strip()
        )
        requested_passwordless = bool(body.pop("_passwordless", False))
        requested_clear_password = bool(body.get("_clear_password") or requested_passwordless)
        if requested_passwordless:
            body["_clear_password"] = True

        current_password = body.pop("_current_password", None)

        # #1560: HERMES_WEBUI_PASSWORD env var takes precedence in
        # api.auth.get_password_hash(), so writing password_hash to settings.json
        # has no effect on auth. Refuse loudly with 409 instead of silently
        # succeeding — the previous behaviour returned 200 + a green save toast
        # while every subsequent login still required the env-var password.
        if requested_password or requested_clear_password:
            if os.getenv("HERMES_WEBUI_PASSWORD", "").strip():
                return bad(
                    handler,
                    "HERMES_WEBUI_PASSWORD env var is set — it overrides the settings password. "
                    "Unset the env var and restart the server before changing the password here.",
                    409,
                )

        max_tokens_provided = "max_tokens" in body
        max_tokens_status = None
        max_tokens_value = body.pop("max_tokens", None) if max_tokens_provided else None

        # First password creation decides who owns a previously passwordless
        # WebUI. While auth is disabled, the generic /api/settings route is also
        # unauthenticated, so gate bootstrap password setup the same way as
        # onboarding setup: local/private networks only, unless the operator
        # explicitly opts into remote bootstrap with HERMES_WEBUI_ONBOARDING_OPEN.
        if requested_password and not auth_enabled_before:
            if not _onboarding_gate_allows(handler, auth_enabled_before):
                return bad(
                    handler,
                    "First password setup is only available from local networks when auth is not enabled. "
                    "To bootstrap this on a remote server, set HERMES_WEBUI_ONBOARDING_OPEN=1.",
                    403,
                )

        # Auth-disable safety: when password auth is currently enabled, require
        # the current password to change, clear, or switch to passwordless.
        if auth_enabled_before and password_auth_enabled_before and (requested_password or requested_clear_password):
            if not isinstance(current_password, str) or not current_password:
                return bad(
                    handler,
                    "Current password is required to change or disable authentication.",
                    403,
                )
            if not verify_password(current_password):
                return bad(
                    handler,
                    "Current password is incorrect.",
                    403,
                )

        if requested_passwordless:
            from api.auth import _passkey_feature_flag_enabled
            from api.passkeys import registered_credentials

            if not _passkey_feature_flag_enabled():
                return bad(handler, "Passkey support is disabled. Enable HERMES_WEBUI_PASSKEY before going passwordless.", 409)
            if not registered_credentials():
                return bad(handler, "Register a passkey before going passwordless.", 409)
        elif requested_clear_password:
            from api.passkeys import clear_credentials

            clear_credentials()

        # Handle auth_disabled_acknowledged setting
        ack = body.pop("_auth_disabled_acknowledged", None)
        if ack is not None and not is_auth_enabled():
            body["auth_disabled_acknowledged"] = bool(ack)
        elif is_auth_enabled() or requested_password:
            body["auth_disabled_acknowledged"] = False

        from api.config import get_max_tokens_status, set_max_tokens

        saved = save_settings(body)
        saved["persisted_speech_keys"] = persisted_speech_settings_keys()
        if max_tokens_provided:
            max_tokens_status = set_max_tokens(max_tokens_value)
        saved.pop("password_hash", None)  # never expose hash to client
        saved.update(max_tokens_status if max_tokens_provided else get_max_tokens_status())

        # Settings that change which sessions appear in the sidebar must
        # invalidate the session-list cache directly. Relying on the cache's
        # settings-file mtime stamp is fragile: a toggle that writes the
        # settings file within the same mtime granularity as a cached entry (and
        # produces the default-valued key, e.g. show_cli_sessions back to its
        # True default) can leave a stale row set served for up to the cache TTL.
        # This is the root cause of the intermittent gateway_sync test flake
        # (a freshly-inserted CLI/gateway session occasionally absent from
        # /api/sessions right after the visibility toggle). Invalidate explicitly.
        if any(
            k in body
            for k in (
                "show_cli_sessions",
                "show_claude_code_sessions",
                "show_cron_sessions",
                "show_webhook_sessions",
                "show_kanban_sessions",
                "show_previous_messaging_sessions",
            )
        ):
            try:
                _clear_session_list_cache()
            except Exception:
                pass
            try:
                from api.models import clear_cli_sessions_cache
                clear_cli_sessions_cache()
            except Exception:
                pass

        auth_enabled_after = is_auth_enabled()
        auth_just_enabled = bool(
            requested_password and auth_enabled_after and not auth_enabled_before
        )
        logged_in_after = logged_in_before
        new_cookie = None

        if auth_just_enabled and not logged_in_before:
            new_cookie = create_session()
            logged_in_after = True

        saved["auth_enabled"] = auth_enabled_after
        saved["password_auth_enabled"] = get_password_hash() is not None
        saved["logged_in"] = logged_in_after
        saved["auth_just_enabled"] = auth_just_enabled
        try:
            from api.auth import _passkey_feature_flag_enabled as _pffe
            from api.passkeys import registered_credentials as _rc
            if _pffe():
                saved["passkeys_enabled"] = bool(_rc())
                saved["passwordless_enabled"] = bool(_rc()) and not saved["password_auth_enabled"]
            else:
                saved["passkeys_enabled"] = False
                saved["passwordless_enabled"] = False
        except Exception:
            pass

        if not new_cookie:
            return j(handler, saved)

        response_body = json.dumps(saved, ensure_ascii=False, indent=2).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(response_body)))
        handler.send_header("Cache-Control", "no-store")
        set_auth_cookie(handler, new_cookie)
        _security_headers(handler)
        handler.end_headers()
        handler.wfile.write(response_body)
        return True


















    # ── Auth endpoints (POST) ──
    if parsed.path == "/api/auth/login":
        from api.auth import (
            verify_password,
            create_session,
            set_auth_cookie,
            is_auth_enabled,
        )
        from api.auth import _check_login_rate, _record_login_attempt, _clear_login_attempts

        if not is_auth_enabled():
            return j(handler, {"ok": True, "message": "Auth not enabled"})
        client_ip = handler.client_address[0]
        if not _check_login_rate(client_ip):
            return j(
                handler,
                {"error": "Too many attempts. Try again in a minute."},
                status=429,
            )
        password = body.get("password", "")
        if not verify_password(password):
            _record_login_attempt(client_ip)
            return bad(handler, "Invalid password", 401)
        _clear_login_attempts(client_ip)
        cookie_val = create_session()
        body = json.dumps({"ok": True}).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        _security_headers(handler)
        set_auth_cookie(handler, cookie_val)
        handler.end_headers()
        handler.wfile.write(body)
        return True

    if parsed.path == "/api/auth/passkey/options":
        from api.auth import _passkey_feature_flag_enabled, is_auth_enabled
        from api.passkeys import PasskeyError, PasskeyRateLimitError, authentication_options

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled. Set HERMES_WEBUI_PASSKEY=1 or webui_passkey_enabled: true to enable."}, status=404)
        if not is_auth_enabled():
            return j(handler, {"error": "Auth not enabled"}, status=400)
        try:
            return j(handler, {"ok": True, "publicKey": authentication_options(handler)})
        except PasskeyRateLimitError as e:
            return bad(handler, str(e), status=429)
        except PasskeyError as e:
            return bad(handler, str(e), status=400)

    if parsed.path == "/api/auth/passkey/login":
        from api.auth import _passkey_feature_flag_enabled, create_session, is_auth_enabled, set_auth_cookie
        from api.auth import _check_login_rate, _record_login_attempt
        from api.passkeys import PasskeyError, finish_login

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        if not is_auth_enabled():
            return j(handler, {"error": "Auth not enabled"}, status=400)
        client_ip = handler.client_address[0]
        if not _check_login_rate(client_ip):
            return j(handler, {"error": "Too many attempts. Try again in a minute."}, status=429)
        try:
            finish_login(body, handler)
        except PasskeyError as e:
            _record_login_attempt(client_ip)
            return bad(handler, str(e), status=401)
        cookie_val = create_session()
        body = json.dumps({"ok": True}).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        _security_headers(handler)
        set_auth_cookie(handler, cookie_val)
        handler.end_headers()
        handler.wfile.write(body)
        return True

    if parsed.path == "/api/auth/passkey/register/options":
        from api.auth import _passkey_feature_flag_enabled
        from api.passkeys import PasskeyError, PasskeyRateLimitError, registration_options

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        ok, error, status = _require_passkey_registration_auth(handler)
        if not ok:
            return j(handler, {"error": error}, status=status)
        try:
            return j(handler, {"ok": True, "publicKey": registration_options(handler)})
        except PasskeyRateLimitError as e:
            return bad(handler, str(e), status=429)
        except PasskeyError as e:
            return bad(handler, str(e), status=400)

    if parsed.path == "/api/auth/passkey/register":
        from api.auth import _passkey_feature_flag_enabled
        from api.passkeys import PasskeyError, finish_registration, registered_credentials

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        ok, error, status = _require_passkey_registration_auth(handler)
        if not ok:
            return j(handler, {"error": error}, status=status)
        try:
            result = finish_registration(body, handler)
            result["credentials"] = registered_credentials()
            return j(handler, result)
        except PasskeyError as e:
            return bad(handler, str(e), status=400)

    if parsed.path == "/api/auth/passkey/delete":
        from api.auth import _passkey_feature_flag_enabled, get_password_hash
        from api.passkeys import PasskeyError, delete_credential, registered_credentials

        if not _passkey_feature_flag_enabled():
            return j(handler, {"error": "Passkey support is disabled."}, status=404)
        try:
            credential_id = str(body.get("id") or "")
            creds = registered_credentials()
            if get_password_hash() is None and len(creds) <= 1 and any(c.get("id") == credential_id for c in creds):
                return bad(handler, "Set a password or disable auth before removing the last passkey.", 409)
            return j(handler, delete_credential(credential_id))
        except PasskeyError as e:
            return bad(handler, str(e), status=404)

    if parsed.path == "/api/auth/passkeys":
        from api.auth import _passkey_feature_flag_enabled
        from api.passkeys import registered_credentials

        if not _passkey_feature_flag_enabled():
            return j(handler, {"credentials": [], "disabled": True})
        return j(handler, {"credentials": registered_credentials()})

    if parsed.path == "/api/auth/logout":
        from api.auth import clear_auth_cookie, ensure_trusted_auth_session, get_trusted_auth_logout_url, invalidate_session, parse_cookie
        from api.helpers import clear_profile_cookie

        session_info = ensure_trusted_auth_session(handler)
        cookie_val = getattr(handler, '_trusted_auth_session_cookie_value', None) or parse_cookie(handler)
        if cookie_val:
            invalidate_session(cookie_val)
        payload = {"ok": True}
        if session_info and session_info.get("auth_type") == "trusted":
            logout_url = get_trusted_auth_logout_url()
            if logout_url:
                payload["trusted_logout_url"] = logout_url
        body = json.dumps(payload).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        _security_headers(handler)
        clear_auth_cookie(handler)
        clear_profile_cookie(handler)
        handler.end_headers()
        handler.wfile.write(body)
        return True


    return False  # 404


def handle_patch(handler, parsed) -> bool:
    """Handle all PATCH routes. Returns True if handled, False for 404."""
    if not _check_csrf(handler):
        return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
    from api import unified_api
    if unified_api.route(handler, parsed, "PATCH", read_body, j):
        return True
    try:
        from api.jaeger_agents import route as jaeger_agents_route
        if jaeger_agents_route(handler, parsed, "PATCH"):
            return True
    except Exception:
        pass
    proxy_result = _handle_extension_sidecar_proxy(
        handler,
        parsed,
        "PATCH",
        read_request_body=True,
    )
    if proxy_result is not False:
        return proxy_result
    body = read_body(handler)
    if not _guard_request_session_visibility(handler, parsed, body=body, method="PATCH"):
        return True
    return False


def handle_delete(handler, parsed) -> bool:
    """Handle all DELETE routes. Returns True if handled, False for 404."""
    if not _check_csrf(handler):
        return j(handler, {"error": _csrf_rejection_error(handler)}, status=403)
    from api import unified_api
    if unified_api.route(handler, parsed, "DELETE", read_body, j):
        return True
    try:
        from api.jaeger_agents import route as jaeger_agents_route
        if jaeger_agents_route(handler, parsed, "DELETE"):
            return True
    except Exception:
        pass
    proxy_result = _handle_extension_sidecar_proxy(
        handler,
        parsed,
        "DELETE",
        read_request_body=True,
    )
    if proxy_result is not False:
        return proxy_result
    body = read_body(handler)
    if not _guard_request_session_visibility(handler, parsed, body=body, method="DELETE"):
        return True

    return False


def handle_put(handler, parsed) -> bool:
    """Handle all PUT routes. Returns True if handled, False for 404."""
    if not _check_csrf(handler):
        return j(handler, {"error": "Cross-origin request rejected"}, status=403)
    from api import unified_api
    if unified_api.route(handler, parsed, "PUT", read_body, j):
        return True
    proxy_result = _handle_extension_sidecar_proxy(
        handler,
        parsed,
        "PUT",
        read_request_body=True,
    )
    if proxy_result is not False:
        return proxy_result
    body = read_body(handler)
    if not _guard_request_session_visibility(handler, parsed, body=body, method="PUT"):
        return True
    if parsed.path == "/v1/dashboard":
        from api import dashboard_store
        try:
            return j(handler, dashboard_store.write(body))
        except ValueError as exc:
            return j(handler, {"error": str(exc)}, status=400)
    return False

# ── GET route helpers ─────────────────────────────────────────────────────────

# MIME types for static file serving. Hoisted to module scope to avoid
# rebuilding the dict on every request.
_STATIC_MIME = {
    "css": "text/css",
    "js": "application/javascript",
    "html": "text/html",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "ico": "image/x-icon",
    "gif": "image/gif",
    "webp": "image/webp",
    "woff": "font/woff",
    "woff2": "font/woff2",
}
# MIME types that are text-based and should carry charset=utf-8
_TEXT_MIME_TYPES = {"text/css", "application/javascript", "text/html", "image/svg+xml", "text/plain"}

# MIME types worth gzipping. Image and font formats (png/jpg/webp/woff2) are
# already compressed; gzip would only add CPU and a few bytes of framing.
_COMPRESSIBLE_MIME = {
    "text/css", "application/javascript", "text/html", "image/svg+xml",
    "application/json", "text/plain",
}

# In-process cache for raw bytes, compressed bytes, and ETag. The cache is keyed
# by absolute path and invalidated on (size, high-precision mtime) change, so a
# redeploy is picked up without a process restart. Missing/random paths never
# enter the cache; memory cost is bounded by the static/ tree's served files.
_STATIC_CACHE: dict = {}
_STATIC_CACHE_LOCK = threading.Lock()


def _serve_static(handler, parsed):
    static_root = api_config.get_static_root().resolve()
    # Strip the leading '/static/' prefix, then resolve and sandbox
    rel = parsed.path[len("/static/") :]
    static_file = (static_root / rel).resolve()
    try:
        static_file.relative_to(static_root)
    except ValueError:
        assets_root = (api_config.REPO_ROOT.parents[1] / "assets").resolve()
        try:
            static_file.relative_to(assets_root)
        except ValueError:
            return j(handler, {"error": "not found"}, status=404)
    if not static_file.exists() or not static_file.is_file():
        return j(handler, {"error": "not found"}, status=404)
    ext = static_file.suffix.lower()
    ct = _STATIC_MIME.get(ext.lstrip("."), "text/plain")
    ct_header = f"{ct}; charset=utf-8" if ct in _TEXT_MIME_TYPES else ct

    # Look up or populate the per-file cache (raw, optional gzip, ETag).
    # Keyed by absolute path; invalidated by (size, nanosecond mtime).
    st = static_file.stat()
    sig = (st.st_size, st.st_mtime_ns)
    cache_key = str(static_file)
    raw = gz = etag = None
    with _STATIC_CACHE_LOCK:
        cached = _STATIC_CACHE.get(cache_key)
        if cached and cached[0] == sig:
            _, raw, gz, etag = cached
    if raw is None:
        raw = static_file.read_bytes()
        # Weak ETag: equality semantics, derived from filesystem identity.
        etag = f'W/"{sig[0]:x}-{sig[1]:x}"'
        gz = (gzip.compress(raw, compresslevel=6)
              if ct in _COMPRESSIBLE_MIME and len(raw) > 1024
              else None)
        with _STATIC_CACHE_LOCK:
            _STATIC_CACHE[cache_key] = (sig, raw, gz, etag)

    # The page template substitutes __WEBUI_VERSION__ at request time (see the
    # `/`/`/index.html`/`/session/` branch above), and static/sw.js's
    # SHELL_ASSETS list relies on the same convention. So a fingerprinted URL
    # is safe to cache aggressively: any redeploy changes the URL.
    version_values = parse_qs(parsed.query, keep_blank_values=True).get("v", [""])
    has_fingerprint = bool(version_values[0])
    cache_control = (
        "public, max-age=31536000, immutable" if has_fingerprint
        else "public, max-age=300"
    )

    # 304 short-circuit on conditional GET.
    if handler.headers.get("If-None-Match") == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", cache_control)
        if gz is not None:
            handler.send_header("Vary", "Accept-Encoding")
        handler.end_headers()
        return True

    accept_enc = (handler.headers.get("Accept-Encoding") or "").lower()
    use_gzip = gz is not None and "gzip" in accept_enc
    body = gz if use_gzip else raw

    handler.send_response(200)
    handler.send_header("Content-Type", ct_header)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("ETag", etag)
    handler.send_header("Cache-Control", cache_control)
    if gz is not None:
        handler.send_header("Vary", "Accept-Encoding")
    if use_gzip:
        handler.send_header("Content-Encoding", "gzip")
    handler.end_headers()
    handler.wfile.write(body)
    return True










def _handle_list_dir(handler, parsed):
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")
    webui_session = None
    try:
        s = get_session_for_file_ops(sid)
        from api.models import _ExternalSessionView
        webui_session = None if isinstance(s, _ExternalSessionView) else s
        workspace = s.workspace
    except KeyError:
        return bad(handler, "Session not found", 404)
    try:
        if webui_session is None:
            workspace = resolve_trusted_workspace(workspace)
            recovered = False
        else:
            stored_workspace = workspace
            workspace, recovered = resolve_implicit_workspace_with_recovery(
                stored_workspace,
                get_last_workspace,
            )
            if recovered:
                persisted = persist_recovered_workspace_binding(
                    webui_session,
                    workspace,
                    expected_workspace=stored_workspace,
                )
                workspace = Path(persisted.workspace)
        rel_path = qs.get("path", ["."])[0]
        entries = list_dir(Path(workspace), rel_path)
        return j(
            handler,
            {
                "entries": serialize_workspace_entries_for_browser(entries),
                "signature": dir_signature(Path(workspace), rel_path, entries),
                "path": rel_path,
                "workspace": str(workspace),
                "workspace_recovered": recovered,
            },
        )
    except WorkspaceBindingPersistenceError as e:
        return bad(handler, _sanitize_error(e), 500)
    except (FileNotFoundError, ValueError) as e:
        return bad(handler, _sanitize_error(e), 404)












def _sse_with_id(handler, event, data, event_id=None):
    if event_id:
        handler.wfile.write(f"id: {event_id}\n".encode("utf-8"))
    _sse(handler, event, data)


def _session_events_path_session_id(path: str | None) -> str | None:
    path = str(path or "")
    parts = path.strip("/").split("/")
    if len(parts) != 4:
        return None
    if parts[0] != "api" or parts[1] != "sessions" or parts[3] != "events":
        return None
    sid = str(parts[2] or "").strip()
    return sid or None


def _session_events_resume_event_id(handler, parsed) -> str | None:
    headers = getattr(handler, "headers", None)
    raw = None
    if headers is not None:
        try:
            raw = headers.get("Last-Event-ID")
        except Exception:
            raw = None
    raw = str(raw or "").strip()
    if raw:
        return raw
    qs = parse_qs(getattr(parsed, "query", "") or "")
    raw = str(qs.get("after_event_id", [None])[0] or "").strip()
    return raw or None


def _session_snapshot_payload(session, *, active_stream_id: str | None = None) -> dict:
    try:
        payload = session.compact(
            include_runtime=bool(active_stream_id),
            active_stream_ids={active_stream_id} if active_stream_id else None,
        )
    except Exception:
        payload = {"session_id": str(getattr(session, "session_id", "") or "")}
    return {"session": payload}


def _parse_run_journal_event_id(raw: str | None) -> tuple[str | None, int | None]:
    return _shared_parse_run_journal_event_id(raw)










def _run_journal_same_run_seq(event_id: str | None, stream_id: str) -> int | None:
    event_run_id, event_seq = _parse_run_journal_event_id(event_id)
    if event_run_id != stream_id:
        return None
    return event_seq










def _runner_event_name(entry: dict) -> str:
    return str(entry.get("event") or entry.get("type") or "message")


def _runner_event_payload(entry: dict):
    if "payload" in entry:
        return entry.get("payload")
    if "data" in entry:
        return entry.get("data")
    return entry







def _persist_runner_done_to_webui_session(session_id: str, done_payload, *, run_id: str | None = None) -> bool:
    """Write runner-local terminal ``done.session`` into the WebUI sidecar.

    Runner-local owns execution outside WebUI ``STREAMS``, so the SSE relay
    alone never commits messages. Without this writeback, GET /api/session
    stays empty after a successful turn (and the sidebar never lists it).
    Idempotent when messages already match the done payload length.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return False
    payload = done_payload if isinstance(done_payload, dict) else {}
    embedded = payload.get("session") if isinstance(payload.get("session"), dict) else None
    if embedded is None and ("messages" in payload or "context_messages" in payload):
        embedded = payload
    try:
        from api.models import Session, get_session
        from api.config import LOCK, SESSIONS
    except Exception:
        logger.exception("runner writeback imports failed for session %s", sid)
        return False
    try:
        try:
            s = get_session(sid)
        except KeyError:
            s = Session.load(sid)
            if s is None:
                # Materialize a WebUI sidecar for first-turn deferred sessions.
                s = Session(
                    session_id=sid,
                    title=str((embedded or {}).get("title") or "Untitled"),
                    workspace=str((embedded or {}).get("workspace") or ""),
                    model=str((embedded or {}).get("model") or ""),
                    model_provider=(embedded or {}).get("model_provider"),
                    profile=str((embedded or {}).get("profile") or "default"),
                )

        messages = (embedded or {}).get("messages")
        if not isinstance(messages, list) or not messages:
            output_text = str(payload.get("output") or payload.get("text") or "").strip()
            if output_text:
                user_msg = str(getattr(s, "pending_user_message", None) or getattr(s, "last_user_message", None) or "")
                existing_clean = [
                    m for m in (getattr(s, "messages", None) or [])
                    if not (isinstance(m, dict) and (m.get("_error") or "Response interrupted" in str(m.get("content", ""))))
                ]
                if user_msg and (not existing_clean or existing_clean[-1].get("content") != user_msg):
                    existing_clean.append({
                        "role": "user",
                        "content": user_msg,
                        "timestamp": int(getattr(s, "pending_started_at", None) or time.time()),
                    })
                existing_clean.append({
                    "role": "assistant",
                    "content": output_text,
                    "timestamp": int(time.time()),
                })
                messages = existing_clean

        if not isinstance(messages, list) or not messages:
            return False

        existing = list(getattr(s, "messages", None) or [])
        has_error_marker = any(
            isinstance(m, dict) and (m.get("_error") or "Response interrupted" in str(m.get("content", "")))
            for m in existing
        )
        if len(existing) >= len(messages) and not has_error_marker:
            # Already persisted (or longer); still clear pending/stream markers.
            pass
        else:
            s.messages = [dict(m) if isinstance(m, dict) else m for m in messages]
        if embedded and embedded.get("title"):
            s.title = embedded.get("title")
        if embedded and embedded.get("model"):
            s.model = embedded.get("model")
        if embedded and embedded.get("model_provider") is not None:
            s.model_provider = embedded.get("model_provider")
        s.message_count = len(s.messages or [])
        s.pending_user_message = None
        s.pending_attachments = []
        s.pending_started_at = None
        s.pending_user_source = None
        s.active_stream_id = None
        s.is_streaming = False
        if not getattr(s, "profile", None):
            s.profile = (embedded or {}).get("profile") or "default"
        if not getattr(s, "source", None):
            try:
                s.source = "webui"
            except Exception:
                pass
        s.save()
        try:
            with LOCK:
                SESSIONS[sid] = s
                SESSIONS.move_to_end(sid)
        except Exception:
            logger.debug("runner writeback LRU update failed for %s", sid, exc_info=True)
        logger.info(
            "runner writeback persisted session %s run=%s messages=%s",
            sid,
            run_id,
            len(s.messages or []),
        )
        return True
    except Exception:
        logger.exception("runner writeback failed for session %s run=%s", sid, run_id)
        return False


def _spawn_runner_session_writeback(run_id: str, session_id: str) -> None:
    """Background observer: persist done.session even if no browser SSE attaches."""
    rid = str(run_id or "").strip()
    sid = str(session_id or "").strip()
    if not rid or not sid:
        return
    with _RUNNER_WRITEBACK_LOCK:
        if rid in _RUNNER_WRITEBACK_STARTED:
            return
        _RUNNER_WRITEBACK_STARTED.add(rid)

    try:
        from api.config import register_active_run
        register_active_run(rid, session_id=sid, runner=True)
    except Exception:
        pass

    def _worker():
        try:
            from api.runtime_adapter import RunnerRuntimeAdapter
            from api.runner_client import runner_client_configured

            if not runner_client_configured():
                return
            adapter = RunnerRuntimeAdapter(client=_runtime_runner_client_factory())
            if adapter is None:
                return
            cursor = None
            deadline = time.time() + 900  # 15m safety
            while time.time() < deadline:
                try:
                    event_stream = adapter.observe_run(rid, cursor=cursor)
                except Exception:
                    logger.debug("runner writeback observe failed for %s", rid, exc_info=True)
                    time.sleep(0.5)
                    continue
                for entry in list(getattr(event_stream, "events", []) or []):
                    if not isinstance(entry, dict):
                        continue
                    event = _runner_event_name(entry)
                    payload = _runner_event_payload(entry)
                    if event in ("done", "error", "apperror", "stream_end", "run.completed", "run.failed", "run.cancelled") or event in SSE_RELAY_CLOSE_EVENTS:
                        if isinstance(payload, dict):
                            _persist_runner_done_to_webui_session(sid, payload, run_id=rid)
                        return
                next_cursor = getattr(event_stream, "cursor", None)
                if next_cursor not in (None, ""):
                    cursor = str(next_cursor)
                try:
                    status = adapter.get_run(rid)
                except Exception:
                    status = None
                state = str(getattr(status, "terminal_state", None) or getattr(status, "status", "") or "").lower()
                if state in ("completed", "complete", "failed", "error", "cancelled", "canceled"):
                    # Terminal without a done payload — still try one more observe from start
                    try:
                        final = adapter.observe_run(rid, cursor=None)
                        for entry in list(getattr(final, "events", []) or []):
                            if isinstance(entry, dict) and _runner_event_name(entry) in ("done", "error", "apperror", "run.completed", "run.failed", "run.cancelled"):
                                _persist_runner_done_to_webui_session(sid, _runner_event_payload(entry), run_id=rid)
                                return
                    except Exception:
                        logger.debug("runner writeback final observe failed for %s", rid, exc_info=True)
                    return
                time.sleep(0.25)
        except Exception:
            logger.exception("runner writeback worker crashed for run %s", rid)
        finally:
            try:
                from api.config import unregister_active_run
                unregister_active_run(rid)
            except Exception:
                pass
            with _RUNNER_WRITEBACK_LOCK:
                _RUNNER_WRITEBACK_STARTED.discard(rid)

    threading.Thread(target=_worker, name=f"runner-writeback-{rid[:12]}", daemon=True).start()






def _handle_session_run_journal_stream_for_session(handler, parsed, session_id):
    if not _session_id_visible_to_request_profile(handler, session_id):
        return True
    try:
        session = get_session(session_id, metadata_only=True)
    except KeyError:
        return j(handler, {"error": "Session not found"}, status=404)

    # Parse the resume cursor and baseline the journal BEFORE committing SSE headers
    # (and thus before any run could complete mid-handler). Capturing after
    # end_sse_headers() leaves a window where a run finishing between header commit
    # and baseline is absorbed into the baseline and silently lost. Both operations
    # are side-effect-free (header read + stat-only fingerprint), safe pre-response.
    resume_event_id = _session_events_resume_event_id(handler, parsed)
    _idle_journal_fp = session_journal_fingerprint(session_id)

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("X-Accel-Buffering", "no")
    # #3103: see _handle_gateway_sse_stream — `Connection: close` causes
    # EventSource reconnect storms in browsers on long-lived SSE.
    end_sse_headers(handler)
    _sse_set_write_deadline(handler)

    active_stream_id = _active_run_stream_for_session(session_id)
    subscriber = None
    subscriber_stream = None
    replay_cutoff_seq = None
    sent_event_ids: set[str] = set()
    sent_event_order = deque()

    def note_sent_event_id(event_id):
        if not event_id:
            return
        sent_event_ids.add(event_id)
        sent_event_order.append(event_id)
        while len(sent_event_order) > _SESSION_SSE_SENT_EVENT_ID_LIMIT:
            sent_event_ids.discard(sent_event_order.popleft())

    def attach_active_stream():
        stream_id = _active_run_stream_for_session(session_id)
        stream = STREAMS.get(stream_id) if stream_id else None
        if stream is None:
            return None, None, None, stream_id
        if hasattr(stream, "subscribe_with_snapshot"):
            queue_, snapshot = stream.subscribe_with_snapshot()
        else:
            queue_ = stream.subscribe() if hasattr(stream, "subscribe") else stream
            snapshot = {}
        return queue_, stream, snapshot, stream_id

    def emit_replay(events, stream_id, cutoff_seq):
        for entry in events:
            event_id = str(entry.get("event_id") or "")
            event_seq = _run_journal_same_run_seq(event_id, stream_id)
            if cutoff_seq is not None and event_seq is not None and event_seq > cutoff_seq:
                continue
            if event_id and event_id in sent_event_ids:
                continue
            _sse_with_id(handler, entry.get("event") or entry.get("type") or "message", entry.get("payload"), event_id)
            if event_id:
                note_sent_event_id(event_id)

    def emit_session_snapshot(active_stream_id):
        try:
            fresh_session = get_session(session_id, metadata_only=True)
        except KeyError:
            fresh_session = session
        _sse(handler, "session_snapshot", _session_snapshot_payload(fresh_session, active_stream_id=active_stream_id))

    try:
        replay_events = []
        replay_ok = False
        if resume_event_id:
            replay = read_session_run_events(session_id, after_event_id=resume_event_id)
            if replay.get("status") != "ok":
                emit_session_snapshot(active_stream_id)
            else:
                replay_ok = True
                replay_events = replay.get("events") or []
        subscriber, subscriber_stream, stream_snapshot, active_stream_id = attach_active_stream()
        if subscriber is None:
            if replay_ok:
                emit_replay(replay_events, active_stream_id, None)
            while True:
                subscriber, subscriber_stream, stream_snapshot, active_stream_id = attach_active_stream()
                if subscriber is not None:
                    break
                # Journal advanced with no live stream to attach → a run completed
                # entirely within the wait (or the first attach). Re-sync via a
                # snapshot boundary (the same honest-recovery contract used for a
                # failed reconciliation), then re-baseline so we only re-sync on
                # genuinely new advances.
                _current_journal_fp = session_journal_fingerprint(session_id)
                if _current_journal_fp != _idle_journal_fp:
                    _idle_journal_fp = _current_journal_fp
                    emit_session_snapshot(active_stream_id)
                handler.wfile.write(b": keepalive\n\n")
                handler.wfile.flush()
                time.sleep(_SSE_HEARTBEAT_INTERVAL_SECONDS)
        if subscriber is None:
            return True
        if replay_ok:
            replay_cutoff_seq = _run_journal_same_run_seq(str(stream_snapshot.get("last_event_id") or ""), active_stream_id)
            reconciled = read_session_run_events(session_id, after_event_id=resume_event_id)
            if reconciled.get("status") == "ok":
                emit_replay(reconciled.get("events") or [], active_stream_id, replay_cutoff_seq)
            else:
                emit_session_snapshot(active_stream_id)
        try:
            while True:
                try:
                    item = subscriber.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
                except queue.Empty:
                    handler.wfile.write(b": keepalive\n\n")
                    handler.wfile.flush()
                    continue
                if len(item) >= 3:
                    event, data, queued_event_id = item[0], item[1], item[2]
                else:
                    event, data = item
                    queued_event_id = STREAM_LAST_EVENT_ID.get(active_stream_id)
                event_id = queued_event_id or STREAM_LAST_EVENT_ID.get(active_stream_id)
                event_seq = _run_journal_same_run_seq(event_id, active_stream_id)
                _is_terminal = event in SSE_RELAY_CLOSE_EVENTS
                _already_sent = (
                    (replay_cutoff_seq is not None and event_seq is not None and event_seq <= replay_cutoff_seq)
                    or (event_id and event_id in sent_event_ids)
                )
                if _already_sent:
                    # Already delivered via replay/reconciliation (cutoff or dedup).
                    # A terminal event still has to end this loop — otherwise, when
                    # reconciliation replayed the active run's terminal at the cutoff,
                    # the live copy would be skipped here and the handler would stay
                    # blocked on a dead run's queue and miss subsequent session runs.
                    if _is_terminal:
                        break
                    continue
                if event_id:
                    _sse_with_id(handler, event, data, event_id)
                    note_sent_event_id(event_id)
                else:
                    _sse(handler, event, data)
                if _is_terminal:
                    break
        except _CLIENT_DISCONNECT_ERRORS:
            pass
    except _CLIENT_DISCONNECT_ERRORS:
        pass
    finally:
        if subscriber is not None and subscriber is not subscriber_stream and hasattr(subscriber_stream, "unsubscribe"):
            try:
                subscriber_stream.unsubscribe(subscriber)
            except Exception:
                pass
    return True


_handle_session_sse_stream_for_session = _handle_session_run_journal_stream_for_session


# (Terminal endpoints extracted to api.route_terminal)


def _gateway_sse_probe_payload(settings, watcher):
    enabled = bool(settings.get('show_cli_sessions'))
    # Use the public is_alive() accessor where available (current GatewayWatcher);
    # fall back to the private _thread check for any older in-memory instance
    # that might still be hanging around mid-upgrade, and for test doubles that
    # don't implement the full public API.
    if watcher is None:
        watcher_alive = False
    elif hasattr(watcher, 'is_alive') and callable(getattr(watcher, 'is_alive')):
        watcher_alive = bool(watcher.is_alive())
    else:
        _t = getattr(watcher, '_thread', None)
        watcher_alive = _t is not None and _t.is_alive()
    payload = {
        'enabled': enabled,
        'fallback_poll_ms': 30000,
        'ok': enabled and watcher_alive,
        'watcher_running': watcher_alive,
        # Cross-client scope markers (hermes-webui/hermes-android#58 follow-up):
        # this probe ONLY describes the optional gateway/agent-sessions stream.
        # Persistent per-session streaming (GET /api/session/stream) is always
        # available and is NOT gated by show_cli_sessions, so a negative gateway
        # probe result must not be read as "session SSE unavailable".
        'scope': 'gateway_sessions',
        'session_stream_available': True,
        'session_stream_path': '/api/session/stream',
    }
    if not enabled:
        payload['error'] = 'agent sessions not enabled'
        return payload, 404
    if not watcher_alive:
        payload['error'] = 'watcher not started'
        return payload, 503
    return payload, 200


def _handle_gateway_sse_stream(handler, parsed):
    """SSE endpoint for real-time gateway session updates.
    Streams change events from the gateway watcher background thread.
    Only active when show_cli_sessions (show_agent_sessions) setting is enabled.

    Probe mode (``?probe=1``) reports the status of THIS optional stream only.
    Its result says nothing about the always-on persistent per-session stream
    (``/api/session/stream``) — the probe payload carries explicit
    ``scope`` / ``session_stream_available`` markers so cross-client consumers
    do not misclassify usable session streaming as unavailable.
    """
    settings = load_settings()

    from api.gateway_watcher import get_watcher
    watcher = get_watcher()

    probe = parse_qs(parsed.query).get('probe', [''])[0].lower() in {'1', 'true', 'yes'}
    if probe:
        payload, status = _gateway_sse_probe_payload(settings, watcher)
        return j(handler, payload, status=status)

    # Check if the feature is enabled
    if not settings.get('show_cli_sessions'):
        return j(handler, {'error': 'agent sessions not enabled'}, status=404)

    # Same watcher_alive semantics as the probe path — centralised via
    # the helper so both branches stay in sync.
    _probe_body, _probe_status = _gateway_sse_probe_payload(settings, watcher)
    if not _probe_body['watcher_running']:
        return j(handler, {'error': 'watcher not started'}, status=503)

    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('X-Accel-Buffering', 'no')
    # #3103: do NOT emit `Connection: close` on long-lived SSE streams.
    # The python BaseHTTPServer worker only handles one request per
    # connection anyway, but browsers (Chrome/Firefox) treat the close
    # header as a hard signal that the EventSource lifecycle has ended
    # and trigger an instant reconnect, producing a tight loop of
    # connect/sessions_changed snapshot/disconnect that thrashes the
    # session list every ~1s. Letting the server close the socket
    # naturally after the stream ends is sufficient.
    end_sse_headers(handler)
    _sse_set_write_deadline(handler)  # Defect A: slow tab can't pin this thread

    q = watcher.subscribe()
    try:
        # Send initial snapshot immediately
        from api.models import get_cli_sessions
        initial = get_cli_sessions()
        _sse(handler, 'sessions_changed', {'sessions': initial})

        while True:
            try:
                event_data = q.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                handler.wfile.write(b': keepalive\n\n')
                handler.wfile.flush()
                continue
            if event_data is None:
                break  # watcher is stopping
            _sse(handler, event_data.get('type', 'sessions_changed'), event_data)
    except _CLIENT_DISCONNECT_ERRORS:
        pass
    finally:
        watcher.unsubscribe(q)
    return True




def _content_disposition_value(disposition: str, filename: str) -> str:
    """Build a latin-1-safe Content-Disposition value with RFC 5987 filename*."""
    import urllib.parse as _up

    safe_name = Path(filename).name.replace("\r", "").replace("\n", "")
    ascii_fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in {'"', '\\'} else "_"
        for ch in safe_name
    ).strip(" .")
    if not ascii_fallback:
        suffix = Path(safe_name).suffix
        ascii_suffix = "".join(
            ch if 32 <= ord(ch) < 127 and ch not in {'"', '\\'} else "_"
            for ch in suffix
        )
        ascii_fallback = f"download{ascii_suffix}" if ascii_suffix else "download"
    quoted_name = _up.quote(safe_name, safe="")
    return (
        f'{disposition}; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quoted_name}"
    )


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single HTTP bytes range into inclusive start/end offsets."""
    if not range_header or not range_header.startswith("bytes=") or file_size < 1:
        return None
    spec = range_header.split("=", 1)[1].strip()
    if "," in spec or "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            # suffix range: bytes=-500
            suffix_len = int(end_s)
            if suffix_len <= 0:
                return None
            start = max(0, file_size - suffix_len)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
            if start < 0:
                return None
            end = min(end, file_size - 1)
        if start > end or start >= file_size:
            return None
        return start, end
    except ValueError:
        return None


def _open_file_read_fd(target: Path, anchor_root: Path | None = None) -> int:
    if anchor_root is None:
        flags = os.O_RDONLY
        # On Windows, files are opened in text mode by default; O_BINARY
        # prevents CRLF translation that would corrupt binary media files.
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        return os.open(str(target), flags)
    return open_anchored_fd(anchor_root, target.resolve(), want_dir=False)


def _close_fd_quietly(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


# Maximum size for which a content-derived ETag is computed.  Files above
# this cap (and all HTML with no-store) are served without ETag to avoid
# hashing every byte of large media / Range requests.
_ETAG_SIZE_CAP = 10 * 1024 * 1024  # 10 MB


def _bytes_etag(data: bytes) -> str:
    """Weak ETag from a content digest of the bytes that will be served.

    The bytes must be an immutable snapshot (e.g. pread or an in-memory copy)
    so the validator cannot diverge from the body under TOCTOU.
    """
    return 'W/"%s"' % hashlib.sha256(data).hexdigest()


def _etag_and_snapshot(fd, *, file_size: int) -> tuple[str | None, bytes | None, int]:
    """Return (weak ETag, snapshot bytes, actual size) for files under the size cap.

    Uses os.lseek + looped os.read to grab an immutable snapshot in a cross-platform
    and short-read-safe manner. The snapshot bytes can be sent directly so the ETag
    and the body can never diverge under TOCTOU (the file may change on disk after read).

    Returns (None, None, file_size) for files above the cap or on unexpected I/O failure.
    Returns (None, None, actual_size) if the file was truncated mid-read (short snapshot).
    The caller must use actual_size (not the original file_size) for Content-Length/Range
    calculations to avoid header/body mismatch.
    """
    if file_size > _ETAG_SIZE_CAP:
        return None, None, file_size

    # Cross-platform: os.lseek + looped os.read instead of POSIX-only os.pread
    # Short reads are possible (interrupted, EOF from truncation), so we loop.
    os.lseek(fd, 0, os.SEEK_SET)
    data = b""
    remaining = file_size
    while remaining > 0:
        chunk = os.read(fd, min(1024 * 1024, remaining))
        if not chunk:  # EOF reached (file was truncated)
            break
        data += chunk
        remaining -= len(chunk)

    actual_size = len(data)
    if actual_size == 0:
        return None, None, 0

    # If the file was truncated after fstat (short snapshot), return the actual
    # size but no ETag — caller will fall back to streaming without ETag.
    # Round-6 fix: keep the captured `data` so the body path serves the immutable
    # snapshot instead of re-reading the fd after headers are committed.
    # Content-Length derives from actual_size == len(data), so header/body match.
    if actual_size != file_size:
        return None, data, actual_size

    return _bytes_etag(data), data, actual_size


def _serve_file_bytes(handler, target: Path, mime: str, disposition: str, cache_control: str, *, csp: str | None = None, anchor_root: Path | None = None, download_name: str | None = None):
    """Serve a file with correct MIME/disposition and optional byte-range support.

    Supports conditional GET via If-None-Match (ETag) — when the ETag matches,
    the request is short-circuited with 304 so revalidating clients (e.g.
    `no-cache` responses) do not re-download unchanged files.

    ``download_name`` overrides the Content-Disposition filename (used when
    serving an immutable media snapshot whose on-disk name is a content digest).
    """
    fd = None
    try:
        fd = _open_file_read_fd(target, anchor_root)
        st = os.fstat(fd)
        file_size = st.st_size
    except PermissionError:
        _close_fd_quietly(fd)
        return bad(handler, "Permission denied", 403)
    except FileNotFoundError:
        _close_fd_quietly(fd)
        return j(handler, {"error": "not found"}, status=404)
    except ValueError as e:
        _close_fd_quietly(fd)
        return bad(handler, _sanitize_error(e), 403)
    except Exception:
        _close_fd_quietly(fd)
        return bad(handler, "Could not stat file", 500)

    try:
        # Pre-commit phase: ETag/snapshot computation and response selection.
        # OSError here is still convertible into a clean 500 because no
        # status line has been written yet. After end_headers() the response
        # is committed, so body-transmission errors must never call bad()
        # again (that would attempt a second send_response on a stream the
        # client may have already closed — see the body phase below).
        try:
            no_store = "no-store" in cache_control
            if no_store or file_size > _ETAG_SIZE_CAP:
                etag = None
                snapshot = None
                # actual_size stays as file_size for over-cap/no-store cases
            else:
                etag, snapshot, actual_size = _etag_and_snapshot(fd, file_size=file_size)
                # If the file was truncated mid-read (short snapshot), use the
                # actual read size for all subsequent calculations so
                # Content-Length/Range match the body we can actually send.
                # Round-6 fix: the captured bytes are kept, so the body path
                # serves the immutable snapshot instead of re-reading the fd.
                if actual_size != file_size:
                    file_size = actual_size  # reconcile to avoid header/body mismatch
        except OSError:
            return bad(handler, "Could not serve file", 500)

        # RFC 7232 §3.2: If-None-Match uses weak comparison (W/ prefixes ignored)
        # and "*" matches any existing resource. On match, GET/HEAD is
        # short-circuited with 304 — processed before Range since a matched
        # conditional request skips the entity entirely.
        if_none_match = handler.headers.get("If-None-Match", "")
        if if_none_match and etag is not None:
            current = etag[2:] if etag.startswith("W/") else etag
            matched = if_none_match.strip() == "*" or any(
                (c.strip()[2:] if c.strip().startswith("W/") else c.strip()) == current
                for c in if_none_match.split(",")
                if c.strip()
            )
            if matched:
                handler.send_response(304)
                handler.send_header("ETag", etag)
                handler.send_header("Cache-Control", cache_control)
                _security_headers(handler)
                handler.end_headers()
                return True

        byte_range = _parse_range_header(handler.headers.get("Range", ""), file_size)
        if handler.headers.get("Range") and byte_range is None:
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{file_size}")
            handler.send_header("Accept-Ranges", "bytes")
            handler.send_header("Content-Length", "0")
            _security_headers(handler)
            handler.end_headers()
            return True

        start, end = byte_range if byte_range else (0, max(0, file_size - 1))
        content_length = end - start + 1 if file_size else 0
        handler.send_response(206 if byte_range else 200)
        handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(content_length))
        handler.send_header("Accept-Ranges", "bytes")
        if etag is not None:
            handler.send_header("ETag", etag)
        if byte_range:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        handler.send_header("Cache-Control", cache_control)
        handler.send_header("Content-Disposition", _content_disposition_value(disposition, download_name or target.name))
        if csp:
            # Sandboxed inline HTML must remain frameable for workspace previews;
            # X-Frame-Options: DENY would block the iframe before CSP sandbox applies.
            handler.send_header("Content-Security-Policy", csp)
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("Referrer-Policy", "same-origin")
            handler.send_header(
                "Permissions-Policy",
                "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)",
            )
        else:
            _security_headers(handler)
        handler.end_headers()

        # Body transmission: the response is committed once end_headers()
        # returns, so attempting bad()/send_response again here would corrupt
        # the stream with a second status line. Client disconnects are normal
        # (tab close, network switch) — log at debug and stop, same contract
        # as _safe_write(). Never emit a 500 after headers are out.
        if content_length:
            try:
                if snapshot is not None:
                    handler.wfile.write(snapshot[start:start + content_length])
                else:
                    with os.fdopen(fd, "rb", closefd=True) as f:
                        fd = None
                        f.seek(start)
                        remaining = content_length
                        while remaining:
                            chunk = f.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            handler.wfile.write(chunk)
                            remaining -= len(chunk)
            except _CLIENT_DISCONNECT_ERRORS as exc:
                logging.getLogger("hermes.webui").debug(
                    "Client disconnected mid-response (%s): %s",
                    type(exc).__name__,
                    getattr(handler, "path", "?"),
                )
            except Exception as exc:
                # Post-commit fail-closed: the status line is already on the
                # wire, so ANY body-transmission error that is not a client
                # disconnect (EIO from a truncated read, a generic OSError,
                # PermissionError, ...) must still be contained here. Letting
                # it escape would reach Handler.do_GET's 500 path and emit a
                # SECOND status line after the committed 200/206, corrupting
                # the HTTP stream. Log at debug and stop — the client already
                # received its headers (and possibly a partial body).
                logging.getLogger("hermes.webui").debug(
                    "Body transmission error after commit (%s): %s",
                    type(exc).__name__,
                    getattr(handler, "path", "?"),
                )
        return True
    finally:
        _close_fd_quietly(fd)



# (TTS implementation extracted to api.route_tts)


def _html_preview_with_blank_base(raw: bytes) -> bytes:
    base = '<base target="_blank">'
    text = raw.decode("utf-8", errors="replace")
    if re.search(r"<head(?:\s[^>]*)?>", text, flags=re.IGNORECASE):
        text = re.sub(r"(<head\b[^>]*>)", r"\1" + base, text, count=1, flags=re.IGNORECASE)
    elif re.search(r"<!doctype[^>]*>", text, flags=re.IGNORECASE):
        text = re.sub(
            r"(<!doctype[^>]*>)",
            r"\1<head>" + base + "</head>",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        text = "<head>" + base + "</head>" + text
    return text.encode("utf-8")


def _serve_inline_html_preview(handler, target: Path, cache_control: str, *, csp: str, anchor_root: Path | None = None):
    """Serve sandboxed workspace HTML preview with links targeting a new tab."""
    fd = None
    try:
        fd = _open_file_read_fd(target, anchor_root)
        with os.fdopen(fd, "rb", closefd=True) as f:
            fd = None
            body = _html_preview_with_blank_base(f.read())
    except PermissionError:
        return bad(handler, "Permission denied", 403)
    except FileNotFoundError:
        return j(handler, {"error": "not found"}, status=404)
    except ValueError as e:
        return bad(handler, _sanitize_error(e), 403)
    except Exception:
        return bad(handler, "Could not read file", 500)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Accept-Ranges", "none")
    handler.send_header("Cache-Control", cache_control)
    handler.send_header("Content-Disposition", _content_disposition_value("inline", target.name))
    handler.send_header("Content-Security-Policy", csp)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "same-origin")
    handler.send_header(
        "Permissions-Policy",
        "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)",
    )
    handler.end_headers()
    handler.wfile.write(body)
    return True




def _message_content_text(content) -> str:
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(part or ""))
        return "\n".join(parts)
    return str(content or "")








def _media_deny_reason(target: Path) -> str | None:
    """Return a reason string when ``target`` must be hard-denied, else None.

    The ``/api/media`` #3234 state/profile deny model, extracted so the
    snapshot CAPTURE side (api/media_snapshots.media_capture_allowed) shares
    the EXACT same predicate — anything the serve path refuses is never
    captured in the first place (#6979 Round 2 MUST-FIX 1 deny parity).

    Model: the ACTIVE WORKSPACE is a legitimate-media carve-out — the user is
    entitled to their own workspace files (that is also how the workspace file
    browser reaches them), even when a workspace happens to live under a
    Hermes root. The deny rules target Hermes's OWN internal state, which lives
    OUTSIDE any workspace. So: if the target is inside the active workspace, it
    is never denied here; otherwise we deny known secret/config basenames and
    the internal state subdirectories across every Hermes root the allowlist
    accepts (active-profile HERMES_HOME, base ~/.hermes, the api.profiles
    default home, and STATE_DIR — which also defends sibling profiles).
    """
    import os as _os

    _HOME = Path(_os.path.expanduser("~"))
    _HERMES_HOME = Path(_os.getenv("HERMES_HOME", str(_HOME / ".jaeger" / "hermes"))).expanduser()

    _DENY_FILENAMES = {
        "settings.json", "state.db", "state.db-wal", "state.db-shm",
        "auth.json", "auth.lock", "config.yaml", "config.yml", ".env",
        ".signing_key", ".pbkdf2_key", ".sessions.json",
        "google_token.json", "google_client_secret.json",
        "gateway_state.json", "channel_directory.json", "jobs.json",
        "passkeys.json", ".passkey_challenges.json", ".login_attempts.json",
    }
    # Internal state subdirs that are sensitive in their entirety. NOTE:
    # `profiles` is intentionally NOT here — it is a container of profile roots,
    # each of which has its own legitimate workspace/. We instead enumerate each
    # named-profile root below and deny ITS state subdirs, so a sibling profile's
    # secrets are blocked without 403-ing a named-profile workspace. (#3234.)
    _DENY_SUBDIRS = (
        "sessions", "memories", "cron", "logs",
        "checkpoints", "backups",
        # Content-addressed media snapshots (api/media_snapshots.py) are an
        # internal store: digest bytes are only reachable through the validated
        # `snap=` parameter, never as a bare `path=` request. (#media-snapshots)
        "media_snapshots",
    )
    _state_dir = None
    try:
        from api.config import STATE_DIR as _STATE_DIR
        _state_dir = Path(_STATE_DIR).resolve()
    except Exception:
        _state_dir = None
    _base_hermes_home = None
    try:
        from api.profiles import _DEFAULT_HERMES_HOME as _BASE_HH
        _base_hermes_home = Path(_BASE_HH).resolve()
    except Exception:
        _base_hermes_home = None
    _hermes_roots = []
    for _r in (
        _HERMES_HOME.resolve(),
        (_HOME / ".jaeger" / "hermes").resolve(),
        _base_hermes_home,
        _state_dir,
    ):
        if _r is not None and _r not in _hermes_roots:
            _hermes_roots.append(_r)
    # Enumerate named-profile roots (<root>/profiles/<name>) and treat each as a
    # Hermes root in its own right, so a sibling/other profile's sensitive subdirs
    # + secret files are denied — WITHOUT denying the whole `profiles` container
    # (which would block a legit named-profile workspace at
    # <root>/profiles/<name>/workspace/). (Codex review #3234.)
    _profile_roots = []
    for _root in list(_hermes_roots):
        _profiles_dir = (_root / "profiles")
        try:
            if _profiles_dir.is_dir():
                for _pchild in _profiles_dir.iterdir():
                    if _pchild.is_dir():
                        _pr = _pchild.resolve()
                        if _pr not in _hermes_roots and _pr not in _profile_roots:
                            _profile_roots.append(_pr)
        except OSError:
            pass
    _hermes_roots.extend(_profile_roots)

    # Case-insensitive path helpers so STATE.DB / Sessions/ casing variants
    # cannot bypass the deny on macOS/Windows filesystems (Codex review #3234).
    def _norm(p):
        return os.path.normcase(str(Path(p).resolve())).casefold()
    def _within_ci(child, root):
        try:
            c, r = _norm(child), _norm(root)
            return os.path.commonpath([c, r]) == r
        except (ValueError, OSError):
            return False
    def _equal_ci(a, b):
        try:
            return _norm(a) == _norm(b)
        except (ValueError, OSError):
            return False

    # State-subdir deny set: each DENY_SUBDIR directly under any Hermes root
    # (which includes STATE_DIR — so STATE_DIR/sessions, STATE_DIR/memories,
    # etc. are covered). These ALWAYS apply — even to a file under the active
    # workspace — so a workspace pointed at (or overlapping) a state dir cannot
    # expose sessions/memories/profiles/etc. We do NOT deny STATE_DIR itself
    # wholesale: the default workspace lives at STATE_DIR/workspace, and that is
    # legitimate user media — direct sensitive files there are still caught by
    # the filename denies below. (Codex review #3234.)
    _deny_dirs = []
    for _root in _hermes_roots:
        for _sub in _DENY_SUBDIRS:
            _deny_dirs.append((_root / _sub).resolve())
        # Per-profile WebUI state lives at <root>/webui_state (api/workspace.py),
        # so its state subdirs (<root>/webui_state/sessions, etc.) must be denied
        # too — they are NOT direct children of <root>. (Codex review #3234.)
        _ws_state = (_root / "webui_state")
        for _sub in _DENY_SUBDIRS:
            _deny_dirs.append((_ws_state / _sub).resolve())
    # The configured media-snapshot store root itself: blobs are internal and
    # only reachable through the validated `snap=` parameter on an authorized
    # path, so a bare `path=` request at or below the store is rejected
    # REGARDLESS of the store's configured name/location
    # (HERMES_WEBUI_MEDIA_SNAPSHOT_DIR may point anywhere, e.g. /tmp/custom-name;
    # the literal "media_snapshots" entry above only covers the default layout).
    # (#6979 Round 2 MUST-FIX 2.)
    try:
        from api.media_snapshots import get_snapshot_dir
        _snap_store = get_snapshot_dir().resolve()
    except Exception:
        _snap_store = None
    if _snap_store is not None and _within_ci(target, _snap_store):
        return "media snapshot store is internal"
    _deny_names_ci = {n.casefold() for n in _DENY_FILENAMES}

    # Active-workspace carve-out: a file inside a genuine PROJECT workspace is
    # the user's own content, so the secret/config FILENAME denies are relaxed
    # for it. The carve-out is DISABLED when the workspace is a broad/internal
    # location ($HOME, a Hermes root itself, an ANCESTOR of a Hermes root, a
    # */profiles dir, a named-profile root, or a state subdir) — honoring those
    # would re-open the disclosure. A workspace that is a proper DESCENDANT of a
    # Hermes root (e.g. STATE_DIR/workspace) is still a legit project workspace
    # and keeps the carve-out. The dir-based denies above are NOT relaxed.
    _active_workspace = None
    try:
        from api.workspace import get_last_workspace
        _aw = Path(get_last_workspace()).resolve()
        if _aw.is_dir():
            _active_workspace = _aw
    except Exception:
        _active_workspace = None

    def _workspace_is_safe_carveout(ws):
        if ws is None:
            return False
        if _equal_ci(ws, _HOME):
            return False
        for _root in _hermes_roots:
            # ws IS a root, or ws is an ANCESTOR of a root → unsafe. (A proper
            # descendant of a root is fine — that's a normal project workspace.)
            if _equal_ci(ws, _root) or _within_ci(_root, ws):
                return False
        if ws.name == "profiles" or ws.parent.name == "profiles":
            return False
        if ws.name in _DENY_SUBDIRS:
            return False
        return True

    _in_active_workspace = (
        _active_workspace is not None
        and _workspace_is_safe_carveout(_active_workspace)
        and _within_ci(target, _active_workspace)
    )

    # Dir-based denies always fire (even inside the active workspace).
    if any(_within_ci(target, d) for d in _deny_dirs):
        return "denied state subdir"
    # Filename-based denies fire for files under a Hermes root, UNLESS the file
    # is inside a genuine project workspace (carve-out).
    if not _in_active_workspace:
        _under_hermes_root = any(_within_ci(target, _root) for _root in _hermes_roots)
        _name_cf = target.name.casefold()
        # Exact secret/state basenames, plus atomic-write temp files for those
        # (api/auth.py and api/passkeys.py write via a `tmp*.<name>.tmp` / `tmp*.tmp`
        # sidecar then rename) — deny those suffixes too so a momentary temp file
        # cannot be fetched. (Codex review #3234.)
        _deny_tmp_suffixes = (".sessions.tmp", ".login_attempts.tmp",
                              ".passkeys.tmp", ".passkey_challenges.tmp")
        if _under_hermes_root and (
            _name_cf in _deny_names_ci
            or _name_cf.endswith(_deny_tmp_suffixes)
        ):
            return "denied state filename"
    return None




def _file_raw_target(session, sid: str, rel: str) -> tuple[Path, Path] | None:
    """Resolve /api/file/raw paths from the workspace or this session's uploads."""
    workspace_root = Path(session.workspace)
    try:
        target = safe_resolve(workspace_root, rel)
    except ValueError:
        target = None
    if target and target.exists() and target.is_file():
        return workspace_root, target

    # Chat uploads now live in a per-session attachment inbox outside the
    # workspace. Keep the public URL stable while scoping fallback lookup to
    # the requesting session's own attachment directory.
    try:
        from api.upload import _session_attachment_dir

        attachment_root = _session_attachment_dir(sid)
        attachment_target = safe_resolve(attachment_root, rel)
    except Exception:
        return None
    if attachment_target.exists() and attachment_target.is_file():
        return attachment_root, attachment_target
    return None


# (Folder download implementation extracted to api.route_folder_download)


def _handle_file_raw(handler, parsed):
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")
    gateway_session = False
    try:
        s = get_session_for_file_ops(sid)
    except KeyError:
        from .gateway_read_workspace import gateway_read_workspace
        from types import SimpleNamespace
        try:
            s = SimpleNamespace(workspace=str(gateway_read_workspace(sid)))
            gateway_session = True
        except KeyError:
            return bad(handler, "Session not found", 404)
    rel = qs.get("path", [""])[0]
    force_download = qs.get("download", [""])[0] == "1"
    try:
        resolved = ((Path(s.workspace), safe_resolve(Path(s.workspace), rel))
                    if gateway_session else _file_raw_target(s, sid, rel))
    except ValueError:
        resolved = None
    if gateway_session and resolved is not None and (
            not resolved[1].exists() or not resolved[1].is_file()):
        resolved = None
    if resolved is None:
        return j(handler, {"error": "not found"}, status=404)
    anchor_root, target = resolved
    ext = target.suffix.lower()
    mime = MIME_MAP.get(ext, "application/octet-stream")
    # Security: force download for dangerous MIME types to prevent XSS.
    # Exception: ?inline=1 permits text/html to be served inline for the
    # sandboxed workspace HTML preview iframe (sandbox="allow-scripts" with no
    # allow-same-origin, so the iframe cannot access parent cookies/storage).
    inline_preview = qs.get("inline", [""])[0] == "1"
    dangerous_types = {"text/html", "application/xhtml+xml", "image/svg+xml"}
    html_inline_ok = inline_preview and mime == "text/html"
    disposition = "attachment" if force_download or (mime in dangerous_types and not html_inline_ok) else "inline"
    # Defense-in-depth for ?inline=1 HTML: even though the workspace.js iframe
    # sets sandbox="allow-scripts", a user could be tricked into opening the
    # ?inline=1 URL directly in a top-level tab (e.g. via a chat link), which
    # would render the HTML in the WebUI's origin without iframe sandbox. The
    # CSP sandbox directive applies the same isolation server-side: without
    # allow-same-origin, the document is treated as a unique opaque origin and
    # cannot read WebUI cookies, localStorage, or postMessage to the parent.
    sandbox_csp = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox"
    csp = sandbox_csp if (inline_preview and not force_download and disposition == "inline") else None
    # _serve_file_bytes sends Content-Security-Policy when csp is set.
    if html_inline_ok:
        return _serve_inline_html_preview(handler, target, "no-store", csp=sandbox_csp, anchor_root=anchor_root)
    return _serve_file_bytes(handler, target, mime, disposition, "no-store", csp=csp, anchor_root=anchor_root)


def _handle_file_read(handler, parsed):
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")
    gateway_session = False
    try:
        s = get_session_for_file_ops(sid)
    except KeyError:
        from .gateway_read_workspace import gateway_read_workspace
        from types import SimpleNamespace
        try:
            s = SimpleNamespace(workspace=str(gateway_read_workspace(sid)))
            gateway_session = True
        except KeyError:
            return bad(handler, "Session not found", 404)
    rel = qs.get("path", [""])[0]
    if not rel:
        return bad(handler, "path is required")
    try:
        return j(handler, read_file_content(Path(s.workspace), rel))
    except ImportError as e:
        return bad(handler, str(e), 503)
    except (FileNotFoundError, ValueError) as e:
        return bad(handler, _sanitize_error(e), 404)






def _webui_gateway_auth() -> dict:
    from jaeger_ai.core.gateway.caller_auth import client_headers
    return client_headers("webui")


def _gateway_store_rows(sid: str) -> list[dict] | None:
    """Pending Gateway approvals for this chat, including the cards its
    background workers / specialists filed under child sessions (``origin``).
    None when the Gateway cannot be asked."""
    from urllib.parse import quote
    from urllib.request import urlopen

    from api.jaeger_sessions import gateway_base

    try:
        req = Request(
            gateway_base() + "/v1/approvals?session_id=" + quote(str(sid or ""), safe=""),
            headers={"Accept": "application/json", **_webui_gateway_auth()},
            method="GET",
        )
        with urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return None
    rows = data.get("approvals") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    return [row for row in rows if isinstance(row, dict) and _gateway_row_belongs(row, sid)]


def _gateway_row_belongs(row: dict, sid: str) -> bool:
    """The card is this chat's own, or a child card whose origin names it."""
    if str(row.get("session_id") or "") == sid:
        return True
    origin = row.get("origin") if isinstance(row.get("origin"), dict) else {}
    return bool(sid) and str(origin.get("parent_session_id") or "") == sid






def _runner_local_resolve(sid: str, approval_id: str, choice: str) -> bool | None:
    from api.runtime_adapter import build_runtime_adapter, runtime_adapter_runner_enabled

    if not runtime_adapter_runner_enabled():
        return None
    try:
        s = get_session(sid)
    except Exception:
        return None
    run_id = str(getattr(s, "active_stream_id", None) or "").strip()
    if not run_id:
        return None
    try:
        adapter = build_runtime_adapter(runner_client_factory=_runtime_runner_client_factory)
        if adapter is None:
            return None
        status = adapter.get_run(run_id)
        pending_id = str(getattr(status, "pending_approval_id", None) or "").strip()
        if pending_id and pending_id != str(approval_id or "").strip():
            return None
        result = adapter.respond_approval(run_id, approval_id, choice)
    except Exception:
        logger.debug("runner-local approval resolve failed", exc_info=True)
        return None
    return bool(getattr(result, "accepted", False))


def _gateway_store_resolve(approval_id: str, choice: str) -> bool | None:
    from urllib.parse import quote
    from urllib.request import urlopen

    from api.jaeger_sessions import gateway_base

    aid = str(approval_id or "").strip()
    if not aid:
        return None
    decision = str(choice) if str(choice) in {"once", "session", "always", "deny"} else "once"
    body = json.dumps({"approved": decision != "deny", "decision": decision}).encode("utf-8")
    try:
        req = Request(
            gateway_base() + "/v1/approvals/" + quote(aid, safe=""),
            data=body,
            method="POST",
            # The Gateway refuses unauthenticated callers; the WebUI answers as itself.
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     **_webui_gateway_auth()},
        )
        with urlopen(req, timeout=8) as resp:
            if 200 <= int(getattr(resp, "status", 200)) < 300:
                return True
            return False
    except HTTPError as exc:
        if int(exc.code) == 404:
            return None
        logger.debug("gateway approval resolve HTTP %s", exc.code, exc_info=True)
        return False
    except Exception:
        logger.debug("gateway approval resolve failed", exc_info=True)
        return None


def _resident_resolve_approval(sid: str, approval_id: str, choice: str) -> bool | None:
    """Resolve a runner-local or Gateway parked approval. None = not ours."""
    mapped = "once" if str(choice) == "session" else str(choice)
    runner = _runner_local_resolve(sid, approval_id, mapped)
    if runner is not None:
        return runner
    return _gateway_store_resolve(approval_id, mapped)
















































# ── POST route helpers ────────────────────────────────────────────────────────








def _checkpoint_user_message_for_eager_session_save(s, msg: str, attachments, started_at: float | None, source: str = "webui") -> None:
    """Materialize the current user turn for eager first-turn persistence.

    The streaming thread still receives ``pending_user_message`` so existing
    cancel/recovery/final-merge paths keep their current contract. Eager mode
    only adds a durable display-message checkpoint before the agent launches.
    """
    if not msg:
        return
    existing = list(getattr(s, "messages", None) or [])
    if existing:
        latest = existing[-1]
        if isinstance(latest, dict) and latest.get("role") == "user":
            latest_text = " ".join(str(latest.get("content") or "").split())
            msg_text = " ".join(str(msg or "").split())
            if latest_text == msg_text:
                if str(source or "").strip().lower() == "fork":
                    latest["_fork_child_turn"] = s.session_id
                return
    user_msg = {"role": "user", "content": msg}
    from api.process_event_utils import build_active_turn_token, stamp_message_source

    stamp_message_source(
        user_msg,
        source,
        active_turn_token=build_active_turn_token(getattr(s, "active_stream_id", None), started_at),
    )
    if str(source or "").strip().lower() == "fork":
        user_msg["_fork_child_turn"] = s.session_id
    if isinstance(started_at, (int, float)) and started_at > 0:
        user_msg["timestamp"] = float(started_at)
    if attachments:
        user_msg["attachments"] = list(attachments)
    s.messages.append(user_msg)
    # The new user turn is now committed to messages (#3831): advance the
    # truncation watermark to the new message's timestamp so that
    # merge_session_messages_append_only() still filters out replaced
    # pre-edit rows from state.db whose timestamps fall below the boundary.
    # The merge's sidecar_advanced_past_watermark guard (models.py:5172)
    # allows state.db rows newer than the watermark, so post-edit turns
    # are not dropped. Never 0.0 (the truncate-to-empty sentinel, #2914).
    if getattr(s, "truncation_watermark", None):
        s.truncation_watermark = user_msg.get("timestamp") or time.time()


def _is_default_or_empty_session_title(title) -> bool:
    return str(title or "").strip() in ("", "Untitled", "New Chat")


def _provisional_title_from_prompt(prompt: str, fallback: str = "Untitled") -> str:
    text = str(prompt or "").strip()
    if not text:
        return fallback
    return title_from([{"role": "user", "content": text}], fallback) or fallback


_RETAINED_CONTEXT_USER_UNSET = object()


def _prepare_chat_start_session_for_stream(
    s,
    *,
    msg: str,
    attachments,
    workspace: str,
    model: str,
    model_provider,
    stream_id: str,
    started_at: float | None = None,
    source: str = "webui",
    retained_user=None,
    retained_context_user=_RETAINED_CONTEXT_USER_UNSET,
    defer_save: bool = False,
):
    """Persist chat-start state according to webui.session_save_mode.

    ``deferred`` keeps the existing sidecar/WAL-backed behaviour: save pending
    fields but leave the display transcript empty until the agent merges the
    result. ``eager`` additionally writes the current user turn into messages so
    a process restart immediately after /api/chat/start preserves the prompt as
    a normal session message. Empty sessions are never saved here because this
    helper only runs after a non-empty message is validated.
    """
    effective_source = (
        "fork"
        if str(getattr(s, "session_source", None) or "").strip().lower() == "fork"
        else source
    )
    s.workspace = workspace
    s.model = model
    s.model_provider = model_provider
    s.active_stream_id = stream_id
    register_session_writeback_owner(s.session_id, stream_id)
    s.post_compression_context_tokens_estimate = None
    s.pending_user_message = msg
    s.pending_attachments = attachments
    s.pending_started_at = started_at if started_at is not None else time.time()
    s.pending_user_source = effective_source
    if retained_user is not None:
        from api.process_event_utils import build_active_turn_token

        retained_user["timestamp"] = s.pending_started_at
        active_turn_token = build_active_turn_token(stream_id, s.pending_started_at)
        retained_user["_active_turn_token"] = active_turn_token
        if str(effective_source or "").strip().lower() == "fork":
            retained_user["_fork_child_turn"] = s.session_id
        if retained_context_user is not _RETAINED_CONTEXT_USER_UNSET:
            if retained_context_user is not None and not any(
                row is retained_context_user
                for row in list(getattr(s, "context_messages", None) or [])
            ):
                raise RuntimeError("regeneration retained context row is not installed")
            if isinstance(retained_context_user, dict):
                retained_context_user["timestamp"] = s.pending_started_at
                retained_context_user["_active_turn_token"] = active_turn_token
                if str(effective_source or "").strip().lower() == "fork":
                    retained_context_user["_fork_child_turn"] = s.session_id
        else:
            retained_id = retained_user.get("id") or retained_user.get("message_id")
            retained_old_timestamp = retained_user.get("timestamp")
            retained_old_content = retained_user.get("content")
            for context_row in reversed(list(getattr(s, "context_messages", None) or [])):
                if not isinstance(context_row, dict) or context_row.get("role") != "user":
                    continue
                context_id = context_row.get("id") or context_row.get("message_id")
                id_match = retained_id is not None and context_id == retained_id
                old_shape_match = (
                    retained_old_timestamp is not None
                    and context_row.get("timestamp") == retained_old_timestamp
                    and context_row.get("content") == retained_old_content
                )
                if not (id_match or old_shape_match):
                    continue
                context_row["timestamp"] = s.pending_started_at
                context_row["_active_turn_token"] = active_turn_token
                if str(effective_source or "").strip().lower() == "fork":
                    context_row["_fork_child_turn"] = s.session_id
                break
    current_title = getattr(s, "title", None)
    if retained_user is None and _is_default_or_empty_session_title(current_title):
        provisional_title = _provisional_title_from_prompt(msg, current_title or "Untitled")
        if provisional_title and not _is_default_or_empty_session_title(provisional_title):
            s.title = provisional_title
    if retained_user is None and get_webui_session_save_mode() == "eager":
        _checkpoint_user_message_for_eager_session_save(
            s,
            msg,
            attachments,
            s.pending_started_at,
            source=effective_source,
        )
    if not defer_save:
        s.save()


def _is_hidden_empty_session(s) -> bool:
    return (
        getattr(s, "title", "Untitled") == "Untitled"
        and not getattr(s, "messages", None)
        and not getattr(s, "active_stream_id", None)
        and not getattr(s, "pending_user_message", None)
        and not getattr(s, "worktree_path", None)
    )


def _active_stream_blocks_chat_start(session, stream_id: str | None) -> bool:
    """Return whether an active_stream_id still owns this session's next turn.

    ``active_stream_id`` is written before the SSE channel is registered, so a
    very fresh pending turn must also block duplicate chat_start requests. If we
    only check STREAMS here, a second request can race through the registration
    gap and overwrite the sidecar owner.
    """
    if not stream_id:
        return False
    with STREAMS_LOCK:
        if stream_id in STREAMS:
            return True
    try:
        from api import config as _live_config
        with _live_config.ACTIVE_RUNS_LOCK:
            if stream_id in (_live_config.ACTIVE_RUNS or {}):
                return True
    except Exception:
        pass
    if getattr(session, "pending_user_message", None):
        try:
            from api.models import _REPAIR_STALE_PENDING_GRACE_SECONDS
            grace_seconds = float(_REPAIR_STALE_PENDING_GRACE_SECONDS)
        except Exception:
            grace_seconds = 30.0
        try:
            pending_started_at = float(getattr(session, "pending_started_at", None) or 0)
        except Exception:
            pending_started_at = 0.0
        if pending_started_at and time.time() - pending_started_at < grace_seconds:
            return True
    return False


def _start_regeneration_stream_locked(
    s,
    *,
    turn,
    workspace: str,
    model: str,
    model_provider,
    normalized_model: bool,
    diag,
    goal_related: bool,
    source: str,
    moa_config,
    backend_is_gateway: bool,
):
    """Commit a retained-row regeneration before releasing its real worker."""
    from api.session_ops import (
        RegenerationUnavailable,
        apply_regeneration_plan,
        plan_regeneration,
        restore_regeneration_state,
        snapshot_regeneration_state,
    )

    try:
        plan = plan_regeneration(
            s, expected_revision=turn.revision, lock_held=True
        )
        turn = plan.turn
    except RegenerationUnavailable as exc:
        return {
            "error": str(exc),
            "code": exc.code,
            "_status": exc.status,
        }
    # Snapshot only after lock-held authority validation, before mutation.
    snapshot = snapshot_regeneration_state(s)
    if compression_recovery_payload_for_session(s):
        clear_compression_recovery(s)
    stream_id = uuid.uuid4().hex
    gateway_starting = False
    thread_started = False
    save_attempted = False
    accepted = False
    journal_event = {}
    release_worker = threading.Event()
    abort_worker = threading.Event()
    worker_thread = None

    worker_target = (
        _run_gateway_chat_streaming if backend_is_gateway else _run_agent_streaming
    )
    worker_kwargs = {
        "model_provider": model_provider,
        "goal_related": goal_related,
    }
    if backend_is_gateway:
        worker_kwargs["regeneration"] = True
    if moa_config and not backend_is_gateway:
        worker_kwargs["moa_config"] = moa_config

    def _gated_worker():
        release_worker.wait()
        if abort_worker.is_set():
            return
        worker_target(
            s.session_id,
            turn.message_text,
            model,
            workspace,
            stream_id,
            copy.deepcopy(turn.attachments),
            **worker_kwargs,
        )

    def _cleanup_owned_start():
        if goal_related:
            STREAM_GOAL_RELATED.pop(stream_id, None)
        with STREAMS_LOCK:
            STREAMS.pop(stream_id, None)
        unregister_stream_owner(stream_id)
        clear_session_writeback_owner_if_owned(s.session_id, stream_id)
        if gateway_starting:
            try:
                from api.gateway_chat import (
                    _clear_gateway_run_starting,
                    _finish_gateway_run_starting,
                )

                _finish_gateway_run_starting(stream_id)
                _clear_gateway_run_starting(stream_id)
            except Exception:
                logger.debug(
                    "Failed to clear compensated gateway start %s",
                    stream_id,
                    exc_info=True,
                )

    try:
        applied, retained_context_user = apply_regeneration_plan(
            s,
            plan,
            return_context_user=True,
        )
        if not applied:
            restore_regeneration_state(s, snapshot)
            return {
                "error": "Session changed while regeneration was being prepared.",
                "code": "stale_regeneration_revision",
                "_status": 409,
            }
        retained_user = s.messages[-1]
        msg = turn.message_text
        attachments = copy.deepcopy(turn.attachments)
        was_hidden_empty_session = _is_hidden_empty_session(s)
        _prepare_chat_start_session_for_stream(
            s,
            msg=msg,
            attachments=attachments,
            workspace=workspace,
            model=model,
            model_provider=model_provider,
            stream_id=stream_id,
            source=turn.source,
            retained_user=retained_user,
            retained_context_user=retained_context_user,
            defer_save=True,
        )

        diag.stage("turn_journal_submitted") if diag else None
        from api.turn_journal import append_turn_journal_event

        journal_event = append_turn_journal_event(
            s.session_id,
            {
                "event": "submitted",
                "stream_id": stream_id,
                "role": "user",
                "content": msg,
                "attachments": attachments,
                "workspace": workspace,
                "model": model,
                "model_provider": model_provider,
                "created_at": s.pending_started_at,
            },
        )
        diag.stage("stream_registration") if diag else None
        stream = create_stream_channel()
        register_stream_owner(stream_id, s.session_id)
        with STREAMS_LOCK:
            STREAMS[stream_id] = stream
        if goal_related:
            STREAM_GOAL_RELATED[stream_id] = True
        if backend_is_gateway:
            from api.gateway_chat import _mark_gateway_run_starting

            gateway_starting = True
            _mark_gateway_run_starting(stream_id)

        diag.stage("worker_thread_start") if diag else None
        worker_thread = threading.Thread(target=_gated_worker, daemon=True)
        worker_thread.start()
        thread_started = True
        save_attempted = True
        s.save()
        accepted = True
        set_last_workspace(workspace)
        release_worker.set()
    except Exception as exc:
        abort_worker.set()
        release_worker.set()
        if (
            thread_started
            and worker_thread is not None
            and callable(getattr(worker_thread, "join", None))
        ):
            worker_thread.join(timeout=1)
        _cleanup_owned_start()
        if accepted:
            if journal_event:
                try:
                    append_turn_journal_event(
                        s.session_id,
                        {
                            "event": "interrupted",
                            "stream_id": stream_id,
                            "turn_id": journal_event.get("turn_id"),
                            "reason": "post_acceptance_workspace_failure",
                        },
                    )
                except Exception:
                    logger.warning("Failed to close accepted regeneration journal", exc_info=True)
            exc._regeneration_accepted = True
            raise
        restore_regeneration_state(s, snapshot)
        if save_attempted:
            try:
                s.save(touch_updated_at=False)
            except Exception:
                logger.exception(
                    "Failed to persist compensated regeneration for %s",
                    s.session_id,
                )
        if journal_event:
            try:
                append_turn_journal_event(
                    s.session_id,
                    {
                        "event": "interrupted",
                        "stream_id": stream_id,
                        "turn_id": journal_event.get("turn_id"),
                        "reason": "start_compensated",
                    },
                )
            except Exception:
                logger.warning(
                    "Failed to close compensated turn journal event",
                    exc_info=True,
                )
        raise

    release_worker.set()
    if was_hidden_empty_session:
        _publish_session_list_changed(
            "session_new",
            profile=getattr(s, "profile", None),
            session_id=getattr(s, "session_id", None),
        )
    response = {
        "stream_id": stream_id,
        "session_id": s.session_id,
        "pending_started_at": s.pending_started_at,
        "turn_id": journal_event.get("turn_id"),
        "title": s.title,
    }
    if normalized_model:
        response["effective_model"] = model
    if model_provider:
        response["effective_model_provider"] = model_provider
    return response


def _active_run_stream_for_session(session_id: str | None) -> str | None:
    """Return a live worker stream for this session even if sidecar stream id is clear.

    cancel_stream() intentionally clears ``session.active_stream_id`` before the
    worker thread fully exits so Stop remains responsive. During that unwind
    window ACTIVE_RUNS is the worker-lifecycle truth; a successor chat/start for
    the same session must wait or it can reuse the cached agent while the old
    interrupt is still landing (#3808).

    Bounded: the post-cancel unwind is short (dominated by the worker finally's
    ``_ckpt_thread.join(timeout=15)``), and ``unregister_active_run`` runs in that
    finally, so a healthy worker leaves ACTIVE_RUNS within seconds. A detached /
    wedged worker that never reaches its finally (e.g. stuck in a provider call,
    or leaked by SIGKILL without restart) must NOT 409 the session forever — so an
    entry older than the unwind ceiling (180s) is treated as stale and ignored
    here. For a phase="cancelling" row the ceiling is anchored on the cancel time
    (``cancelled_at``), never on the original run start: cancel_stream() removes
    STREAMS itself, so absence from STREAMS is not worker-death proof, and a
    long-running turn that was just cancelled must not be reaped (and a successor
    admitted) while the old worker is still alive (#6623). A legitimately
    long-running turn keeps ``active_stream_id`` SET and is handled by
    ``_active_stream_blocks_chat_start`` above; this guard only covers the
    cleared-stream-id unwind window. (Codex brick-gate hardening, #3822.)
    """
    sid = str(session_id or "").strip()
    if not sid:
        return None
    ceiling = 180.0  # generous vs the 15s checkpoint-join unwind; finite to avoid permanent-409
    now = time.time()
    try:
        from api import config as _live_config
        # Snapshot the live-worker set BEFORE taking ACTIVE_RUNS_LOCK (sequential,
        # not nested, so no lock-ordering/deadlock risk). A long turn whose
        # active_stream_id was already cleared during final writeback can still be
        # mid-teardown — its STREAMS entry present — past the age ceiling, so age
        # alone must NOT pop its lifecycle row (health / background-wakeup /
        # active-agent-cache consumers read ACTIVE_RUNS as worker-lifecycle truth).
        with _live_config.STREAMS_LOCK:
            live_stream_ids = set(_live_config.STREAMS.keys())
        stale_stream_ids = []
        with _live_config.ACTIVE_RUNS_LOCK:
            for run_stream_id, raw in list((_live_config.ACTIVE_RUNS or {}).items()):
                stream_id = str((raw or {}).get("stream_id") or run_stream_id or "").strip()
                run_sid = str((raw or {}).get("session_id") or "").strip()
                if run_sid != sid or not stream_id:
                    continue
                try:
                    started_at = float((raw or {}).get("started_at") or 0)
                except (TypeError, ValueError):
                    started_at = 0.0
                # #6623 re-gate: cancel_stream() removes STREAMS itself, so a
                # missing SSE channel is NOT proof that a cancelled worker is
                # dead. For a phase="cancelling" row the unwind ceiling must be
                # anchored on the CANCEL time (cancelled_at, started_at as a
                # legacy fallback), never on the original run start: a turn that
                # ran for minutes and was just cancelled would otherwise be
                # reaped the instant its started_at crosses the ceiling and a
                # successor admitted while the old worker is still alive. A
                # recently cancelled run therefore keeps blocking a successor
                # (this function returns its stream id) until the worker either
                # unwinds (its finally unregisters the row within seconds) or
                # the cancel itself has been outstanding past the ceiling.
                _run_phase = str((raw or {}).get("phase") or "").strip()
                if _run_phase == "cancelling":
                    try:
                        _age_anchor = float(
                            (raw or {}).get("cancelled_at") or started_at or 0
                        )
                    except (TypeError, ValueError):
                        _age_anchor = started_at
                else:
                    _age_anchor = started_at
                # Past the unwind ceiling: never block a successor on it (the
                # anti-permanent-409 guarantee, #3822). Additionally reconcile the
                # zombie out of ACTIVE_RUNS so health/recovery polling stops seeing a
                # half-alive run — but ONLY when the worker is truly gone from
                # STREAMS, so a still-live / still-tearing-down worker keeps its
                # lifecycle row. Pop by the real dict key. (Codex gate, #4492)
                if _age_anchor and (now - _age_anchor) > ceiling:
                    if run_stream_id not in live_stream_ids and stream_id not in live_stream_ids:
                        stale_stream_ids.append(run_stream_id)
                    continue
                return stream_id
            for stale_stream_id in stale_stream_ids:
                (_live_config.ACTIVE_RUNS or {}).pop(stale_stream_id, None)
                # The zombie run is pruned directly here (not via the normal teardown
                # finally / unregister_active_run), so release its stream-owner entry too
                # or STREAM_SESSION_OWNERS leaks for every reconciled zombie. (#5198 gate)
                unregister_stream_owner(stale_stream_id)
    except Exception:
        return None
    return None


def _agent_runtime_barrier_response(
    *,
    runner_local_owned: bool = False,
    external_runtime_owned: bool | None = None,
) -> dict | None:
    """Return the typed stale-runtime response for local in-process turns."""
    if external_runtime_owned is True:
        return None
    if runner_local_owned and webui_gateway_chat_enabled(get_config()):
        return None
    from api.runtime_adapter import runtime_adapter_runner_enabled

    if runner_local_owned and runtime_adapter_runner_enabled():
        return None
    try:
        ensure_agent_runtime_current()
    except AgentRuntimeChangedError as exc:
        return {
            "error": str(exc),
            "type": "agent_runtime_stale",
            "retryable": True,
        }
    return None


def _run_profile_scoped_gateway_chat_streaming(*args, **kwargs):
    """Bind the persisted session profile in the detached gateway worker."""
    session_id = args[0]
    session = get_session(session_id)
    profile_name = str(getattr(session, "profile", "") or "").strip()
    with profile_scope_for_detached_worker(
        profile_name,
        "gateway chat streaming",
        logger_override=logger,
    ):
        return _run_gateway_chat_streaming(*args, **kwargs)


def _start_chat_stream_for_session(
    s,
    *,
    msg: str,
    attachments=None,
    workspace: str,
    model: str,
    model_provider=None,
    normalized_model: bool = False,
    diag=None,
    goal_related: bool = False,
    source: str = "webui",
    moa_config=None,
    external_runtime_owned: bool | None = None,
    regeneration=None,
):
    """Persist pending state, register an SSE channel, and start an agent turn."""
    if external_runtime_owned is None:
        external_runtime_owned = webui_gateway_chat_enabled(get_config())
    backend_is_gateway = bool(external_runtime_owned)
    stale_response = _agent_runtime_barrier_response(
        external_runtime_owned=backend_is_gateway,
    )
    if stale_response is not None:
        stale_response["_status"] = 409
        return stale_response
    attachments = attachments or []
    # Prevent duplicate runs in the same session while a stream is still active.
    # This commonly happens after page refresh/reconnect races and can produce
    # duplicated clarify cards for what appears to be a single user request.
    diag.stage("active_stream_check") if diag else None
    current_stream_id = getattr(s, "active_stream_id", None)
    if current_stream_id:
        if _active_stream_blocks_chat_start(s, current_stream_id):
            diag.stage("response_write") if diag else None
            return {
                "error": "session already has an active stream",
                "active_stream_id": current_stream_id,
                "_status": 409,
            }
        # Stale stream id from a previous run; clear and continue.
        diag.stage("stale_stream_cleanup") if diag else None
        _clear_stale_stream_state(s)

    # #1932: check if this session has a pending goal continuation flag.
    # The streaming hook sets PENDING_GOAL_CONTINUATION when goal_continue fires,
    # so the next chat/start for this session is automatically treated as goal-related.
    if not goal_related and s.session_id in PENDING_GOAL_CONTINUATION:
        goal_related = True
        PENDING_GOAL_CONTINUATION.discard(s.session_id)

    # process_complete wakeup (ours-original, Option B): if this session has a
    # pending process_complete marker (set by api/background_process.py drain),
    # discard it atomically here. Mirrors the goal_continue pattern (#1932).
    # The marker is server-internal telemetry; the actual wakeup is delivered
    # either server-side (Option Z) or via the PR #2279 next-turn drain.
    if s.session_id in PENDING_BG_TASK_COMPLETIONS:
        PENDING_BG_TASK_COMPLETIONS.discard(s.session_id)

    session_lock = _get_session_agent_lock(s.session_id)
    diag.stage("session_lock_wait") if diag else None
    while True:
        with session_lock:
            locked_stream_id = getattr(s, "active_stream_id", None)
            if locked_stream_id:
                if _active_stream_blocks_chat_start(s, locked_stream_id):
                    diag.stage("response_write") if diag else None
                    return {
                        "error": "session already has an active stream",
                        "active_stream_id": locked_stream_id,
                        "_status": 409,
                    }
                needs_stale_cleanup = True
            else:
                blocking_run_stream_id = _active_run_stream_for_session(s.session_id)
                if blocking_run_stream_id:
                    diag.stage("response_write") if diag else None
                    return {
                        "error": "session already has an active stream",
                        "active_stream_id": blocking_run_stream_id,
                        "_status": 409,
                    }
                needs_stale_cleanup = False
                if regeneration is not None:
                    return _start_regeneration_stream_locked(
                        s,
                        turn=regeneration,
                        workspace=workspace,
                        model=model,
                        model_provider=model_provider,
                        normalized_model=normalized_model,
                        diag=diag,
                        goal_related=goal_related,
                        source=source,
                        moa_config=moa_config,
                        backend_is_gateway=backend_is_gateway,
                    )
                stream_id = uuid.uuid4().hex
                diag.stage("save_pending_state") if diag else None
                was_hidden_empty_session = _is_hidden_empty_session(s)
                _prepare_chat_start_session_for_stream(
                    s,
                    msg=msg,
                    attachments=attachments,
                    workspace=workspace,
                    model=model,
                    model_provider=model_provider,
                    stream_id=stream_id,
                    source=source,
                )
                break
        if needs_stale_cleanup:
            diag.stage("stale_stream_cleanup") if diag else None
            cleared = _clear_stale_stream_state(s)
            if not cleared and getattr(s, "active_stream_id", None):
                diag.stage("response_write") if diag else None
                return {
                    "error": "session already has an active stream",
                    "active_stream_id": getattr(s, "active_stream_id", None),
                    "_status": 409,
                }
    if was_hidden_empty_session:
        _publish_session_list_changed(
            "session_new",
            profile=getattr(s, "profile", None),
            session_id=getattr(s, "session_id", None),
        )
    diag.stage("turn_journal_submitted") if diag else None
    journal_event = {}
    try:
        from api.turn_journal import append_turn_journal_event
        journal_event = append_turn_journal_event(
            s.session_id,
            {
                "event": "submitted",
                "stream_id": stream_id,
                "role": "user",
                "content": msg,
                "attachments": attachments,
                "workspace": workspace,
                "model": model,
                "model_provider": model_provider,
                "created_at": s.pending_started_at,
            },
        )
    except Exception:
        logger.warning("Failed to append submitted turn journal event", exc_info=True)
    diag.stage("set_last_workspace") if diag else None
    set_last_workspace(workspace)
    diag.stage("stream_registration") if diag else None
    stream = create_stream_channel()
    register_stream_owner(stream_id, s.session_id)
    with STREAMS_LOCK:
        STREAMS[stream_id] = stream
    # #1932: mark stream as goal-related so the streaming hook evaluates the goal.
    if goal_related:
        STREAM_GOAL_RELATED[stream_id] = True
    diag.stage("worker_thread_start") if diag else None
    worker_target = (
        _run_profile_scoped_gateway_chat_streaming
        if backend_is_gateway
        else _run_agent_streaming
    )
    worker_kwargs = {"model_provider": model_provider, "goal_related": goal_related}
    if moa_config and not backend_is_gateway:
        worker_kwargs["moa_config"] = moa_config
    if backend_is_gateway:
        from api.gateway_chat import _mark_gateway_run_starting
        _mark_gateway_run_starting(stream_id)
    thr = threading.Thread(
        target=worker_target,
        args=(s.session_id, msg, model, workspace, stream_id, attachments),
        kwargs=worker_kwargs,
        daemon=True,
    )
    try:
        thr.start()
    except Exception:
        if backend_is_gateway:
            try:
                from api.gateway_chat import _finish_gateway_run_starting
                _finish_gateway_run_starting(stream_id)
                from api.gateway_chat import _clear_gateway_run_starting
                _clear_gateway_run_starting(stream_id)
            except Exception:
                logger.debug("Failed to record gateway run-start failure for stream %s", stream_id, exc_info=True)
        raise
    response = {
        "stream_id": stream_id,
        "session_id": s.session_id,
        "pending_started_at": s.pending_started_at,
        "turn_id": journal_event.get("turn_id"),
        "title": s.title,
    }
    if normalized_model:
        response["effective_model"] = model
    if model_provider:
        response["effective_model_provider"] = model_provider
    return response


def _runtime_runner_client_factory():
    """Return the configured runner-local client.

    `runner-local` remains default-off and bounded: without an explicit runner
    endpoint this factory preserves the existing "runner-local chat backend is
    not configured" 501 path. When
    `HERMES_WEBUI_RUNNER_BASE_URL` is set, the WebUI process only acts as a
    transport client; the runner endpoint owns execution, run ids, replay, and
    controls.
    """
    # Keep this literal here for route-level contract tests and readable 501 provenance:
    # "runner-local chat backend is not configured"
    from api.runner_client import HttpRunnerClient

    return HttpRunnerClient.from_env()




def _chat_start_response_from_run_start(result):
    """Expose only the legacy browser-facing chat-start response fields."""
    payload = dict(getattr(result, "payload", {}) or {})
    response = {}
    for key in (
        "stream_id",
        "session_id",
        "pending_started_at",
        "turn_id",
        "title",
        "effective_model",
        "effective_model_provider",
        "error",
        "code",
        "active_stream_id",
        "_status",
    ):
        if key in payload:
            response[key] = payload[key]
    response.setdefault("stream_id", result.stream_id)
    response.setdefault("session_id", result.session_id)
    return response












def _native_table_runtime(profile) -> str | None:
    """Return hermes/openclaw/roundtable when that profile owns native execution."""
    from jaeger_ai.contract.frameworks import UnknownFramework, canonical_runtime

    try:
        runtime = canonical_runtime(profile or "")
    except UnknownFramework:
        return None
    if runtime in {"hermes", "openclaw", "roundtable"}:
        return runtime
    return None


def _start_native_profile_run(
    s,
    *,
    msg: str,
    attachments,
    workspace: str,
    model,
    model_provider,
    source: str,
    route: str,
):
    """Send Roundtable/Hermes/OpenClaw turns to the native runner, not AIAgent."""
    from api.runtime_adapter import RunnerRuntimeAdapter, StartRunRequest
    from api.runner_client import RunnerClientError

    if attachments:
        return {
            "error": "This profile cannot receive WebUI attachments; use the native tools.",
            "_status": 400,
        }
    try:
        adapter = RunnerRuntimeAdapter(client=_runtime_runner_client_factory())
        result = adapter.start_run(
            StartRunRequest(
                session_id=s.session_id,
                message=msg,
                attachments=[],
                workspace=workspace if workspace in ("", "/workspace") else "",
                profile=getattr(s, "profile", None),
                provider=model_provider,
                model=model,
                source=source,
                metadata={"route": route},
            )
        )
    except NotImplementedError as exc:
        return {"error": str(exc), "_status": 501}
    except (RunnerClientError, ValueError) as exc:
        return {"error": str(exc), "_status": 503}
    stream_id = result.stream_id or result.run_id
    try:
        from api.config import register_active_run
        register_active_run(
            stream_id,
            session_id=s.session_id,
            profile=getattr(s, "profile", None),
            runner=True,
        )
    except Exception:
        pass
    _prepare_chat_start_session_for_stream(
        s,
        msg=msg,
        attachments=[],
        workspace=workspace,
        model=model,
        model_provider=model_provider,
        stream_id=stream_id,
        source=source,
    )
    try:
        _spawn_runner_session_writeback(stream_id, s.session_id)
    except Exception:
        logger.debug("failed to spawn runner writeback for %s", s.session_id, exc_info=True)
    response = _chat_start_response_from_run_start(result)
    response.setdefault("stream_id", stream_id)
    response.setdefault("session_id", s.session_id)
    return response


def _start_run(
    s,
    *,
    msg: str,
    attachments,
    workspace: str,
    model,
    model_provider,
    normalized_model,
    source: str,
    route: str,
    diag=None,
    moa_config=None,
    gateway_chat_enabled: bool | None = None,
    regeneration=None,
):
    """Shared start-run helper for /api/chat/start and start_session_turn.

    Centralizes the runtime-adapter selection block (Q-2979-A2 / Copilot
    discussion_r3305864087/r3305864173) so both entrypoints honor
    ``runtime_adapter_enabled()`` / ``runtime_adapter_runner_enabled()`` the
    same way. Prior to this helper ``start_session_turn`` bypassed the
    adapter path entirely, so a process-wakeup turn skipped the adapter that
    a human-typed turn would have hit — a behavioral divergence.

    ``source`` is the StartRunRequest.source (``"webui"`` for browser POSTs,
    ``"process_wakeup"`` for the drain-thread wakeup). ``route`` is the
    metadata.route label that lands on the run record for observability.

    Returns a dict with ``_status`` plus the legacy chat-start response
    fields (``stream_id``, ``session_id``, etc.). Adapter selection that
    returns no adapter is surfaced as ``{"error": str(exc), "_status": 501}``
    so both call sites can map it onto their own HTTP shape.
    """
    from api.runtime_adapter import (
        LegacyJournalRuntimeAdapter,
        RunStartResult,
        StartRunRequest,
        build_runtime_adapter,
        runtime_adapter_enabled,
        runtime_adapter_runner_enabled,
    )

    native_runtime = _native_table_runtime(getattr(s, "profile", None))
    if native_runtime:
        # Hermes/OpenClaw/Roundtable profiles execute on the :8791 runner, a
        # second execution path. Isolated unless legacy paths are re-enabled.
        from jaeger_ai.contract.legacy_paths import disabled_reason, legacy_paths_enabled
        if not legacy_paths_enabled():
            return {
                "error": disabled_reason(f"The {native_runtime} profile runner"),
                "code": "legacy_path_isolated",
                "_status": 409,
            }
        return _start_native_profile_run(
            s,
            msg=msg,
            attachments=attachments,
            workspace=workspace,
            model=model,
            model_provider=model_provider,
            source=source,
            route=route,
        )

    if gateway_chat_enabled is None:
        from api.gateway_chat import webui_gateway_chat_enabled
        from api.config import get_config
        gateway_chat_enabled = webui_gateway_chat_enabled(get_config())

    if gateway_chat_enabled:
        return _start_chat_stream_for_session(
            s,
            msg=msg,
            attachments=attachments,
            workspace=workspace,
            model=model,
            model_provider=model_provider,
            normalized_model=normalized_model,
            diag=diag,
            source=source,
            moa_config=moa_config,
            external_runtime_owned=True,
            regeneration=regeneration,
        )

    if runtime_adapter_enabled() or runtime_adapter_runner_enabled():
        if regeneration is not None and runtime_adapter_runner_enabled():
            return {"error": "Regeneration is not supported by the runner backend.", "code": "unsupported_regeneration_backend", "_status": 409}
        def _legacy_start_run(request: StartRunRequest) -> dict:
            return _start_chat_stream_for_session(
                s,
                msg=request.message,
                attachments=request.attachments,
                workspace=request.workspace or workspace,
                model=request.model or model,
                model_provider=request.provider or model_provider,
                normalized_model=normalized_model,
                diag=diag,
                source=request.source or source,
                moa_config=moa_config,
                external_runtime_owned=gateway_chat_enabled,
                regeneration=regeneration,
            )

        def _legacy_adapter_factory():
            return LegacyJournalRuntimeAdapter(start_run_delegate=_legacy_start_run)

        try:
            adapter = build_runtime_adapter(
                legacy_adapter_factory=_legacy_adapter_factory,
                runner_client_factory=_runtime_runner_client_factory,
            )
            if adapter is None:
                raise NotImplementedError("runtime adapter selection returned no adapter")
            result = adapter.start_run(
                StartRunRequest(
                    session_id=s.session_id,
                    message=msg,
                    attachments=attachments,
                    workspace=workspace,
                    profile=getattr(s, "profile", None),
                    provider=model_provider,
                    model=model,
                    source=source,
                    metadata={"route": route},
                )
            )
        except NotImplementedError as exc:
            return {"error": str(exc), "_status": 501}
        try:
            _spawn_runner_session_writeback(getattr(result, "stream_id", None) or getattr(result, "run_id", None), s.session_id)
        except Exception:
            logger.debug("failed to spawn runner writeback for %s", getattr(s, "session_id", None), exc_info=True)
        return _chat_start_response_from_run_start(result)

    return _start_chat_stream_for_session(
        s,
        msg=msg,
        attachments=attachments,
        workspace=workspace,
        model=model,
        model_provider=model_provider,
        normalized_model=normalized_model,
        diag=diag,
        source=source,
        moa_config=moa_config,
        external_runtime_owned=gateway_chat_enabled,
        regeneration=regeneration,
    )


def _process_wakeup_revalidation_provider(model, provider) -> str:
    """Return the canonical provider id used for wakeup credential revalidation."""
    try:
        _resolved_model, resolved_provider = canonical_model_provider_lane(model, provider)
    except Exception:
        logger.debug(
            "failed to canonicalize process_wakeup revalidation lane for model=%r provider=%r",
            model,
            provider,
            exc_info=True,
        )
        resolved_provider = None
    candidate = resolved_provider if resolved_provider else provider
    return str(candidate or "").strip()


def _process_wakeup_provider_has_recovery_credential(
    session,
    *,
    model,
    provider,
    provider_id: str | None = None,
) -> bool:
    """Check paused credential-pool recovery in the owning session profile."""
    provider_id = str(
        provider_id or _process_wakeup_revalidation_provider(model, provider) or ""
    ).strip()
    if not provider_id:
        return False
    profile_name = str(getattr(session, "profile", "") or "").strip()
    if profile_name and not _is_root_profile(profile_name):
        with profile_scope_for_detached_worker(
            profile_name,
            "process_wakeup credential revalidation",
            logger_override=logger,
        ):
            return provider_has_process_wakeup_recovery_credential(provider_id, refresh=True)
    return provider_has_process_wakeup_recovery_credential(provider_id, refresh=True)


def _refresh_process_wakeup_pause_credential_fingerprint(session) -> bool:
    """Refresh the stored credential fingerprint without clearing the pause."""
    pause = getattr(session, "process_wakeup_pause", None)
    if not isinstance(pause, dict) or not pause.get("paused"):
        return False
    updated = dict(pause)
    updated["credential_state_fingerprint"] = process_wakeup_credential_state_fingerprint(session)
    session.process_wakeup_pause = updated
    return True


def start_session_turn(
    session_id: str,
    message: str,
    *,
    source: str = "process_wakeup",
):
    """Start a server-side agent turn for ``session_id`` with ``message``.

    Option Z primary wakeup entrypoint. This is the minimal, HTTP-handler-free
    core that ``/api/chat/start`` already reaches via ``_handle_chat_start`` →
    ``_start_chat_stream_for_session``. The drain thread
    (``api/background_process._process_one``) calls this directly with a
    synthetic ``[IMPORTANT: …]`` wakeup_prompt so a background process can wake
    the agent server-side with NO browser round-trip — exactly how CLI /
    gateway self-wake from a ``notify_on_complete`` completion.

    Contract:
      - Resolves the session record (profile/workspace/model/model_provider are
        already persisted on it; no user auth needed — same trust level as
        gateway/cron starting a turn).
      - Resolves workspace + model/provider through the SAME helpers
        ``_handle_chat_start`` uses, so a process-wakeup turn is constructed
        identically to a human-typed turn. If the session record has no model
        persisted, ``_resolve_compatible_session_model_state`` falls back to the
        configured default model/provider (documented in the impl report §1).
      - Delegates to ``_start_chat_stream_for_session`` which spawns the agent
        on a daemon worker thread (the drain thread NEVER blocks) and serializes
        on the per-session agent lock + active-stream guard, so a concurrent
        human ``/api/chat/start`` cannot double-start (one wins, the other gets
        the existing 409 "session already has an active stream").

    Returns the same dict ``_start_chat_stream_for_session`` returns, including
    ``_status`` (200 on start, 409 when a turn is already active). On 409 the
    caller must leave the ``PENDING_BG_TASK_COMPLETIONS`` marker in place so the
    PR #2279 next-turn drain delivers the wakeup when the active turn ends.
    """
    msg = str(message or "").strip()
    if _is_silent_control_message(msg):
        return {
            "status": "suppressed",
            "reason": "silent_control_message",
            "_status": 200,
        }
    if not msg:
        return {"error": "message is required", "_status": 400}
    stale_response = _agent_runtime_barrier_response(runner_local_owned=True)
    if stale_response is not None:
        stale_response["_status"] = 409
        return stale_response
    turn_source = str(source or "process_wakeup").strip() or "process_wakeup"
    try:
        s = get_session(session_id)
    except KeyError:
        return {"error": "Session not found", "_status": 404}

    try:
        workspace = _resolve_chat_workspace_with_recovery(s, None)
    except WorkspaceBindingPersistenceError as e:
        return {"error": str(e), "_status": 500}
    except ValueError as e:
        return {"error": str(e), "_status": 400}

    requested_model = s.model
    requested_provider = getattr(s, "model_provider", None)
    # Server-initiated wakeup (Option Z): resolve persisted model via the
    # standard helper in cache-only mode so wakeups never trigger a cold
    # catalog rebuild. Thread the session's PROFILE model defaults through too
    # (mirrors _handle_chat_start) — a brand-new session that spawned a
    # background task before its first human turn has an empty s.model, and
    # without the profile defaults the resolver would fall back to the global
    # DEFAULT_MODEL instead of the profile's configured default (greptile flag).
    _pp_provider, _pp_default, _pp_cfg = _read_profile_model_config(s, requested_provider)
    model, model_provider, normalized_model = _resolve_compatible_session_model_state(
        requested_model,
        requested_provider,
        profile_provider=_pp_provider,
        profile_default_model=_pp_default,
        profile_config=_pp_cfg,
        prefer_cached_catalog=True,
    )
    _paused_wakeup_response = None
    with _get_session_agent_lock(s.session_id):
        try:
            s = get_session(session_id)
        except KeyError:
            return {"error": "Session not found", "_status": 404}
        if clear_process_wakeup_pause_if_model_changed(
            s,
            model=model,
            provider=model_provider,
        ):
            try:
                s.save(touch_updated_at=False)
            except Exception:
                logger.debug(
                    "failed to persist process_wakeup pause reset for session %s",
                    session_id,
                    exc_info=True,
                )
        if turn_source == "process_wakeup":
            _credential_state_changed = False
            try:
                _credential_state_changed = process_wakeup_pause_credential_state_changed(s)
            except Exception:
                logger.debug(
                    "failed to compare process_wakeup credential state for session %s",
                    session_id,
                    exc_info=True,
                )
            if process_wakeup_pause_matches(
                s,
                model=model,
                provider=model_provider,
                classification='credential_pool_empty',
            ):
                _credential_recovered = False
                _credential_revalidation_provider = _process_wakeup_revalidation_provider(
                    model,
                    model_provider,
                )
                try:
                    _credential_recovered = _process_wakeup_provider_has_recovery_credential(
                        s,
                        model=model,
                        provider=model_provider,
                        provider_id=_credential_revalidation_provider,
                    )
                except Exception:
                    logger.debug(
                        "failed to revalidate process_wakeup credential availability for session %s",
                        session_id,
                        exc_info=True,
                    )
                if _credential_recovered:
                    _recovery_reason = (
                        'credential_state_changed'
                        if _credential_state_changed
                        else 'credential_recovered'
                    )
                    if clear_process_wakeup_pause(s, reason=_recovery_reason):
                        try:
                            s.save(touch_updated_at=False)
                        except Exception:
                            logger.debug(
                                "failed to persist process_wakeup credential recovery reset for session %s",
                                session_id,
                                exc_info=True,
                            )
                elif _credential_state_changed:
                    if _refresh_process_wakeup_pause_credential_fingerprint(s):
                        try:
                            s.save(touch_updated_at=False)
                        except Exception:
                            logger.debug(
                                "failed to persist process_wakeup credential-state fingerprint refresh for session %s",
                                session_id,
                                exc_info=True,
                            )
            _paused_wakeup = suppress_process_wakeup_for_provider_pause(
                s,
                model=model,
                provider=model_provider,
                classification='credential_pool_empty',
            )
            if _paused_wakeup is not None:
                try:
                    PENDING_BG_TASK_COMPLETIONS.discard(s.session_id)
                except Exception:
                    logger.debug(
                        "failed to discard pending bg-task marker for paused wakeup %s",
                        session_id,
                        exc_info=True,
                    )
                try:
                    s.save(touch_updated_at=False)
                except Exception:
                    logger.debug(
                        "failed to persist process_wakeup suppression for session %s",
                        session_id,
                        exc_info=True,
                    )
                _paused_wakeup_response = {
                    "error": PROCESS_WAKEUP_PAUSE_ERROR,
                    "message": (
                        "Automatic process wakeups are paused for this session because "
                        "the provider credential pool is unavailable."
                    ),
                    "process_wakeup_pause": _paused_wakeup,
                    "_status": 409,
                }
    if _paused_wakeup_response is not None:
        return _paused_wakeup_response
    resp = _start_run(
        s,
        msg=msg,
        attachments=[],
        workspace=workspace,
        model=model,
        model_provider=model_provider,
        normalized_model=normalized_model,
        source=turn_source,
        route="start_session_turn",
    )

    # ── Defect B: live-view of server-initiated turns ──────────────────────
    # Option Z starts this turn server-side, so NO browser EventSource is
    # attached to the new STREAMS[stream_id] (the browser only opens
    # /api/chat/stream when IT POSTs /api/chat/start). An already-open tab
    # would therefore see nothing until a manual refresh re-reads persisted
    # state. Fix: fan a lightweight `server_turn_started` {stream_id} frame
    # onto the persistent per-session live-view channel. messages.js handles
    # it by attaching its EXISTING chat-stream renderer (attachLiveStream) to
    # that stream_id — no second renderer, no chat/start POST.
    #
    # Idempotent with the closed-tab path: get_session_channel() is the
    # NON-creating accessor, so when no tab is open this is a pure no-op and
    # the server-side wakeup (the Option Z headline) is completely unaffected.
    # If the user also has the per-turn chat-stream open, the frontend dedupes
    # by stream_id so there is no double-render.
    try:
        status = int((resp or {}).get("_status", 200) or 200)
        stream_id = (resp or {}).get("stream_id")
        if status < 400 and stream_id:
            from api.background_process import get_session_channel

            ch = get_session_channel(session_id)
            if ch is not None:
                ch.emit(
                    "server_turn_started",
                    {
                        "session_id": str(session_id),
                        "stream_id": str(stream_id),
                        "pending_started_at": (resp or {}).get("pending_started_at"),
                        "source": source,
                    },
                )
    except Exception:
        logger.debug(
            "server_turn_started fan-out failed for session %s", session_id, exc_info=True
        )
    return resp








def _is_silent_control_message(message) -> bool:
    """Return True only for the scheduler's exact suppression sentinel.

    ``[SILENT]`` is control-plane output, never conversation content. If a wake
    relay POSTs it and 8701 restarts while the turn is pending, recovery
    materializes it as a visible ``_recovered`` user message. Suppress it before
    session lookup or pending-state mutation. Matching stays exact and
    case-sensitive so ordinary user text is unaffected.
    """
    return str(message or "").strip() == "[SILENT]"


def _handle_chat_start(handler, body, diag=None):
    from api.gateway_chat import webui_gateway_chat_enabled

    try:
        diag.stage("validate_session_id") if diag else None
        try:
            require(body, "session_id")
        except ValueError as e:
            return bad(handler, str(e))
        if _is_silent_control_message(body.get("message")):
            return j(
                handler,
                {"status": "suppressed", "reason": "silent_control_message"},
                status=200,
            )
        if body.get("regenerate") is True:
            from api.runtime_adapter import runtime_adapter_runner_enabled

            if runtime_adapter_runner_enabled():
                return j(handler, {
                    "error": "Regeneration is not supported by the runner backend.",
                    "code": "unsupported_regeneration_backend",
                }, status=409)
        # Reject a stale local Agent runtime before materialising, claiming, or
        # mutating any session state. Gateway-backed turns run in the gateway's
        # process and do not depend on this WebUI process's imported checkout.
        stale_response = _agent_runtime_barrier_response(runner_local_owned=True)
        if stale_response is not None:
            return j(handler, stale_response, status=409)
        diag.stage("get_session") if diag else None
        try:
            s = _get_or_materialize_session(
                body["session_id"],
                refresh_cli_messages=body.get("regenerate") is not True,
            )
        except KeyError:
            # No WebUI sidecar. If this is a foreign-origin session (CLI,
            # TUI, Desktop) with recoverable state.db messages, claim it by
            # materialising a WebUI-owned Session and persisting it as a
            # sidecar. This closes the GET-vs-POST asymmetry where a
            # TUI/Desktop session loads read-only via GET /api/session but
            # 404s on the first POST /api/chat/start, making the typed
            # message disappear into the empty state.
            synth, reason = _claim_or_synthesize_cli_session(body["session_id"])
            if synth is None:
                if webui_gateway_chat_enabled() and is_safe_session_id(body["session_id"]):
                    s = Session(
                        session_id=body["session_id"],
                        workspace=str(resolve_trusted_workspace(get_last_workspace())),
                        model=body.get("model", DEFAULT_MODEL),
                        profile=body.get("profile") or get_active_profile_name(),
                    )
                    with LOCK:
                        SESSIONS[s.session_id] = s
                    try:
                        s.save()
                    except Exception:
                        pass
                else:
                    # 'was_webui' (deleted WebUI session, client should self-heal
                    # via the existing 404 path), 'no_foreign_state' (sid has
                    # no recoverable state anywhere), or 'invalid_sid' (path
                    # safety violation). All collapse to 404 — the client only
                    # knows the right thing to do for "this session is gone".
                    return bad(handler, "Session not found", 404)
            elif reason == "not_claimable":
                # Foreign store says this session is read-only / owned by
                # a non-WebUI process (messaging, claude_code,
                # external_agent, cron, gateway/unknown, or explicit
                # read_only flag). The session is real and viewable, but
                # the WebUI must not take write ownership of it — that
                # would be an ownership-boundary violation (#4911 review).
                # 403 (not 404) because 404 triggers the frontend's
                # empty-state self-heal handler which strips the URL and
                # clears localStorage; for a legitimately-listed read-only
                # session the user should keep their URL and see a refusal,
                # not have their session vanish.
                return bad(
                    handler,
                    "session is read-only in its foreign store; cannot be claimed writeable in WebUI",
                    403,
                )
            else:
                try:
                    synth.save()
                except Exception as _save_err:
                    # Persisting the sidecar failed: surface a generic 500 to
                    # the client (paths sanitised, see _sanitize_error) and log
                    # the full exception server-side. Returning the raw str(exc)
                    # would leak /root/.hermes/webui/sessions/<sid>.json or any
                    # other absolute filesystem path the OSError happened to
                    # carry — #4911 review feedback.
                    logger.exception(
                        "failed to persist materialised sidecar for foreign session %s",
                        body["session_id"],
                    )
                    return bad(
                        handler,
                        f"failed to claim session: {_sanitize_error(_save_err)}",
                        500,
                    )
                s = synth
                try:
                    with LOCK:
                        SESSIONS[s.session_id] = s
                        SESSIONS.move_to_end(s.session_id)
                except Exception:
                    pass
        except PermissionError:
            return bad(handler, "Read-only imported sessions cannot be continued from WebUI", 403)
        diag.stage("validate_profile") if diag else None
        requested_profile = str(body.get("profile") or "").strip()
        if requested_profile:
            try:
                from api.profiles import _PROFILE_ID_RE

                if requested_profile != "default" and not _PROFILE_ID_RE.fullmatch(requested_profile):
                    return bad(handler, "invalid profile", 400)
            except ImportError:
                requested_profile = ""
        session_profile = getattr(s, "profile", None)
        has_persisted_turns = bool(
            getattr(s, "messages", None)
            or getattr(s, "context_messages", None)
            or getattr(s, "pending_user_message", None)
        )
        if requested_profile:
            try:
                from api.profiles import set_request_profile

                set_request_profile(requested_profile)
            except Exception:
                pass
        active_profile = _get_active_profile_name()
        visible = (
            _session_visible_to_active_profile(session_profile, handler)
            or (bool(requested_profile) and _profiles_match(session_profile, requested_profile))
        )
        if not visible:
            if not has_persisted_turns:
                target_prof = requested_profile or active_profile
                if target_prof:
                    s.profile = target_prof
                    session_profile = s.profile
                    visible = True
        if not visible:
            return bad(handler, "Session not found", 404)
        regeneration = None
        if body.get("regenerate") is True:
            if any(key in body for key in ("message", "attachments", "keep_count", "prompt", "prompt_index")):
                return j(handler, {"error": "regeneration accepts only regeneration_revision", "code": "invalid_regeneration_request"}, status=400)
            if not isinstance(body.get("regeneration_revision"), str):
                return j(handler, {"error": "regeneration_revision is required", "code": "stale_regeneration_revision"}, status=409)
            try:
                from api.session_ops import plan_regeneration, RegenerationUnavailable
                regeneration = plan_regeneration(
                    s, expected_revision=body["regeneration_revision"]
                )
            except RegenerationUnavailable as exc:
                return j(handler, {"error": str(exc), "code": exc.code}, status=exc.status)
            msg = regeneration.turn.message_text
            attachments = copy.deepcopy(regeneration.turn.attachments)[:20]
        else:
            msg = None
            attachments = None
        diag.stage("normalize_message") if diag else None
        msg = str(msg if msg is not None else body.get("message", "")).strip()
        if not msg:
            return bad(handler, "message is required")
        diag.stage("normalize_attachments") if diag else None
        if attachments is None:
            attachments = _normalize_chat_attachments(body.get("attachments") or [])[:20]
        recovery = compression_recovery_payload_for_session(s)
        if recovery and not attachments and is_generic_continuation_intent(msg):
            return j(
                handler,
                {
                    "error": "This session exhausted context compression. Start a focused continuation, then describe the next narrow task.",
                    "type": "compression_recovery_required",
                    "recommended_recovery_action": recovery.get("recommended_action"),
                    "compression_recovery": recovery,
                    "session_id": getattr(s, "session_id", body["session_id"]),
                },
                status=409,
            )
        diag.stage("resolve_workspace") if diag else None
        try:
            if regeneration is not None:
                workspace = _resolve_chat_workspace_for_regeneration(s, body.get("workspace"))
            else:
                workspace = _resolve_chat_workspace_with_recovery(s, body.get("workspace"))
        except WorkspaceBindingPersistenceError as e:
            return bad(handler, str(e), 500)
        except ValueError as e:
            return bad(handler, str(e))
        requested_model = body.get("model") or s.model
        requested_provider = (
            body.get("model_provider")
            if "model_provider" in body
            else getattr(s, "model_provider", None)
        )
        _pp_provider, _pp_default, _pp_cfg = _read_profile_model_config(s, requested_provider)
        explicit_model_pick = bool(body.get("explicit_model_pick"))
        moa_config = None
        config_snapshot = get_config_snapshot()
        gateway_chat_enabled = webui_gateway_chat_enabled(config_snapshot)
        if body.get("moa_config"):
            if gateway_chat_enabled:
                return bad(handler, "MoA override is unavailable on gateway-backed sessions", 409)
            from api.commands import resolve_moa_config

            try:
                moa_config = resolve_moa_config()
            except RuntimeError as e:
                return bad(handler, str(e), 503)
        diag.stage("resolve_model_provider") if diag else None
        model, model_provider, normalized_model = _resolve_compatible_session_model_state(
            requested_model,
            requested_provider,
            profile_provider=_pp_provider,
            profile_default_model=_pp_default,
            profile_config=_pp_cfg,
            explicit_model_pick=explicit_model_pick,
        )
        # #5979: record a SIGNATURE of the deliberately-picked model+provider so
        # the streaming resolver can preserve a custom-proxy vendor namespace on a
        # cold catalog — but ONLY while the routing context still matches. On a
        # fresh explicit pick, stamp the signature of the resolved model+provider;
        # otherwise leave any prior signature in place (it self-invalidates when
        # the model/provider changes, since the streaming side recomputes and
        # compares). This survives same-model follow-up sends (the onchange marker
        # is one-shot) yet can't outlive a real switch.
        try:
            if explicit_model_pick and regeneration is None:
                from api.models import model_explicit_pick_signature as _mk_sig
                s.model_explicit_pick_signature = _mk_sig(model, model_provider)
        except Exception:
            pass
        catalog_profile_provider = _pp_provider
        if catalog_profile_provider is None and isinstance(_pp_cfg, dict):
            profile_model_config = _pp_cfg.get("model") or {}
            if isinstance(profile_model_config, dict):
                catalog_profile_provider = profile_model_config.get("provider")
        model_provider = _repair_foreign_session_model_provider(
            s,
            requested_model=requested_model,
            requested_provider=requested_provider,
            resolved_model=model,
            resolved_provider=model_provider,
            explicit_model_pick=explicit_model_pick,
            profile_provider=catalog_profile_provider,
        )
        if model_provider == "moa" and gateway_chat_enabled:
            from api.config import get_effective_default_model

            model_config = config_snapshot.get("model") if isinstance(config_snapshot, dict) else None
            configured_default, configured_default_provider, configured_default_is_moa = (
                _moa_fast_path_model_state(get_effective_default_model(config_snapshot))
            )
            configured_provider = _clean_session_model_provider(
                model_config.get("provider") if isinstance(model_config, dict) else None
            )
            if configured_provider is None and configured_default_is_moa:
                configured_provider = configured_default_provider
            if (
                configured_provider != "moa"
                or model != configured_default
                or explicit_model_pick
            ):
                return bad(handler, "MoA override is unavailable on gateway-backed sessions", 409)
        elif model_provider == "moa" and moa_config is None:
            from api.commands import resolve_moa_config

            try:
                moa_config = resolve_moa_config(model)
            except RuntimeError as e:
                return bad(handler, str(e), 503)
        # NOTE: runtime-adapter selection is delegated to _start_run (shared
        # with start_session_turn so both entry points behave identically
        # under runtime_adapter_enabled() / runtime_adapter_runner_enabled()
        # — Q-2979-A2 / Copilot discussion_r3305864087/r3305864173).
        start_run_kwargs = {
            "msg": msg,
            "attachments": attachments,
            "workspace": workspace,
            "model": model,
            "model_provider": model_provider,
            "normalized_model": normalized_model,
            "source": "webui",
            "route": "/api/chat/start",
            "diag": diag,
            "gateway_chat_enabled": gateway_chat_enabled,
            "regeneration": regeneration,
        }
        if not gateway_chat_enabled and moa_config is not None:
            start_run_kwargs["moa_config"] = moa_config
        recovery_cleared_for_start = None
        def _restore_cleared_recovery():
            if recovery_cleared_for_start is None:
                return None
            s.compression_recovery = recovery_cleared_for_start
            s.recommended_recovery_action = recovery_cleared_for_start.get("recommended_action")
            try:
                s.save()
            except Exception as restore_err:
                logger.exception("failed to restore compression recovery after chat start rejection for %s", getattr(s, "session_id", None))
                return restore_err
            return None

        if recovery and regeneration is None:
            recovery_cleared_for_start = copy.deepcopy(recovery)
            clear_compression_recovery(s)
        try:
            response = _start_run(
                s,
                **start_run_kwargs,
            )
        except Exception as exc:
            if not getattr(exc, "_regeneration_accepted", False):
                _restore_cleared_recovery()
            raise
        # Map adapter-selection NotImplementedError (501) onto the legacy
        # bad-request response shape that this route exposed historically
        # before the helper extraction.
        if response.get("_status") == 501 and "error" in response:
            restore_err = _restore_cleared_recovery()
            if restore_err is not None:
                return bad(handler, f"failed to restore compression recovery: {_sanitize_error(restore_err)}", 500)
            return j(handler, {"error": response["error"]}, status=501)
        status = int(response.pop("_status", 200) or 200)
        if status >= 400 and recovery_cleared_for_start is not None:
            restore_err = _restore_cleared_recovery()
            if restore_err is not None:
                return bad(handler, f"failed to restore compression recovery: {_sanitize_error(restore_err)}", 500)
        diag.stage("response_write") if diag else None
        return j(handler, response, status=status)
    finally:
        if diag:
            diag.finish()



def _resolve_chat_workspace_with_recovery(s, requested_workspace) -> str:
    """Recover stale implicit session workspaces without hiding explicit errors."""
    explicit = requested_workspace not in (None, "")
    if explicit:
        return str(resolve_trusted_workspace(requested_workspace))
    stored_workspace = getattr(s, "workspace", None)
    workspace, recovered = resolve_implicit_workspace_with_recovery(
        stored_workspace,
        get_last_workspace,
    )
    if not recovered:
        return str(workspace)
    persisted = persist_recovered_workspace_binding(
        s,
        workspace,
        expected_workspace=stored_workspace,
    )
    return str(persisted.workspace)


def _resolve_chat_workspace_for_regeneration(s, requested_workspace) -> str:
    """Resolve regeneration's workspace without persisting before start acceptance."""
    if requested_workspace not in (None, ""):
        return str(resolve_trusted_workspace(requested_workspace))
    workspace, _recovered = resolve_implicit_workspace_with_recovery(
        getattr(s, "workspace", None),
        get_last_workspace,
    )
    return str(workspace)


def _normalize_chat_attachments(raw_attachments):
    """Normalize attachment payloads from the browser.

    Older clients send a list of filenames. Newer clients send upload result
    objects containing name/path/mime/size so image attachments can be supplied
    to Hermes as native multimodal inputs for the current turn.
    """
    normalized = []
    if not isinstance(raw_attachments, list):
        return normalized
    for item in raw_attachments:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("filename") or "").strip()
            path = str(item.get("path") or "").strip()
            mime = str(item.get("mime") or "").strip()
            att = {"name": name or path, "path": path, "mime": mime}
            size = item.get("size")
            if isinstance(size, int):
                att["size"] = size
            is_image = item.get("is_image")
            if isinstance(is_image, bool):
                att["is_image"] = is_image
            normalized.append(att)
        else:
            value = str(item).strip()
            if value:
                normalized.append({"name": value, "path": "", "mime": ""})
    return normalized




















# (Git workspace endpoints extracted to api.route_git)






























def _resolve_approval_legacy(sid: str, approval_id: str, choice: str, run_id: str = "") -> bool:
    """Resolve an approval through the existing callback path.

    Slice 3b keeps the RuntimeAdapter as a protocol translator: it delegates to
    this legacy helper rather than owning approval queues or callback state.
    """
    # Pop the targeted entry from the pending queue by approval_id. Old clients
    # that omit approval_id still resolve the oldest entry for compatibility.
    pending = None
    found_target = False
    gateway_keys = []
    local_gateway_approval_id = ""
    gateway_head_matches_target = False
    with _lock:
        reconcile_gateway_pending_mirror_locked(sid)
        queue = _pending.get(sid)
        if isinstance(queue, list):
            if approval_id:
                # Prefer a local exact-id match over a mirrored one, so a
                # preceding remote mirror cannot consume the user's local choice.
                preferred_index = None
                fallback_index = None
                for i, entry in enumerate(queue):
                    if entry.get("approval_id") != approval_id:
                        continue
                    if run_id and str(entry.get("run_id") or "").strip() != run_id:
                        continue
                    if not entry.get(_GATEWAY_MIRROR_FLAG) or not str(entry.get("run_id") or "").strip():
                        preferred_index = i
                        break
                    if fallback_index is None:
                        fallback_index = i
                match_index = preferred_index if preferred_index is not None else fallback_index
                if match_index is not None:
                    pending = queue.pop(match_index)
                    found_target = True
                else:
                    # A stale explicit id must not accidentally approve the
                    # oldest queued command; duplicate/stale responses are
                    # bounded as not-active by the adapter route.
                    pending = None
            else:
                pending = queue.pop(0) if queue else None
                found_target = pending is not None
            if not queue:
                _pending.pop(sid, None)
        elif queue:
            # Legacy single-dict value.
            if (
                not approval_id
                or (
                    queue.get("approval_id") == approval_id
                    and (not run_id or str(queue.get("run_id") or "").strip() == run_id)
                )
            ):
                pending = _pending.pop(sid, None)
                found_target = pending is not None
        # When no _pending entry found AND no explicit approval_id was
        # given, peek into _gateway_queues for pattern_keys so legacy
        # no-id clients still work. When approval_id IS given but not
        # found, the caller sent a stale/duplicate id — do NOT fall
        # through to the gateway queue, or a stale click on approval A
        # would resolve the unrelated live approval B.
        if not pending and not approval_id:
            gw_queue = _gateway_queues.get(sid)
            if gw_queue and len(gw_queue) > 0:
                gw_entry = gw_queue[0]
                # _gateway_queues stores _ApprovalEntry objects; their
                # .data dict carries command, pattern_key, pattern_keys.
                gw_data = getattr(gw_entry, 'data', None) or {}
                gateway_keys = gw_data.get("pattern_keys") or [gw_data.get("pattern_key", "")]
                # Peek is not strict — a concurrent resolver may pop a
                # different gateway entry before we reach
                # resolve_gateway_approval below, but approve_session is
                # idempotent over the session key set so the outcome is
                # the same regardless of which entry wins the race.
                found_target = True
        elif approval_id:
            gw_queue = _gateway_queues.get(sid)
            if gw_queue and len(gw_queue) > 0:
                gw_entry = gw_queue[0]
                gw_data = getattr(gw_entry, "data", None) or {}
                gw_approval_id = str(gw_data.get("approval_id") or "").strip()
                gw_run_id = str(gw_data.get("run_id") or "").strip()
                gateway_head_matches_target = bool(
                    run_id and gw_approval_id == approval_id and gw_run_id == run_id
                )
                if gw_approval_id == approval_id and (not run_id or gw_run_id == run_id):
                    local_gateway_approval_id = approval_id
                elif not run_id and found_target and pending:
                    # The no-run mirror may belong to a NON-head producer
                    # (multiple parked entries, #7093). The queue head's own
                    # token won't match a non-head mirror, so scan every live
                    # producer for a token/approval_id match instead of only
                    # comparing against `_gateway_queues[0]`.
                    pending_token = str(pending.get(_GATEWAY_MIRROR_TOKEN) or "").strip()
                    matched_data = None
                    for _cand in gw_queue:
                        _cand_data = getattr(_cand, "data", None) or {}
                        _cand_token = str(_cand_data.get("_webui_mirror_token") or "").strip()
                        if pending_token and _cand_token == pending_token:
                            matched_data = _cand_data
                            break
                        if (str(_cand_data.get("approval_id") or "").strip() == approval_id
                                and not str(_cand_data.get("run_id") or "").strip()):
                            matched_data = _cand_data
                            break
                    if matched_data is not None:
                        matched_data["approval_id"] = approval_id
                        local_gateway_approval_id = approval_id
        # Notify SSE subscribers of the new head (or empty state) so the UI
        # surfaces any trailing approvals that were queued behind this one
        # without waiting for the next submit_pending. Without this, a parallel
        # tool-call scenario (#527) would leave the second approval invisible
        # in the SSE path until the next event ever fired (the agent thread
        # would be parked indefinitely from the user's perspective).
        if not local_gateway_approval_id:
            if isinstance(_pending.get(sid), list) and _pending[sid]:
                _approval_sse_notify_locked(sid, _pending[sid][0], len(_pending[sid]))
            else:
                _approval_sse_notify_locked(sid, None, 0)

    # Collect keys from both _pending and _gateway_queues
    keys_from_pending = pending.get("pattern_keys") or [pending.get("pattern_key", "")] if pending else []
    all_keys = [k for k in keys_from_pending if k] + [k for k in gateway_keys if k]
    if choice == "session":
        for k in all_keys:
            approve_session(sid, k)
    elif choice == "always":
        for k in all_keys:
            approve_session(sid, k)
            approve_permanent(k)
        save_permanent_allowlist(_permanent_approved)
    # choice == "once": no persistence — approval lasts this single call only.
    # resolve_gateway_approval() below unblocks the parked agent thread for
    # every choice, so "once" still lets the current tool run; we just must not
    # call approve_session() here, or the next matching guarded call would find
    # the pattern already session-approved and skip its approval card (#6017).
    # Unblock the agent thread waiting in the gateway approval queue.
    # This is the primary signal when streaming is active — the agent
    # thread is parked in entry.event.wait() and needs to be woken up.
    gateway_resolved = 0
    local_gateway_resolved = 0
    if approval_id and found_target and not run_id and local_gateway_approval_id:
        local_gateway_resolved, _head, _total = resolve_gateway_pending_local(
            sid, local_gateway_approval_id, choice
        )
    elif approval_id and found_target and run_id and gateway_head_matches_target:
        gateway_resolved = resolve_gateway_approval(sid, choice, resolve_all=False) or 0
    elif not approval_id:
        gateway_resolved = resolve_gateway_approval(sid, choice, resolve_all=False) or 0
    # Keep the historical no-id response path truthy for old clients/tests while
    # making stale explicit ids bounded as not-active for Slice 3b.
    resolved = bool(pending) or bool(gateway_resolved) or bool(local_gateway_resolved) or not bool(approval_id)
    if resolved:
        publish_session_list_changed("attention_resolved")
    return resolved


_GATEWAY_APPROVAL_RELAY_UNAVAILABLE = (
    "Gateway approval could not be relayed because the active run is unavailable. "
    "Reopen the session or retry after it reconnects."
)
_GATEWAY_APPROVAL_RELAY_IN_PROGRESS = (
    "Another approval response for this Gateway run is already in progress. "
    "Wait for it to finish, then retry if the card is still visible."
)


def _gateway_approval_failure(
    sid: str,
    choice: str,
    *,
    code: str,
    error: str,
    status: int,
    enable_yolo: bool,
    relayed: bool = False,
) -> tuple[dict, int]:
    """Build a failed relay response with authoritative session-YOLO state."""
    payload = {
        "ok": False,
        "choice": choice,
        "relayed": relayed,
        "code": code,
        "error": error,
    }
    if enable_yolo:
        payload["yolo_enabled"] = bool(is_session_yolo_enabled(sid))
    return payload, status


def _relay_gateway_run_approval(
    sid: str,
    mirror: dict,
    choice: str,
    *,
    enable_yolo: bool,
) -> tuple[dict, int]:
    """Relay one exact run-backed mirror under the shared `(session, run)` owner.

    The mirror remains actionable unless the remote Runs API confirms success.
    Both the approval-card endpoint and the ordinary session-YOLO endpoint use
    this chokepoint so one tab cannot retire another tab's parked remote run.
    """
    from api.config import gateway_supports_approval_identity_v1, get_config as _get_config
    from api.gateway_chat import _gateway_api_key, _gateway_base_url
    from api.runner_client import HttpRunnerClient, RunnerClientError

    run_id = str(mirror.get("run_id") or "").strip()
    approval_id = str(mirror.get("approval_id") or "").strip()
    mirror_token = str(mirror.get(_GATEWAY_MIRROR_TOKEN) or "").strip()
    if not run_id or not approval_id:
        return _gateway_approval_failure(
            sid,
            choice,
            code="gateway_run_unavailable",
            error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
            status=409,
            enable_yolo=enable_yolo,
        )
    if not claim_gateway_approval_relay_owner(sid, run_id, approval_id):
        return _gateway_approval_failure(
            sid,
            choice,
            code="gateway_approval_in_progress",
            error=_GATEWAY_APPROVAL_RELAY_IN_PROGRESS,
            status=409,
            enable_yolo=enable_yolo,
        )

    try:
        current_mirror = gateway_pending_mirror(
            sid,
            approval_id=approval_id,
            run_id=run_id,
            mirror_token=mirror_token,
        )
        if not current_mirror:
            return _gateway_approval_failure(
                sid,
                choice,
                code="gateway_run_unavailable",
                error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                status=409,
                enable_yolo=enable_yolo,
            )

        base_url = _gateway_base_url(_get_config())
        api_key = _gateway_api_key()
        from api.jaeger_gateway_routes import lookup
        pinned_route = lookup(run_id)
        if pinned_route:
            base_url, api_key = pinned_route
        identity_v1 = bool(current_mirror.get(_GATEWAY_AGENT_IDENTITY_V1)) and (
            gateway_supports_approval_identity_v1(base_url, api_key)
        )
        if not identity_v1:
            run_head = gateway_pending_mirror(sid, run_id=run_id)
            if not run_head or str(run_head.get("approval_id") or "").strip() != approval_id:
                return _gateway_approval_failure(
                    sid,
                    choice,
                    code="gateway_run_unavailable",
                    error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                    status=409,
                    enable_yolo=enable_yolo,
                )

        yolo_transition = begin_session_yolo_transition(sid) if enable_yolo else None
        relay_error = None
        relay_succeeded = False
        try:
            HttpRunnerClient(base_url=base_url, api_key=api_key).respond_approval(
                run_id,
                approval_id if identity_v1 else "",
                choice,
            )
            relay_succeeded = True
        except (RunnerClientError, ValueError) as exc:
            relay_error = str(exc)
        finally:
            finish_session_yolo_transition(sid, yolo_transition, succeeded=relay_succeeded)

        if relay_error is not None:
            return _gateway_approval_failure(
                sid,
                choice,
                code="gateway_approval_relay_failed",
                error=relay_error,
                status=502,
                enable_yolo=enable_yolo,
                relayed=True,
            )

        # The outbound relay resumes the remote run. Retire the local projection
        # only after that succeeds, then settle any matching in-process mirror.
        _resolve_approval_legacy(sid, approval_id, choice, run_id=run_id)
        retire_gateway_pending_mirror(
            sid,
            approval_id=approval_id,
            run_id=run_id,
            mirror_token=mirror_token,
        )
        return {
            "ok": True,
            "choice": choice,
            "relayed": True,
            **(
                {"yolo_enabled": bool(is_session_yolo_enabled(sid))}
                if enable_yolo
                else {}
            ),
        }, 200
    finally:
        release_gateway_approval_relay_owner(sid, run_id, approval_id)


def _pending_approval_owner_state(
    sid: str,
    approval_id: str,
    run_id: str = "",
    mirror_token: str = "",
) -> tuple[bool, bool]:
    """Return `(exact_owner_exists, any_pending_exists)` under queue authority."""
    approval_id = str(approval_id or "").strip()
    run_id = str(run_id or "").strip()
    mirror_token = str(mirror_token or "").strip()
    with _lock:
        reconcile_gateway_pending_mirror_locked(sid)
        queue = _pending.get(sid)
        entries = queue if isinstance(queue, list) else [queue] if queue else []
        exact = False
        for entry in entries:
            if not isinstance(entry, dict) or str(entry.get("approval_id") or "") != approval_id:
                continue
            entry_run_id = str(entry.get("run_id") or "").strip()
            entry_mirror_token = str(entry.get(_GATEWAY_MIRROR_TOKEN) or "").strip()
            if run_id and entry_run_id != run_id:
                continue
            if mirror_token and entry_mirror_token != mirror_token:
                continue
            if (run_id or mirror_token) and not entry.get(_GATEWAY_MIRROR_FLAG):
                continue
            exact = True
            break
        return exact, bool(entries or _gateway_queues.get(sid))


def _enable_session_yolo_and_release_pending(
    sid: str,
    *,
    choice: str,
    approval_id: str = "",
    run_id: str = "",
    mirror_token: str = "",
    include_choice: bool = False,
) -> tuple[dict, int]:
    """Relay every parked remote approval, drain local waiters, then commit YOLO."""
    approval_id = str(approval_id or "").strip()
    run_id = str(run_id or "").strip()
    mirror_token = str(mirror_token or "").strip()
    has_exact_remote_owner = bool(run_id or mirror_token)
    if has_exact_remote_owner and (not approval_id or not run_id or not mirror_token):
        return _gateway_approval_failure(
            sid,
            choice,
            code="gateway_run_unavailable",
            error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
            status=409,
            enable_yolo=True,
        )

    yolo_transition = None
    try:
        with gateway_yolo_handoff(sid):
            yolo_transition = begin_session_yolo_transition(sid)
            stale_cleared = False
            if approval_id:
                exact_owner, any_pending = _pending_approval_owner_state(
                    sid,
                    approval_id,
                    run_id,
                    mirror_token,
                )
                if not exact_owner and (has_exact_remote_owner or any_pending):
                    return _gateway_approval_failure(
                        sid,
                        choice,
                        code="gateway_run_unavailable",
                        error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                        status=409,
                        enable_yolo=True,
                    )
                stale_cleared = not exact_owner

            run_mirrors = gateway_pending_mirrors(sid)
            relayed = 0
            for mirror in run_mirrors:
                relay_payload, relay_status = _relay_gateway_run_approval(
                    sid,
                    mirror,
                    choice,
                    enable_yolo=False,
                )
                if relay_status != 200 or not relay_payload.get("ok"):
                    finish_session_yolo_transition(
                        sid,
                        yolo_transition,
                        succeeded=False,
                    )
                    yolo_transition = None
                    return {
                        **relay_payload,
                        "yolo_enabled": bool(is_session_yolo_enabled(sid)),
                    }, relay_status
                relayed += 1

            resolve_gateway_pending_local_all(
                sid,
                choice,
            )
            finish_session_yolo_transition(sid, yolo_transition, succeeded=True)
            yolo_transition = None
            return {
                "ok": True,
                "yolo_enabled": bool(is_session_yolo_enabled(sid)),
                **({"choice": choice} if include_choice or relayed else {}),
                **({"relayed": True} if relayed else {}),
                **({"stale_cleared": True} if stale_cleared else {}),
            }, 200
    finally:
        if yolo_transition is not None:
            finish_session_yolo_transition(sid, yolo_transition, succeeded=False)




def _session_has_pending_approval(sid: str) -> bool:
    """True when the session still has any live pending approval to act on.

    Used to tell a benign STALE-CARD click (the card's approval already
    resolved or its stream ended, so nothing is pending) apart from a stale
    explicit-id click made WHILE a different approval is still live (which must
    stay unresolved so it can't accidentally approve the wrong command — #527).
    Reconciles the gateway mirror first so a purged orphan is not counted.
    """
    with _lock:
        reconcile_gateway_pending_mirror_locked(sid)
        queue = _pending.get(sid)
        if isinstance(queue, list):
            if queue:
                return True
        elif queue:
            return True
        gw_queue = _gateway_queues.get(sid)
        return bool(gw_queue)


def _respond_gateway_store_approval(sid: str, approval_id: str, choice: str) -> tuple[dict, int] | None:
    """Answer a pending Gateway approval by id when it belongs to this chat
    (or to one of its child sessions). None = not a Gateway card here."""
    rows = _gateway_store_rows(sid)
    if not rows or not any(str(r.get("approval_id") or "") == approval_id for r in rows):
        return None
    ok = _gateway_store_resolve(approval_id, choice)
    if ok:
        logger.info("approval %s resolved on the Gateway (%s) for session %s", approval_id, choice, sid)
        return {"ok": True, "choice": choice, "approval_id": approval_id, "relayed": True,
                "via": "gateway_approvals"}, 200
    return {"ok": False, "choice": choice, "code": "gateway_approval_relay_failed",
            "error": "The Gateway did not accept the approval response."}, 502


def _handle_approval_respond(handler, body):
    sid = body.get("session_id", "")
    if not sid:
        return bad(handler, "session_id is required")
    choice = body.get("choice", "deny")
    if choice not in ("once", "session", "always", "deny"):
        return bad(handler, f"Invalid choice: {choice}")
    approval_id = body.get("approval_id", "")
    enable_yolo = body.get("yolo") is True
    requested_run_id = str(body.get("run_id") or "").strip()
    requested_mirror_token = str(body.get("mirror_token") or "").strip()

    # Jaeger Gateway cards (tool confirms, handoffs, background workers'
    # child cards) are Gateway records keyed by approval_id. They never had a
    # Runs-API run behind them, so the run relay below can only answer 409
    # gateway_run_unavailable for them. Resolve them by id instead.
    if approval_id and not enable_yolo:
        gateway_answer = _respond_gateway_store_approval(sid, approval_id, choice)
        if gateway_answer is not None:
            return j(handler, gateway_answer[0], status=gateway_answer[1])

    if enable_yolo:
        payload, status = _enable_session_yolo_and_release_pending(
            sid,
            choice=choice,
            approval_id=approval_id,
            run_id=requested_run_id,
            mirror_token=requested_mirror_token,
            include_choice=True,
        )
        return j(handler, payload, status=status)

    if requested_run_id or requested_mirror_token:
        if not approval_id or not requested_run_id or not requested_mirror_token:
            relay_payload, relay_status = _gateway_approval_failure(
                sid,
                choice,
                code="gateway_run_unavailable",
                error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                status=409,
                enable_yolo=False,
            )
            return j(handler, relay_payload, status=relay_status)
        exact_mirror = gateway_pending_mirror(
            sid,
            approval_id=approval_id,
            run_id=requested_run_id,
            mirror_token=requested_mirror_token,
        )
        if exact_mirror is None:
            relay_payload, relay_status = _gateway_approval_failure(
                sid,
                choice,
                code="gateway_run_unavailable",
                error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                status=409,
                enable_yolo=False,
            )
            return j(handler, relay_payload, status=relay_status)
        relay_payload, relay_status = _relay_gateway_run_approval(
            sid,
            exact_mirror,
            choice,
            enable_yolo=False,
        )
        return j(handler, relay_payload, status=relay_status)

    # Gateway relay: forward choice to the runs API when session has an active run,
    # or recover the run_id from the mirrored gateway approval entry if the
    # stream pointer has already been cleared.
    try:
        from api.gateway_chat import (
            _STREAM_RUN_IDS,
            webui_gateway_chat_enabled,
        )
        from api.config import get_config as _get_config
        s = get_session(sid)
        _candidate_run_id = None
        if s is not None:
            active_sid = getattr(s, "active_stream_id", None)
            if active_sid:
                _candidate_run_id = _STREAM_RUN_IDS.get(active_sid)
        local_match = False
        run_backed_gateway_matches = 0
        same_run_stale_without_token = False
        with _lock:
            queue = _pending.get(sid)
            entries = queue if isinstance(queue, list) else [queue] if queue else []
            if approval_id:
                local_match = any(
                    isinstance(entry, dict)
                    and entry.get("approval_id") == approval_id
                    and (
                        not entry.get(_GATEWAY_MIRROR_FLAG)
                        or not str(entry.get("run_id") or "").strip()
                    )
                    for entry in entries
                )
                run_backed_gateway_matches = sum(
                    1
                    for entry in entries
                    if isinstance(entry, dict)
                    and entry.get("approval_id") == approval_id
                    and entry.get(_GATEWAY_MIRROR_FLAG)
                    and str(entry.get("run_id") or "").strip()
                )
                gateway_queue = _gateway_queues.get(sid) or []
                live_head_data = getattr(gateway_queue[0], "data", None) or {} if gateway_queue else {}
                live_head_run_id = str(live_head_data.get("run_id") or "").strip()
                live_head_token = (
                    _gateway_mirror_entry_token(gateway_queue[0])
                    if gateway_queue and live_head_data
                    else None
                )
                live_head_approval_id = str(live_head_data.get("approval_id") or "").strip()
                if not live_head_approval_id and live_head_token and live_head_run_id:
                    live_head_approval_id = f"gwrun:{live_head_run_id}:{live_head_token}"
                stale_same_run_id = _candidate_run_id or live_head_run_id
                if (
                    stale_same_run_id
                    and live_head_run_id == stale_same_run_id
                    and live_head_approval_id
                    and live_head_approval_id != approval_id
                ):
                    same_run_stale_without_token = any(
                        isinstance(entry, dict)
                        and entry.get("approval_id") == approval_id
                        and entry.get(_GATEWAY_MIRROR_FLAG)
                        and str(entry.get("run_id") or "").strip() == stale_same_run_id
                        and not str(entry.get(_GATEWAY_MIRROR_TOKEN) or "").strip()
                        for entry in entries
                    )
            else:
                local_match = any(
                    isinstance(entry, dict)
                    and (
                        not entry.get(_GATEWAY_MIRROR_FLAG)
                        or not str(entry.get("run_id") or "").strip()
                    )
                    for entry in entries
                )
        if local_match:
            _candidate_run_id = None
        if approval_id and not local_match and same_run_stale_without_token:
            relay_payload, relay_status = _gateway_approval_failure(
                sid,
                choice,
                code="gateway_run_unavailable",
                error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                status=409,
                enable_yolo=enable_yolo,
            )
            return j(handler, relay_payload, status=relay_status)
        matched_mirror = (
            gateway_pending_mirror(sid, approval_id=approval_id, run_id=_candidate_run_id)
            if approval_id and not local_match
            else None
        )
        _run_id = matched_mirror["run_id"] if matched_mirror else None
        if not matched_mirror and approval_id:
            if local_match:
                _candidate_run_id = None
            elif run_backed_gateway_matches > 1 and not _candidate_run_id:
                relay_payload, relay_status = _gateway_approval_failure(
                    sid,
                    choice,
                    code="gateway_run_unavailable",
                    error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                    status=409,
                    enable_yolo=enable_yolo,
                )
                return j(handler, relay_payload, status=relay_status)
        if _run_id:
            if enable_yolo:
                # The visible card path must serialize the same session-wide
                # handoff as the ordinary /api/session/yolo route and the Runs
                # stream. Revalidate the exact mirror after acquiring it so a
                # later approval cannot be parked while this relay commits YOLO.
                with gateway_yolo_handoff(sid):
                    current_mirror = gateway_pending_mirror(
                        sid,
                        approval_id=approval_id,
                        run_id=_run_id,
                    )
                    if current_mirror is None:
                        relay_payload, relay_status = _gateway_approval_failure(
                            sid,
                            choice,
                            code="gateway_run_unavailable",
                            error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                            status=409,
                            enable_yolo=True,
                        )
                    else:
                        relay_payload, relay_status = _relay_gateway_run_approval(
                            sid,
                            current_mirror,
                            choice,
                            enable_yolo=True,
                        )
            else:
                relay_payload, relay_status = _relay_gateway_run_approval(
                    sid,
                    matched_mirror or {},
                    choice,
                    enable_yolo=False,
                )
            return j(handler, relay_payload, status=relay_status)
        if _candidate_run_id:
            relay_payload, relay_status = _gateway_approval_failure(
                sid,
                choice,
                code="gateway_run_unavailable",
                error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                status=409,
                enable_yolo=enable_yolo,
            )
            return j(handler, relay_payload, status=relay_status)
        # A no-run mirror is local visibility state only. Resolve it only while
        # the exact parked producer still exists; otherwise keep the card live
        # and fail closed instead of claiming success.
        if webui_gateway_chat_enabled(_get_config()):
            handled_no_run_mirror, resolved_count, _, _ = resolve_gateway_pending_local_no_run_mirror(
                sid, approval_id, choice
            )
            if handled_no_run_mirror and resolved_count == 1:
                if enable_yolo:
                    set_session_yolo_enabled(sid, True)
                return j(handler, {
                    "ok": True,
                    "choice": choice,
                    "local_retired": True,
                    **(
                        {"yolo_enabled": bool(is_session_yolo_enabled(sid))}
                        if enable_yolo
                        else {}
                    ),
                })
            if handled_no_run_mirror:
                relay_payload, relay_status = _gateway_approval_failure(
                    sid,
                    choice,
                    code="gateway_run_unavailable",
                    error=_GATEWAY_APPROVAL_RELAY_UNAVAILABLE,
                    status=409,
                    enable_yolo=enable_yolo,
                )
                return j(handler, relay_payload, status=relay_status)
    except Exception:
        pass  # fall through to local approval path

    resident = _resident_resolve_approval(sid, approval_id, choice)
    if resident is True:
        return j(handler, {"ok": True, "choice": choice})
    if resident is False:
        return j(handler, {"ok": False, "error": "Approval response not accepted."}, status=409)

    from api.runtime_adapter import LegacyJournalRuntimeAdapter, runtime_adapter_enabled

    if runtime_adapter_enabled():
        adapter = LegacyJournalRuntimeAdapter(approval_delegate=_resolve_approval_legacy)
        ok = adapter.respond_approval(sid, approval_id, choice).accepted
    else:
        ok = _resolve_approval_legacy(sid, approval_id, choice)
    if not ok and not _session_has_pending_approval(sid):
        # The local resolution path returns False when an explicit approval_id
        # was sent but no matching pending entry exists. There are two distinct
        # causes, and only one is an error:
        #   (a) a STALE CARD — the approval the card was rendered from already
        #       resolved or its stream ended (cancel / fork / provider error /
        #       completion while pending), so the agent's gateway entry was
        #       dropped and reconcile purged the mirror. Nothing is pending for
        #       this session anymore. Before #4771 the frontend was
        #       fire-and-forget and this silently cleared the card; #4771 began
        #       surfacing the bare {ok:false} as "Approval response not
        #       accepted." with a STUCK card (reported by Jamie on .666 / b3nw;
        #       the local-backend variant of #4948).
        #   (b) a STALE EXPLICIT ID while a DIFFERENT approval IS live — that
        #       MUST stay ok:false so a stale click on resolved approval A can
        #       never resolve the unrelated live approval B (#527 guard).
        # Distinguish them: when the session has NO pending approval at all,
        # the click is benign — report it resolved so the UI clears the orphan
        # card instead of dead-ending. When something IS still pending, keep
        # the protective ok:false. `stale_cleared` lets the frontend log/branch
        # without showing an error toast.
        if enable_yolo:
            set_session_yolo_enabled(sid, True)
        return j(handler, {
            "ok": True,
            "choice": choice,
            "stale_cleared": True,
            **(
                {"yolo_enabled": bool(is_session_yolo_enabled(sid))}
                if enable_yolo
                else {}
            ),
        })
    if ok and enable_yolo:
        set_session_yolo_enabled(sid, True)
    return j(handler, {
        "ok": ok,
        "choice": choice,
        **(
            {"yolo_enabled": bool(is_session_yolo_enabled(sid))}
            if ok and enable_yolo
            else {}
        ),
    })































































