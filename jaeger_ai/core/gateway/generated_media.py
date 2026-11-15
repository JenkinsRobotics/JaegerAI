"""Register an official image-generation tool result as a session attachment.

The tool (Grok Imagine via the official CLI, or a later sanctioned backend)
writes a raster file under the instance workspace or skills dir. This copies
those bytes into the session attachment store so the chat bubble can render
them as a first-class attachment — not a markdown image — and so they survive
reload.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IMAGE_TOOLS = frozenset({"image_generate", "image_edit", "generate_image_fal"})
RASTER_MIMES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
def _sniff_mime(path: Path) -> str | None:
    with path.open("rb") as fh:
        head = fh.read(16)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed if guessed in RASTER_MIMES else None


def _under_allowed(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if not resolved.is_file() or resolved.is_dir():
        return False
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)


def _instance_roots(session_workspace: str | None) -> list[Path]:
    roots: list[Path] = []
    try:
        from jaeger_ai.core.entity.runtime import EntityRuntime
        layout = getattr(EntityRuntime.get_singleton(), "layout", None)
        if layout is not None:
            for attr in ("root", "workspace_dir", "skills_dir"):
                value = getattr(layout, attr, None)
                if value:
                    roots.append(Path(value).resolve())
    except Exception:
        logger.debug("Instance layout unavailable while registering a generated image", exc_info=True)
    if session_workspace:
        try:
            roots.append(Path(session_workspace).resolve())
        except OSError:
            pass
    # Unique, existing directories only.
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if root in seen or not root.exists():
            continue
        seen.add(root)
        out.append(root)
    return out


def _result_path(result: dict[str, Any]) -> Path | None:
    for key in ("absolute_path", "path", "output_path", "file_path"):
        raw = result.get(key)
        if isinstance(raw, str) and raw.strip():
            return Path(raw.strip())
    return None


def register_generated_image(gateway: Any, *, session_id: str, request_id: str, tool_name: str, result: Any) -> dict[str, Any] | None:
    """Copy a successful image-tool file into the session attachment store.

    Returns a public attachment view (id, name, mime, size, sha256) or None
    when this result is not a registerable generated image.
    """
    if tool_name not in IMAGE_TOOLS or not isinstance(result, dict):
        return None
    if not result.get("generated"):
        return None
    source = _result_path(result)
    if source is None:
        return None
    session = gateway.store.get_session(session_id) if getattr(gateway, "store", None) is not None else None
    if session is None:
        return None
    roots = _instance_roots(session.get("workspace"))
    if not roots or not _under_allowed(source, roots):
        logger.warning("Generated image path is outside the instance workspace; not attached")
        return None
    resolved = source.resolve()
    mime = _sniff_mime(resolved)
    if mime not in RASTER_MIMES:
        logger.warning("Generated file is not a supported raster image; not attached")
        return None
    size = resolved.stat().st_size
    if size <= 0 or size > 25 * 1024 * 1024:
        logger.warning("Generated image size is not attachable")
        return None
    digest = hashlib.sha256()
    with resolved.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    sha = digest.hexdigest()
    att_id = f"att_{uuid.uuid4().hex[:16]}"
    suffix = { "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif" }[mime]
    name = Path(str(result.get("filename") or resolved.name or f"generated{suffix}")).name
    if Path(name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        name = f"{Path(name).stem or 'generated'}{suffix}"
    name = name.replace('/', '_').replace(chr(92), '_')[:180]
    stage = gateway._staged_upload_dir(session_id) / att_id
    stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest = stage / name
    shutil.copy2(resolved, dest)
    row = gateway.store.add_attachment(session_id, {
        "attachment_id": att_id,
        "original_filename": name,
        "stored_filename": name,
        "safe_path": str(dest),
        "mime_type": mime,
        "size_bytes": size,
        "sha256": sha,
        "provenance": "image_generate",
        "metadata": {"request_id": request_id, "tool": tool_name, "backend": result.get("backend")},
    })
    gateway.event_bus.publish(session_id, "attachment.added", {"attachment": row})
    return {
        "attachment_id": att_id,
        "name": name,
        "mime": mime,
        "size": size,
        "sha256": sha,
    }
