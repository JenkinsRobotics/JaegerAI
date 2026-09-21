"""Incremental document indexing (PRODUCTION OS SPEC Parts 20–21).

Indexed text is document memory, not semantic belief.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

from jaeger_ai.core.entity.events import EventType, JaegerEvent

logger = logging.getLogger("jaeger.entity.indexing")

MAX_FILES_PER_SWEEP = 50
MAX_SWEEP_SECONDS = 60.0
MAX_FILE_BYTES = 400_000


@dataclass
class IndexSource:
    source_id: str
    path: str
    source_type: str
    trust_class: str = "operator_approved"


class IndexManifest:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS indexed_sources (
                    source_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    content_hash TEXT,
                    modified_at REAL,
                    indexed_at REAL,
                    trust_class TEXT
                );
                CREATE TABLE IF NOT EXISTS indexed_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    metadata TEXT,
                    FOREIGN KEY(source_id) REFERENCES indexed_sources(source_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS indexed_chunks_fts USING fts5(
                    text, source_id UNINDEXED, chunk_id UNINDEXED
                );
                """
            )

    def source_hash(self, source_id: str) -> str | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT content_hash FROM indexed_sources WHERE source_id=?",
                (source_id,),
            ).fetchone()
        return str(row["content_hash"]) if row and row["content_hash"] else None

    def upsert_source(self, source: IndexSource, content_hash: str, modified_at: float, chunks: list[str]) -> None:
        now = time.time()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO indexed_sources(source_id, path, source_type, content_hash, modified_at, indexed_at, trust_class)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    modified_at=excluded.modified_at,
                    indexed_at=excluded.indexed_at
                """,
                (source.source_id, source.path, source.source_type, content_hash, modified_at, now, source.trust_class),
            )
            con.execute("DELETE FROM indexed_chunks WHERE source_id=?", (source.source_id,))
            try:
                con.execute("DELETE FROM indexed_chunks_fts WHERE source_id=?", (source.source_id,))
            except sqlite3.OperationalError:
                pass
            for i, text in enumerate(chunks):
                chunk_id = f"{source.source_id}:{i}"
                con.execute(
                    "INSERT INTO indexed_chunks(chunk_id, source_id, ordinal, text, metadata) VALUES(?,?,?,?,?)",
                    (chunk_id, source.source_id, i, text, "{}"),
                )
                try:
                    con.execute(
                        "INSERT INTO indexed_chunks_fts(text, source_id, chunk_id) VALUES(?,?,?)",
                        (text, source.source_id, chunk_id),
                    )
                except sqlite3.OperationalError:
                    pass

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        with self._connect() as con:
            try:
                rows = con.execute(
                    "SELECT chunk_id, source_id, text FROM indexed_chunks_fts WHERE indexed_chunks_fts MATCH ? LIMIT ?",
                    (q, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = con.execute(
                    "SELECT chunk_id, source_id, text FROM indexed_chunks WHERE text LIKE ? LIMIT ?",
                    (f"%{q}%", limit),
                ).fetchall()
        return [dict(r) for r in rows]


class IndexSourceRegistry:
    """Approved source scopes only: repo, docs, skills, explicit project dirs."""

    def __init__(self, extra: Iterable[Path] | None = None) -> None:
        self.extra = [Path(p) for p in (extra or [])]

    def iter_files(self, *, skills_dir: Path | None = None, docs_dir: Path | None = None) -> list[IndexSource]:
        files: list[IndexSource] = []
        roots: list[tuple[Path, str, str]] = []
        if docs_dir and docs_dir.is_dir():
            roots.append((docs_dir, "docs", "system"))
        if skills_dir and skills_dir.is_dir():
            roots.append((skills_dir, "skills", "system"))
        for extra in self.extra:
            if extra.is_dir():
                roots.append((extra, "project", "operator_approved"))
        for root, kind, trust in roots:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".md", ".txt", ".py", ".yaml", ".yml", ".json"}:
                    continue
                if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
                    continue
                rel = str(path)
                files.append(IndexSource(source_id=rel, path=rel, source_type=kind, trust_class=trust))
        return files


class IndexCoordinator:
    def __init__(self, memory_dir: Path, event_store: Any | None = None) -> None:
        self.memory_dir = Path(memory_dir)
        self.manifest = IndexManifest(self.memory_dir / "indexes.sqlite3")
        self.event_store = event_store
        self.registry = IndexSourceRegistry()

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_store is None:
            return
        try:
            self.event_store.append(
                JaegerEvent(
                    event_id="",
                    event_type=event_type,
                    actor="system:indexer",
                    source="indexing",
                    timestamp=time.time(),
                    payload=payload,
                    salience=0.2,
                )
            )
        except Exception:
            logger.debug("index event emit skipped", exc_info=True)

    def sweep(
        self,
        *,
        skills_dir: Path | None = None,
        docs_dir: Path | None = None,
        extra: Iterable[Path] | None = None,
        max_files: int = MAX_FILES_PER_SWEEP,
        max_seconds: float = MAX_SWEEP_SECONDS,
    ) -> dict[str, Any]:
        t0 = time.time()
        self._emit(EventType.INDEX_STARTED.value, {"reason": "idle_sweep"})
        if extra:
            self.registry.extra = [Path(p) for p in extra]
        updated = 0
        skipped = 0
        for source in self.registry.iter_files(skills_dir=skills_dir, docs_dir=docs_dir)[: max_files * 4]:
            if time.time() - t0 > max_seconds or updated >= max_files:
                break
            path = Path(source.path)
            try:
                stat = path.stat()
                if stat.st_size > MAX_FILE_BYTES:
                    skipped += 1
                    continue
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if self.manifest.source_hash(source.source_id) == digest:
                    skipped += 1
                    continue
                text = raw.decode("utf-8", errors="replace")
                chunks = _chunk_text(text)
                self.manifest.upsert_source(source, digest, stat.st_mtime, chunks)
                updated += 1
                self._emit(EventType.INDEX_SOURCE_UPDATED.value, {"source_id": source.source_id, "chunks": len(chunks)})
            except OSError:
                skipped += 1
        result = {"updated": updated, "skipped": skipped, "duration_s": time.time() - t0}
        self._emit(EventType.INDEX_COMPLETED.value, result)
        return result

    def retrieve(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        hits = self.manifest.search(query, limit=limit)
        for hit in hits:
            hit["provenance"] = "RETRIEVED_DOCUMENT"
        return hits


def _chunk_text(text: str, size: int = 1200) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), size)][:40]
