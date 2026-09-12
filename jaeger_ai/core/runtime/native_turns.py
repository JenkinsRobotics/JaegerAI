"""Native bridge-owned admission and terminal receipts for safe reconciliation.

These are execution receipts, not another transcript store or an execution queue.
Only the bridge epoch that accepted a turn can attest its terminal result.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

EPOCH = uuid.uuid4().hex


class NativeTurns:
    def __init__(self, root: Path, *, epoch=EPOCH, max_pending=256, read_only=False):
        self.path = root / 'native-turns.sqlite3'
        self.epoch, self.max_pending = epoch, max_pending
        self.read_only = read_only
        if read_only:
            return
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS turns ('
                       'id TEXT PRIMARY KEY, session TEXT NOT NULL, epoch TEXT NOT NULL, '
                       'status TEXT NOT NULL, reply TEXT, updated REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS session_tool_grants ('
                       'session TEXT PRIMARY KEY, tools TEXT NOT NULL)')

    def bind_tool_grant(self, session, tools):
        """A session's first native grant survives process restart unchanged."""
        self.validate('grant', session)
        if tools is not None and (not isinstance(tools, list) or any(
            not isinstance(name, str) or not name.strip() for name in tools
        )):
            raise ValueError('allowed_tools must be a list of nonempty tool names')
        if session.startswith('specialist:') and tools is None:
            raise ValueError('Specialist sessions require an explicit tool grant')
        encoded = json.dumps(sorted(set(tools)) if tools is not None else None)
        with self.transaction() as db:
            row = db.execute('SELECT tools FROM session_tool_grants WHERE session=?', (session,)).fetchone()
            if row is not None and row['tools'] != encoded:
                raise ValueError('Session tool grant cannot change; create a new child session')
            db.execute('INSERT OR IGNORE INTO session_tool_grants VALUES (?, ?)', (session, encoded))

    @contextmanager
    def transaction(self):
        db = (sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5, isolation_level=None)
              if self.read_only else sqlite3.connect(self.path, timeout=5, isolation_level=None))
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN' if self.read_only else 'BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def validate(turn, session):
        if not isinstance(turn, str) or not re.fullmatch(r'[\w-]{1,128}', turn, re.ASCII):
            raise ValueError('Invalid native turn identity')
        if not isinstance(session, str) or not session or len(session) > 512:
            raise ValueError('Invalid native session identity')

    def accept(self, turn, session):
        self.validate(turn, session)
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM turns WHERE id=?', (turn,)).fetchone():
                raise ValueError('Duplicate native turn identity; query its receipt instead of replaying')
            count = db.execute("SELECT COUNT(*) FROM turns WHERE reply IS NULL").fetchone()[0]
            if count >= self.max_pending:
                raise RuntimeError('Native turn capacity reached; reconcile outstanding turns before dispatch')
            db.execute('INSERT INTO turns VALUES (?, ?, ?, ?, NULL, ?)',
                       (turn, session, self.epoch, 'queued', time.time()))

    def finish(self, turn, session, reply):
        self.validate(turn, session)
        status = ('cancelled' if reply.get('cancelled') or reply.get('halt_reason') == 'interrupted'
                  else 'failed' if reply.get('error') or reply.get('halt_reason') else 'completed')
        encoded = json.dumps(reply)
        with self.transaction() as db:
            changed = db.execute('UPDATE turns SET status=?, reply=?, updated=? '
                                 'WHERE id=? AND session=? AND epoch=? AND reply IS NULL',
                                 (status, encoded, time.time(), turn, session, self.epoch))
            if changed.rowcount != 1:
                raise ValueError('Native receipt owner does not match or is already terminal')

    def get(self, turn, session):
        self.validate(turn, session)
        unknown = {'turn_id': turn, 'session_id': session, 'status': 'unknown', 'execution_unknown': True}
        with self.transaction() as db:
            row = db.execute('SELECT * FROM turns WHERE id=? AND session=?', (turn, session)).fetchone()
        if row is None:
            return unknown
        if row['reply'] is None:
            return {**unknown, 'status': row['status'] if row['epoch'] == self.epoch else 'unknown'}
        reply = json.loads(row['reply'])
        # Older receipts labelled structured halts "completed". Interpret
        # their preserved evidence honestly without rewriting that history.
        status = row['status']
        if status == 'completed' and reply.get('halt_reason'):
            status = 'cancelled' if reply['halt_reason'] == 'interrupted' else 'failed'
        return {'turn_id': turn, 'session_id': session, 'status': status,
                'execution_unknown': bool(reply.get('execution_unknown')), 'reply': reply,
                'observed_at': row['updated'], 'source': 'native_bridge_receipt'}
