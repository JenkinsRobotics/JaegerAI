"""Instance-scoped persistent memory — the public facade over SQLite.

The store is ``<instance>/memory/state.db`` (see ``sqlite_store.py`` and
dev/docs/memory_architecture.md): ``facts`` is the current subject-attributed
view, ``fact_log`` the append-only assertion history, ``episodic`` +
``episodic_embeddings`` the per-turn log with semantic search. The old flat
files (``facts.json`` / ``episodic.jsonl`` / ``schedules.jsonl``) are legacy —
read once by the ``_lazy_import_*`` helpers to migrate a pre-0.2.0 instance,
never written.

No cross-imports from the project root — Jaeger owns its memory store, and
files live inside each instance dir so two instances never share state.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Per-process state — bound to one InstanceLayout at startup
# ---------------------------------------------------------------------------
_state: dict[str, Any] = {
    "facts_path": None,
    "episodic_path": None,
    "schedules_path": None,
    "facts_lock_path": None,
    "schedules_lock_path": None,
    "embed_path": None,           # semantic-search embedding cache
}


def bind(layout: Any) -> None:
    """Wire memory paths to a specific instance layout. Called once at
    startup by the agent loop; subsequent calls re-bind cleanly.

    Group 9 (0.2.0): opens the SQLite state store at
    ``<instance>/memory/state.db`` and triggers the lazy importers
    that move any pre-0.2.0 ``facts.json`` / ``episodic.jsonl`` /
    ``schedules.jsonl`` / ``logs/audit.log`` rows into SQL on first
    bind. The legacy paths are still tracked in ``_state`` because
    the formal ``v1_1_0_to_v1_2_0`` migration renames them to
    ``.legacy`` after a successful import — and the lazy importers
    need to know where to look.
    """
    from jaeger_os.core.memory import sqlite_store
    mem = layout.memory_dir
    mem.mkdir(parents=True, exist_ok=True)
    _state["facts_path"] = mem / "facts.json"
    _state["episodic_path"] = mem / "episodic.jsonl"
    _state["schedules_path"] = mem / "schedules.jsonl"
    _state["facts_lock_path"] = mem / ".facts.lock"
    _state["schedules_lock_path"] = mem / ".schedules.lock"
    _state["embed_path"] = mem / "episodic.embeddings.npz"
    # DB-7: layout.audit_log_path lives under logs/; capture it here
    # so memory can dual-write the SQL audit_log table and lazy-import
    # any pre-0.2.0 JSONL on first bind.
    _state["audit_log_path"] = getattr(layout, "audit_log_path", None)
    sqlite_store.bind(layout)
    # DB-2 / DB-3: lazy-migrate facts.json + episodic.jsonl into the
    # new SQL tables on first 0.2.0 boot. Each is idempotent and
    # gated on "SQL table empty AND legacy file present". The formal
    # DB-8 migration renames the files aside; this just makes the
    # upgrade transparent for users who never explicitly migrate.
    _lazy_import_facts_from_json()
    _lazy_import_episodic_from_jsonl()
    _lazy_import_schedules_from_jsonl()
    _lazy_import_audit_log_from_jsonl()


def _require(path_key: str) -> Path:
    p = _state.get(path_key)
    if p is None:
        raise RuntimeError("memory not bound — call jaeger_os.memory.bind(layout) first")
    return p


# ---------------------------------------------------------------------------
# fcntl-backed cross-process advisory locking
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _file_lock(lock_key: str, *, exclusive: bool = True):
    path = _require(lock_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    flag = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    with open(path, "a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), flag)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# facts — DB-2 backed by SQLite via ``sqlite_store``
# ---------------------------------------------------------------------------
# Public API unchanged from the 0.1.x JSON era — same signatures, same
# return shapes — so the tool layer (``core/tools/memory.py``) and the
# agent's prompt rules don't know the storage swapped underneath.
#
# Legacy SCHEMA_VERSION constant: was the schema version of the JSON
# payload. The new authoritative schema version lives in
# ``sqlite_store.SCHEMA_VERSION``. Kept here for backward-compat
# imports; do not use for new code.
SCHEMA_VERSION = 1


def _norm_category(category: str | None) -> str:
    """Normalise a free-form category label. Empty ⇒ 'general'."""
    return (category or "").strip().lower() or "general"


def _lazy_import_facts_from_json() -> None:
    """One-shot: copy ``facts.json`` into the SQL facts table on first
    boot of a 0.1.x → 0.2.0 instance. No-op when the SQL table already
    has rows OR the JSON file is absent. The formal DB-8 migration
    will rename the JSON file aside; this just makes the upgrade
    transparent for users who never explicitly migrate."""
    from jaeger_os.core.memory import sqlite_store
    if not sqlite_store.is_bound():
        return
    path = _state.get("facts_path")
    if path is None or not path.exists():
        return
    conn = sqlite_store.connection()
    # Skip if the SQL table already has data (idempotent re-runs).
    if conn.execute("SELECT 1 FROM facts LIMIT 1").fetchone() is not None:
        return

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict):
        return

    # Both old and new JSON shapes:
    #   old: {key: value, ...}
    #   new: {"schema_version": 1, "facts": {...}, "categories": {...}}
    if "schema_version" in raw and isinstance(raw.get("facts"), dict):
        facts = {k: v for k, v in raw["facts"].items() if isinstance(k, str)}
        cats = raw.get("categories") or {}
        if not isinstance(cats, dict):
            cats = {}
    else:
        facts = {k: v for k, v in raw.items()
                 if isinstance(k, str) and not k.startswith("_")}
        cats = {}

    if not facts:
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite_store.writer() as wconn:
        for k, v in facts.items():
            cat = _norm_category(cats.get(k))
            wconn.execute(
                "INSERT OR REPLACE INTO facts "
                "(key, value, category, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (k, str(v), cat, now, now),
            )
            # Seed the history log so imported facts are traceable —
            # a fact with no fact_log row looks like it never existed.
            wconn.execute(
                "INSERT INTO fact_log "
                "(subject, key, value, category, source, tags, note, ts) "
                "VALUES ('user', ?, ?, ?, 'user', '', "
                "'imported from facts.json', ?)",
                (k, str(v), cat, now),
            )


# Who is setting facts right now. Live operator turns leave it at "user";
# the benchmark sets it to "benchmark" so its facts are tagged (and easy to
# purge: DELETE FROM facts WHERE source='benchmark'), and never masquerade as
# the operator's. The agent can pass source="agent" for things it inferred.
_memory_source: str = "user"


def set_memory_source(source: str) -> str:
    """Set the source tag applied to subsequent ``remember`` writes (and the
    filter ``recall`` applies). Returns the PREVIOUS value so callers can
    restore it. Used by the bench to tag its facts 'benchmark'."""
    global _memory_source
    prev = _memory_source
    _memory_source = (source or "user").strip().lower() or "user"
    return prev


def current_memory_source() -> str:
    return _memory_source


def _norm_subject(subject: str | None) -> str:
    return (subject or "user").strip().lower() or "user"


def _norm_tags(tags: Any) -> str:
    """Normalise tags to a comma-separated string (accepts list or string)."""
    if not tags:
        return ""
    if isinstance(tags, str):
        parts = tags.replace(",", " ").split()
    else:
        parts = [str(t) for t in tags]
    seen: list[str] = []
    for t in parts:
        t = t.strip().lower()
        if t and t not in seen:
            seen.append(t)
    return ",".join(seen)


def remember(key: str, value: str, category: str | None = None,
             source: str | None = None, subject: str | None = None,
             tags: Any = None, note: str = "") -> None:
    """Store a fact and append it to the history log.

    ``subject`` = who/what it's ABOUT (the operator by default, or another
    person/thing). ``source`` = who SET it (defaults to the active memory
    source — 'user' live, 'benchmark' during a bench run). ``category``
    groups it; ``tags`` (list or comma string) + ``note`` carry context. The
    current view (``facts``) is upserted; every call also appends to
    ``fact_log`` so the value can be traced over time."""
    from jaeger_os.core.memory import sqlite_store
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cat = _norm_category(category)
    src = (source or _memory_source or "user").strip().lower() or "user"
    subj = _norm_subject(subject)
    tag_str = _norm_tags(tags)
    with sqlite_store.writer() as conn:
        existing = conn.execute(
            "SELECT created_at FROM facts "
            "WHERE subject = ? AND key = ? AND source = ?",
            (subj, key, src),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            "INSERT OR REPLACE INTO facts "
            "(subject, key, value, category, source, tags, note, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (subj, key, value, cat, src, tag_str, note, created_at, now),
        )
        conn.execute(
            "INSERT INTO fact_log "
            "(subject, key, value, category, source, tags, note, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (subj, key, value, cat, src, tag_str, note, now),
        )


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"my", "the", "a", "an", "is", "of", "do", "i", "what", "this", "that"}


def _source_filter() -> tuple[str, tuple[str, ...]]:
    """The operator's recall ignores 'benchmark' facts (and a bench run only
    sees its own) — so the benchmark's favourite colour is never returned as
    the operator's."""
    if _memory_source == "benchmark":
        return "source = ?", ("benchmark",)
    return "source != ?", ("benchmark",)


