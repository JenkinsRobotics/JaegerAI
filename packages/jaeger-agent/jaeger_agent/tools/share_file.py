"""``share_file`` — hand a file to the owner as a download in this chat (parity P14).

Grok Bot-style delivery: the file shows up in the conversation as an
attachment chip with a Download button (and in the chat's Files panel), not
just as a path. The bytes are snapshotted into the session's staged store so the
download serves exactly what was shared. Secrets are never shared: the credentials folder and
secrets.env are refused.
"""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from jaeger_tools.tool_registry import register_tool_from_function

_MAX_BYTES = 50 * 1024 * 1024
_REFUSE = ("credentials", "secrets.env", ".ssh", "keychain", ".env")


def share_file(path: str, note: str = "") -> dict:
    from jaeger_agent.task_port import current_task_context
    from jaeger_agent.core.workspace import _require_layout

    ctx = current_task_context()
    if ctx is None or not ctx.get("session_id"):
        return {"ok": False, "error": "No chat to share into (share_file runs inside a Gateway chat turn)."}
    layout = _require_layout()
    ws = Path(layout.workspace_dir).resolve()
    src = Path(path).expanduser()
    if not src.is_absolute():
        src = ws / src
    src = src.resolve()
    if any(part.lower() in _REFUSE for part in src.parts):
        return {"ok": False, "error": "Refused: that location holds secrets."}
    if not src.is_file():
        return {"ok": False, "error": f"Not a file: {src}"}
    size = src.stat().st_size
    if size > _MAX_BYTES:
        return {"ok": False, "error": f"File is {size} bytes; the chat download limit is {_MAX_BYTES}."}
    gateway = ctx["owner"].gateway
    sid = str(ctx["session_id"])
    data = src.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    # Immutable snapshot in the session's staged store (same as uploads and
    # generated images), so the download always serves the bytes shared now.
    staged = Path(gateway._staged_upload_dir(sid))
    staged.mkdir(parents=True, exist_ok=True)
    target = staged / f"shared-{digest[:12]}-{src.name}"
    if not target.exists():
        target.write_bytes(data)
    mime = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
    row = gateway.store.add_attachment(sid, {
        "original_filename": src.name, "safe_path": str(target), "mime_type": mime,
        "size_bytes": len(data), "sha256": digest,
        "provenance": "agent_shared", "metadata": {"note": note[:200], "source_path": str(src)},
    })
    return {
        "ok": True, "attachment_id": row["attachment_id"], "name": src.name, "size_bytes": len(data),
        "mime": mime, "sha256": digest, "path": str(src),
        "download": "Shown in this chat as a file card with a Download button (also in the chat's Files panel).",
        "next": "Tell the owner the file is attached in the chat with a Download button; give the path too.",
    }


@register_tool_from_function(name="share_file")
def _t_share_file(path: str, note: str = "") -> dict:
    """Give the owner a file as a DOWNLOAD in this chat ("send me the file",
    "downloadable", "attach it", "give me the CSV"). Adds it to the chat as a
    file card with a Download button. Use after you create or find the file;
    path may be absolute or workspace-relative."""
    return share_file(path, note)
