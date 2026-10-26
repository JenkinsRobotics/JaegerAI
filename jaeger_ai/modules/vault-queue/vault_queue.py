import json
import sqlite3
import time
import uuid


class VaultQueue:
    def __init__(self, db_path, max_retries=3):
        self.db_path = db_path
        self.max_retries = max_retries
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    task_type TEXT,
                    payload TEXT,
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status_priority "
                "ON jobs (status, priority DESC, created_at)"
            )

    def enqueue(self, task_type, payload, priority=0):
        job_id = str(uuid.uuid4())
        now = time.time()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO jobs (id, task_type, payload, priority, status,
                                  retry_count, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', 0, NULL, ?, ?)
                """,
                (job_id, task_type, json.dumps(payload), priority, now, now),
            )
        return job_id

    def dequeue(self):
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute(
                """
                SELECT id, task_type, payload, priority, retry_count
                FROM jobs
                WHERE status = 'pending'
                ORDER BY priority DESC, created_at ASC, rowid ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                self.conn.execute("COMMIT")
                return None
            self.conn.execute(
                """
                UPDATE jobs
                SET status = 'running', updated_at = ?
                WHERE id = ?
                """,
                (time.time(), row["id"]),
            )
            self.conn.execute("COMMIT")
        except sqlite3.OperationalError:
            self.conn.rollback()
            return None
        return {
            "id": row["id"],
            "task_type": row["task_type"],
            "payload": json.loads(row["payload"]),
            "priority": row["priority"],
            "retry_count": row["retry_count"],
        }

    def complete(self, job_id):
        with self.conn:
            self.conn.execute(
                """
                UPDATE jobs
                SET status = 'completed', updated_at = ?
                WHERE id = ?
                """,
                (time.time(), job_id),
            )

    def fail(self, job_id, error):
        now = time.time()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            row = self.conn.execute(
                "SELECT retry_count FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                self.conn.execute("COMMIT")
                raise ValueError(f"job not found: {job_id}")
            new_count = row["retry_count"] + 1
            status = "pending" if new_count < self.max_retries else "failed"
            self.conn.execute(
                """
                UPDATE jobs
                SET retry_count = ?, status = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_count, status, error, now, job_id),
            )
            self.conn.execute("COMMIT")
            return status
        except sqlite3.OperationalError:
            self.conn.rollback()
            raise


if __name__ == "__main__":
    import os
    for suffix in ("", "-shm", "-wal"):
        try:
            os.remove("test_init.db" + suffix)
        except FileNotFoundError:
            pass
    q = VaultQueue("test_init.db")
    row = q.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()
    mode = q.conn.execute("PRAGMA journal_mode").fetchone()[0]
    print("jobs table exists:", row is not None)
    print("journal_mode:", mode)
