"""Safe read-only corpus registry with local full-text indexing."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst", ".org", ".json", ".yaml", ".yml", ".toml", ".csv"})
MAX_FILE_BYTES = 2_000_000
MAX_FILES = 20_000


class LibraryError(ValueError):
    pass


class KnowledgeLibrary:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collections (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, root TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS library_documents (
                    id TEXT PRIMARY KEY, collection_id TEXT NOT NULL, relative_path TEXT NOT NULL,
                    title TEXT NOT NULL, content TEXT NOT NULL, digest TEXT NOT NULL,
                    modified_at REAL NOT NULL, indexed_at REAL NOT NULL,
                    UNIQUE(collection_id, relative_path)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS library_documents_fts USING fts5(
                    title, content, content='library_documents', content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS library_fts_insert AFTER INSERT ON library_documents BEGIN
                    INSERT INTO library_documents_fts(rowid,title,content)
                    VALUES(new.rowid,new.title,new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS library_fts_delete AFTER DELETE ON library_documents BEGIN
                    INSERT INTO library_documents_fts(library_documents_fts,rowid,title,content)
                    VALUES('delete',old.rowid,old.title,old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS library_fts_update AFTER UPDATE ON library_documents BEGIN
                    INSERT INTO library_documents_fts(library_documents_fts,rowid,title,content)
                    VALUES('delete',old.rowid,old.title,old.content);
                    INSERT INTO library_documents_fts(rowid,title,content)
                    VALUES(new.rowid,new.title,new.content);
                END;
                """
            )

    def close(self) -> None:
        self.conn.close()

    def add(self, root: str, label: str = "") -> dict:
        path = Path(root).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise LibraryError(f"not a directory: {path}")
        clean_label = str(label or "").strip() or path.name
        collection_id = hashlib.sha256(str(path).encode()).hexdigest()[:16]
        kind = "obsidian" if (path / ".obsidian").is_dir() else "folder"
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO collections VALUES(?,?,?,?,?)",
                    (collection_id, clean_label, str(path), kind, time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise LibraryError(f"collection already exists: {path}") from exc
        return {"id": collection_id, "label": clean_label, "root": str(path), "kind": kind}

    def list(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT id,label,root,kind,created_at FROM collections ORDER BY label"
        )]

    def index(self, collection_id: str) -> dict:
        collection = self._collection(collection_id)
        root = Path(collection["root"]).resolve(strict=True)
        indexed = unchanged = skipped = 0
        seen: set[str] = set()
        for candidate in root.rglob("*"):
            if len(seen) >= MAX_FILES:
                break
            if candidate.name.startswith(".") or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                relative = str(resolved.relative_to(root))
                size = resolved.stat().st_size
            except (OSError, ValueError):
                skipped += 1
                continue
            if resolved.suffix.lower() not in TEXT_SUFFIXES or size > MAX_FILE_BYTES:
                skipped += 1
                continue
            seen.add(relative)
            try:
                raw = resolved.read_bytes()
                content = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                skipped += 1
                continue
            digest = hashlib.sha256(raw).hexdigest()
            existing = self.conn.execute(
                "SELECT digest FROM library_documents WHERE collection_id=? AND relative_path=?",
                (collection_id, relative),
            ).fetchone()
            if existing and existing["digest"] == digest:
                unchanged += 1
                continue
            doc_id = hashlib.sha256(f"{collection_id}:{relative}".encode()).hexdigest()[:24]
            with self.conn:
                self.conn.execute(
                    "INSERT INTO library_documents VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(collection_id,relative_path) DO UPDATE SET "
                    "title=excluded.title,content=excluded.content,digest=excluded.digest,"
                    "modified_at=excluded.modified_at,indexed_at=excluded.indexed_at",
                    (
                        doc_id,
                        collection_id,
                        relative,
                        resolved.stem,
                        content,
                        digest,
                        resolved.stat().st_mtime,
                        time.time(),
                    ),
                )
            indexed += 1
        with self.conn:
            stale = self.conn.execute(
                "SELECT relative_path FROM library_documents WHERE collection_id=?",
                (collection_id,),
            ).fetchall()
            removed = [row[0] for row in stale if row[0] not in seen]
            self.conn.executemany(
                "DELETE FROM library_documents WHERE collection_id=? AND relative_path=?",
                [(collection_id, path) for path in removed],
            )
        return {
            "collection_id": collection_id,
            "indexed": indexed,
            "unchanged": unchanged,
            "skipped": skipped,
            "removed": len(removed),
            "truncated": len(seen) >= MAX_FILES,
        }

    def search(self, query: str, limit: int = 20) -> list[dict]:
        clean = str(query or "").strip()
        if not clean:
            return []
        phrase = '"' + clean.replace('"', '""') + '"'
        rows = self.conn.execute(
            "SELECT d.id,d.collection_id,d.relative_path,d.title,"
            "snippet(library_documents_fts,1,'[',']','…',24) AS snippet "
            "FROM library_documents_fts JOIN library_documents d "
            "ON d.rowid=library_documents_fts.rowid "
            "WHERE library_documents_fts MATCH ? ORDER BY rank LIMIT ?",
            (phrase, max(1, min(int(limit), 100))),
        ).fetchall()
        return [dict(row) for row in rows]

    def read(self, document_id: str) -> dict:
        row = self.conn.execute(
            "SELECT id,collection_id,relative_path,title,content,digest,modified_at "
            "FROM library_documents WHERE id=?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise LibraryError(f"document not found: {document_id}")
        return dict(row)

    def _collection(self, collection_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM collections WHERE id=?", (collection_id,)
        ).fetchone()
        if row is None:
            raise LibraryError(f"collection not found: {collection_id}")
        return row
