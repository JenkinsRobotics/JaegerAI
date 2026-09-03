"""ARES WebUI JSON transcript source."""

import json
from pathlib import Path

from jaeger_ai.core.ares_interop import ares_migration_source

from ..contracts import ParsedConversation
from ..parsing import content_text, timestamp

MAX_SESSION_BYTES = 32 * 1024 * 1024


class AresHistorySource:
    source_id = "ares"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or ares_migration_source() / "webui" / "sessions"

    def discover(self) -> tuple[Path, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(
            path
            for path in sorted(self.root.glob("*.json"))
            if not path.name.startswith("_") and path.stat().st_size <= MAX_SESSION_BYTES
        )

    def parse(self, path: Path) -> ParsedConversation | None:
        if path.stat().st_size > MAX_SESSION_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None
        raw_messages = value.get("messages") or value.get("context_messages") or []
        if not isinstance(raw_messages, list):
            return None
        fallback = float(value.get("created_at") or path.stat().st_mtime)
        messages = []
        for item in raw_messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or item.get("type") or "").lower()
            role = "tool" if role in {"tool_result", "tool_use"} else role
            text = content_text(item.get("content") or item.get("text"))
            if role in {"user", "assistant", "system", "tool"} and text:
                messages.append({
                    "role": role,
                    "text": text,
                    "ts": timestamp(item.get("timestamp"), fallback),
                })
        if not messages:
            return None
        original_id = str(value.get("session_id") or path.stem)
        title = str(value.get("title") or "").strip() or next(
            (row["text"][:200] for row in messages if row["role"] == "user"),
            original_id,
        )
        return ParsedConversation(
            self.source_id,
            path,
            original_id,
            title,
            tuple(messages),
            str(value.get("model") or value.get("model_provider") or ""),
            str(value.get("workspace") or ""),
        )
