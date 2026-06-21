"""DB-4 — semantic search backed by SQL ``episodic_embeddings``.

Most semantic-search tests need the real sentence-transformers
model. Those are marked ``model`` so the default tier skips them;
the smoke tier runs them. The non-model tests below cover the
BLOB pack/unpack helpers and the SQL plumbing without touching
the encoder.
"""

from __future__ import annotations

from pathlib import Path
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


# ── BLOB helpers ─────────────────────────────────────────────────


def test_vector_to_blob_round_trip(bound):
    import numpy as np
    vec = np.array([1.0, -0.5, 0.25, 0.0], dtype="float32")
    blob = mem._vector_to_blob(vec)
    restored = mem._blob_to_vector(blob)
    assert restored.dtype == np.dtype("float32")
    assert list(restored) == [1.0, -0.5, 0.25, 0.0]


def test_vector_to_blob_handles_lists(bound):
    blob = mem._vector_to_blob([0.1, 0.2, 0.3])
    restored = mem._blob_to_vector(blob)
    assert len(restored) == 3
    assert abs(restored[0] - 0.1) < 1e-6


def test_episodic_text_for_strips_and_formats(bound):
    text = mem._episodic_text_for("hi   ", "  hello back")
    assert text.startswith("USER: hi")
    assert "ASSISTANT: hello back" in text


def test_episodic_text_for_handles_missing(bound):
    assert mem._episodic_text_for(None, None) == "USER: \nASSISTANT:"
    assert mem._episodic_text_for("just q", None).startswith("USER: just q")
    assert mem._episodic_text_for(None, "just a").endswith("ASSISTANT: just a")


# ── search behaviour without the encoder ─────────────────────────


def test_search_empty_query_returns_empty(bound):
    """A blank query should never trigger the encoder + DB scan."""
    assert mem.search_memory("") == []
    assert mem.search_memory("   ") == []


def test_search_negative_k_returns_empty(bound):
    assert mem.search_memory("hi", k=0) == []
    assert mem.search_memory("hi", k=-1) == []


def test_search_returns_empty_when_no_episodes(bound, monkeypatch):
    """No episodic rows → search returns [] without invoking the
    encoder. Pin this — encoder load is expensive; skipping when
    there's nothing to search is the right behaviour."""
    called = {"flag": False}

    def fake_encoder():
        called["flag"] = True
        raise RuntimeError("encoder should not have been called")

    monkeypatch.setattr(mem, "_ensure_semantic_model", fake_encoder)
    assert mem.search_memory("anything", k=5) == []
    assert called["flag"] is False


# ── _ensure_embeddings_up_to_date ────────────────────────────────


def test_ensure_embeddings_writes_one_row_per_episode(bound, monkeypatch):
    """Encoder mocked to return deterministic vectors; verify one
    embedding row per episodic row + correct dim + BLOB shape."""
    import numpy as np

    class _FakeModel:
        def encode(self, texts, normalize_embeddings=False, show_progress_bar=False):
            # Each text → a fixed-dim unit vector keyed on len(texts).
            dim = 4
            out = np.zeros((len(texts), dim), dtype="float32")
            for i, _ in enumerate(texts):
                out[i, i % dim] = 1.0
            return out

    monkeypatch.setattr(mem, "_ensure_semantic_model", lambda: _FakeModel())

    mem.append_episodic({"user": "q1", "decision_raw": "a1", "answer": "a1",
                         "session_key": "default"})
    mem.append_episodic({"user": "q2", "decision_raw": "a2", "answer": "a2",
                         "session_key": "default"})
    written = mem._ensure_embeddings_up_to_date()
    assert written == 2

    conn = sqlite_store.connection()
    rows = conn.execute(
        "SELECT episodic_id, dim, model, length(vector) AS blob_len "
        "FROM episodic_embeddings ORDER BY episodic_id"
    ).fetchall()
    assert [r["episodic_id"] for r in rows] == [1, 2]
    assert all(r["dim"] == 4 for r in rows)
    # float32 × 4 dims = 16 bytes per blob.
    assert all(r["blob_len"] == 16 for r in rows)


def test_ensure_embeddings_is_idempotent(bound, monkeypatch):
    import numpy as np

    class _FakeModel:
        def encode(self, texts, **_):
            return np.ones((len(texts), 4), dtype="float32")

    monkeypatch.setattr(mem, "_ensure_semantic_model", lambda: _FakeModel())

    mem.append_episodic({"user": "q", "decision_raw": "a", "answer": "a",
                         "session_key": "default"})
    first = mem._ensure_embeddings_up_to_date()
    second = mem._ensure_embeddings_up_to_date()
    assert first == 1
    assert second == 0  # nothing new to write


