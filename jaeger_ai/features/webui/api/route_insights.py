"""Insights, LLM-Wiki status, and Project-OS dashboard route handlers.

Extracted from routes.py to isolate analytics, wiki stats, and project status logic.
"""
from __future__ import annotations

import collections
import html as _html
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

from api.helpers import bad, j
from api.models import SESSION_DIR

logger = logging.getLogger(__name__)

_LLM_WIKI_DOCS_URL = "https://hermes-agent.nousresearch.com/docs/user-guide/skills/bundled/research/research-llm-wiki"
_LLM_WIKI_PAGE_DIRS = ("entities", "concepts", "comparisons", "queries")


def _llm_wiki_active_hermes_home() -> Path:
    try:
        from api.profiles import get_active_hermes_home
        return Path(get_active_hermes_home()).expanduser()
    except Exception:
        return Path(os.getenv("HERMES_HOME", str(Path.home() / ".jaeger" / "hermes"))).expanduser()


def _llm_wiki_env_file_path(hermes_home: Path) -> str | None:
    env_path = hermes_home / ".env"
    if not env_path.exists() or not env_path.is_file():
        return None
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != "WIKI_PATH":
                continue
            value = value.strip().strip('"').strip("'")
            return value or None
    except Exception:
        return None
    return None


def _llm_wiki_get_config_path_value(config: dict, dotted_key: str) -> str | None:
    if not isinstance(config, dict):
        return None
    if dotted_key in config and config.get(dotted_key):
        return str(config.get(dotted_key))
    cur = config
    for part in dotted_key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return str(cur) if cur else None


def _llm_wiki_config_path() -> str | None:
    try:
        from api.config import get_config as _get_cfg
        cfg = _get_cfg()
    except Exception:
        return None
    return (
        _llm_wiki_get_config_path_value(cfg, "skills.config.wiki.path")
        or _llm_wiki_get_config_path_value(cfg, "wiki.path")
    )


# Cap WIKI walks to prevent self-DoS if WIKI_PATH points at /, /etc, /home, etc.
# Real LLM wikis have under a few thousand files; 10k is generous and catches misconfig.
_LLM_WIKI_MAX_FILES = 10000
# Cap a single served wiki page at 2 MiB so a huge/binary file can't be slurped
# wholesale into memory + a JSON response (DoS / memory-blowup guard).
_LLM_WIKI_MAX_PAGE_BYTES = 2 * 1024 * 1024
# Refuse to walk these system roots even if explicitly configured.
_LLM_WIKI_FORBIDDEN_ROOTS = frozenset(
    str(Path(p).expanduser().resolve()) for p in ("/", "/etc", "/usr", "/var", "/opt", "/sys", "/proc")
)
_WIKI_ALLOWLIST_TTL = 5.0  # seconds
_wiki_allowlist_cache: dict[str, dict[str, object]] = {}
_wiki_allowlist_cache_lock = threading.Lock()


def _llm_wiki_resolve_path() -> tuple[Path, str, bool]:
    hermes_home = _llm_wiki_active_hermes_home()
    raw = os.getenv("WIKI_PATH") or _llm_wiki_env_file_path(hermes_home)
    source = "WIKI_PATH" if raw else "default"
    configured = bool(raw)
    if not raw:
        raw = _llm_wiki_config_path()
        if raw:
            source = "skills.config.wiki.path"
            configured = True
    if not raw:
        raw = "~/wiki"
    return Path(os.path.expandvars(raw)).expanduser(), source, configured


