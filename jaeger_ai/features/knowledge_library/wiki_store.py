"""Private-safe local wiki inventory and page reader."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path


PAGE_DIRS = ("entities", "concepts", "comparisons", "queries")
MAX_FILES = 10_000
MAX_PAGE_BYTES = 2 * 1024 * 1024
DOCS_URL = "https://ares-agent.nousresearch.com/docs/user-guide/skills/bundled/research/research-llm-wiki"
FORBIDDEN_ROOTS = {str(Path(path).resolve()) for path in ("/", "/etc", "/usr", "/var", "/opt", "/sys", "/proc")}


class WikiStoreError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _nested(config: dict, key: str):
    if key in config and config.get(key):
        return config[key]
    value = config
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def resolve_root() -> tuple[Path, str, bool]:
    home = Path(os.environ.get("JAEGER_HOME", os.environ.get("ARES_HOME", Path.home() / ".jaeger")))
    raw = os.getenv("WIKI_PATH", "").strip()
    source = "WIKI_PATH" if raw else "default"
    if not raw:
        env_file = home / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("WIKI_PATH="):
                    raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                    source = "WIKI_PATH"
                    break
    if not raw:
        config = get_config()
        raw = _nested(config, "skills.config.wiki.path") or _nested(config, "wiki.path")
        if raw:
            source = "skills.config.wiki.path"
    configured = bool(raw)
    return Path(os.path.expandvars(str(raw or "~/wiki"))).expanduser(), source, configured


def _allowlist(root: Path) -> dict[str, tuple[Path, tuple[int, int]]]:
    try:
        real_root = root.resolve()
    except OSError:
        return {}
    if str(real_root) in FORBIDDEN_ROOTS:
        return {}
    entries = {}
    visited = 0
    for dirname in PAGE_DIRS:
        section = real_root / dirname
        try:
            real_section = section.resolve()
            real_section.relative_to(real_root)
        except (OSError, ValueError):
            continue
        if not real_section.is_dir():
            continue
        for listed in section.rglob("*.md"):
            visited += 1
            if visited > MAX_FILES:
                return entries
            try:
                relative = listed.relative_to(real_root)
                if any(part.startswith(".") or part in {"", ".", ".."} for part in relative.parts):
                    continue
                entry_stat = listed.lstat()
                if entry_stat.st_nlink > 1 or listed.is_symlink():
                    continue
                target = listed.resolve()
                target.relative_to(real_section)
                target.relative_to(real_root)
                stat = target.stat()
                if stat.st_nlink > 1 or not target.is_file():
                    continue
                entries[relative.as_posix()] = (target, (stat.st_dev, stat.st_ino))
            except (OSError, ValueError):
                continue
    return entries


def browse() -> dict:
    root, _source, _configured = resolve_root()
    if not root.is_dir():
        raise WikiStoreError("Wiki not configured or directory not found", 404)
    pages = []
    for relative, (path, identity) in sorted(_allowlist(root).items(), key=lambda row: row[0].lower()):
        try:
            stat = path.stat()
        except OSError:
            continue
        if (stat.st_dev, stat.st_ino) != identity:
            continue
        pages.append(
            {
                "name": Path(relative).name,
                "path": relative,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        )
    return {"pages": pages}


def read_page(relative_path: str) -> dict:
    relative_path = str(relative_path or "")
    parts = relative_path.split("/")
    if not relative_path or "\\" in relative_path or os.path.isabs(relative_path):
        raise WikiStoreError("Invalid path")
    if any(part in {"", ".", ".."} for part in parts):
        raise WikiStoreError("Invalid path")
    root, _source, _configured = resolve_root()
    entry = _allowlist(root).get(relative_path)
    if entry is None:
        raise WikiStoreError("Page not found", 404)
    target, identity = entry
    fd = None
    try:
        fd = os.open(str(target), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        stat = os.fstat(fd)
        if (stat.st_dev, stat.st_ino) != identity:
            raise WikiStoreError("Page not found", 404)
        raw = os.read(fd, MAX_PAGE_BYTES + 1)[:MAX_PAGE_BYTES]
    except WikiStoreError:
        raise
    except OSError as exc:
        raise WikiStoreError("Could not read page", 404) from exc
    finally:
        if fd is not None:
            os.close(fd)
    return {"content": raw.decode("utf-8", errors="replace"), "path": relative_path}


def status() -> dict:
    root, source, configured = resolve_root()
    base = {
        "available": False,
        "enabled": False,
        "status": "missing",
        "entry_count": 0,
        "page_count": 0,
        "raw_source_count": 0,
        "last_updated": None,
        "last_writer": "ai-agent",
        "path_configured": configured,
        "path_source": source,
        "toggle_available": False,
        "toggle_reason": "ARES exposes WIKI_PATH/wiki.path for location, but no stable on/off config flag is currently available.",
        "docs_url": DOCS_URL,
    }
    if not root.exists():
        return base
    if not root.is_dir():
        return {**base, "status": "not_directory"}
    entries = _allowlist(root)
    mtimes = []
    for path, identity in entries.values():
        try:
            stat = path.stat()
            if (stat.st_dev, stat.st_ino) == identity:
                mtimes.append(stat.st_mtime)
        except OSError:
            continue
    raw_count = 0
    raw_dir = root / "raw"
    if raw_dir.is_dir():
        for index, path in enumerate(raw_dir.rglob("*")):
            if index >= MAX_FILES:
                break
            if path.is_file():
                raw_count += 1
    latest = max(mtimes) if mtimes else None
    return {
        **base,
        "available": True,
        "enabled": True,
        "status": "ready" if entries else "empty",
        "entry_count": len(entries),
        "page_count": len(entries),
        "raw_source_count": raw_count,
        "last_updated": (
            datetime.fromtimestamp(latest, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            if latest
            else None
        ),
    }
