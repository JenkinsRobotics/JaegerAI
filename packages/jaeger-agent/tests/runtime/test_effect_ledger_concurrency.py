"""Red-team concurrency checks for authoritative side-effect settlement."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
from jaeger_agent.memory import sqlite_store


@pytest.fixture
def ledger(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteEffectLedger()
    finally:
        sqlite_store.close()


def test_stale_abandon_cannot_delete_a_concurrently_resolved_effect(ledger):
    """A stale pending snapshot must not re-arm a completed side effect."""
    pending_key = "invoice:43"
    with pytest.raises(RuntimeError, match="lost"):
        ledger.once(pending_key, "send_email", lambda: (_ for _ in ()).throw(RuntimeError("lost")))

    original_get = ledger.get
    snapshots_read = threading.Barrier(2)
    resolved = threading.Event()

    def coordinated_get(key: str):
        effect = original_get(key)
        if key != pending_key:
            return effect
        snapshots_read.wait(timeout=5)
        if threading.current_thread().name == "abandon-client":
            assert resolved.wait(timeout=5)
        return effect

    ledger.get = coordinated_get  # type: ignore[method-assign]
    errors: list[BaseException] = []

    def resolve_client() -> None:
        try:
            ledger.resolve(pending_key, "sent-after-all")
            resolved.set()
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)
            resolved.set()

    def abandon_client() -> None:
        try:
            ledger.abandon(pending_key)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    threads = [
        threading.Thread(target=resolve_client, name="resolve-client"),
        threading.Thread(target=abandon_client, name="abandon-client"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "settlement client deadlocked"

    assert not errors
    effect = original_get(pending_key)
    assert effect is not None, "stale abandon deleted a completed effect claim"
    assert effect.status == "done"
    assert effect.result == "sent-after-all"
