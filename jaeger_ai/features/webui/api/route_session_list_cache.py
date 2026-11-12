"""Session-list cache helpers extracted from api.routes."""

import os
import copy
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

from api.config import LOCK, SESSION_DIR, SESSIONS, SETTINGS_FILE
from api.models import _active_state_db_path, _active_stream_ids
from api.profiles import _profiles_match




_SESSIONS_CACHE_TTL_SECONDS = 2.5
_SESSIONS_CACHE: OrderedDict[tuple, tuple[float, tuple, dict]] = OrderedDict()
_SESSIONS_CACHE_LOCK = threading.RLock()
_SESSIONS_CACHE_GLOBAL_INVALIDATION_VERSION = 0
_SESSIONS_CACHE_ALL_PROFILES_INVALIDATION_VERSION = 0
_SESSIONS_CACHE_PROFILE_INVALIDATION_VERSION: dict[str, int] = {}




def _session_list_cache_session_dir() -> Path:
    try:
        import api.routes as _routes

        value = getattr(_routes, "SESSION_DIR", SESSION_DIR)
        return Path(value)
    except Exception:
        return SESSION_DIR


def _session_list_cache_settings_file() -> Path:
    try:
        import api.routes as _routes

        value = getattr(_routes, "SETTINGS_FILE", SETTINGS_FILE)
        return Path(value)
    except Exception:
        return SETTINGS_FILE


def _session_list_cache_state_db_path():
    try:
        import api.routes as _routes

        override = getattr(_routes, "_active_state_db_path", None)
        if callable(override) and override is not _session_list_cache_state_db_path:
            return override()
    except Exception:
        pass
    return _active_state_db_path()


def _session_list_cache_gateway_session_metadata_path() -> Path:
    try:
        import api.routes as _routes

        override = getattr(_routes, "_gateway_session_metadata_path", None)
        if callable(override) and override is not _session_list_cache_gateway_session_metadata_path:
            return Path(override())
    except Exception:
        pass

    try:
        from api.profiles import get_active_hermes_home

        hermes_home = Path(get_active_hermes_home()).expanduser().resolve()
    except Exception:
        hermes_home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".jaeger" / "hermes"))).expanduser().resolve()
    return hermes_home / "sessions" / "sessions.json"


def _session_list_cache_active_stream_ids():
    try:
        import api.routes as _routes

        override = getattr(_routes, "_active_stream_ids", None)
        if callable(override) and override is not _session_list_cache_active_stream_ids:
            return override()
    except Exception:
        pass
    return _active_stream_ids()






def _session_list_cache_profile_scope(profile: str | None) -> str:
    normalized = str(profile or "").strip() or "default"
    if _profiles_match(normalized, "default"):
        return "default"
    return normalized










def _session_list_cache_clear(profile: str | None = None) -> None:
    normalized_profile = _session_list_cache_profile_scope(profile) if profile else None
    with _SESSIONS_CACHE_LOCK:
        global _SESSIONS_CACHE_GLOBAL_INVALIDATION_VERSION
        global _SESSIONS_CACHE_ALL_PROFILES_INVALIDATION_VERSION
        if not profile:
            _SESSIONS_CACHE_GLOBAL_INVALIDATION_VERSION += 1
            _SESSIONS_CACHE_ALL_PROFILES_INVALIDATION_VERSION += 1
            _SESSIONS_CACHE_PROFILE_INVALIDATION_VERSION.clear()
            _SESSIONS_CACHE.clear()
            return
        _SESSIONS_CACHE_ALL_PROFILES_INVALIDATION_VERSION += 1
        _SESSIONS_CACHE_PROFILE_INVALIDATION_VERSION[normalized_profile] = (
            _SESSIONS_CACHE_PROFILE_INVALIDATION_VERSION.get(normalized_profile, 0) + 1
        )
        for cache_key in list(_SESSIONS_CACHE.keys()):
            cache_profile, cache_all_profiles, *_rest = cache_key
            if cache_all_profiles:
                _SESSIONS_CACHE.pop(cache_key, None)
                continue
            if _profiles_match(cache_profile, normalized_profile):
                _SESSIONS_CACHE.pop(cache_key, None)


def _clear_session_list_cache(profile: str | None = None) -> None:
    _session_list_cache_clear(profile=profile)




def _session_list_cache_path_stamp(path: Path | None) -> tuple[int, int]:
    try:
        if path is None:
            return (0, 0)
        st = Path(path).stat()
        return (int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))), int(st.st_size))
    except Exception:
        return (0, 0)


