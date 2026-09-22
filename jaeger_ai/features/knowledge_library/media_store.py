"""Authorization and response metadata for local media previews."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from jaeger_ai.features.webui.api.config import MIME_MAP
except Exception:
    import mimetypes
    MIME_MAP = {ext.lstrip('.'): mime for ext, mime in mimetypes.types_map.items()}


INLINE_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/x-icon",
    "image/bmp",
}
AUDIO_VIDEO_PDF_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/opus",
    "audio/flac",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/ogg",
    "application/pdf",
}
SESSION_MEDIA_TYPES = INLINE_IMAGE_TYPES | AUDIO_VIDEO_PDF_TYPES | {"text/html"}
DENY_FILENAMES = {
    "settings.json",
    "state.db",
    "state.db-wal",
    "state.db-shm",
    "auth.json",
    "auth.lock",
    "config.yaml",
    "config.yml",
    ".env",
    ".signing_key",
    ".pbkdf2_key",
    ".sessions.json",
    "google_token.json",
    "google_client_secret.json",
    "gateway_state.json",
    "channel_directory.json",
    "jobs.json",
    "passkeys.json",
    ".passkey_challenges.json",
    ".login_attempts.json",
}
DENY_SUBDIRS = ("sessions", "memories", "cron", "logs", "checkpoints", "backups")
DENY_TEMP_SUFFIXES = (
    ".sessions.tmp",
    ".login_attempts.tmp",
    ".passkeys.tmp",
    ".passkey_challenges.tmp",
)
MEDIA_TOKEN_RE = re.compile(r"MEDIA:([^\s\)\]]+)")


class MediaStoreError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MediaFile:
    path: Path
    media_type: str
    disposition: str
    content_security_policy: str | None = None


def path_is_within_root(child: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(child), str(root)]) == str(root)
    except ValueError:
        return False


def _normalized(path: Path) -> str:
    return os.path.normcase(str(path.resolve())).casefold()


def _within_ci(child: Path, root: Path) -> bool:
    try:
        normalized_child = _normalized(child)
        normalized_root = _normalized(root)
        return os.path.commonpath([normalized_child, normalized_root]) == normalized_root
    except (OSError, ValueError):
        return False


def _equal_ci(left: Path, right: Path) -> bool:
    try:
        return _normalized(left) == _normalized(right)
    except (OSError, ValueError):
        return False


def _message_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part or "")
            for part in content
        )
    return str(content or "")


def session_media_token_allows_path(session_id: str, target: Path) -> bool:
    session_id = str(session_id or "").strip()
    media_type = MIME_MAP.get(target.suffix.lower(), "application/octet-stream")
    if not session_id or media_type not in SESSION_MEDIA_TYPES:
        return False
    try:
        from api.models import get_session

        session = get_session(session_id)
        target = target.resolve()
    except Exception:
        return False
    for message in getattr(session, "messages", []) or []:
        if not isinstance(message, dict) or str(message.get("role") or "").lower() == "user":
            continue
        text = _message_text(message.get("content"))
        for reference in MEDIA_TOKEN_RE.findall(text) if "MEDIA:" in text else ():
            if "://" in reference:
                continue
            try:
                if Path(reference).expanduser().resolve() == target:
                    return True
            except Exception:
                pass
    return False


def _active_workspace() -> Path | None:
    try:
        from api.workspace import get_last_workspace

        workspace = Path(get_last_workspace()).resolve()
        return workspace if workspace.is_dir() else None
    except Exception:
        return None


def _ares_roots(ares_home: Path, home: Path) -> list[Path]:
    from api.config import STATE_DIR

    candidates: list[Path | None] = [ares_home, home / ".ares", Path(STATE_DIR)]
    try:
        from api.profiles import _DEFAULT_ARES_HOME

        candidates.append(Path(_DEFAULT_ARES_HOME))
    except Exception:
        pass
    roots: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = candidate.expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)
    profile_roots: list[Path] = []
    for root in roots:
        profiles = root / "profiles"
        try:
            profile_roots.extend(child.resolve() for child in profiles.iterdir() if child.is_dir())
        except OSError:
            pass
    for root in profile_roots:
        if root not in roots:
            roots.append(root)
    return roots


def _safe_workspace_carveout(workspace: Path | None, home: Path, roots: list[Path]) -> bool:
    if workspace is None or _equal_ci(workspace, home):
        return False
    if workspace.name.casefold() in {"profiles", *DENY_SUBDIRS} or workspace.parent.name.casefold() == "profiles":
        return False
    return not any(_equal_ci(workspace, root) or _within_ci(root, workspace) for root in roots)


def _reject_sensitive(target: Path, workspace: Path | None, home: Path, roots: list[Path]) -> None:
    deny_dirs = [root / subdir for root in roots for subdir in DENY_SUBDIRS]
    deny_dirs.extend(root / "webui_state" / subdir for root in roots for subdir in DENY_SUBDIRS)
    if any(_within_ci(target, path.resolve()) for path in deny_dirs):
        raise MediaStoreError(403, "Path not in allowed location")
    in_workspace = (
        _safe_workspace_carveout(workspace, home, roots)
        and workspace is not None
        and _within_ci(target, workspace)
    )
    name = target.name.casefold()
    if not in_workspace and any(_within_ci(target, root) for root in roots):
        if name in DENY_FILENAMES or name.endswith(DENY_TEMP_SUFFIXES):
            raise MediaStoreError(403, "Path not in allowed location")


def resolve_media(path: str, *, session_id: str = "", inline: bool = False) -> MediaFile:
    raw_path = str(path or "").strip()
    if not raw_path:
        raise MediaStoreError(400, "path parameter required")
    try:
        target = Path(raw_path).expanduser().resolve()
    except Exception as exc:
        raise MediaStoreError(400, "Invalid path") from exc
    home = Path.home().resolve()
    try:
        from api.profiles import get_active_ares_home

        ares_home = Path(get_active_ares_home()).resolve()
    except Exception:
        ares_home = Path(os.getenv("ARES_HOME", str(home / ".ares"))).expanduser().resolve()
    workspace = _active_workspace()
    allowed_roots = [ares_home, Path("/tmp").resolve(), (home / ".ares").resolve()]
    if workspace is not None:
        allowed_roots.append(workspace)
    for value in os.getenv("MEDIA_ALLOWED_ROOTS", "").split(os.pathsep):
        if value.strip():
            root = Path(value.strip()).expanduser().resolve()
            if root.is_dir():
                allowed_roots.append(root)
    roots = _ares_roots(ares_home, home)
    _reject_sensitive(target, workspace, home, roots)
    within_allowed = any(root.exists() and path_is_within_root(target, root) for root in allowed_roots)
    if not within_allowed and not session_media_token_allows_path(session_id, target):
        raise MediaStoreError(403, "Path not in allowed location")
    if not target.is_file():
        raise MediaStoreError(404, "not found")
    media_type = MIME_MAP.get(target.suffix.lower(), "application/octet-stream")
    html_inline = inline and media_type == "text/html"
    inline_types = INLINE_IMAGE_TYPES | AUDIO_VIDEO_PDF_TYPES
    disposition = (
        "inline"
        if media_type != "image/svg+xml"
        and (media_type in INLINE_IMAGE_TYPES or (inline and media_type in inline_types) or html_inline)
        else "attachment"
    )
    return MediaFile(
        target,
        media_type,
        disposition,
        "sandbox allow-scripts" if html_inline else None,
    )


def html_preview_with_blank_base(raw: bytes) -> bytes:
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
    return text.encode()