def recall(key: str, subject: str | None = None) -> str | None:
    """Look up the CURRENT value of a fact by exact key, with fuzzy fallback.
    ``subject`` scopes whose fact (the operator by default). For the value
    OVER TIME, use :func:`recall_history`.

    The fuzzy path lets the agent ask for ``"birthday"`` and find
    ``"users_birthday"`` — the model's phrasing drifts. Order: exact key →
    substring match against keys → word-overlap (excluding stopwords)."""
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    subj = _norm_subject(subject)
    src_sql, src_args = _source_filter()
    # Precedence when the same (subject, key) exists under several sources
    # (user-stated vs agent-inferred): what the USER said wins; ties break
    # by recency. Without an explicit ORDER BY the row returned is
    # PK-storage order — effectively arbitrary.
    _prec = "ORDER BY (source = 'user') DESC, updated_at DESC"
    # 1) Exact key.
    row = conn.execute(
        f"SELECT value FROM facts WHERE subject = ? AND key = ? AND {src_sql} "
        f"{_prec} LIMIT 1",
        (subj, key, *src_args),
    ).fetchone()
    if row is not None:
        return row["value"]
    # 2) Substring match across this subject's keys (precedence-ordered, so
    #    the first hit is the authoritative row for its key).
    all_rows = conn.execute(
        f"SELECT key, value FROM facts WHERE subject = ? AND {src_sql} {_prec}",
        (subj, *src_args),
    ).fetchall()
    if not all_rows:
        return None
    needle = key.lower().strip()
    needle_alt = needle.replace(" ", "_")
    for r in all_rows:
        stored_key = r["key"]
        normalized = stored_key.lower().replace("_", " ")
        if needle in normalized or needle_alt in stored_key.lower():
            return r["value"]
    # 3) Word-overlap fallback.
    needle_words = {w for w in _WORD_RE.findall(needle) if w not in _STOPWORDS}
    if not needle_words:
        return None
    best_value: str | None = None
    best_overlap = 0
    for r in all_rows:
        stored_words = {
            w for w in _WORD_RE.findall(r["key"].lower().replace("_", " "))
            if w not in _STOPWORDS
        }
        overlap = len(needle_words & stored_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_value = r["value"]
    return best_value if best_overlap >= 1 else None


def recall_history(key: str, subject: str | None = None) -> list[dict[str, str]]:
    """The full timeline of a fact from ``fact_log`` — every value it has
    held, oldest first, with when/who/tags/note. Lets the agent answer
    "you said blue on d1 and black on d2; your colours are blue and black."
    Subject-scoped; source-filtered like ``recall``."""
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    subj = _norm_subject(subject)
    src_sql, src_args = _source_filter()
    rows = conn.execute(
        f"SELECT value, source, tags, note, ts FROM fact_log "
        f"WHERE subject = ? AND key = ? AND {src_sql} ORDER BY ts",
        (subj, key, *src_args),
    ).fetchall()
    return [
        {"value": r["value"], "source": r["source"], "tags": r["tags"],
         "note": r["note"], "when": r["ts"]}
        for r in rows
    ]


def forget(key: str, subject: str | None = None) -> bool:
    """Remove a fact by exact key (scoped to ``subject``, default the
    operator). Returns True if a row existed. History in ``fact_log`` is
    kept — forgetting the current value doesn't erase that it was once true.

    Source-scoped like ``recall``: a benchmark run can only delete its own
    facts, never the operator's (a bench "forget my hometown" case must not
    reach through and destroy the real hometown row), and the operator's
    forget never touches benchmark rows."""
    from jaeger_os.core.memory import sqlite_store
    subj = _norm_subject(subject)
    src_sql, src_args = _source_filter()
    with sqlite_store.writer() as conn:
        cur = conn.execute(
            f"DELETE FROM facts WHERE subject = ? AND key = ? AND {src_sql}",
            (subj, key, *src_args),
        )
        return cur.rowcount > 0


def list_facts(subject: str | None = "user") -> dict[str, str]:
    """Facts as a ``{key: value}`` dict — the OPERATOR's facts by default
    (``subject="user"``). Pass another subject for their facts, or ``None``
    for every subject with keys prefixed ``subject:key`` so different
    subjects' facts can never silently clobber each other in the merged
    dict (Alice's favorite_color must not read as the operator's).
    Benchmark-sourced facts are always excluded."""
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    src_sql, src_args = _source_filter()
    if subject is None:
        rows = conn.execute(
            f"SELECT subject, key, value FROM facts WHERE {src_sql} "
            f"ORDER BY subject, key", src_args
        ).fetchall()
        return {
            (r["key"] if r["subject"] == "user"
             else f'{r["subject"]}:{r["key"]}'): r["value"]
            for r in rows
        }
    subj = _norm_subject(subject)
    rows = conn.execute(
        f"SELECT key, value FROM facts WHERE subject = ? AND {src_sql} "
        f"ORDER BY key", (subj, *src_args)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def list_facts_by_category(subject: str | None = "user") -> dict[str, dict[str, str]]:
    """Facts grouped by category — ``{category: {key: value}}`` — for one
    subject (the operator by default; this feeds the system-prompt facts
    snapshot, which must never present someone else's fact as the
    operator's). Categories are sorted with 'general' last."""
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    src_sql, src_args = _source_filter()
    subj = _norm_subject(subject)
    rows = conn.execute(
        f"SELECT key, value, category FROM facts "
        f"WHERE subject = ? AND {src_sql} "
        f"ORDER BY category, key", (subj, *src_args)
    ).fetchall()
    grouped: dict[str, dict[str, str]] = {}
    for r in rows:
        grouped.setdefault(r["category"] or "general", {})[r["key"]] = r["value"]
    return dict(sorted(grouped.items(),
                       key=lambda kv: (kv[0] == "general", kv[0])))


# ---------------------------------------------------------------------------
# episodic — DB-3 backed by SQLite via ``sqlite_store``
# ---------------------------------------------------------------------------
# Each agent turn lands as one row. The dict the caller passes can
# include any subset of known fields plus arbitrary extras; known
# ones get dedicated columns, everything else lands in ``meta_json``
# so future query work doesn't need a schema bump.

# Fields that map to dedicated columns in the episodic table.
# Everything in the entry dict OTHER than these (and ``timestamp``,
# which becomes ``ts``) lands in ``meta_json`` as a JSON blob.
_EPISODIC_KNOWN_FIELDS = (
    "user", "answer", "decision_raw", "tool_activity",
    "first_decision", "skipped_final",
)


def _extract_episodic_columns(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Pull dedicated-column values out of ``entry``; everything else
    (after known field + ``session_key`` + ``timestamp``) is bundled
    into the trailing ``meta_json`` column."""
    session_key = entry.get("session_key") or "default"
    ts = entry.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    user_text = entry.get("user")
    answer = entry.get("answer")
    decision_raw = entry.get("decision_raw")
    tool_activity = entry.get("tool_activity")
    if isinstance(tool_activity, list):
        # Stored as JSON for round-trip fidelity.
        tool_activity_str = json.dumps(tool_activity, ensure_ascii=True)
    elif tool_activity is None:
        tool_activity_str = None
    else:
        tool_activity_str = str(tool_activity)
    first_decision = entry.get("first_decision")
    if first_decision is not None and not isinstance(first_decision, str):
        first_decision = json.dumps(first_decision, ensure_ascii=True)
    skipped_final = 1 if entry.get("skipped_final") else 0

    latency_ms: int | None = None
    latency = entry.get("latency")
    if isinstance(latency, dict):
        total = latency.get("total")
        if isinstance(total, (int, float)):
            latency_ms = int(round(float(total) * 1000))
    elif isinstance(latency, (int, float)):
        latency_ms = int(round(float(latency) * 1000))

    # Stash the remainder (unknown fields) for future query work.
    extras = {
        k: v for k, v in entry.items()
        if k not in _EPISODIC_KNOWN_FIELDS
        and k not in ("session_key", "timestamp", "latency")
    }
    meta_json = json.dumps(extras, ensure_ascii=True, default=str) if extras else None

    return (session_key, ts, user_text, answer, decision_raw,
            tool_activity_str, latency_ms, first_decision,
            skipped_final, meta_json)


def append_episodic(entry: dict[str, Any]) -> None:
    """Persist one agent turn into the ``episodic`` SQL table."""
    from jaeger_os.core.memory import sqlite_store
    cols = _extract_episodic_columns(entry)
    with sqlite_store.writer() as conn:
        conn.execute(
            "INSERT INTO episodic ("
            " session_key, ts, user, answer, decision_raw, tool_activity,"
            " latency_ms, first_decision, skipped_final, meta_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            cols,
        )


def load_recent_turns(n: int = 5, session_key: str | None = None) -> list[dict[str, str]]:
    """Return the last ``n`` (user, assistant) message pairs as
    ``[{"role": "user", "content": ...}, {"role": "assistant",
    "content": ...}, ...]``. Optionally filtered by ``session_key``.

    Matches the legacy contract used by the TUI history loader and
    the messaging-gateway initialiser.
    """
    if n <= 0:
        return []
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    if session_key is None:
        rows = conn.execute(
            "SELECT user, decision_raw FROM episodic "
            "ORDER BY id DESC LIMIT ?", (n,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT user, decision_raw FROM episodic "
            "WHERE session_key = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_key, n),
        ).fetchall()
    # ORDER BY id DESC gives newest-first; flip to chronological
    # (oldest-first) so the message replay matches conversation
    # order.
    messages: list[dict[str, str]] = []
    for row in reversed(rows):
        user = row["user"]
        decision = row["decision_raw"]
        if user and decision:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": decision})
    return messages


def recent_qa_pairs(
    n: int = 6, session_key: str | None = None,
) -> list[dict[str, str]]:
    """Return the last ``n`` (user, answer) pairs as
    ``[{"user": ..., "answer": ...}, ...]``, oldest first.

    Unlike :func:`load_recent_turns` (which returns ``decision_raw``
    for the legacy replay contract), this reads the human-facing
    ``answer`` column — the right source for the cross-restart
    session digest, where the point is what was SAID, not the raw
    routing decision."""
    if n <= 0:
        return []
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    if session_key is None:
        rows = conn.execute(
            "SELECT user, answer FROM episodic "
            "WHERE user IS NOT NULL AND answer IS NOT NULL "
            "ORDER BY id DESC LIMIT ?", (n,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT user, answer FROM episodic "
            "WHERE session_key = ? "
            "AND user IS NOT NULL AND answer IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (session_key, n),
        ).fetchall()
    return [
        {"user": row["user"], "answer": row["answer"]}
        for row in reversed(rows)
    ]


def _lazy_import_episodic_from_jsonl() -> None:
    """One-shot: copy ``episodic.jsonl`` into the SQL ``episodic``
    table on first 0.2.0 boot. No-op when SQL already has rows OR
    the JSONL file is absent. DB-8 will rename the JSONL file aside
    formally; this just makes the upgrade transparent.
    """
    from jaeger_os.core.memory import sqlite_store
    if not sqlite_store.is_bound():
        return
    path = _state.get("episodic_path")
    if path is None or not path.exists():
        return
    conn = sqlite_store.connection()
    if conn.execute("SELECT 1 FROM episodic LIMIT 1").fetchone() is not None:
        return  # idempotent

    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return

    if not entries:
        return

    with sqlite_store.writer() as wconn:
        for entry in entries:
            cols = _extract_episodic_columns(entry)
            wconn.execute(
                "INSERT INTO episodic ("
                " session_key, ts, user, answer, decision_raw, tool_activity,"
                " latency_ms, first_decision, skipped_final, meta_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                cols,
            )


# ---------------------------------------------------------------------------
# Semantic search — DB-4, backed by SQLite ``episodic_embeddings``
# ---------------------------------------------------------------------------
# Each episodic row gets one embedding row (FK + ON DELETE CASCADE).
# The encoder is a small sentence-transformers model loaded lazily;
# the vector is stored as a normalised float32 BLOB so cosine
# similarity is a dot product. ``sqlite-vec`` is preferred when
# available (native KNN); we fall back to a Python-side scan over
# the BLOBs when not (the common case until sqlite-vec is packaged
# for the host).
EMBED_MODEL_ID = os.environ.get("SEMANTIC_MEMORY_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_semantic_state: dict[str, Any] = {
    "model": None,
    "model_id": None,
}


def _ensure_semantic_model() -> Any:
    """Lazy-load sentence-transformers on the first ``search_memory``
    call. Pinned to CPU — the all-MiniLM model is tiny and CPU-fast,
    and putting it on Apple Metal collides with llama-cpp-python's
    Metal context (corrupts subsequent LLM decodes)."""
    if _semantic_state["model"] is not None and _semantic_state["model_id"] == EMBED_MODEL_ID:
        return _semantic_state["model"]
    from sentence_transformers import SentenceTransformer
    import time as _t

    started = _t.perf_counter()
    model = SentenceTransformer(EMBED_MODEL_ID, device="cpu")
    print(f"[semantic-memory] {EMBED_MODEL_ID} loaded on CPU in "
          f"{_t.perf_counter() - started:.1f}s", flush=True)
    _semantic_state["model"] = model
    _semantic_state["model_id"] = EMBED_MODEL_ID
    return model


def _episodic_text_for(user: str | None, answer: str | None) -> str:
    """The string the encoder sees for one episodic row."""
    u = (user or "").strip()
    a = (answer or "").strip()
    return f"USER: {u}\nASSISTANT: {a}".strip()


def _vector_to_blob(vec: Any) -> bytes:
    """Pack a float32 numpy vector into raw bytes for BLOB storage."""
    import numpy as np
    arr = np.asarray(vec, dtype="float32").reshape(-1)
    return arr.tobytes()


def _blob_to_vector(blob: bytes) -> Any:
    """Inverse of ``_vector_to_blob``."""
    import numpy as np
    return np.frombuffer(blob, dtype="float32")


def _ensure_embeddings_up_to_date() -> int:
    """Encode + INSERT embeddings for any ``episodic`` row that
    doesn't have one yet. Returns the number of new embeddings
    written. Idempotent — re-runs find no missing rows.

    Encoding is batched (32 rows at a time) so a fresh instance
    importing thousands of rows doesn't pay 1 model.encode() call
    per row. Latency on a small Mac for 1000 rows ≈ 1-2s after the
    model is warm.
    """
    from jaeger_os.core.memory import sqlite_store
    import numpy as np

    conn = sqlite_store.connection()
    missing = conn.execute(
        "SELECT e.id, e.user, e.answer FROM episodic e "
        "LEFT JOIN episodic_embeddings em ON em.episodic_id = e.id "
        "WHERE em.episodic_id IS NULL "
        "ORDER BY e.id"
    ).fetchall()
    if not missing:
        return 0

    model = _ensure_semantic_model()
    written = 0
    batch_size = 32
    for i in range(0, len(missing), batch_size):
        batch = missing[i : i + batch_size]
        texts = [_episodic_text_for(r["user"], r["answer"]) for r in batch]
        vectors = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False,
        )
        vectors = np.asarray(vectors, dtype="float32")
        dim = int(vectors.shape[1])
        with sqlite_store.writer() as wconn:
            for row, vec in zip(batch, vectors):
                wconn.execute(
                    "INSERT INTO episodic_embeddings "
                    "(episodic_id, model, dim, vector) "
                    "VALUES (?, ?, ?, ?)",
                    (row["id"], EMBED_MODEL_ID, dim, _vector_to_blob(vec)),
                )
                written += 1
    return written


def search_memory(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Return up to ``k`` semantically-closest episodic entries for
    ``query``. Each result has ``user`` / ``answer`` / ``timestamp``
    / ``score`` (cosine, 0-1).

    Encodes missing embeddings on first call after new turns have
    been appended — incremental, not a full rebuild. Uses
    ``sqlite-vec``'s native KNN when the extension loaded (DB-1);
    otherwise scans the embedding BLOBs in Python (still O(N) but
    fast on numpy: ~ms for 10K rows, ~tens-of-ms for 100K).
    """
    import numpy as np
    from jaeger_os.core.memory import sqlite_store

    clean = (query or "").strip()
    if not clean:
        return []
    if k <= 0:
        return []

    _ensure_embeddings_up_to_date()

    conn = sqlite_store.connection()
    rows = conn.execute(
        "SELECT e.id, e.user, e.answer, e.ts, em.vector "
        "FROM episodic e "
        "JOIN episodic_embeddings em ON em.episodic_id = e.id"
    ).fetchall()
    if not rows:
        return []

    model = _ensure_semantic_model()
    q_vec = np.asarray(
        model.encode([clean], normalize_embeddings=True, show_progress_bar=False),
        dtype="float32",
    )[0]

    # Python-side cosine scan over the BLOB rows. (sqlite-vec wiring
    # for KNN is a follow-up — see DB-4 in the roadmap. The fallback
    # is the realistic path for most hosts today.)
    vectors = np.stack(
        [_blob_to_vector(r["vector"]) for r in rows]
    )
    scores = vectors @ q_vec
    top_idx = scores.argsort()[::-1][: max(1, k)]
    out: list[dict[str, Any]] = []
    for i in top_idx:
        row = rows[int(i)]
        out.append({
            "user": row["user"] or "",
            "answer": row["answer"] or "",
            "timestamp": row["ts"],
            "score": float(scores[int(i)]),
        })
    return out


# ---------------------------------------------------------------------------
# schedules — DB-5 backed by SQLite via ``sqlite_store``
# ---------------------------------------------------------------------------
# Same public API as the JSONL era. The SQL schema column names
# (``schedule_id`` / ``next_fire_at`` / ``status`` / ``last_fired_at``)
# differ from the JSON keys (``name`` / ``next_run_at`` / ``cancelled``
# / ``last_run_at``); ``_row_to_dict`` translates back so callers get
# the same shape.

def _schedule_row_to_dict(row: Any) -> dict[str, Any]:
    """SQL row → legacy dict shape callers expect."""
    return {
        "name": row["schedule_id"],
        "cron": row["cron"],
        "prompt": row["prompt"],
        "created_at": row["created_at"],
        "next_run_at": row["next_fire_at"],
        "last_run_at": row["last_fired_at"],
        "cancelled": row["status"] == "cancelled",
    }


ONCE_CRON = "@once"   # sentinel in the cron column: fire once, then done


def add_schedule(cron_expr: str, prompt: str, name: str | None = None,
                 at: str | None = None) -> dict[str, Any]:
    """Register a new scheduled prompt. Same contract as the
    JSONL-era function; returns the row in legacy dict shape.

    ``at`` (0.7.2) makes it a ONE-SHOT: an ISO datetime (naive = local
    time) stored as cron ``@once`` — it fires once at that moment and
    the row flips to ``done`` (no yearly cron re-fire, no cleanup
    prompt needed). ``cron_expr`` is ignored when ``at`` is given."""
    from croniter import croniter
    from jaeger_os.core.memory import sqlite_store

    cron_expr = (cron_expr or "").strip()
    prompt = (prompt or "").strip()
    if not prompt or not (cron_expr or at):
        raise ValueError("prompt and (cron_expr or at) are required")
    # The agent authors cron expressions against LOCAL wall-clock time
    # (``get_time`` returns local time, and its docstring tells the model
    # to anchor the cron to "the real current wall time"). So croniter
    # must interpret the cron fields in the LOCAL zone — anchoring to UTC
    # here shifted every fire by the UTC offset (a "remind me in 1 minute"
    # fired hours late). Store next_fire_at in UTC so the string-ordered
    # comparison in claim_due_schedules stays consistent.
    now_local = datetime.now().astimezone()
    if at:
        try:
            nxt = datetime.fromisoformat(str(at).strip())
        except ValueError as exc:
            raise ValueError(f"invalid 'at' datetime: {at!r}") from exc
        if nxt.tzinfo is None:                 # naive = operator-local
            nxt = nxt.replace(tzinfo=now_local.tzinfo)
        cron_expr = ONCE_CRON
    else:
        if not croniter.is_valid(cron_expr):
            raise ValueError(f"invalid cron expression: {cron_expr!r}")
        nxt = croniter(cron_expr, now_local).get_next(datetime)
    now = now_local.astimezone(timezone.utc)
    name = (name or f"sched_{int(now.timestamp())}").strip()
    created_at = now.isoformat(timespec="seconds")
    next_fire = nxt.astimezone(timezone.utc).isoformat(timespec="seconds")

    with sqlite_store.writer() as conn:
        # ``schedule_id`` is UNIQUE — re-adding under the same name
        # is treated as resurrect-and-replace (matches JSONL semantics
        # where a later row would shadow the earlier one).
        conn.execute(
            "INSERT INTO schedules "
            "(schedule_id, cron, prompt, next_fire_at, status, created_at) "
            "VALUES (?, ?, ?, ?, 'active', ?) "
            "ON CONFLICT(schedule_id) DO UPDATE SET "
            "  cron = excluded.cron, "
            "  prompt = excluded.prompt, "
            "  next_fire_at = excluded.next_fire_at, "
            "  status = 'active'",
            (name, cron_expr, prompt, next_fire, created_at),
        )
    return {
        "name": name,
        "cron": cron_expr,
        "prompt": prompt,
        "created_at": created_at,
        "next_run_at": next_fire,
        "last_run_at": None,
        "cancelled": False,
    }


def list_schedules() -> list[dict[str, Any]]:
    """Active (not-cancelled) schedules, in cron-pinned dict shape."""
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    rows = conn.execute(
        "SELECT * FROM schedules WHERE status = 'active' "
        "ORDER BY schedule_id"
    ).fetchall()
    return [_schedule_row_to_dict(r) for r in rows]


def cancel_schedule(name: str) -> bool:
    """Mark a schedule as cancelled. Returns True if it existed AND
    was active before the call. Cancelling an already-cancelled or
    non-existent schedule returns False (no-op)."""
    name = (name or "").strip()
    if not name:
        return False
    from jaeger_os.core.memory import sqlite_store
    with sqlite_store.writer() as conn:
        cur = conn.execute(
            "UPDATE schedules SET status = 'cancelled' "
            "WHERE schedule_id = ? AND status = 'active'",
            (name,),
        )
        return cur.rowcount > 0


def claim_due_schedules(now: Any = None) -> list[dict[str, Any]]:
    """Atomically claim every schedule whose ``next_fire_at`` is at
    or before ``now``. Recompute next_fire_at + bump last_fired_at
    inside the same transaction so a second cron worker can't
    double-fire.

    Returns the schedule dicts AS THEY WERE before the bump (legacy
    contract — callers want to know which prompt + cron to run).
    """
    from croniter import croniter
    from jaeger_os.core.memory import sqlite_store

    now = now or datetime.now(timezone.utc)
    if hasattr(now, "isoformat"):
        cutoff = now.isoformat(timespec="seconds")
        now_dt = now
    else:
        cutoff = str(now)
        now_dt = datetime.now(timezone.utc)

    claimed: list[dict[str, Any]] = []
    with sqlite_store.writer() as conn:
        due_rows = conn.execute(
            "SELECT * FROM schedules "
            "WHERE status = 'active' "
            "  AND next_fire_at IS NOT NULL "
            "  AND next_fire_at <= ?",
            (cutoff,),
        ).fetchall()
        for row in due_rows:
            claimed.append(_schedule_row_to_dict(row))
            fired_at = (now_dt.astimezone(timezone.utc)
                        .isoformat(timespec="seconds"))
            if row["cron"] == ONCE_CRON:
                # One-shot: this fire IS the schedule's whole life —
                # flip to done, never recompute.
                conn.execute(
                    "UPDATE schedules SET status = 'done', "
                    "next_fire_at = NULL, last_fired_at = ? WHERE id = ?",
                    (fired_at, row["id"]),
                )
                continue
            try:
                # Recompute the next fire in LOCAL wall-clock (matching
                # add_schedule), then store it back in UTC.
                nxt = croniter(row["cron"], now_dt.astimezone()).get_next(datetime)
            except Exception:  # noqa: BLE001 — malformed cron, leave alone
                continue
            conn.execute(
                "UPDATE schedules SET next_fire_at = ?, last_fired_at = ? "
                "WHERE id = ?",
                (nxt.astimezone(timezone.utc).isoformat(timespec="seconds"),
                 fired_at, row["id"]),
            )
    return claimed


def _lazy_import_schedules_from_jsonl() -> None:
    """One-shot: copy ``schedules.jsonl`` into the SQL schedules
    table on first 0.2.0 boot. Idempotent — no-op when SQL table
    already has rows OR the JSONL file is absent.

    The JSONL log was append-only with cancel-rows; we replay it
    in order to get the LIVE picture (latest row wins per name,
    cancel-rows drop the entry).
    """
    from jaeger_os.core.memory import sqlite_store
    if not sqlite_store.is_bound():
        return
    path = _state.get("schedules_path")
    if path is None or not path.exists():
        return
    conn = sqlite_store.connection()
    if conn.execute("SELECT 1 FROM schedules LIMIT 1").fetchone() is not None:
        return

    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return

    # Replay: latest row per name wins. Cancel-rows drop the entry.
    live: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        if row.get("cancelled"):
            live.pop(name, None)
        else:
            live[name] = row
    if not live:
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite_store.writer() as wconn:
        for name, sched in live.items():
            wconn.execute(
                "INSERT OR IGNORE INTO schedules "
                "(schedule_id, cron, prompt, next_fire_at, status, "
                " created_at, last_fired_at) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (
                    name,
                    sched.get("cron", ""),
                    sched.get("prompt", ""),
                    sched.get("next_run_at"),
                    sched.get("created_at") or now,
                    sched.get("last_run_at"),
                ),
            )


# ---------------------------------------------------------------------------
# tool_calls — DB-6: every dispatched tool lands here for training-
# data extraction. ``record_tool_call`` is the only entry point;
# call sites are in the agent loop. Arguments + result already pass
# through ``redact_obj`` at the audit layer; this stores the same
# redacted shape JSON-encoded for query.
# ---------------------------------------------------------------------------

def record_tool_call(
    *,
    session_key: str,
    tool_name: str,
    args: dict[str, Any] | None = None,
    result: Any = None,
    ok: bool = True,
    error: str | None = None,
    elapsed_s: float | None = None,
    episodic_id: int | None = None,
    ts: str | None = None,
) -> int | None:
    """Persist one tool dispatch. Returns the new row id, or
    ``None`` when the store isn't bound (best-effort: callers never
    fail a turn because the log couldn't write).

    Args + result get JSON-encoded with the redactor's
    ``default=str`` fallback so non-JSON-able values don't crash the
    log. Set ``ok=False`` + ``error`` for failed dispatches.
    """
    from jaeger_os.core.memory import sqlite_store
    if not sqlite_store.is_bound():
        return None
    when = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Redact secrets before they land in the DB — same posture as
    # the audit log writer in ``core/tools/_common.py:_audit``.
    try:
        from jaeger_os.core.safety.redact import redact_obj
        args_obj = redact_obj(args or {})
        result_obj = redact_obj(result) if result is not None else None
    except Exception:  # noqa: BLE001 — redaction is advisory; never crash a tool log
        args_obj = args or {}
        result_obj = result

    try:
        args_json = json.dumps(args_obj, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        args_json = json.dumps({"_unserialisable": str(args_obj)})
    if result_obj is None:
        result_json = None
    else:
        try:
            result_json = json.dumps(result_obj, ensure_ascii=True, default=str)
        except (TypeError, ValueError):
            result_json = json.dumps({"_unserialisable": str(result_obj)})

    try:
        with sqlite_store.writer() as conn:
            cur = conn.execute(
                "INSERT INTO tool_calls ("
                " episodic_id, session_key, tool_name, args_json,"
                " result_json, ok, error, elapsed_s, ts"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episodic_id, session_key, tool_name, args_json,
                    result_json, 1 if ok else 0, error, elapsed_s, when,
                ),
            )
            return cur.lastrowid
    except Exception:  # noqa: BLE001 — never fail a turn over a log write
        return None


def list_tool_calls(
    *,
    session_key: str | None = None,
    tool_name: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read recent tool dispatches. Used by ``--doctor`` / future
    ``jaeger memory export`` (DB-10) and by tests. Newest-first."""
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    sql = ("SELECT id, episodic_id, session_key, tool_name, args_json,"
           " result_json, ok, error, elapsed_s, ts "
           "FROM tool_calls WHERE 1 = 1")
    params: list[Any] = []
    if session_key is not None:
        sql += " AND session_key = ?"
        params.append(session_key)
    if tool_name is not None:
        sql += " AND tool_name = ?"
        params.append(tool_name)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": r["id"],
            "episodic_id": r["episodic_id"],
            "session_key": r["session_key"],
            "tool_name": r["tool_name"],
            "args": _safe_loads(r["args_json"]),
            "result": _safe_loads(r["result_json"]),
            "ok": bool(r["ok"]),
            "error": r["error"],
            "elapsed_s": r["elapsed_s"],
            "ts": r["ts"],
        })
    return out


def _safe_loads(s: str | None) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s


# ---------------------------------------------------------------------------
# audit_log — DB-7: tamper-evidence trail mirrored into SQL.
#
# ``core/tools/_common.py:_audit`` writes the canonical JSONL line to
# ``<instance>/logs/audit.log`` (kept for forensic append-only posture)
# and *also* calls ``record_audit_event`` here so the daemon's
# ``--doctor`` + future ``jaeger memory export`` can query the same
# events without scanning the JSONL.
# ---------------------------------------------------------------------------

def record_audit_event(
    *,
    event: str,
    payload: dict[str, Any] | None = None,
    session_key: str | None = None,
    ts: str | None = None,
) -> int | None:
    """Persist one audit event to the SQL ``audit_log`` table. Returns
    the new row id, or ``None`` when the store isn't bound (best-effort:
    never raises — the JSONL writer is the canonical record).

    Note: payload is assumed to already be redacted by the caller
    (the file-level ``_audit`` runs ``redact_obj`` once before either
    write site so there's no double-redact tax).
    """
    from jaeger_os.core.memory import sqlite_store
    if not sqlite_store.is_bound():
        return None
    when = ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        payload_json = json.dumps(payload or {}, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        payload_json = json.dumps({"_unserialisable": str(payload)})
    try:
        with sqlite_store.writer() as conn:
            cur = conn.execute(
                "INSERT INTO audit_log (ts, event, payload_json, session_key)"
                " VALUES (?, ?, ?, ?)",
                (when, event, payload_json, session_key),
            )
            return cur.lastrowid
    except Exception:  # noqa: BLE001 — JSONL is the canonical write
        return None


def list_audit_events(
    *,
    event: str | None = None,
    session_key: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Newest-first audit-log query. Used by ``--doctor`` and the
    future ``jaeger memory export`` verb."""
    from jaeger_os.core.memory import sqlite_store
    conn = sqlite_store.connection()
    sql = ("SELECT id, ts, event, payload_json, session_key"
           " FROM audit_log WHERE 1 = 1")
    params: list[Any] = []
    if event is not None:
        sql += " AND event = ?"
        params.append(event)
    if session_key is not None:
        sql += " AND session_key = ?"
        params.append(session_key)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, limit))
    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "id": r["id"],
            "ts": r["ts"],
            "event": r["event"],
            "payload": _safe_loads(r["payload_json"]),
            "session_key": r["session_key"],
        })
    return out


