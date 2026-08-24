"""SQLite adapter for :class:`MemoryStore` — production persistence."""

from __future__ import annotations

from typing import Any

from jaeger_agent.memory import memory as _mem


class SqliteMemoryStore:
    """Delegates to the bound instance ``state.db`` facade."""

    def remember(
        self,
        key: str,
        value: str,
        *,
        category: str | None = None,
        subject: str | None = None,
    ) -> None:
        _mem.remember(key, value, category=category, subject=subject)

    def recall(self, key: str, *, subject: str | None = None) -> str | None:
        return _mem.recall(key, subject=subject)

    def forget(self, key: str, *, subject: str | None = None) -> bool:
        return _mem.forget(key, subject=subject)

    def list_facts(self, *, subject: str | None = "user") -> dict[str, str]:
        return _mem.list_facts(subject=subject)

    def append_episodic(self, entry: dict[str, Any]) -> None:
        _mem.append_episodic(entry)

    def load_recent_turns(
        self, n: int = 5, *, session_key: str | None = None
    ) -> list[dict[str, str]]:
        return _mem.load_recent_turns(n, session_key=session_key)
