"""Roundtable-owned decisions, task intents and native member-run mappings.

Native agents retain conversation history. This store holds only orchestration
state; an interrupted table is never automatically replayed from these records.
"""
from contextlib import contextmanager
import json
import os
import sqlite3
import time


class TableStore:
    def __init__(self, root):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / 'tables.sqlite3'
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tables (session TEXT PRIMARY KEY, preferences TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS chairs (session TEXT PRIMARY KEY, member TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, session TEXT NOT NULL, '
                       'message TEXT NOT NULL, plan TEXT NOT NULL, created REAL NOT NULL, decision TEXT, output TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, '
                       'member TEXT NOT NULL, phase TEXT NOT NULL, session TEXT NOT NULL, '
                       'prompt TEXT NOT NULL, status TEXT NOT NULL, result TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS attempts_turn ON attempts(turn_id)')
            db.execute('CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, '
                       'attempt_id TEXT NOT NULL, receipt TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, turn_id TEXT NOT NULL, '
                       'owner TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL)')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def preferences(self, session):
        with self.transaction() as db:
            row = db.execute('SELECT preferences FROM tables WHERE session=?', (session,)).fetchone()
        return json.loads(row[0]) if row else {}

    def last_chair(self, session):
        with self.transaction() as db:
            row = db.execute('SELECT member FROM chairs WHERE session=?', (session,)).fetchone()
        return row[0] if row else None

    def record_chair(self, session, member):
        with self.transaction() as db:
            db.execute('INSERT INTO chairs VALUES (?, ?) ON CONFLICT(session) DO UPDATE SET member=excluded.member',
                       (session, member))

    def create_turn(self, run, plan, *, persist_preferences=True):
        with self.transaction() as db:
            db.execute('INSERT INTO turns VALUES (?, ?, ?, ?, ?, NULL, NULL)',
                       (run.id, run.session, run.message, json.dumps(plan), time.time()))
            if persist_preferences:
                db.execute('INSERT INTO tables VALUES (?, ?) ON CONFLICT(session) DO UPDATE SET preferences=excluded.preferences',
                           (run.session, json.dumps(plan['preferences'])))

    def turn(self, identity):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM turns WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('Roundtable turn not found')
        value = dict(row)
        value['plan'] = json.loads(value['plan'])
        value['decision'] = json.loads(value['decision']) if value['decision'] else None
        return value

    def attempt(self, identity, turn, member, phase, session, prompt):
        with self.transaction() as db:
            db.execute('INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, NULL)',
                       (identity, turn, member, phase, session, prompt, 'dispatch_intent'))

    def finish_attempt(self, identity, result):
        with self.transaction() as db:
            db.execute('UPDATE attempts SET status=?, result=? WHERE id=?',
                       (result['status'], json.dumps(result), identity))

    def attempts(self, turn):
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM attempts WHERE turn_id=? ORDER BY rowid', (turn,)).fetchall()
        return [{**dict(row), 'result': json.loads(row['result']) if row['result'] else None} for row in rows]

    def add_evidence(self, identity, turn, attempt, receipt):
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO evidence VALUES (?, ?, ?, ?)',
                       (identity, turn, attempt, json.dumps(receipt)))

    def assign(self, identity, turn, owner, description):
        with self.transaction() as db:
            db.execute('INSERT INTO tasks VALUES (?, ?, ?, ?, ?)',
                       (identity, turn, owner or '', description, 'assigned' if owner else 'unassigned'))

    def task_result(self, identity, status):
        # A completed native conversation is not proof a real-world task is done.
        value = 'response_received' if status == 'completed' else status
        with self.transaction() as db:
            db.execute('UPDATE tasks SET status=? WHERE id=?', (value, identity))

    def decision(self, turn, value, output=''):
        with self.transaction() as db:
            db.execute('UPDATE turns SET decision=?, output=? WHERE id=?', (json.dumps(value), output, turn))

    def ledger(self, turn):
        current = self.turn(turn)
        with self.transaction() as db:
            tasks = [dict(row) for row in db.execute('SELECT * FROM tasks WHERE turn_id=?', (turn,))]
            evidence = [json.loads(row[0]) for row in db.execute('SELECT receipt FROM evidence WHERE turn_id=?', (turn,))]
        return {'turn_id': turn, 'session_id': current['session'], 'decision': current['decision'],
                'open_questions': (current['decision'] or {}).get('open_questions', []) +
                    [{'task_id': task['id'], 'reason': 'unassigned'} for task in tasks if task['status'] == 'unassigned'],
                'tasks': tasks, 'evidence': evidence, 'attempts': [
                    {key: attempt[key] for key in ('id', 'member', 'phase', 'session', 'status')}
                    for attempt in self.attempts(turn)]}

    def summary(self, session, limit=4000):
        with self.transaction() as db:
            rows = db.execute('SELECT decision FROM turns WHERE session=? AND decision IS NOT NULL '
                              'ORDER BY created DESC LIMIT 3', (session,)).fetchall()
            tasks = [dict(row) for row in db.execute('SELECT tasks.id, tasks.owner, tasks.description, tasks.status '
                'FROM tasks JOIN turns ON tasks.turn_id=turns.id WHERE turns.session=? ORDER BY turns.created DESC LIMIT 6', (session,))]
        compact = []
        for row in rows:
            decision = json.loads(row[0])
            compact.extend({'id': p['id'], 'owner': p['owner'], 'outcome': p['outcome'],
                            'text': p['text'][:350], 'evidence': 'reported'}
                           for p in decision.get('proposals', []))
        text = json.dumps({'decisions': compact, 'tasks': tasks}, ensure_ascii=False)
        return text if len(text) <= limit else text[:limit] + '\n[Earlier decisions abbreviated.]'
