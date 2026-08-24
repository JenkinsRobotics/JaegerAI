"""Concurrency checks for authoritative side-effect settlement."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.effects import EffectError
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
from jaeger_agent.memory import sqlite_store


@pytest.fixture
def ledger(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteEffectLedger()
    finally:
        sqlite_store.close()


def test_concurrent_resolve_and_abandon_leave_one_consistent_outcome(ledger):
    """Resolve and abandon racing a pending claim: the row is either
    done with the recorded result, or gone. Never a completed effect
    that has been deleted (which would re-arm the side effect)."""
    pending_key = "invoice:43"
    with pytest.raises(RuntimeError, match="lost"):
        ledger.once(
            pending_key,
            "send_email",
            lambda: (_ for _ in ()).throw(RuntimeError("lost")),
        )

    start = threading.Barrier(2)
    resolved: list[bool] = []
    abandoned: list[bool] = []
    errors: list[BaseException] = []

    def resolve_client() -> None:
        start.wait(timeout=5)
        try:
            ledger.resolve(pending_key, "sent-after-all")
            resolved.append(True)
        except EffectError:
            resolved.append(False)
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    def abandon_client() -> None:
        start.wait(timeout=5)
        try:
            ledger.abandon(pending_key)
            abandoned.append(True)
        except EffectError:
            abandoned.append(False)
        except BaseException as exc:  # pragma: no cover
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
    assert resolved == [True] or resolved == [False]
    assert abandoned == [True] or abandoned == [False]
    assert resolved[0] != abandoned[0], "exactly one settler must win"

    effect = ledger.get(pending_key)
    if resolved[0]:
        assert effect is not None
        assert effect.status == "done"
        assert effect.result == "sent-after-all"
    else:
        assert effect is None
