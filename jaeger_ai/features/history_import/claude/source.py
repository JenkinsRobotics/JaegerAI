"""Claude Code JSONL transcript source."""

from pathlib import Path

from ..contracts import ParsedConversation
from ..parsing import content_text, jsonl, timestamp


class ClaudeHistorySource:
    source_id = "claude"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".claude" / "projects"

    def discover(self) -> tuple[Path, ...]:
        return tuple(sorted(self.root.glob("*/*.jsonl"))) if self.root.is_dir() else ()

    def parse(self, path: Path) -> ParsedConversation | None:
        messages = []
        session_id = path.stem
        workspace = ""
        model = ""
        fallback = path.stat().st_mtime
        for entry in jsonl(path):
            message = entry.get("message") if isinstance(entry.get("message"), dict) else entry
            role = str(message.get("role") or entry.get("type") or "").lower()
            if role not in {"user", "assistant", "system", "tool"}:
                continue
            text = content_text(message.get("content"))
            if not text:
                continue
            session_id = str(entry.get("sessionId") or session_id)
            workspace = str(entry.get("cwd") or workspace)
            model = str(message.get("model") or model)
            messages.append({
                "role": role,
                "text": text,
                "ts": timestamp(entry.get("timestamp"), fallback),
            })
        if not messages:
            return None
        title = next((row["text"][:200] for row in messages if row["role"] == "user"), path.stem)
        return ParsedConversation(
            self.source_id, path, session_id, title, tuple(messages), model, workspace
        )
