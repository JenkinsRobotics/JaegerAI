"""Authenticated inbox data. No message is an execution instruction."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time

from jaeger_ai.core.gateway.caller_auth import CALLERS
from jaeger_ai.core.redaction import redact_value

KEY = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
KINDS = frozenset({"task", "status", "result", "question", "answer"})


class BridgeError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def enabled():
    if os.environ.get("JAEGER_AGENT_BRIDGE", "1") == "0":
        raise BridgeError("Agent bridge disabled", 503)


def key(value):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise BridgeError("Invalid identifier")
    return value


def migrate(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_threads (
            thread TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_goals (
            caller TEXT NOT NULL, id TEXT NOT NULL, thread TEXT NOT NULL,
            session TEXT NOT NULL, request_id TEXT NOT NULL, digest TEXT NOT NULL,
            PRIMARY KEY(caller,id));
        CREATE TABLE IF NOT EXISTS agent_messages (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL,
            thread TEXT NOT NULL REFERENCES agent_threads(thread),
            sender TEXT NOT NULL, recipient TEXT NOT NULL,
            digest TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL,
            UNIQUE(sender, id));
        CREATE INDEX IF NOT EXISTS agent_messages_thread ON agent_messages(thread, seq);
        CREATE INDEX IF NOT EXISTS agent_messages_recipient ON agent_messages(recipient, seq);
        CREATE TABLE IF NOT EXISTS agent_bridge_audit (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, caller TEXT NOT NULL,
            action TEXT NOT NULL, outcome INTEGER NOT NULL, created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS agent_bridge_rate ON agent_bridge_audit(caller, created_at);
    """)


class AgentMessages:
    def __init__(self, store):
        self.store = store

    def gate(self, caller, action):
        enabled()
        if caller not in CALLERS:
            raise BridgeError("Unknown caller", 403)
        now = time.time()
        with self.store._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute(
                "SELECT count(*) FROM agent_bridge_audit WHERE caller=? AND created_at>?",
                (caller, now - 60),
            ).fetchone()[0]
            limited = count >= 60
            conn.execute(
                "INSERT INTO agent_bridge_audit(caller,action,outcome,created_at) VALUES(?,?,?,?)",
                (caller, action, 429 if limited else 200, now),
            )
        if limited:
            raise BridgeError("Client rate limit exceeded", 429)

    def audit_failure(self, caller, action, status):
        with self.store._get_conn() as conn:
            conn.execute(
                "INSERT INTO agent_bridge_audit(caller,action,outcome,created_at) VALUES(?,?,?,?)",
                (caller, action, status, time.time()),
            )

    @staticmethod
    def access(conn, caller, thread):
        row = conn.execute(
            "SELECT * FROM agent_threads WHERE thread=?", (key(thread),)
        ).fetchone()
        if row is None or caller not in (row["sender"], row["recipient"]):
            raise BridgeError("Thread unavailable", 404)
        return row

    def send(self, caller, data, *, correlation=None):
        if not isinstance(data, dict) or set(data) - {
            "id",
            "thread",
            "to",
            "kind",
            "title",
            "body",
            "refs",
            "status_line",
            "reply_to",
        }:
            raise BridgeError("Unknown fields (sender and timestamp are server owned)")
        for field in ("id", "thread"):
            key(data.get(field))
        if "reply_to" in data:
            key(data["reply_to"])
        recipient = data.get("to")
        if recipient not in CALLERS or recipient == caller:
            raise BridgeError("Invalid recipient")
        if data.get("kind") not in KINDS:
            raise BridgeError("Invalid message kind")
        for field, maximum in (("title", 256), ("body", 16384), ("status_line", 512)):
            value = data.get(field, "")
            if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
                raise BridgeError("Invalid message text")
        refs = data.get("refs", [])
        if (
            not isinstance(refs, list)
            or len(refs) > 16
            or any(
                not isinstance(ref, str) or len(ref.encode("utf-8")) > 512
                for ref in refs
            )
        ):
            raise BridgeError("Invalid references")
        safe = {
            **data,
            **redact_value(
                {
                    "title": data.get("title", ""),
                    "body": data.get("body", ""),
                    "refs": refs,
                    "status_line": data.get("status_line", ""),
                }
            ),
        }
        if correlation is not None:
            safe["correlation"] = correlation
        digest = hashlib.sha256(
            json.dumps(
                {**data, "refs": refs, "status_line": data.get("status_line", ""),
                 **({"correlation": correlation} if correlation is not None else {})},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with self.store._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT * FROM agent_messages WHERE sender=? AND id=?",
                (caller, data["id"]),
            ).fetchone()
            if prior:
                if prior["digest"] != digest:
                    raise BridgeError("Delivery id reused with different content", 409)
                return json.loads(prior["payload"])
            thread = conn.execute(
                "SELECT * FROM agent_threads WHERE thread=?", (data["thread"],)
            ).fetchone()
            if thread:
                if {thread["sender"], thread["recipient"]} != {caller, recipient}:
                    raise BridgeError("Thread unavailable", 404)
            else:
                conn.execute(
                    "INSERT INTO agent_threads VALUES(?,?,?)",
                    (data["thread"], caller, recipient),
                )
            if "reply_to" in data and conn.execute(
                "SELECT 1 FROM agent_messages WHERE thread=? AND sender=? AND id=?",
                (data["thread"], recipient, data["reply_to"]),
            ).fetchone() is None:
                raise BridgeError("Reply target unavailable", 404)
            safe.update({"from": caller, "created_at": time.time()})
            conn.execute(
                "INSERT INTO agent_messages(id,thread,sender,recipient,digest,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    safe["id"],
                    safe["thread"],
                    caller,
                    recipient,
                    digest,
                    json.dumps(safe),
                    safe["created_at"],
                ),
            )
            from .outbox import OutboxPayloadError, enqueue

            try:
                enqueue(conn, safe)
            except OutboxPayloadError:
                # Context-manager rollback includes the thread/message rows.
                raise BridgeError("Webhook message exceeds 16 KiB", 413) from None
            return safe

    def list(self, caller, *, thread=None, after=0, limit=50):
        if (
            type(after) is not int
            or after < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise BridgeError("Pagination requires after >= 0 and limit 1..100")
        with self.store._get_conn() as conn:
            if thread:
                self.access(conn, caller, thread)
            rows = conn.execute(
                "SELECT seq,payload FROM agent_messages WHERE (sender=? OR recipient=?) AND seq>? "
                + ("AND thread=? " if thread else "")
                + "ORDER BY seq LIMIT ?",
                (caller, caller, after, *((thread,) if thread else ()), limit + 1),
            ).fetchall()
        return {
            "messages": [json.loads(row["payload"]) for row in rows[:limit]],
            "next_after": rows[limit - 1]["seq"] if len(rows) > limit else None,
        }
