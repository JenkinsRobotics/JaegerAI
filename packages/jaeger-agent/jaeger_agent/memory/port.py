"""MemoryStore — the replaceable persistence contract for SI state.

The agent loop and tools talk to this protocol, not to SQLite. The
production adapter is :class:`SqliteMemoryStore` (``state.db``). Tests
use :class:`InMemoryMemoryStore`. A future store (Postgres, a remote
service) implements the same methods and must pass
``tests/contract/test_memory_store_contract.py``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryStore(Protocol):
    """Facts + episodic turns. Schedules stay on the schedule port."""

    def remember(
        self,
        key: str,
        value: str,
        *,
        category: str | None = None,
        subject: str | None = None,
    ) -> None: ...

    def recall(self, key: str, *, subject: str | None = None) -> str | None: ...

    def forget(self, key: str, *, subject: str | None = None) -> bool: ...

    def list_facts(self, *, subject: str | None = "user") -> dict[str, str]: ...

    def append_episodic(self, entry: dict[str, Any]) -> None: ...

    def load_recent_turns(
        self, n: int = 5, *, session_key: str | None = None
    ) -> list[dict[str, str]]: ...


__all__ = ["MemoryStore"]
