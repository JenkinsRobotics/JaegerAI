"""Provider-independent admission and resource conflict checks."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from jaeger_agent.schemas.message_types import Message, ToolCall


def unique_tool_call_ids(calls: list[ToolCall], history: list[Message]) -> list[ToolCall]:
    """Keep valid provider IDs; repair missing/reused IDs before any observer sees them."""
    used = {call.get("id") for msg in history for call in (msg.get("tool_calls") or [])}
    admitted = []
    for original in calls:
        call = dict(original)
        identifier = call.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in used:
            if identifier:
                call["provider_id"] = str(identifier)
            call["id"] = "call_" + uuid.uuid4().hex
        used.add(call["id"])
        admitted.append(call)
    return admitted


def paths_overlap(a: str, b: str) -> bool:
    """Conservative scheduling check, never a replacement for path authorization.

    Relative paths may use different session/workspace roots in read and write
    tools. Without that tool-specific resolution, serialize rather than guess
    against the process cwd. Absolute paths resolve existing symlink parents,
    including for files that have not been created yet; samefile covers hardlinks.
    """
    try:
        pa, pb = Path(a).expanduser(), Path(b).expanduser()
        if not pa.is_absolute() or not pb.is_absolute():
            return True
        try:
            if os.path.samefile(pa, pb):
                return True
        except FileNotFoundError:
            pass
        # Case-fold conservatively, including nonexistent children on macOS.
        left, right = str(pa.resolve()).casefold(), str(pb.resolve()).casefold()
        common = os.path.commonpath((left, right))
        return common == left or common == right
    except (OSError, RuntimeError, ValueError):
        return True


def cancelled_tool_result() -> dict:
    return {"ok": False, "error": "Tool not executed: turn interrupted",
            "error_type": "interrupted", "retryable": False}
