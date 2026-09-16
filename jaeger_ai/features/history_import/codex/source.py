"""Codex rollout JSONL transcript source."""

from pathlib import Path

from ..contracts import ParsedConversation
from ..parsing import content_text, jsonl, timestamp


def _is_injected_context_message(text: str) -> bool:
    """Exclude Codex host context that is serialized as a user message.

    Desktop Codex rollouts prepend repository instructions and environment
    metadata as user-role records. They are execution context, not conversation
    turns, and otherwise become misleading session titles in history views.
    """
    normalized = text.lstrip()
    return normalized.startswith("# AGENTS.md instructions for ") or normalized.startswith(
        "<environment_context>"
    )


class CodexHistorySource:
    source_id = "codex"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.home() / ".codex" / "sessions"

    def discover(self) -> tuple[Path, ...]:
        return tuple(sorted(self.root.rglob("*.jsonl"))) if self.root.is_dir() else ()

    def parse(self, path: Path) -> ParsedConversation | None:
        messages = []
        session_id = path.stem
        workspace = ""
        model = ""
        fallback = path.stat().st_mtime
        for entry in jsonl(path):
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            if entry.get("type") == "session_meta":
                session_id = str(payload.get("id") or payload.get("session_id") or session_id)
                workspace = str(payload.get("cwd") or workspace)
                model = str(payload.get("model_provider") or model)
                continue
            if entry.get("type") != "response_item" or payload.get("type") != "message":
                continue
            role = str(payload.get("role") or "").lower()
            text = content_text(payload.get("content"))
            if role == "user" and _is_injected_context_message(text):
                continue
            if role in {"user", "assistant", "system"} and text:
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