def _llm_wiki_safe_iso(ts: float | None) -> str | None:
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _llm_wiki_count_files(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    # Defense in depth: refuse to walk forbidden system roots even if WIKI_PATH
    # was set to one. The endpoint is auth-gated but a misconfigured server
    # shouldn't self-DoS by rglob'ing all of /etc on every Insights load.
    try:
        if str(root.resolve()) in _LLM_WIKI_FORBIDDEN_ROOTS:
            return 0
    except Exception:
        return 0
    count = 0
    iterated = 0
    for item in root.rglob("*"):
        iterated += 1
        if iterated > _LLM_WIKI_MAX_FILES:
            break  # bounded — prevents hangs on symlink loops or huge trees
        try:
            if item.is_file() and not any(part.startswith(".") for part in item.relative_to(root).parts):
                count += 1
        except Exception:
            continue
    return count


def _llm_wiki_page_files_cache_signature(wiki_path: Path) -> tuple:
    """Return a change-detection signature over the configured wiki sections.

    Reads only the section-level directories (not every page), using
    st_mtime_ns, st_dev, and st_ino so that quick section replacements and
    mtime-ns-resolution changes are both caught.  Missing or inaccessible
    section dirs are represented as ``(section, None)`` so their appearance
    or disappearance also invalidates the cache.
    """
    sig = []
    for section in _LLM_WIKI_PAGE_DIRS:
        section_dir = wiki_path / section
        try:
            st = section_dir.lstat()
        except OSError:
            sig.append((section, None))
            continue
        sig.append((section, st.st_dev, st.st_ino, st.st_mtime_ns))
    return tuple(sig)


def _llm_wiki_page_files_uncached(wiki_path: Path) -> list[Path]:
    pages: list[Path] = []
    # Defense in depth: refuse forbidden system roots, and resolve the wiki root
    # ONCE as the single trust base for all containment checks below.
    try:
        wiki_real = wiki_path.resolve()
        if str(wiki_real) in _LLM_WIKI_FORBIDDEN_ROOTS:
            return pages
    except Exception:
        return pages

    def _is_clean_relpath(rel: Path) -> bool:
        # No dot-prefixed segment (dotfile/dotdir) anywhere in the path.
        return not any(part.startswith(".") for part in rel.parts)

    iterated = 0
    for dirname in _LLM_WIKI_PAGE_DIRS:
        section = wiki_path / dirname
        if not section.exists() or not section.is_dir():
            continue
        # The section itself must resolve UNDER the real wiki root — guards a
        # symlinked section (e.g. concepts -> /tmp/outside) from exposing files
        # outside the wiki tree entirely.
        try:
            section_real = section.resolve()
            section_real.relative_to(wiki_real)
        except (OSError, ValueError):
            continue
        for item in section.rglob("*.md"):
            iterated += 1
            if iterated > _LLM_WIKI_MAX_FILES:
                return pages  # bounded
            try:
                rel = item.relative_to(section)
                if not item.is_file() or not _is_clean_relpath(rel):
                    continue
                # Reject multi-link (hardlinked) page files. A hardlink at a
                # clean *.md name can point at an arbitrary inode (incl. one
                # outside the wiki); O_NOFOLLOW + inode-identity at read time
                # cannot tell such a hardlink apart from the real page, so
                # exclude any file with st_nlink > 1 from the allowlist. (#4375)
                try:
                    if item.lstat().st_nlink > 1:
                        continue
                except OSError:
                    continue
                # Resolve the real target and require it to live under BOTH the
                # real wiki root and the real section, with no dot-prefixed
                # segment on the resolved-relative path. This closes symlink
                # escapes whose link name looks like a clean *.md page but whose
                # target is an arbitrary / hidden / out-of-tree file (the read
                # endpoint would otherwise serve it).
                item_real = item.resolve()
                item_real.relative_to(section_real)
                rel_real = item_real.relative_to(wiki_real)
                if not _is_clean_relpath(rel_real):
                    continue
                pages.append(item)
            except (OSError, ValueError):
                continue
    return pages


def _llm_wiki_page_files(wiki_path: Path) -> list[Path]:
    """Return all allowlisted wiki page paths under *wiki_path*.

    Trust boundary: the allowlist uses ``(st_dev, st_ino)`` inode identity.
    A hardlink created at a listed page name *before* this snapshot is taken
    would carry that page's identity through to the caller's fstat check.
    This is only exploitable with write access to the wiki directory, which
    is outside the realistic threat model (the wiki directory is
    operator-controlled).  Defense-in-depth via an ``openat``-chain with
    no-follow directory fds would close the gap but is deferred — the inode
    match already defeats path-swap and symlink races at open time.
    """
    try:
        wiki_root = wiki_path.resolve()
    except OSError:
        wiki_root = wiki_path

    key = str(wiki_root)
    sig = _llm_wiki_page_files_cache_signature(wiki_root)
    now = time.monotonic()

    with _wiki_allowlist_cache_lock:
        cached = _wiki_allowlist_cache.get(key)
        if (
            cached is not None
            and cached.get("signature") == sig
            and now < cached.get("expires_at", 0)
        ):
            return list(cached["files"])

    pages = _llm_wiki_page_files_uncached(wiki_root)

    with _wiki_allowlist_cache_lock:
        _wiki_allowlist_cache[key] = {
            "signature": sig,
            "expires_at": now + _WIKI_ALLOWLIST_TTL,
            "files": tuple(pages),
        }
    return list(pages)


def _llm_wiki_clear_page_files_cache() -> None:
    """Clear the allowlist cache; intended for tests only."""
    with _wiki_allowlist_cache_lock:
        _wiki_allowlist_cache.clear()


def _llm_wiki_allowlisted_entries(wiki_path: Path) -> dict[str, tuple[Path, tuple[int, int]]]:
    """Return listed relpaths mapped to resolved targets plus stable identity."""
    try:
        wiki_real = wiki_path.resolve()
    except OSError:
        return {}

    def _wiki_read_relpath_is_clean(rel: Path) -> bool:
        rel_text = rel.as_posix()
        return bool(rel.parts) and "\\" not in rel_text and not any(part.startswith(".") for part in rel.parts)

    entries: dict[str, tuple[Path, tuple[int, int]]] = {}
    try:
        for listed_path in _llm_wiki_page_files(wiki_real):
            try:
                rel_listed = listed_path.relative_to(wiki_real)
                if not _wiki_read_relpath_is_clean(rel_listed):
                    continue
                section_real = (wiki_real / rel_listed.parts[0]).resolve()
                section_real.relative_to(wiki_real)
                resolved_target = listed_path.resolve()
                resolved_target.relative_to(section_real)
                if not resolved_target.is_file():
                    continue
                # Reject hardlinked targets (st_nlink > 1): a multi-link file at
                # a clean page name can carry an arbitrary inode through the
                # O_NOFOLLOW + identity read check. Defense in depth alongside
                # the same rejection in the allowlist walk. (#4375)
                if resolved_target.stat().st_nlink > 1:
                    continue
                rel_resolved = resolved_target.relative_to(wiki_real)
                if not _wiki_read_relpath_is_clean(rel_resolved):
                    continue
                st0 = resolved_target.stat()
                if listed_path.resolve() != resolved_target:
                    continue
                entries[rel_listed.as_posix()] = (resolved_target, (st0.st_dev, st0.st_ino))
            except (OSError, ValueError):
                continue
    except Exception:
        return {}
    return entries


def _llm_wiki_status_file_entry_stat(wiki_path: Path, path: Path) -> os.stat_result | None:
    """Return the current top-level status-file entry metadata when it is safe to trust."""
    try:
        wiki_root = wiki_path.resolve()
    except OSError:
        wiki_root = wiki_path
    try:
        path.resolve().relative_to(wiki_root)
        st_entry = path.lstat()
    except (OSError, ValueError):
        return None
    if not _stat.S_ISREG(st_entry.st_mode):
        return None
    return st_entry


def _llm_wiki_verified_status_file_stat(wiki_path: Path, path: Path) -> os.stat_result | None:
    """Return identity-checked metadata for a top-level wiki status file."""
    st_entry = _llm_wiki_status_file_entry_stat(wiki_path, path)
    if st_entry is None:
        return None
    fd = None
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        st_open = os.fstat(fd)
        if (st_open.st_dev, st_open.st_ino) != (st_entry.st_dev, st_entry.st_ino):
            return None
        return st_open
    except OSError:
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _llm_wiki_last_writer(
    wiki_path: Path,
    page_files: list[Path] | list[tuple[Path, tuple[int, int]]],
) -> str:
    """Best-effort last-writer detection for the LLM Wiki status card.

    Closes the gap left by the original panel (commit 2684d6fa, Issue #1257):
    the field was reserved as ``"last_writer": None`` with no reader wired up,
    so the UI always rendered "Not available". This helper makes the field
    useful without breaking the private-safe contract (reads only one line
    of frontmatter and one line of log.md headings, never page bodies).

    Priority:
      1. Most-recently-modified page frontmatter ``updated_by`` / ``writer`` /
         ``author`` (case-insensitive).
      2. Most recent ``log.md`` heading of the form
         ``## [YYYY-MM-DD] <action> | subject`` — returns
         ``"ai-agent (<action>)"`` so the user can see ingest vs update.
      3. Static fallback ``"ai-agent"`` so the UI never shows "Not available"
         for a configured wiki.
    """
    # #3455 review (Codex): resolve the wiki root once and require every file we
    # read to stay under it, so a symlinked .md page can't leak frontmatter from
    # outside the wiki. Also read bounded line-by-line (frontmatter only / log
    # headings only), never full page bodies, per the private-safe status contract.
    try:
        wiki_root = wiki_path.resolve()
    except Exception:
        wiki_root = wiki_path

    def _within_wiki(p: Path) -> bool:
        try:
            return p.resolve().is_relative_to(wiki_root)
        except Exception:
            return False

    # Priority 1: most recent page frontmatter (resolved-path must stay in-wiki)
    latest_page: Path | None = None
    latest_identity: tuple[int, int] | None = None
    latest_mtime = -1.0
    for item in page_files:
        candidate, identity = item if isinstance(item, tuple) else (item, None)
        if not _within_wiki(candidate):
            continue  # skip symlinks resolving outside the wiki
        try:
            st_candidate = candidate.stat()
        except Exception:
            continue
        if identity is not None and (st_candidate.st_dev, st_candidate.st_ino) != identity:
            continue
        mtime = st_candidate.st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_page = candidate
            latest_identity = identity
    if latest_page is not None:
        try:
            fd = os.open(str(latest_page), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                if latest_identity is not None:
                    st_open = os.fstat(fd)
                    if (st_open.st_dev, st_open.st_ino) != latest_identity:
                        raise FileNotFoundError("wiki page changed after allowlist snapshot")
                with os.fdopen(fd, encoding="utf-8", errors="replace") as fh:
                    fd = None
                    first = fh.readline()
                    if first.strip() == "---":
                        # Read only the frontmatter block, bounded to a small line cap.
                        for _ in range(200):
                            line = fh.readline()
                            if line == "" or line.strip() == "---":
                                break  # EOF or end of frontmatter — never touch the body
                            stripped = line.strip()
                            lower = stripped.lower()
                            for key in ("updated_by", "writer", "author"):
                                if lower.startswith(f"{key}:"):
                                    value = stripped.split(":", 1)[1].strip()
                                    if value:
                                        return value
            finally:
                if fd is not None:
                    os.close(fd)
        except Exception:
            pass

    # Priority 2: log.md last entry action verb (heading lines only, bounded)
    log_path = wiki_path / "log.md"
    log_entry = _llm_wiki_status_file_entry_stat(wiki_path, log_path)
    if log_entry is not None:
        try:
            fd = os.open(str(log_path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                st_open = os.fstat(fd)
                if (st_open.st_dev, st_open.st_ino) != (log_entry.st_dev, log_entry.st_ino):
                    raise FileNotFoundError("wiki log changed before open")
                with os.fdopen(fd, encoding="utf-8", errors="replace") as fh:
                    fd = None
                    for _ in range(5000):  # cap the heading scan
                        line = fh.readline()
                        if line == "":
                            break
                        stripped = line.strip()
                        if not stripped.startswith("## [") or "|" not in stripped:
                            continue
                        tail = stripped.split("]", 1)[1].strip() if "]" in stripped else ""
                        action = tail.split()[0] if tail else "update"
                        return f"ai-agent ({action})"
            finally:
                if fd is not None:
                    os.close(fd)
        except Exception:
            pass

    # Priority 3: never return None / "Not available" for a configured wiki
    return "ai-agent"


def _build_llm_wiki_status() -> dict:
    """Return private-safe LLM Wiki status metadata without reading page bodies."""
    try:
        wiki_path, path_source, path_configured = _llm_wiki_resolve_path()
        base = {
            "available": False,
            "enabled": False,
            "status": "missing",
            "entry_count": 0,
            "page_count": 0,
            "raw_source_count": 0,
            "last_updated": None,
            "last_writer": "ai-agent",
            "path_configured": path_configured,
            "path_source": path_source,
            "toggle_available": False,
            "toggle_reason": "Hermes Agent exposes WIKI_PATH/wiki.path for location, but no stable on/off config flag is currently available.",
            "docs_url": _LLM_WIKI_DOCS_URL,
        }
        if not wiki_path.exists():
            return base
        if not wiki_path.is_dir():
            base["status"] = "not_directory"
            return base

        allowlisted_entries = _llm_wiki_allowlisted_entries(wiki_path)
        verified_page_entries: list[tuple[Path, tuple[int, int], os.stat_result]] = []
        for target, identity in allowlisted_entries.values():
            try:
                st = target.stat()
            except Exception:
                continue
            if (st.st_dev, st.st_ino) != identity:
                continue
            verified_page_entries.append((target, identity, st))
        page_entries = [(target, identity) for target, identity, _ in verified_page_entries]
        page_files = [target for target, _, _ in verified_page_entries]
        status_files: list[tuple[Path, float]] = []
        for path in (wiki_path / "SCHEMA.md", wiki_path / "index.md", wiki_path / "log.md"):
            st_status = _llm_wiki_verified_status_file_stat(wiki_path, path)
            if st_status is None:
                continue
            status_files.append((path, st_status.st_mtime))
        status_files.extend((target, st.st_mtime) for target, _, st in verified_page_entries)
        latest = None
        for _, mtime in status_files:
            latest = mtime if latest is None else max(latest, mtime)

        base.update({
            "available": True,
            "enabled": True,
            "status": "ready" if page_files else "empty",
            "entry_count": len(page_files),
            "page_count": len(page_entries),
            "raw_source_count": _llm_wiki_count_files(wiki_path / "raw"),
            "last_updated": _llm_wiki_safe_iso(latest),
            "last_writer": _llm_wiki_last_writer(wiki_path, page_entries),
        })
        return base
    except Exception as exc:
        return {
            "available": False,
            "enabled": False,
            "status": "error",
            "entry_count": 0,
            "page_count": 0,
            "raw_source_count": 0,
            "last_updated": None,
            "last_writer": "ai-agent",
            "path_configured": False,
            "path_source": "unknown",
            "toggle_available": False,
            "toggle_reason": "Unable to inspect LLM Wiki status safely.",
            "docs_url": _LLM_WIKI_DOCS_URL,
            "error": type(exc).__name__,
        }


def _handle_llm_wiki_status(handler, parsed) -> bool:
    j(handler, _build_llm_wiki_status())
    return True


def _handle_insights(handler, parsed) -> bool:
    """Return usage analytics from local WebUI session data."""
    import collections
    import time as _time

    from api.usage import prompt_cache_hit_percent

    query = parse_qs(parsed.query)
    try:
        days = min(max(int(query.get("days", ["30"])[0]), 1), 365)
    except (ValueError, TypeError):
        days = 30

    now = _time.time()
    today = _time.localtime(now)
    today_midnight = _time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, today.tm_wday, today.tm_yday, today.tm_isdst))
    day_secs = 86400
    first_day_ts = today_midnight - ((days - 1) * day_secs)
    cutoff = first_day_ts

    def _safe_usage_int(value) -> int:
        try:
            return max(int(float(value or 0)), 0)
        except (TypeError, ValueError):
            return 0

    def _safe_cost_float(value) -> float:
        if value is None:
            return 0.0
        try:
            if isinstance(value, str):
                value = value.strip().replace("$", "").replace(",", "")
                if not value:
                    return 0.0
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _session_usage_ts(session: dict) -> float:
        return session.get("updated_at", session.get("created_at", 0)) or session.get("created_at", 0) or 0

    # Walk session index (fast, no full JSON parse)
    sessions_data = []
    idx_path = SESSION_DIR / "_index.json"
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = []
    else:
        idx = []

    for entry in idx:
        created = entry.get("created_at", 0) or 0
        updated = entry.get("updated_at", 0) or 0
        # Session is relevant if it was created or updated within the calendar window.
        if max(created, updated) < cutoff:
            continue
        sessions_data.append(entry)

    # Aggregate
    total_sessions = len(sessions_data)
    total_messages = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cost = 0.0
    model_stats: dict[str, dict] = {}
    daily_tokens: dict[str, dict] = {}
    # Activity by day of week (0=Mon .. 6=Sun)
    dow_activity = collections.Counter()
    # Activity by hour of day (0-23)
    hod_activity = collections.Counter()

    for s in sessions_data:
        input_tokens = _safe_usage_int(s.get("input_tokens"))
        output_tokens = _safe_usage_int(s.get("output_tokens"))
        cache_read_tokens = _safe_usage_int(s.get("cache_read_tokens"))
        cost_value = _safe_cost_float(s.get("estimated_cost"))
        total_messages += _safe_usage_int(s.get("message_count"))
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_cache_read_tokens += cache_read_tokens
        total_cost += cost_value

        model = s.get("model") or "unknown"
        bucket = model_stats.setdefault(model, {
            "sessions": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cost": 0.0,
        })
        bucket["sessions"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["cache_read_tokens"] += cache_read_tokens
        bucket["cost"] += cost_value

        # Activity patterns
        ts = _session_usage_ts(s)
        if ts:
            try:
                dt = _time.localtime(ts)
                day_key = _time.strftime("%Y-%m-%d", dt)
                daily_bucket = daily_tokens.setdefault(day_key, {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "sessions": 0,
                    "cost": 0.0,
                })
                daily_bucket["input_tokens"] += input_tokens
                daily_bucket["output_tokens"] += output_tokens
                daily_bucket["cache_read_tokens"] += cache_read_tokens
                daily_bucket["sessions"] += 1
                daily_bucket["cost"] += cost_value
                dow_activity[dt.tm_wday] += 1
                hod_activity[dt.tm_hour] += 1
            except Exception:
                pass

    # ── Also include CLI sessions from Hermes state.db ─────────────────────
    try:
        from api.models import _active_state_db_path
        db_path = _active_state_db_path()
        if db_path and db_path.exists():
            with closing(sqlite3.connect(str(db_path))) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                # cache_read_tokens may not exist on older agent state DBs;
                # fall back to a query without it if the column is missing.
                try:
                    cur.execute("""
                        SELECT id, model, message_count, input_tokens, output_tokens,
                               estimated_cost_usd,
                               COALESCE(cache_read_tokens, 0) AS cache_read_tokens,
                               started_at, ended_at
                        FROM sessions
                        WHERE (started_at >= ? OR ended_at >= ?)
                          AND COALESCE(source, '') != 'webui'
                    """, (cutoff, cutoff))
                except sqlite3.OperationalError:
                    cur.execute("""
                        SELECT id, model, message_count, input_tokens, output_tokens,
                               estimated_cost_usd,
                               0 AS cache_read_tokens,
                               started_at, ended_at
                        FROM sessions
                        WHERE (started_at >= ? OR ended_at >= ?)
                          AND COALESCE(source, '') != 'webui'
                    """, (cutoff, cutoff))
                for row in cur.fetchall():
                    _input = _safe_usage_int(row["input_tokens"])
                    _output = _safe_usage_int(row["output_tokens"])
                    _cache_read = _safe_usage_int(row["cache_read_tokens"])
                    _cost = _safe_cost_float(row["estimated_cost_usd"])
                    _msgs = _safe_usage_int(row["message_count"])
                    total_sessions += 1
                    total_messages += _msgs
                    total_input_tokens += _input
                    total_output_tokens += _output
                    total_cache_read_tokens += _cache_read
                    total_cost += _cost

                    _model = row["model"] or "unknown"
                    bucket = model_stats.setdefault(_model, {
                        "sessions": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_tokens": 0,
                        "cost": 0.0,
                    })
                    bucket["sessions"] += 1
                    bucket["input_tokens"] += _input
                    bucket["output_tokens"] += _output
                    bucket["cache_read_tokens"] += _cache_read
                    bucket["cost"] += _cost

                    _ts = row["started_at"] or row["ended_at"] or 0
                    if _ts:
                        _dt = _time.localtime(_ts)
                        _day_key = _time.strftime("%Y-%m-%d", _dt)
                        _daily = daily_tokens.setdefault(_day_key, {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_read_tokens": 0,
                            "sessions": 0,
                            "cost": 0.0,
                        })
                        _daily["input_tokens"] += _input
                        _daily["output_tokens"] += _output
                        _daily["cache_read_tokens"] += _cache_read
                        _daily["sessions"] += 1
                        _daily["cost"] += _cost
                        dow_activity[_dt.tm_wday] += 1
                        hod_activity[_dt.tm_hour] += 1
    except Exception:
        logger.debug("Failed to include CLI sessions in insights", exc_info=True)

    # Build model breakdown
    total_tokens = total_input_tokens + total_output_tokens
    models_breakdown = []
    for model, stats in model_stats.items():
        row_total_tokens = stats["input_tokens"] + stats["output_tokens"]
        row_cost = round(stats["cost"], 6)
        row_cache_read = stats["cache_read_tokens"]
        # Bounded prompt-cache hit rate: cached reads over the FULL prompt total
        # (ordinary input + cache reads), so it can never exceed 100%. Computing
        # cache_read / input_tokens alone would overshoot 100% on cache-heavy
        # sessions. prompt_cache_hit_percent clamps to [0,100] and returns None
        # when there is nothing meaningful to display.
        row_cache_hit_percent = prompt_cache_hit_percent(
            row_cache_read, stats["input_tokens"] + row_cache_read
        )
        models_breakdown.append({
            "model": model,
            "sessions": stats["sessions"],
            "input_tokens": stats["input_tokens"],
            "output_tokens": stats["output_tokens"],
            "cache_read_tokens": row_cache_read,
            "cache_hit_percent": row_cache_hit_percent,
            "total_tokens": row_total_tokens,
            "cost": row_cost,
            "session_share": int(round((stats["sessions"] / total_sessions) * 100)) if total_sessions else 0,
            "token_share": int(round((row_total_tokens / total_tokens) * 100)) if total_tokens else 0,
            "cost_share": int(round((row_cost / total_cost) * 100)) if total_cost else 0,
        })
    models_breakdown.sort(key=lambda r: (-r["cost"], -r["sessions"], r["model"]))

    daily_series = []
    for i in range(days):
        day_ts = first_day_ts + (i * day_secs)
        day_key = _time.strftime("%Y-%m-%d", _time.localtime(day_ts))
        bucket = daily_tokens.get(day_key, {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "sessions": 0,
            "cost": 0.0,
        })
        daily_series.append({
            "date": day_key,
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "cache_read_tokens": bucket.get("cache_read_tokens", 0),
            "sessions": bucket["sessions"],
            "cost": round(bucket["cost"], 6),
        })

    # Day-of-week labels
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_data = [{"day": dow_labels[i], "sessions": dow_activity.get(i, 0)} for i in range(7)]

    # Hour-of-day data
    hod_data = [{"hour": h, "sessions": hod_activity.get(h, 0)} for h in range(24)]

    return j(handler, {
        "period_days": days,
        "total_sessions": total_sessions,
        "total_messages": total_messages,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cache_read_tokens": total_cache_read_tokens,
        # Aggregate prompt-cache hit rate, bounded 0-100% via the shared helper
        # (cache_read over input + cache_read).
        "total_cache_hit_percent": prompt_cache_hit_percent(
            total_cache_read_tokens, total_input_tokens + total_cache_read_tokens
        ),
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "models": models_breakdown,
        "daily_tokens": daily_series,
        "activity_by_day": dow_data,
        "activity_by_hour": hod_data,
    })


def _project_os_workspace_read(repo_root: Path, rel: str) -> dict | None:
    try:
        return read_file_content(repo_root, rel)
    except Exception:
        return None


def _project_os_workspace_json(repo_root: Path, rel: str) -> dict | None:
    payload = _project_os_workspace_read(repo_root, rel)
    if not payload or not isinstance(payload.get("content"), str):
        return None
    try:
        parsed = json.loads(payload.get("content") or "")
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _project_os_truth_board_slugs(repo_root: Path) -> set[str]:
    slugs: set[str] = set()

    def add(value) -> None:
        text = str(value or "").strip()
        if text:
            slugs.add(text)

    for rel in (
        ".ax/handoff/current.json",
        ".ax/status/active.json",
        ".ax/status/heartbeat.json",
    ):
        truth = _project_os_workspace_json(repo_root, rel)
        if not isinstance(truth, dict):
            continue
        raw_board = truth.get("board")
        if isinstance(raw_board, dict):
            add(raw_board.get("slug"))
            add(raw_board.get("id"))
            add(raw_board.get("name"))
            add(raw_board.get("display_name"))
        else:
            add(raw_board)
        for key in (
            "selected_board_slug",
            "canonical_backlog_board_id",
            "current_browser_board_id",
            "active_proof_board_id",
            "recover_board_id",
        ):
            add(truth.get(key))
    return slugs


def _project_os_repo_matches_board(repo_root: Path, board_slug: str | None) -> bool:
    slug = str(board_slug or "").strip()
    return bool(slug and slug in _project_os_truth_board_slugs(repo_root))


def _project_os_candidate_repo_roots(workspace_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser().resolve()
        except Exception:
            return
        if not resolved.is_dir():
            return
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            candidates.append(resolved)

    add(workspace_root)

    scan_root = None
    if workspace_root is not None:
        try:
            scan_root = workspace_root.expanduser().resolve()
        except Exception:
            scan_root = None
    if not scan_root or not scan_root.is_dir():
        return candidates

    skip_names = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "__pycache__",
        "node_modules",
        "vendor",
        "dist",
        "build",
    }
    queue_dirs: list[tuple[Path, int]] = [(scan_root, 0)]
    inspected = 0
    while queue_dirs and inspected < 300:
        current, depth = queue_dirs.pop(0)
        inspected += 1
        if (current / ".ax").is_dir() or (current / "docs" / "project-os").is_dir():
            add(current)
        if depth >= 3:
            continue
        try:
            children = sorted(
                (child for child in current.iterdir() if child.is_dir()),
                key=lambda child: child.name,
            )
        except Exception:
            continue
        for child in children:
            name = child.name
            if name in skip_names or (name.startswith(".") and name != ".ax"):
                continue
            queue_dirs.append((child, depth + 1))
    add(Path.cwd())
    return candidates


def _project_os_resolve_repo_root_for_board(repo_root: Path | None, board_slug: str | None) -> Path | None:
    slug = str(board_slug or "").strip()
    if not slug:
        return repo_root if repo_root and repo_root.exists() else None
    if repo_root and repo_root.exists() and _project_os_repo_matches_board(repo_root, slug):
        return repo_root
    for candidate in _project_os_candidate_repo_roots(repo_root):
        if _project_os_repo_matches_board(candidate, slug):
            return candidate
    return repo_root if repo_root and repo_root.exists() else None


def _project_os_goal_summary(project_md: dict | None, handoff: dict | None, status_md: dict | None, board_name: str | None = None, board_desc: str | None = None) -> str:
    project_text = str((project_md or {}).get("content") or "")
    for line in project_text.splitlines():
        text = line.strip().lstrip("- ").strip()
        if not text or text.startswith("#"):
            continue
        return text[:220]
    handoff_summary = str((handoff or {}).get("goal_summary") or "").strip()
    if handoff_summary:
        return handoff_summary[:220]
    desc = str(board_desc or "").strip()
    if desc:
        return desc[:220]
    status_text = str((status_md or {}).get("content") or "")
    for line in status_text.splitlines():
        text = line.strip().lstrip("- ").strip()
        if not text or text.startswith("#"):
            continue
        return text[:220]
    return str(board_name or "Project OS").strip()[:220]


def _project_os_onboarding_context(repo_root: Path, project_md: dict | None, plan_md: dict | None, status_md: dict | None) -> dict:
    project_text = str((project_md or {}).get("content") or "")
    plan_text = str((plan_md or {}).get("content") or "")
    status_text = str((status_md or {}).get("content") or "")
    merged = "\n".join([project_text, plan_text, status_text])
    is_non_git_workspace = not (repo_root / ".git").exists()
    has_boundary_hold = "TO_BE_VALIDATED_BY_HERMES" in merged
    child_repo_blocked = (
        "auto-promoted" in merged
        or "auto-adopted" in merged
        or "auto-adoption | `금지`" in merged
        or "자동 승격 금지" in merged
        or "canonical repo continuity로 승격하지 않습니다" in merged
    )
    workspace_root_confirmed = str(repo_root) in merged
    if not (is_non_git_workspace and (project_text or plan_text or status_text)):
        return {
            "active": False,
            "doc_source": "project-os",
        }
    status_label = "보류(안전)" if has_boundary_hold else "확인됨"
    summary = "workspace root onboarding 진행 중 · 저장소 경계는 아직 미확정이며 자동 승격은 금지됩니다."
    next_safe_action = "workspace-root 기준으로 경계만 좁게 검증"
    if has_boundary_hold:
        summary = "workspace root onboarding 진행 중 · 저장소 경계는 아직 미확정이며 TO_BE_VALIDATED_BY_HERMES 상태를 유지합니다."
    return {
        "active": True,
        "doc_source": "root",
        "status_label": status_label,
        "summary": summary,
        "next_safe_action": next_safe_action,
        "workspace_root_confirmed": workspace_root_confirmed,
        "repo_boundary_status": "TO_BE_VALIDATED_BY_HERMES" if has_boundary_hold else "confirmed",
        "child_repo_auto_promotion_blocked": bool(child_repo_blocked),
        "guardrails": [
            "workspace root 확인됨" if workspace_root_confirmed else "workspace root 확인 필요",
            "child repo 자동 승격 금지 유지" if child_repo_blocked else "child repo guardrail 확인 필요",
            "repo boundary 미확정 유지" if has_boundary_hold else "repo boundary confirmed",
        ],
    }


def _handle_project_os_dashboard(handler, parsed) -> bool:
    qs = parse_qs(parsed.query or "")
    requested_board = str((qs.get("board") or [""])[0] or "").strip()
    workspace_raw = str(get_last_workspace() or "").strip()
    repo_root = Path(workspace_raw).expanduser() if workspace_raw else None
    selected_board_meta = None
    if requested_board:
        try:
            from api.kanban_bridge import _kb, _board_meta_dict
            kb = _kb()
            for meta in kb.list_boards(include_archived=True) or []:
                board = _board_meta_dict(meta)
                if str(board.get("slug") or "") == requested_board:
                    selected_board_meta = board
                    workdir = str(board.get("default_workdir") or "").strip()
                    if workdir:
                        candidate = Path(workdir).expanduser()
                        if candidate.exists():
                            repo_root = candidate
                    break
        except Exception:
            selected_board_meta = None
    repo_root = _project_os_resolve_repo_root_for_board(repo_root, requested_board)
    if not repo_root or not repo_root.exists():
        j(handler, {
            "workspace": None,
            "repo_root": None,
            "git": None,
            "docs": {},
            "handoff": None,
            "active": None,
            "heartbeat": None,
            "goal_summary": "",
        })
        return True

    handoff = _project_os_workspace_json(repo_root, ".ax/handoff/current.json")
    active = _project_os_workspace_json(repo_root, ".ax/status/active.json")
    heartbeat = _project_os_workspace_json(repo_root, ".ax/status/heartbeat.json")
    project_md = _project_os_workspace_read(repo_root, "docs/project-os/PROJECT.md")
    plan_md = _project_os_workspace_read(repo_root, "docs/project-os/PLAN.md")
    status_md = _project_os_workspace_read(repo_root, "docs/project-os/STATUS.md")
    blocker_md = _project_os_workspace_read(repo_root, "docs/project-os/BLOCKER-RESOLVER.md")
    root_project_md = _project_os_workspace_read(repo_root, "PROJECT.md")
    root_plan_md = _project_os_workspace_read(repo_root, "PLAN.md")
    root_status_md = _project_os_workspace_read(repo_root, "STATUS.md")
    onboarding = _project_os_onboarding_context(repo_root, root_project_md, root_plan_md, root_status_md)
    if onboarding.get("active"):
        project_md = root_project_md or project_md
        plan_md = root_plan_md or plan_md
        status_md = root_status_md or status_md

    if isinstance(active, dict):
        original_repo_root = repo_root
        active_repo_root = str(active.get("repo_root") or "").strip()
        if active_repo_root:
            candidate = Path(active_repo_root).expanduser()
            if candidate.exists():
                try:
                    repo_root = candidate.resolve()
                except Exception:
                    repo_root = candidate
        if repo_root != original_repo_root:
            handoff = _project_os_workspace_json(repo_root, ".ax/handoff/current.json")
            active = _project_os_workspace_json(repo_root, ".ax/status/active.json")
            heartbeat = _project_os_workspace_json(repo_root, ".ax/status/heartbeat.json")
            project_md = _project_os_workspace_read(repo_root, "docs/project-os/PROJECT.md")
            plan_md = _project_os_workspace_read(repo_root, "docs/project-os/PLAN.md")
            status_md = _project_os_workspace_read(repo_root, "docs/project-os/STATUS.md")
            blocker_md = _project_os_workspace_read(repo_root, "docs/project-os/BLOCKER-RESOLVER.md")
            root_project_md = _project_os_workspace_read(repo_root, "PROJECT.md")
            root_plan_md = _project_os_workspace_read(repo_root, "PLAN.md")
            root_status_md = _project_os_workspace_read(repo_root, "STATUS.md")
            onboarding = _project_os_onboarding_context(repo_root, root_project_md, root_plan_md, root_status_md)
            if onboarding.get("active"):
                project_md = root_project_md or project_md
                plan_md = root_plan_md or plan_md
                status_md = root_status_md or status_md

    try:
        git = git_info_for_workspace(repo_root)
    except Exception:
        git = None

    board_name = None
    board_desc = None
    if isinstance(handoff, dict):
        board_dict: dict = {}
        raw_board = handoff.get("board")
        if isinstance(raw_board, dict):
            board_dict = raw_board
        board_name = board_dict.get("display_name") or board_dict.get("name") or board_dict.get("slug")
        board_desc = handoff.get("goal_summary") or board_dict.get("repo_corroboration")
    if selected_board_meta:
        board_name = board_name or selected_board_meta.get("name") or selected_board_meta.get("slug")
        board_desc = board_desc or selected_board_meta.get("description")

    j(handler, {
        "workspace": str(repo_root),
        "repo_root": str(repo_root),
        "selected_board_slug": requested_board or (selected_board_meta or {}).get("slug"),
        "git": git,
        "docs": {
            "project": project_md,
            "plan": plan_md,
            "status": status_md,
            "blocker_resolver": blocker_md,
        },
        "handoff": handoff,
        "active": active,
        "heartbeat": heartbeat,
        "onboarding": onboarding,
        "goal_summary": _project_os_goal_summary(project_md, handoff, status_md, board_name, board_desc),
    })
    return True


