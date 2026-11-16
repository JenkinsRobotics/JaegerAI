"""``share_file`` — hand a file to the owner as a download in this chat (parity P14).

Grok Bot-style delivery: the file shows up in the conversation as an
attachment chip with a Download button (and in the chat's Files panel), not
just as a path. Files outside the instance workspace are copied into
``<workspace>/outbox/`` first so the Gateway's workspace-bound file access can
serve verified bytes. Secrets are never shared: the credentials folder and
secrets.env are refused.
"""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path

from jaeger_os.core.tools.tool_registry import register_tool_from_function

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
    target = src
    if not src.is_relative_to(ws):
        outbox = ws / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        target = outbox / src.name
        if target.exists() and target.resolve() != src:
            target = outbox / f"{src.stem}-{hashlib.sha256(str(src).encode()).hexdigest()[:6]}{src.suffix}"
        shutil.copy2(src, target)
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    gateway = ctx["owner"].gateway
    sid = str(ctx["session_id"])
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    row = gateway.store.add_attachment(sid, {
        "original_filename": target.name, "safe_path": str(target), "mime_type": mime,
        "size_bytes": len(data), "sha256": digest,
        "provenance": "agent_output", "metadata": {"note": note[:200], "source_path": str(src)},
    })
    return {
        "ok": True, "attachment_id": row["attachment_id"], "name": target.name, "size_bytes": len(data),
        "mime": mime, "sha256": digest, "path": str(target),
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
