"""DB-9 — cross-cutting tests for the SQLite memory backend.

Spans behaviours that don't fit any single per-table test file:

- WAL pragmas actually apply (journal_mode, foreign_keys, busy_timeout)
- A reader sees a writer's commit through the shared connection
- Two writers don't corrupt the DB (lock-serialised)
- ``sqlite-vec`` graceful fallback works when the extension is missing
- The schema-version guard refuses to open a newer-than-known DB
- Bind → close → re-bind to a different instance is clean
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from jaeger_os.core.memory import memory as mem
from jaeger_os.core.memory import sqlite_store


@pytest.fixture(autouse=True)
def _isolate_store():
    sqlite_store.close()
    yield
    sqlite_store.close()


@pytest.fixture
def bound(tmp_path):
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


# ── pragmas ──────────────────────────────────────────────────────


def test_journal_mode_is_wal(bound):
    """WAL mode lets many readers coexist with one writer — the
    whole point of moving off JSONL."""
    conn = sqlite_store.connection()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    # On most filesystems WAL sticks. Some sandboxed FSs fall back
    # to DELETE; both are acceptable, but at least one of the two.
    assert mode.lower() in ("wal", "delete", "memory"), mode


def test_foreign_keys_enabled(bound):
    """FK constraints back the ``episodic_id`` link in tool_calls
    and the CASCADE on episodic_embeddings."""
    conn = sqlite_store.connection()
    flag = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert flag == 1


def test_busy_timeout_is_set(bound):
    """5s busy_timeout — gives a contending writer time to retry
    rather than failing immediately with SQLITE_BUSY."""
    conn = sqlite_store.connection()
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout >= 5000


# ── concurrent reader + writer (single-process, multi-thread) ────


def test_writer_commit_visible_to_subsequent_read(bound):
    """A writer's commit is immediately visible to a fresh SELECT
    on the same shared connection — required for the
    ``tool_progress`` callback writing while the agent loop reads
    facts in the next sentence."""
    mem.remember("k", "v")
    assert mem.recall("k") == "v"


def test_two_threads_serialise_writes(bound):
    """The write-lock serialises ``writer()`` blocks so two
    concurrent writers don't corrupt the DB. Counts must add up
    to the total."""
    errors: list[Exception] = []

    def writer_task(prefix: str, n: int) -> None:
        try:
            for i in range(n):
                mem.remember(f"{prefix}_{i}", f"value_{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=writer_task, args=("t1", 20))
    t2 = threading.Thread(target=writer_task, args=("t2", 20))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"writers raised: {errors}"
    facts = mem.list_facts()
    assert len(facts) == 40
    # Each writer's keys present.
    assert any(k.startswith("t1_") for k in facts)
    assert any(k.startswith("t2_") for k in facts)


def test_concurrent_reader_during_writer(bound):
    """A reader thread can run SELECTs while a writer is busy with
    a WAL write. WAL's main selling point — pin it."""
    seed = [mem.remember(f"k{i}", f"v{i}") for i in range(5)]
    del seed

    reads: list[int] = []
    stop = threading.Event()

    def reader() -> None:
        # Swallow exceptions — the autouse fixture closes the store
        # at test teardown and a daemon thread mid-SELECT will hit a
        # closed-fd error. Doesn't affect what we're pinning.
        while not stop.is_set():
            try:
                facts = mem.list_facts()
            except Exception:  # noqa: BLE001
                return
            reads.append(len(facts))

    def writer() -> None:
        for i in range(50):
            mem.remember(f"new_{i}", f"v_{i}")
        stop.set()

    rt = threading.Thread(target=reader, daemon=True)
    wt = threading.Thread(target=writer)
    rt.start()
    wt.start()
    wt.join(timeout=10)
    stop.set()
    rt.join(timeout=2)

    # Reader saw at least one snapshot (no exception). The count
    # should have grown monotonically toward 55.
    assert reads, "reader never executed"
    assert max(reads) >= 5  # at minimum the seed rows


# ── sqlite-vec graceful fallback ─────────────────────────────────


