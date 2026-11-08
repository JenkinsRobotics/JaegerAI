"""Private external SQLite state; no bearer tokens or signing keys in rows."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        supplied = Path(path).expanduser().absolute()
        if supplied.is_symlink():
            raise ValueError("State symlinks forbidden")
        # Resolve parent aliases before enforcing the source boundary. A path
        # outside the checkout can otherwise point back into it via a symlink.
        self.path = supplied.resolve()
        # Refuse source-tree runtime state, including worktree paths.
        if any(
            (parent / "pyproject.toml").exists() and (parent / "jaeger_ai").is_dir()
            for parent in self.path.parents
        ):
            raise ValueError("Events state must be outside the source tree")
        from jaeger_ai.core.gateway.session_store import default_store_path
        if self.path == default_store_path(create=False).resolve():
            raise ValueError("Events require a dedicated database, not the Gateway store")
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
            CREATE TABLE IF NOT EXISTS secret_cleanup (account TEXT PRIMARY KEY, owner TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS logout_receipts (receipt TEXT PRIMARY KEY, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS event_budget (
              subscription TEXT NOT NULL, event TEXT NOT NULL, thread TEXT NOT NULL, at REAL NOT NULL,
              PRIMARY KEY(subscription,event));
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
            c.execute(
                "INSERT OR IGNORE INTO event_budget SELECT subscription,event,thread,created FROM deliveries WHERE state!='limited' AND created>=strftime('%s','now')-172800"
            )
            columns = {r[1] for r in c.execute("PRAGMA table_info(subscriptions)")}
            if "generation" not in columns:
                import secrets

                c.execute(
                    "ALTER TABLE subscriptions ADD COLUMN generation TEXT NOT NULL DEFAULT ''"
                )
                for row in c.execute("SELECT id FROM subscriptions").fetchall():
                    c.execute(
                        "UPDATE subscriptions SET generation=? WHERE id=?",
                        (secrets.token_hex(16), row[0]),
                    )

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
            c.execute("BEGIN IMMEDIATE")
            c.execute("INSERT OR IGNORE INTO revoked VALUES(?)", (owner,))
            c.execute(
                "INSERT OR IGNORE INTO secret_cleanup SELECT id,owner FROM subscriptions WHERE owner=?",
                (owner,),
            )
            c.execute(
                "DELETE FROM deliveries WHERE subscription IN (SELECT id FROM subscriptions WHERE owner=?)",
                (owner,),
            )
            c.execute("DELETE FROM subscriptions WHERE owner=?", (owner,))

    def cleanup_accounts(self, owner=None):
        with self.conn() as c:
            query = "SELECT account FROM secret_cleanup" + (
                " WHERE owner=?" if owner is not None else ""
            )
            return [
                r[0] for r in c.execute(query, (owner,) if owner is not None else ())
            ]

    def cleaned(self, account):
        with self.conn() as c:
            c.execute("DELETE FROM secret_cleanup WHERE account=?", (account,))

    def record_logout(self, receipt, now):
        with self.conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO logout_receipts VALUES(?,?)", (receipt, now)
            )

    def prune(self, now):
        """Retain dedup tombstones until expiry; budgets outlive unsubscribe."""
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            expired = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM subscriptions WHERE expires<=? OR auth_until<=?",
                    (now, now),
                )
            ]
            c.execute(
                "INSERT OR IGNORE INTO secret_cleanup SELECT id,owner FROM subscriptions WHERE expires<=? OR auth_until<=?",
                (now, now),
            )
            c.execute(
                "DELETE FROM subscriptions WHERE expires<=? OR auth_until<=?",
                (now, now),
            )
            c.execute(
                "DELETE FROM deliveries WHERE subscription NOT IN (SELECT id FROM subscriptions)"
            )
            c.execute("UPDATE deliveries SET body=x'' WHERE state!='pending'")
            c.execute("DELETE FROM event_budget WHERE at<?", (now - 172800,))
            c.execute("DELETE FROM audit WHERE at<?", (now - 604800,))
            c.execute("DELETE FROM logout_receipts WHERE at<?", (now - 604800,))
            return expired
