"""Gemini CLI snapshot-JSONL transcript source."""

from pathlib import Path

from ..contracts import ParsedConversation
from ..parsing import content_text, jsonl, timestamp


class GeminiHistorySource:
    source_id = "gemini"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".gemini" / "tmp"

    def discover(self) -> tuple[Path, ...]:
        return tuple(sorted(self.root.glob("*/chats/*.jsonl"))) if self.root.is_dir() else ()

    def parse(self, path: Path) -> ParsedConversation | None:
        latest: dict = {}
        session_id = path.stem
        fallback = path.stat().st_mtime
        for entry in jsonl(path):
            session_id = str(entry.get("sessionId") or session_id)
            changed = entry.get("$set")
            if isinstance(changed, dict) and isinstance(changed.get("messages"), list):
                latest = changed
        messages = []
        for item in latest.get("messages", []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("type") or item.get("role") or "").lower()
            text = content_text(item.get("content"))
            if role in {"user", "assistant", "system", "tool"} and text:
                messages.append({
                    "role": role,
                    "text": text,
                    "ts": timestamp(item.get("timestamp"), fallback),
                })
        if not messages:
            return None
        title = next((row["text"][:200] for row in messages if row["role"] == "user"), path.stem)
        return ParsedConversation(
            self.source_id,
            path,
            session_id,
            title,
            tuple(messages),
            "gemini",
            str(path.parent.parent),
        )