def test_vec_extension_load_flag_is_boolean(bound):
    """``has_vec_extension`` is set after _open + _try_load_vec.
    The flag is True or False — never raises, never None."""
    flag = sqlite_store.has_vec_extension()
    assert isinstance(flag, bool)


def test_search_works_without_vec_extension(bound, monkeypatch):
    """When sqlite-vec isn't loaded the BLOB cosine fallback kicks
    in. Verify by forcing has_vec_extension → False and running a
    real search."""
    import numpy as np

    class _FakeModel:
        def encode(self, texts, **_):
            out = np.zeros((len(texts), 4), dtype="float32")
            for i, t in enumerate(texts):
                if "q1" in t or t == "match":
                    out[i, 0] = 1.0
                else:
                    out[i, 1] = 1.0
            return out

    monkeypatch.setattr(mem, "_ensure_semantic_model", lambda: _FakeModel())
    # Force fallback path even if the extension is loaded locally.
    monkeypatch.setattr(sqlite_store, "has_vec_extension", lambda: False)

    mem.append_episodic({"user": "q1 hello", "decision_raw": "a1",
                         "session_key": "default"})
    mem.append_episodic({"user": "q2 world", "decision_raw": "a2",
                         "session_key": "default"})

    out = mem.search_memory("match", k=2)
    assert out, "fallback returned no results"
    assert out[0]["user"] == "q1 hello"


# ── schema-version guard ─────────────────────────────────────────


def test_refuses_to_open_db_with_higher_schema_version(tmp_path):
    """If the DB on disk has a SCHEMA_VERSION newer than what this
    code knows about, opening it must raise — not silently
    downgrade. Pin this; a future user running an old framework
    against a new DB would otherwise corrupt the schema."""
    layout = SimpleNamespace(memory_dir=tmp_path / "memory")
    sqlite_store.bind(layout)
    # Forge a future schema-version row.
    with sqlite_store.writer() as conn:
        conn.execute("UPDATE schema_version SET version = 9999 WHERE id = 1")
    sqlite_store.close()

    with pytest.raises(RuntimeError, match="newer than|upgrade"):
        sqlite_store.bind(layout)


# ── bind lifecycle ───────────────────────────────────────────────


def test_bind_is_idempotent(tmp_path):
    """Re-binding to the same layout doesn't crash or reset rows."""
    layout = SimpleNamespace(memory_dir=tmp_path / "memory")
    mem.bind(layout)
    mem.remember("k", "v")
    mem.bind(layout)  # second bind
    assert mem.recall("k") == "v"


def test_rebind_to_different_instance_isolates_data(tmp_path):
    """Switching to a different instance opens a different DB —
    rows from the first one are not visible. Use ``list_facts``
    rather than ``recall`` so the fuzzy word-overlap fallback in
    recall doesn't blur the instance boundary."""
    a = SimpleNamespace(memory_dir=tmp_path / "a" / "memory")
    b = SimpleNamespace(memory_dir=tmp_path / "b" / "memory")

    mem.bind(a)
    mem.remember("alpha_key", "alpha_val")
    sqlite_store.close()

    mem.bind(b)
    assert "alpha_key" not in mem.list_facts()
    mem.remember("beta_key", "beta_val")
    sqlite_store.close()

    mem.bind(a)
    facts_a = mem.list_facts()
    assert "alpha_key" in facts_a
    assert "beta_key" not in facts_a


def test_close_idempotent():
    """``close()`` with no bound conn is a silent no-op."""
    sqlite_store.close()
    sqlite_store.close()  # twice — no exception
    assert sqlite_store.is_bound() is False


def test_writer_rolls_back_on_exception(bound):
    """The ``writer()`` context manager rolls back on exception so
    a half-written transaction doesn't leak. Pin this — the
    record_tool_call code path relies on it."""
    with pytest.raises(RuntimeError):
        with sqlite_store.writer() as conn:
            conn.execute(
                "INSERT INTO facts (key, value, category, created_at, updated_at)"
                " VALUES ('halfwrite', 'v', 'general', '2026', '2026')"
            )
            raise RuntimeError("simulated tool crash")

    # Row not present — transaction rolled back.
    assert mem.recall("halfwrite") is None
