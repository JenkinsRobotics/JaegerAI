"""Folder download API route and helper functions.

Decomposed from routes.py for modular WebUI backend architecture.
Streams a zip archive of <session.workspace>/<path> with directory walk size/file limits.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from typing import Any
import urllib.parse as _up
from urllib.parse import parse_qs
import zipfile

from .helpers import bad, j, safe_resolve

logger = logging.getLogger("hermes.webui")


def _content_disposition_value(disposition: str, filename: str) -> str:
    """Build a latin-1-safe Content-Disposition value with RFC 5987 filename*."""
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


def _folder_zip_max_bytes() -> int:
    try:
        mb = int(os.getenv("HERMES_WEBUI_FOLDER_ZIP_MAX_MB", "1024"))
    except ValueError:
        mb = 1024
    return max(1, mb) * 1024 * 1024


def _folder_zip_max_files() -> int:
    try:
        return max(1, int(os.getenv("HERMES_WEBUI_FOLDER_ZIP_MAX_FILES", "50000")))
    except ValueError:
        return 50000


def _folder_download_collect(
    target: Path,
    workspace_root: Path,
    max_bytes: int,
    max_files: int,
) -> tuple[list[tuple[Path, str]], int, str | None]:
    """Walk target dir; return (files, total_bytes, hit_limit_reason_or_None).

    files is a list of (filesystem_path, archive_name) tuples. Each filesystem
    path is reopened through the workspace anchor when streamed into the ZIP.
    Symlinks escaping the workspace are skipped.
    """
    files: list[tuple[Path, str]] = []
    total_bytes = 0
    for root, dirs, names in os.walk(target, followlinks=False):
        root_path = Path(root)
        try:
            if not root_path.resolve().is_relative_to(workspace_root):
                dirs[:] = []
                continue
        except (ValueError, OSError):
            dirs[:] = []
            continue
        for name in names:
            fp = root_path / name
            if fp.is_symlink():
                try:
                    if not fp.resolve().is_relative_to(workspace_root):
                        continue
                except (ValueError, OSError):
                    continue
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if len(files) >= max_files:
                return files, total_bytes, "max_files"
            if total_bytes + size > max_bytes:
                return files, total_bytes, "max_bytes"
            try:
                arcname = fp.relative_to(target)
            except ValueError:
                continue
            files.append((fp, str(arcname)))
            total_bytes += size
    return files, total_bytes, None


def handle_folder_download(handler: Any, parsed: Any) -> bool:
    """GET /api/folder/download?session_id=...&path=...

    Streams a zip of <session.workspace>/<path>. Symlinks escaping the
    workspace are skipped. Empty folders return an empty (valid) zip.
    Respects HERMES_WEBUI_FOLDER_ZIP_MAX_MB and HERMES_WEBUI_FOLDER_ZIP_MAX_FILES.
    Pre-flights the walk so size/count failures return a clean 413 with JSON
    body BEFORE any zip bytes are sent.
    """
    try:
        from api.models import get_session_for_file_ops
        from api.workspace import open_anchored_fd
    except Exception:
        from .models import get_session_for_file_ops
        from .workspace import open_anchored_fd

    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id is required")
    try:
        s = get_session_for_file_ops(sid)
    except KeyError:
        return bad(handler, "Session not found", 404)

    rel = qs.get("path", [""])[0]
    try:
        target = safe_resolve(Path(s.workspace), rel)
    except ValueError:
        return bad(handler, "invalid path", 400)
    if not target.exists():
        return j(handler, {"error": "not found"}, status=404)
    if not target.is_dir():
        return bad(handler, "path must be a directory; use /api/file/raw for single files", 400)

    workspace_root = Path(s.workspace).resolve()
    max_bytes = _folder_zip_max_bytes()
    max_files = _folder_zip_max_files()

    files, total_bytes, limit_hit = _folder_download_collect(
        target, workspace_root, max_bytes, max_files
    )
    if limit_hit == "max_files":
        return j(handler, {
            "error": "too many files",
            "limit": max_files,
            "configure": "HERMES_WEBUI_FOLDER_ZIP_MAX_FILES",
        }, status=413)
    if limit_hit == "max_bytes":
        return j(handler, {
            "error": "folder too large",
            "limit_bytes": max_bytes,
            "configure": "HERMES_WEBUI_FOLDER_ZIP_MAX_MB",
        }, status=413)

    zip_name = (target.name or "workspace") + ".zip"
    handler.send_response(200)
    handler.send_header("Content-Type", "application/zip")
    handler.send_header(
        "Content-Disposition",
        _content_disposition_value("attachment", zip_name),
    )
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Connection", "close")
    handler.end_headers()

    written = 0
    with zipfile.ZipFile(handler.wfile, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for fp, arcname in files:
            fd = None
            try:
                fd = open_anchored_fd(workspace_root, fp.resolve(), want_dir=False)
                info = zipfile.ZipInfo(arcname)
                info.compress_type = zipfile.ZIP_DEFLATED
                with os.fdopen(fd, "rb", closefd=True) as src:
                    fd = None
                    with zf.open(info, "w") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                written += 1
            except (ValueError, OSError, PermissionError) as e:
                logger.warning("folder-download: skipping %s: %s", fp, e)
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
    logger.info(
        "folder-download: streamed %d/%d files (~%d bytes) from %s",
        written, len(files), total_bytes, target,
    )
    return True

