"""Grok Build native-session JSONL transcript source."""

import json
from pathlib import Path
from urllib.parse import unquote

from ..contracts import ParsedConversation
from ..parsing import content_text, jsonl, timestamp


class GrokHistorySource:
    source_id = "grok"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".grok" / "sessions"

    def discover(self) -> tuple[Path, ...]:
        return tuple(sorted(self.root.glob("*/*/chat_history.jsonl"))) if self.root.is_dir() else ()

    def parse(self, path: Path) -> ParsedConversation | None:
        messages = []
        fallback = path.stat().st_mtime
        for entry in jsonl(path):
            role = str(entry.get("role") or entry.get("type") or "").lower()
            role = "tool" if role == "tool_result" else role
            text = content_text(entry.get("content"))
            if role in {"user", "assistant", "system", "tool", "reasoning"} and text:
                messages.append({
                    "role": role,
                    "text": text,
                    "ts": timestamp(entry.get("timestamp"), fallback),
                })
        if not messages:
            return None
        summary_path = path.parent / "summary.json"
        summary = {}
        try:
            value = json.loads(summary_path.read_text(encoding="utf-8"))
            summary = value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            pass
        title = str(summary.get("title") or "") or next(
            (row["text"][:200] for row in messages if row["role"] == "user"),
            path.parent.name,
        )
        workspace = unquote(path.parent.parent.name)
        return ParsedConversation(
            self.source_id,
            path,
            path.parent.name,
            title,
            tuple(messages),
            str(summary.get("model") or "grok"),
            workspace,
        )