def _lazy_import_audit_log_from_jsonl() -> None:
    """First-bind copy of ``logs/audit.log`` into ``audit_log``. Gated
    on "SQL table empty AND legacy JSONL present" so re-binds are
    idempotent. Corrupt lines are skipped, not fatal."""
    from jaeger_os.core.memory import sqlite_store
    if not sqlite_store.is_bound():
        return
    audit_path = _state.get("audit_log_path")
    if audit_path is None or not Path(audit_path).exists():
        return
    conn = sqlite_store.connection()
    existing = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    if existing:
        return  # SQL already has rows — don't clobber
    rows: list[tuple[str, str, str, str | None]] = []
    try:
        with open(audit_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (TypeError, ValueError):
                    continue  # corrupt line — skip, JSONL is the authority
                if not isinstance(entry, dict):
                    continue
                ts = entry.pop("ts", None) or datetime.now(
                    timezone.utc
                ).isoformat(timespec="seconds")
                event = entry.pop("event", None) or "unknown"
                session_key = entry.pop("session_key", None)
                # Whatever's left is the payload.
                try:
                    payload_json = json.dumps(
                        entry, ensure_ascii=True, default=str,
                    )
                except (TypeError, ValueError):
                    payload_json = json.dumps({"_unserialisable": str(entry)})
                rows.append((ts, event, payload_json, session_key))
    except OSError:
        return
    if not rows:
        return
    with sqlite_store.writer() as wconn:
        wconn.executemany(
            "INSERT INTO audit_log (ts, event, payload_json, session_key)"
            " VALUES (?, ?, ?, ?)",
            rows,
        )


# ---------------------------------------------------------------------------
# Identity (read-only here — wizard owns identity.yaml; the agent loop
# combines it with the v2 system prompt at startup, never via this module).
# ---------------------------------------------------------------------------
def load_identity_string(layout: Any) -> str:
    """Render identity.yaml into the prose blurb the agent sees in its
    system prompt: a few short lines naming the agent and its persona."""
    from jaeger_os.core.instance.schemas import load_yaml, Identity

    if not layout.identity_path.exists():
        return ""
    try:
        ident: Identity = load_yaml(layout.identity_path, Identity)
    except Exception:
        return ""
    return (
        f"You are {ident.name}. That is your name and your identity — when "
        f"asked who or what you are, answer as {ident.name}. The underlying "
        f"language model — whatever its base name (Qwen, Gemma, Llama, GPT, "
        f"or any other) — is only the engine that runs you; it is not who "
        f"you are. Never introduce yourself by the base model's name, by its "
        f"maker, or as \"just a large language model\".\n"
        f"Role: {ident.role}\n"
        f"Voice: {ident.personality}"
    )