def _session_list_cache_streaming_freeze_marker():
    """Return a hold-down marker while any session is actively streaming, else None.

    During an active chat turn the gateway/CLI writes message rows to state.db
    continuously. Each write advances the WAL stat and the content fingerprint
    (``MAX(rowid)`` of ``messages``) that ``_session_list_cache_source_stamp``
    folds in, so the source stamp changes on essentially every ``/api/sessions``
    poll — popping the cache and forcing a full ``all_sessions()`` rebuild
    mid-stream. That rebuild then contends for the global ``LOCK`` the streaming
    worker holds while writing, which is what drags token output down to
    ~2 tok/s and produces the multi-second (and occasional ~15s) ``/api/sessions``
    latencies in issue #4672.

    The marker is keyed only on the *set* of active stream ids, not on any
    per-write state, so:
      * while the same turn(s) stream, the marker is constant → the cache holds
        steady and rebuilds are bounded to the TTL cadence (one per
        ``_SESSIONS_CACHE_TTL_SECONDS``) instead of one per poll;
      * the instant a stream starts or stops, the active set changes → the
        marker changes → the cache re-validates and the just-finished turn's
        final title/message_count is picked up immediately.

    Structural sidebar mutations (new/deleted/renamed/imported sessions,
    attention, cron completion) do NOT rely on this stamp — they invalidate the
    cache directly through the ``publish_session_list_changed`` listener — so the
    only thing that can lag under the hold-down is a streaming session's own
    title/message_count, which already tolerates a <=TTL refresh delay.
    """
    try:
        active = _session_list_cache_active_stream_ids()
    except Exception:
        return None
    if not active:
        return None
    try:
        return ("streaming", tuple(sorted(str(x) for x in active)))
    except Exception:
        return ("streaming",)


def _session_list_cache_state_db_fingerprint(state_db_path: Path | None):
    try:
        import api.routes as _routes

        override = getattr(_routes, "_session_list_cache_state_db_fingerprint", None)
        if callable(override) and override is not _session_list_cache_state_db_fingerprint:
            return override(state_db_path)
    except Exception:
        pass
    return _session_list_cache_state_db_fingerprint_impl(state_db_path)


def _session_list_cache_state_db_fingerprint_impl(state_db_path: Path | None):
    if state_db_path is None:
        return None
    try:
        from api.models import _sqlite_content_fingerprint

        return _sqlite_content_fingerprint(state_db_path)
    except Exception:
        return None


def _session_list_cache_source_stamp(key: tuple) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int], object, int]:
    _cache_profile, _cache_all_profiles, _cache_show_cli_sessions, *_rest = key
    try:
        swv = _session_list_cache_settings_write_version()
    except Exception:
        swv = 0
    # WebUI-origin sessions can also receive settled rows in state.db when the
    # official Hermes Desktop App continues the same agent session.  The sidebar
    # therefore watches state.db even when the CLI/external-session tab is hidden.
    #
    # Streaming hold-down (#4672): while a turn is in flight, collapse the
    # volatile state.db-derived components (db/WAL stat, gateway metadata, index
    # stat, content fingerprint) to a marker that only changes when a stream
    # starts or stops. This stops per-token message writes from busting the
    # cache and triggering LOCK-contending rebuilds on every poll. The TTL still
    # forces a periodic rebuild so the streaming session's own count/title stay
    # fresh within the TTL window, and settings_file + the settings write
    # version stay live so user-initiated sidebar/setting toggles invalidate
    # immediately. Skipping the fingerprint's SQLite connect here also makes the
    # streaming-path stamp strictly cheaper than the idle path.
    streaming_marker = _session_list_cache_streaming_freeze_marker()
    if streaming_marker is not None:
        return (
            streaming_marker,
            streaming_marker,
            streaming_marker,
            streaming_marker,
            _session_list_cache_path_stamp(_session_list_cache_settings_file()),
            streaming_marker,
            swv,
        )
    try:
        state_db_path = Path(_session_list_cache_state_db_path())
    except Exception:
        state_db_path = None
    try:
        state_db_wal_path = state_db_path.with_name(f"{state_db_path.name}-wal") if state_db_path is not None else None
    except Exception:
        state_db_wal_path = None
    try:
        gateway_metadata_path = _session_list_cache_gateway_session_metadata_path()
    except Exception:
        gateway_metadata_path = None
    try:
        session_index_path = _session_list_cache_session_dir() / "_index.json"
    except Exception:
        session_index_path = None
    return (
        _session_list_cache_path_stamp(state_db_path),
        _session_list_cache_path_stamp(state_db_wal_path),
        _session_list_cache_path_stamp(gateway_metadata_path),
        _session_list_cache_path_stamp(session_index_path),
        _session_list_cache_path_stamp(_session_list_cache_settings_file()),
        # Commit-reliable content fingerprint of state.db — the file-stat stamps
        # above can collide under WAL-mode writes (same mtime_ns bucket + WAL
        # frame size), so without this a freshly-committed CLI/gateway session
        # could be served stale for the cache TTL. Mirrors the models-layer fix.
        _session_list_cache_state_db_fingerprint(state_db_path),
        swv,
    )


def _session_list_cache_settings_write_version() -> int:
    try:
        import api.routes as _routes

        override = getattr(_routes, "_session_list_cache_settings_write_version", None)
        if callable(override) and override is not _session_list_cache_settings_write_version:
            return int(override())
    except Exception:
        pass
    try:
        from api.config import _SETTINGS_WRITE_VERSION

        return int(_SETTINGS_WRITE_VERSION)
    except Exception:
        return 0
















