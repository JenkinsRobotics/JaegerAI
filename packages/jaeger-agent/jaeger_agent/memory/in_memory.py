"""In-memory MemoryStore — the contract test reference implementation."""

from __future__ import annotations

from typing import Any


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self._facts: dict[tuple[str, str], str] = {}
        self._episodic: list[dict[str, Any]] = []

    def remember(
        self,
        key: str,
        value: str,
        *,
        category: str | None = None,
        subject: str | None = None,
    ) -> None:
        self._facts[(subject or "user", key)] = value

    def recall(self, key: str, *, subject: str | None = None) -> str | None:
        return self._facts.get((subject or "user", key))

    def forget(self, key: str, *, subject: str | None = None) -> bool:
        return self._facts.pop((subject or "user", key), None) is not None

    def list_facts(self, *, subject: str | None = "user") -> dict[str, str]:
        subj = subject or "user"
        return {k: v for (s, k), v in self._facts.items() if s == subj}

    def append_episodic(self, entry: dict[str, Any]) -> None:
        self._episodic.append(dict(entry))

    def load_recent_turns(
        self, n: int = 5, *, session_key: str | None = None
    ) -> list[dict[str, str]]:
        rows = self._episodic
        if session_key is not None:
            rows = [r for r in rows if r.get("session_key") == session_key]
        out: list[dict[str, str]] = []
        for row in rows[-n:]:
            out.append({
                "user": str(row.get("user") or ""),
                "answer": str(row.get("answer") or ""),
                "session_key": str(row.get("session_key") or ""),
            })
        return out
