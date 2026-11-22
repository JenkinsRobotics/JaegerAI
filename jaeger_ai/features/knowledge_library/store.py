"""Safe read-only corpus registry with local full-text indexing."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from .managed import ManagedDocuments

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".rst", ".org", ".json", ".yaml", ".yml", ".toml", ".csv"})
MAX_FILE_BYTES = 2_000_000
MAX_FILES = 20_000
IGNORED_DIR_NAMES = frozenset({
    "__pycache__", "node_modules", "vendor", ".venv", "venv", "env",
    "dist", "build", "target", ".cache", ".git", ".hg", ".svn",
})


class LibraryError(ValueError):
    pass


class KnowledgeLibrary(ManagedDocuments):
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
                CREATE TABLE IF NOT EXISTS library_index_state (
                    collection_id TEXT PRIMARY KEY, cursor TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS library_source_documents (
                    document_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL, provenance TEXT NOT NULL,
                    UNIQUE(source_id, external_id)
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
            self.init_managed()

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
            existing = self.conn.execute(
                "SELECT id,label,root,kind,created_at FROM collections WHERE root=?",
                (str(path),),
            ).fetchone()
            if existing is None:
                raise LibraryError(f"could not register collection: {path}") from exc
            return {**dict(existing), "already_exists": True}
        return {"id": collection_id, "label": clean_label, "root": str(path), "kind": kind,
                "already_exists": False}

    def list(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute(
            "SELECT c.id,c.label,c.root,c.kind,c.created_at,COUNT(d.id) AS document_count,"
            "MAX(d.indexed_at) AS last_indexed_at FROM collections c "
            "LEFT JOIN library_documents d ON d.collection_id=c.id "
            "GROUP BY c.id,c.label,c.root,c.kind,c.created_at ORDER BY c.label"
        )]

    def index(self, collection_id: str) -> dict:
        collection = self._collection(collection_id)
        if collection['kind'] == 'managed':
            raise LibraryError('Managed documents are already indexed; no filesystem import applies')
        root = Path(collection["root"]).resolve(strict=True)
        indexed = unchanged = skipped = scanned = pruned_dirs = 0
        seen: set[str] = set()
        truncated = False
        files: list[tuple[Path, str]] = []
        for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            allowed = [name for name in directories
                       if not name.startswith(".") and name not in IGNORED_DIR_NAMES]
            pruned_dirs += len(directories) - len(allowed)
            directories[:] = sorted(allowed)
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                candidate = Path(directory) / name
                files.append((candidate, str(candidate.relative_to(root))))

        state = self.conn.execute(
            "SELECT cursor FROM library_index_state WHERE collection_id=?", (collection_id,)
        ).fetchone()
        cursor = str(state["cursor"] if state else "")
        start = 0
        if cursor:
            for position, (_, raw_relative) in enumerate(files):
                if raw_relative == cursor:
                    start = position + 1
                    break
            else:
                # The cursor target was renamed or removed. Restarting is safe:
                # content-addressed upserts do not duplicate documents.
                cursor = ""

        last_cursor = cursor
        for candidate, raw_relative in files[start:]:
            if len(seen) >= MAX_FILES:
                truncated = True
                break
            last_cursor = raw_relative
            scanned += 1
            if not candidate.is_file():
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
        removed: list[str] = []
        # A single-page complete scan can reconcile deletions. A resumed scan
        # intentionally retains older rows because this page has not observed
        # the earlier portion of the tree.
        if not truncated and start == 0:
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
        with self.conn:
            if truncated:
                self.conn.execute(
                    "INSERT INTO library_index_state(collection_id,cursor,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(collection_id) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at",
                    (collection_id, last_cursor, time.time()),
                )
            else:
                self.conn.execute("DELETE FROM library_index_state WHERE collection_id=?", (collection_id,))
        return {
            "collection_id": collection_id,
            "indexed": indexed,
            "unchanged": unchanged,
            "skipped": skipped,
            "removed": len(removed),
            "truncated": truncated,
            "scanned": scanned,
            "pruned_directories": pruned_dirs,
            "resumed_from": cursor or None,
            "next_cursor": last_cursor if truncated else None,
            "complete": not truncated,
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
            "WHERE library_documents_fts MATCH ? AND NOT EXISTS (SELECT 1 FROM library_managed_documents m WHERE m.document_id=d.id AND m.archived=1) ORDER BY rank LIMIT ?",
            (phrase, max(1, min(int(limit), 100))),
        ).fetchall()
        return [dict(row) for row in rows]

    def sync_source(self, source_id: str, label: str, documents: list[dict], *,
                    full_snapshot: bool = True) -> dict:
        """Upsert one normalized external source into the canonical library.

        Adapters own access to Notes, Reminders, Mail, chat history, or future
        systems. This store owns stable identity, deduplication, provenance,
        search indexing, and full-snapshot reconciliation.
        """
        clean_source = str(source_id or "").strip()
        clean_label = str(label or "").strip()
        if not clean_source or not clean_label:
            raise LibraryError("source_id and label are required")
        collection_id = "source_" + hashlib.sha256(clean_source.encode()).hexdigest()[:16]
        root = f"jaeger-source://{clean_source}"
        now = time.time()
        inserted = updated = unchanged = 0
        seen: set[str] = set()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO collections VALUES(?,?,?,?,?)",
                (collection_id, clean_label, root, "source", now),
            )
            for item in documents:
                external_id = str(item.get("external_id") or "").strip()
                title = str(item.get("title") or "").strip()
                content = str(item.get("content") or "")
                if not external_id or not title:
                    raise LibraryError("every source document needs external_id and title")
                seen.add(external_id)
                raw = content.encode("utf-8")
                if len(raw) > MAX_FILE_BYTES:
                    raise LibraryError(f"source document exceeds size limit: {external_id}")
                digest = hashlib.sha256(raw).hexdigest()
                document_id = hashlib.sha256(
                    f"{clean_source}:{external_id}".encode()
                ).hexdigest()[:24]
                existing = self.conn.execute(
                    "SELECT title,digest FROM library_documents WHERE id=?", (document_id,)
                ).fetchone()
                provenance = json.dumps(item.get("provenance") or {}, sort_keys=True,
                                        ensure_ascii=False)
                modified_at = float(item.get("modified_at") or now)
                if existing and existing["digest"] == digest and existing["title"] == title:
                    unchanged += 1
                else:
                    inserted += int(existing is None)
                    updated += int(existing is not None)
                    self.conn.execute(
                        "INSERT INTO library_documents VALUES(?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET title=excluded.title,content=excluded.content,"
                        "digest=excluded.digest,modified_at=excluded.modified_at,indexed_at=excluded.indexed_at",
                        (document_id, collection_id, external_id, title, content, digest,
                         modified_at, now),
                    )
                self.conn.execute(
                    "INSERT INTO library_source_documents VALUES(?,?,?,?) "
                    "ON CONFLICT(document_id) DO UPDATE SET provenance=excluded.provenance",
                    (document_id, clean_source, external_id, provenance),
                )
            removed = 0
            if full_snapshot:
                rows = self.conn.execute(
                    "SELECT document_id,external_id FROM library_source_documents WHERE source_id=?",
                    (clean_source,),
                ).fetchall()
                stale = [(row["document_id"],) for row in rows if row["external_id"] not in seen]
                removed = len(stale)
                self.conn.executemany("DELETE FROM library_source_documents WHERE document_id=?", stale)
                self.conn.executemany("DELETE FROM library_documents WHERE id=?", stale)
        return {"source_id": clean_source, "collection_id": collection_id,
                "inserted": inserted, "updated": updated, "unchanged": unchanged,
                "removed": removed, "document_count": len(seen),
                "complete": bool(full_snapshot)}

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