def test_ensure_embeddings_only_writes_missing(bound, monkeypatch):
    """Add 3 episodes, encode them, then add 2 more — only the new
    ones get encoded. Important for performance: a stable instance
    with one new turn shouldn't re-encode the whole history."""
    import numpy as np

    class _FakeModel:
        def encode(self, texts, **_):
            return np.ones((len(texts), 4), dtype="float32")

    monkeypatch.setattr(mem, "_ensure_semantic_model", lambda: _FakeModel())

    for i in range(3):
        mem.append_episodic({"user": f"q{i}", "decision_raw": f"a{i}",
                              "answer": f"a{i}", "session_key": "default"})
    mem._ensure_embeddings_up_to_date()

    for i in range(3, 5):
        mem.append_episodic({"user": f"q{i}", "decision_raw": f"a{i}",
                              "answer": f"a{i}", "session_key": "default"})
    written = mem._ensure_embeddings_up_to_date()
    assert written == 2

    conn = sqlite_store.connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM episodic_embeddings"
    ).fetchone()[0]
    assert count == 5


def test_search_uses_cosine_over_blobs(bound, monkeypatch):
    """Mocked encoder + canned vectors — verify the cosine scan
    returns the highest-scoring row first."""
    import numpy as np

    # Three turns. Their "embeddings" are orthonormal vectors in
    # different dimensions, so we can pick a query vector that
    # points clearly at one of them.
    vectors_for = {
        "q0": np.array([1.0, 0.0, 0.0, 0.0], dtype="float32"),
        "q1": np.array([0.0, 1.0, 0.0, 0.0], dtype="float32"),
        "q2": np.array([0.0, 0.0, 1.0, 0.0], dtype="float32"),
        "qry": np.array([0.0, 1.0, 0.0, 0.0], dtype="float32"),  # matches q1
    }

    class _FakeModel:
        def encode(self, texts, **_):
            out = np.zeros((len(texts), 4), dtype="float32")
            for i, t in enumerate(texts):
                if t == "qry":
                    out[i] = vectors_for["qry"]
                else:
                    key = next(
                        (k for k in ("q0", "q1", "q2") if k in t),
                        None,
                    )
                    if key is not None:
                        out[i] = vectors_for[key]
            return out

    monkeypatch.setattr(mem, "_ensure_semantic_model", lambda: _FakeModel())

    for i in range(3):
        mem.append_episodic({"user": f"q{i}", "decision_raw": f"a{i}",
                              "answer": f"a{i}", "session_key": "default"})
    # search_memory will encode "qry" → matches q1 vector
    out = mem.search_memory("qry", k=3)
    assert out, "search returned no results"
    # Highest score should be the q1 row.
    assert out[0]["user"] == "q1"
    assert out[0]["score"] == pytest.approx(1.0, abs=1e-5)
    # The orthogonal rows score 0 (cosine of orthogonal unit vectors).
    assert all(r["score"] < 0.01 for r in out[1:])


def test_search_respects_k_limit(bound, monkeypatch):
    import numpy as np

    class _FakeModel:
        def encode(self, texts, **_):
            return np.ones((len(texts), 4), dtype="float32")

    monkeypatch.setattr(mem, "_ensure_semantic_model", lambda: _FakeModel())

    for i in range(10):
        mem.append_episodic({"user": f"q{i}", "decision_raw": f"a{i}",
                              "answer": f"a{i}", "session_key": "default"})
    out = mem.search_memory("anything", k=3)
    assert len(out) == 3


def test_search_skips_rows_without_text(bound, monkeypatch):
    """An episodic row with no user OR answer can't be encoded
    meaningfully; the embedding still gets written (zero vector)
    but the search result still surfaces by ts. This is a
    pragmatic call — the fake model just returns whatever; we
    pin that no exception escapes."""
    import numpy as np

    class _FakeModel:
        def encode(self, texts, **_):
            return np.ones((len(texts), 4), dtype="float32")

    monkeypatch.setattr(mem, "_ensure_semantic_model", lambda: _FakeModel())

    mem.append_episodic({"session_key": "default"})  # all-None
    out = mem.search_memory("anything", k=5)
    # No exception, may or may not return a row depending on the
    # zero-length text — important is that we don't crash.
    assert isinstance(out, list)
