"""Private external SQLite state; no bearer tokens or signing keys in rows."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path).absolute()
        # Refuse source-tree runtime state, including worktree paths.
        if any(
            (parent / "pyproject.toml").exists() and (parent / "jaeger_ai").is_dir()
            for parent in self.path.parents
        ):
            raise ValueError("Events state must be outside the source tree")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("State symlinks forbidden")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS subscriptions (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, url TEXT NOT NULL,
              arguments TEXT NOT NULL, expires REAL NOT NULL, verified REAL NOT NULL,
              created REAL NOT NULL, auth_until REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS revoked (owner TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS deliveries (
              subscription TEXT NOT NULL, event TEXT NOT NULL, thread TEXT NOT NULL,
              body BLOB NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              due REAL NOT NULL, created REAL NOT NULL,
              PRIMARY KEY(subscription,event));
            CREATE TABLE IF NOT EXISTS audit (
              seq INTEGER PRIMARY KEY, action TEXT NOT NULL, outcome TEXT NOT NULL,
              subscription TEXT, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS watermark (singleton INTEGER PRIMARY KEY, at REAL NOT NULL, page INTEGER NOT NULL);
            """)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def audit(self, action, outcome, now, subscription=None):
        # Only code-owned categories and hashed handles; never callback URLs,
        # OAuth claims, exception strings, headers, signing keys or message text.
        with self.conn() as c:
            c.execute(
                "INSERT INTO audit(action,outcome,subscription,at) VALUES(?,?,?,?)",
                (action, outcome, subscription, now),
            )

    def admit(self, now):
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            count = c.execute(
                "SELECT count(*) FROM audit WHERE action='request' AND outcome='authenticated' AND at>?",
                (now - 60,),
            ).fetchone()[0]
            if count >= 60:
                return False
            c.execute(
                "INSERT INTO audit(action,outcome,at) VALUES('request','authenticated',?)",
                (now,),
            )
            return True

    def revoked(self, owner):
        with self.conn() as c:
            return (
                c.execute("SELECT 1 FROM revoked WHERE owner=?", (owner,)).fetchone()
                is not None
            )

    def revoke(self, owner):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO revoked VALUES(?)", (owner,))
            c.execute(
                "DELETE FROM deliveries WHERE subscription IN (SELECT id FROM subscriptions WHERE owner=?)",
                (owner,),
            )
            c.execute("DELETE FROM subscriptions WHERE owner=?", (owner,))
