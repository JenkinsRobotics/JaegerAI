"""Durable native-run exclusion; a lost observer cannot authorize replay.

This registry owns admission only. Native agents still own execution and history.
An uncertain owner is deliberately retained until native reconciliation exists.
"""
from contextlib import contextmanager
import json
import fcntl
import os
from pathlib import Path
import re
import sqlite3


class Ownership:
    def __init__(self, root: Path):
        self.path = root / 'ownership.sqlite3'
        if self.path.is_symlink():
            raise RuntimeError('Refusing symlinked native ownership registry')
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS owners (run_id TEXT PRIMARY KEY, session TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS issued (run_id TEXT PRIMARY KEY)')
            db.execute('CREATE INDEX IF NOT EXISTS owners_session ON owners(session)')
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY)')
            if not db.execute("SELECT 1 FROM metadata WHERE key='receipts_imported'").fetchone():
                for path in root.iterdir():
                    if not re.fullmatch(r'[0-9a-f]{32}\.json', path.name):
                        continue
                    # A malformed legacy receipt is not evidence of completion.
                    try:
                        saved = json.loads(path.read_text())
                        session, status = saved['session_id'], saved['status']
                        if not isinstance(session, str) or not session:
                            raise ValueError('invalid session')
                    except (OSError, ValueError, KeyError, TypeError):
                        raise RuntimeError('Native receipt needs inspection before accepting new work') from None
                    uncertain = saved.get('execution_unknown', status not in {'completed', 'cancelled'})
                    if uncertain or status not in {'completed', 'failed', 'cancelled'}:
                        db.execute('INSERT OR IGNORE INTO owners VALUES (?, ?)', (path.stem, session))
                db.execute("INSERT INTO metadata VALUES ('receipts_imported')")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def claim(self, session, run_id):
        with self.transaction() as db:
            # Explicit table-child IDs are single use, even after completion or
            # pre-dispatch rejection. Keep a tombstone when releasing the active
            # owner; a new observer must never overwrite the old control receipt.
            if (db.execute('SELECT 1 FROM issued WHERE run_id=?', (run_id,)).fetchone()
                    or (self.path.parent / f'{run_id}.json').exists()):
                raise RuntimeError('run_identity_used: observe the original receipt or use a new run identity')
            if db.execute('SELECT 1 FROM owners WHERE session=?', (session,)).fetchone():
                raise RuntimeError('session_busy: native work is active or its execution state is unknown; reconcile the native run before retrying')
            db.execute('INSERT INTO owners VALUES (?, ?)', (run_id, session))
            db.execute('INSERT INTO issued VALUES (?)', (run_id,))

    def release(self, run_id):
        """Call only after a native terminal result or proven no dispatch."""
        with self.transaction() as db:
            db.execute('DELETE FROM owners WHERE run_id=?', (run_id,))

    def observer_lease(self, run_id):
        """Exclude recovery while any process still observes/writes this run.

        The kernel releases this lease on process exit. It says nothing about
        native execution: a separate native terminal receipt is still required.
        """
        if not re.fullmatch(r'[0-9a-f]{32}', run_id):
            raise ValueError('Invalid observer identity')
        path = self.path.parent / f'{run_id}.observer'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise RuntimeError('observer_busy: the native run still has a live observer') from None
        except BaseException:
            os.close(fd)
            raise
        return fd
