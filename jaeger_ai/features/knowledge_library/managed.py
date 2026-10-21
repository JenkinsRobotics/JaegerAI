"""App-owned documents in the existing library DB; indexed source files stay read-only."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager


from jaeger_ai.contract.knowledge import DOCUMENT_WRITE_WINDOW_SECONDS, MANAGED_DOCUMENT_MAX_BYTES
from jaeger_ai.contract.workflows import WORKFLOW_COLLECTION_ID


_write_time = time.monotonic

class DocumentConflict(ValueError):
    pass


class ManagedDocuments:
    conn: sqlite3.Connection

    def init_managed(self) -> None:
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS library_managed_documents (
                document_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0, creation_payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS library_document_versions (
                document_id TEXT NOT NULL, revision INTEGER NOT NULL,
                title TEXT NOT NULL, content TEXT NOT NULL, digest TEXT NOT NULL,
                created_at REAL NOT NULL, PRIMARY KEY(document_id,revision)
            );
        ''')

    @staticmethod
    def _text(title: str, content: str) -> tuple[str, str, str]:
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise ValueError('Title must contain 1–200 characters')
        if not isinstance(content, str) or len(content.encode('utf-8')) > MANAGED_DOCUMENT_MAX_BYTES:
            raise ValueError('Document content must be text, at most 2 MB')
        return title.strip(), content, hashlib.sha256(content.encode()).hexdigest()

    def managed_documents(self, *, include_archived: bool = False) -> list[dict]:
        return [{**dict(row), 'archived': bool(row['archived'])} for row in self.conn.execute(
            'SELECT d.id,d.title,d.digest,d.modified_at,m.revision,m.archived '
            'FROM library_documents d JOIN library_managed_documents m ON m.document_id=d.id '
            'WHERE (? OR m.archived=0) ORDER BY d.modified_at DESC,d.id', (include_archived,))]

    def managed_document(self, document_id: str) -> dict:
        row = self.conn.execute('SELECT d.*,m.revision,m.archived,m.creation_payload FROM library_documents d '
                                'JOIN library_managed_documents m ON m.document_id=d.id WHERE d.id=?', (document_id,)).fetchone()
        if row is None:
            raise KeyError('Managed document not found')
        result = {**dict(row), 'archived': bool(row['archived'])}
        creation = json.loads(result.pop('creation_payload'))
        if isinstance(creation,list) and isinstance(creation[-1],dict):result['provenance'] = creation[-1]
        return result

    def create_document(self, *, title: str, content: str, command_id: str, collection_id: str = "managed", provenance: dict | None = None) -> dict:
        title, content, digest = self._text(title, content)
        if not isinstance(command_id, str) or not command_id.strip() or len(command_id) > 128:
            raise ValueError('Stable command_id required (at most128 characters)')
        document_id = 'doc_' + hashlib.sha256(command_id.encode()).hexdigest()[:32]
        if collection_id not in {'managed', WORKFLOW_COLLECTION_ID}:
            raise ValueError('Unsupported managed document classification')
        creation = [title, content] if collection_id == 'managed' else [title, content, collection_id]
        if provenance is not None:
            import re
            if set(provenance)!={'kind','server_id','resource_id','source_text_digest','observed_at','redacted'} or provenance['kind']!='configured_mcp_resource' or not re.fullmatch(r'[a-f0-9]{24}',provenance['server_id']) or not re.fullmatch(r'[a-f0-9]{32}',provenance['resource_id']) or not re.fullmatch(r'[a-f0-9]{64}',provenance['source_text_digest']) or type(provenance['redacted']) is not bool or not isinstance(provenance['observed_at'],(int,float)):
                raise ValueError('Invalid resource snapshot provenance')
            creation.append(provenance)
        payload = json.dumps(creation, ensure_ascii=False)
        with self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            previous = self.conn.execute('SELECT creation_payload FROM library_managed_documents WHERE document_id=?', (document_id,)).fetchone()
            if previous:
                if previous['creation_payload'] != payload:
                    raise DocumentConflict('Command ID already used for different content')
                return {**self.managed_document(document_id), 'replayed': True}
            now = time.time()
            self.conn.execute("INSERT OR IGNORE INTO collections VALUES(?,?,?,?,?)", (collection_id, "Jaeger documents" if collection_id == "managed" else "Workflows", "jaeger://" + collection_id, collection_id, now))
            self.conn.execute('INSERT INTO library_documents VALUES(?,?,?,?,?,?,?,?)', (document_id, collection_id, document_id, title, content, digest, now, now))
            self.conn.execute('INSERT INTO library_managed_documents VALUES(?,1,0,?)', (document_id, payload))
            self.conn.execute('INSERT INTO library_document_versions VALUES(?,1,?,?,?,?)', (document_id, title, content, digest, now))
        return {**self.managed_document(document_id), 'replayed': False}

    def export_document(self, document_id: str, *, expected_revision: int, expected_digest: str) -> dict:
        """One consistent saved snapshot; exporting never grants recipient access."""
        row = self.managed_document(document_id)
        if type(expected_revision) is not int or row['revision'] != expected_revision or row['digest'] != expected_digest:
            raise DocumentConflict('Saved document changed; reload and review before exporting')
        digest = hashlib.sha256(row['content'].encode('utf-8')).hexdigest()
        if digest != row['digest']:
            raise DocumentConflict('Saved document digest is inconsistent; export withheld')
        return {'format': 'jaeger.document.snapshot', 'schema_version': 1,
                'document': {k: row[k] for k in ('id', 'title', 'content', 'revision', 'digest', 'archived')},
                'access': 'manual_local_export_no_recipient_grant'}

    @contextmanager
    def _write_window(self, deadline):
        # A server command window, not a bearer credential or an exclusive edit
        # lease. Hold the SQLite writer reservation across CAS and final guard.
        with self.conn:
            try:
                self.conn.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as exc:
                # BEGIN failed before this command wrote anything. Do not call
                # later commit/I/O failures known rejections: those stay unknown.
                if getattr(exc, 'sqlite_errorcode', None) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                    raise DocumentConflict('Write reservation unavailable; no document changes committed') from None
                raise
            if _write_time() >= deadline:
                raise DocumentConflict('Write window expired; reload and review before a new action')
            yield
            if _write_time() >= deadline:
                raise DocumentConflict('Write window expired before commit; changes rolled back')

    def save_document(self, document_id: str, *, title: str, content: str, expected_revision: int, write_deadline: float | None = None) -> dict:
        deadline = _write_time() + DOCUMENT_WRITE_WINDOW_SECONDS if write_deadline is None else write_deadline
        title, content, digest = self._text(title, content)
        with self._write_window(deadline):
            row = self.managed_document(document_id)
            if type(expected_revision) is not int or row['revision'] != expected_revision:
                raise DocumentConflict('Document changed; reload before saving')
            if row['archived']:
                raise DocumentConflict('Restore archived document before editing')
            if row['title'] == title and row['content'] == content:
                return row
            revision, now = row['revision'] + 1, time.time()
            self.conn.execute('UPDATE library_documents SET title=?,content=?,digest=?,modified_at=?,indexed_at=? WHERE id=?', (title, content, digest, now, now, document_id))
            self.conn.execute('UPDATE library_managed_documents SET revision=? WHERE document_id=?', (revision, document_id))
            self.conn.execute('INSERT INTO library_document_versions VALUES(?,?,?,?,?,?)', (document_id, revision, title, content, digest, now))
            committed = self.managed_document(document_id)
        return committed

    def archive_document(self, document_id: str, *, archived: bool, expected_revision: int, write_deadline: float | None = None) -> dict:
        deadline = _write_time() + DOCUMENT_WRITE_WINDOW_SECONDS if write_deadline is None else write_deadline
        if type(archived) is not bool:
            raise ValueError('archived must be boolean')
        with self._write_window(deadline):
            row = self.managed_document(document_id)
            if type(expected_revision) is not int or row['revision'] != expected_revision:
                raise DocumentConflict('Document changed; reload before archiving/restoring')
            if bool(row['archived']) != archived:
                revision = row['revision'] + 1
                self.conn.execute('UPDATE library_managed_documents SET archived=?,revision=? WHERE document_id=?', (archived, revision, document_id))
                self.conn.execute('INSERT INTO library_document_versions VALUES(?,?,?,?,?,?)', (document_id, revision, row['title'], row['content'], row['digest'], time.time()))
            committed = self.managed_document(document_id)
        return committed

    def document_versions(self, document_id: str) -> list[dict]:
        self.managed_document(document_id)
        return [dict(row) for row in self.conn.execute('SELECT revision,title,digest,created_at FROM library_document_versions WHERE document_id=? ORDER BY revision DESC', (document_id,))]

    def restore_document_version(self, document_id: str, *, revision: int, expected_revision: int, write_deadline: float | None = None) -> dict:
        deadline = _write_time() + DOCUMENT_WRITE_WINDOW_SECONDS if write_deadline is None else write_deadline
        if type(revision) is not int or revision < 1:
            raise ValueError('Version must be a positive integer')
        row = self.conn.execute('SELECT title,content FROM library_document_versions WHERE document_id=? AND revision=?', (document_id, revision)).fetchone()
        if row is None:
            raise KeyError('Document version not found')
        return self.save_document(document_id, title=row['title'], content=row['content'], expected_revision=expected_revision, write_deadline=deadline)
