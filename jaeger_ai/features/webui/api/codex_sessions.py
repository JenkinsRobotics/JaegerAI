"""Read-only projection of Codex desktop and CLI rollout sessions."""

from __future__ import annotations

import functools
import hashlib
import os
from pathlib import Path

from jaeger_ai.features.history_import.codex import CodexHistorySource


CODEX_SOURCE = "codex"
CODEX_SOURCE_LABEL = "Codex"
CODEX_MAX_FILES = 200
CODEX_MAX_FILE_BYTES = 10 * 1024 * 1024


def _default_codex_sessions_dir() -> Path | None:
    override = os.getenv("HERMES_WEBUI_CODEX_SESSIONS_DIR")
    if override:
        return Path(override).expanduser()
    if os.getenv("HERMES_WEBUI_TEST_STATE_DIR"):
        return None
    codex_home = Path(os.getenv("CODEX_HOME", "").strip() or (Path.home() / ".codex"))
    return codex_home.expanduser() / "sessions"


def _session_id(path: Path) -> str:
    digest = hashlib.sha256(str(path.expanduser().resolve()).encode("utf-8")).hexdigest()[:24]
    return f"{CODEX_SOURCE}_{digest}"


def _iter_rollouts(
    sessions_dir: Path | str | None = None,
    *,
    max_files: int = CODEX_MAX_FILES,
    max_file_bytes: int = CODEX_MAX_FILE_BYTES,
):
    root = Path(sessions_dir).expanduser() if sessions_dir is not None else _default_codex_sessions_dir()
    if root is None:
        return
    try:
        if root.is_symlink():
            return
        root = root.resolve(strict=False)
        if not root.is_dir():
            return
        candidates = []
        for path in root.rglob("*.jsonl"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                stat = path.stat()
                if stat.st_size > max_file_bytes:
                    continue
                candidates.append((stat.st_mtime_ns, path))
            except OSError:
                continue
        for _mtime, path in sorted(candidates, key=lambda item: item[0], reverse=True)[:max_files]:
            yield path
    except OSError:
        return


@functools.lru_cache(maxsize=1000)
def _parse_cached(path_text: str, mtime_ns: int, size: int, ctime_ns: int):
    del mtime_ns, size, ctime_ns
    return CodexHistorySource().parse(Path(path_text))


def _parse(path: Path):
    try:
        stat = path.stat()
    except OSError:
        return None
    try:
        return _parse_cached(str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
    except (OSError, ValueError):
        return None


def _messages(parsed) -> list[dict]:
    return [
        {"role": row.get("role"), "content": row.get("text", ""), "timestamp": row.get("ts")}
        for row in parsed.messages
        if row.get("text")
    ]


def get_codex_sessions(
    sessions_dir: Path | str | None = None,
    *,
    max_files: int = CODEX_MAX_FILES,
    max_file_bytes: int = CODEX_MAX_FILE_BYTES,
) -> list[dict]:
    sessions = []
    for path in _iter_rollouts(
        sessions_dir, max_files=max_files, max_file_bytes=max_file_bytes
    ) or ():
        parsed = _parse(path)
        if parsed is None:
            continue
        messages = _messages(parsed)
        if not messages:
            continue
        timestamps = [row["timestamp"] for row in messages if row.get("timestamp") is not None]
        try:
            fallback = path.stat().st_mtime
        except OSError:
            fallback = 0.0
        created_at = min(timestamps) if timestamps else fallback
        updated_at = max(timestamps) if timestamps else fallback
        sessions.append(
            {
                "session_id": _session_id(path),
                "title": parsed.title or "Codex Session",
                "workspace": parsed.workspace,
                "model": parsed.model or "codex",
                "message_count": len(messages),
                "created_at": created_at,
                "updated_at": updated_at,
                "last_message_at": updated_at,
                "pinned": False,
                "archived": False,
                "project_id": None,
                "profile": None,
                "source_tag": CODEX_SOURCE,
                "raw_source": CODEX_SOURCE,
                "session_source": "external_agent",
                "source_label": CODEX_SOURCE_LABEL,
                "is_cli_session": True,
                "read_only": True,
            }
        )
    return sessions


def get_codex_session_messages(
    sid: str,
    sessions_dir: Path | str | None = None,
    *,
    max_files: int = CODEX_MAX_FILES,
    max_file_bytes: int = CODEX_MAX_FILE_BYTES,
) -> list[dict]:
    sid = str(sid or "")
    if not sid.startswith(f"{CODEX_SOURCE}_"):
        return []
    for path in _iter_rollouts(
        sessions_dir, max_files=max_files, max_file_bytes=max_file_bytes
    ) or ():
        if _session_id(path) != sid:
            continue
        parsed = _parse(path)
        return _messages(parsed) if parsed is not None else []
    return []


def clear_codex_parse_cache() -> None:
    _parse_cached.cache_clear()
