"""Durable at-least-once webhook delivery; credentials never enter persistent state."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from urllib.parse import urlsplit

import aiohttp

MAX_BODY_BYTES = 16 * 1024
MAX_ATTEMPTS = 5
LEASE_SECONDS = 60
REQUEST_TIMEOUT = 10
KEYCHAIN_SERVICE = "ai.jaeger.bridge.webhook"


class OutboxPayloadError(ValueError):
    pass


def migrate(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_webhook_outbox (
            sender TEXT NOT NULL, message_id TEXT NOT NULL, payload BLOB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL, lease_until REAL, lease_token TEXT,
            created_at REAL NOT NULL, finished_at REAL,
            PRIMARY KEY(sender,message_id));
        CREATE INDEX IF NOT EXISTS agent_webhook_ready
            ON agent_webhook_outbox(status,available_at,lease_until);
    """)


def enqueue(conn, message):
    """Use the message transaction's connection; caller owns commit/rollback."""
    if message["to"] != "grokbot":
        return
    # Explicit wire projection: future internal fields and attachments cannot leak.
    fields = (
        "id",
        "thread",
        "from",
        "to",
        "kind",
        "title",
        "body",
        "refs",
        "status_line",
        "created_at",
    )
    payload = json.dumps(
        {field: message[field] for field in fields if field in message},
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(payload) > MAX_BODY_BYTES:
        raise OutboxPayloadError("Webhook message exceeds 16 KiB")
    conn.execute(
        "INSERT OR IGNORE INTO agent_webhook_outbox(sender,message_id,payload,available_at,created_at) VALUES(?,?,?,?,?)",
        (message["from"], message["id"], payload, time.time(), time.time()),
    )


def validate_url(url, allowed_host):
    """Exact DNS host, verified HTTPS only; reject ambiguous parser spellings."""
    if not isinstance(url, str) or not isinstance(allowed_host, str):
        raise TypeError("Invalid webhook configuration")
    hostname = re.compile(
        r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
    )
    if (
        len(url) > 2048
        or not hostname.fullmatch(allowed_host)
        or any(ord(c) <= 32 or ord(c) == 127 for c in url)
    ):
        raise ValueError("Invalid webhook configuration")
    try:
        ipaddress.ip_address(allowed_host)
    except ValueError:
        pass
    else:
        raise ValueError("Invalid webhook configuration")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == allowed_host
            and parsed.netloc == allowed_host
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and "\\" not in url
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Invalid webhook configuration")
    return url


class KeychainCredentials:
    """Read-only adapter. Provisioning is a separate operator action."""

    def __call__(self):
        values = []
        for account in ("grokbot-url", "grokbot-key"):
            try:
                result = subprocess.run(
                    [
                        "/usr/bin/security",
                        "find-generic-password",
                        "-s",
                        KEYCHAIN_SERVICE,
                        "-a",
                        account,
                        "-w",
                    ],
                    capture_output=True,
                    timeout=3,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            if result.returncode:
                return None
            values.append(result.stdout.decode("utf-8", errors="strict").strip())
        return tuple(values) if all(values) else None


async def https_post(url, key, payload, message_id):
    # No redirects, proxy inheritance, custom TLS context, or exception text logging.
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:  # noqa: SIM117
        async with session.post(
            url,
            data=payload,
            allow_redirects=False,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "Idempotency-Key": message_id,
            },
        ) as response:
            return response.status


class OutboxWorker:
    def __init__(
        self, store, *, allowed_host, credentials=None, transport=None, clock=time.time
    ):
        self.store = store
        self.allowed_host = allowed_host
        self.credentials = (
            credentials if credentials is not None else KeychainCredentials()
        )
        self.transport = transport if transport is not None else https_post
        self.clock = clock

    def _claim(self):
        now = self.clock()
        with self.store._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE agent_webhook_outbox SET status='failed',finished_at=?,lease_token=NULL,lease_until=NULL "
                "WHERE attempts>=? AND (status='pending' OR (status='sending' AND lease_until<=?))",
                (now, MAX_ATTEMPTS, now),
            )
            row = conn.execute(
                "SELECT * FROM agent_webhook_outbox WHERE attempts<? AND "
                "((status='pending' AND available_at<=?) OR (status='sending' AND lease_until<=?)) "
                "ORDER BY created_at LIMIT 1",
                (MAX_ATTEMPTS, now, now),
            ).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            conn.execute(
                "UPDATE agent_webhook_outbox SET status='sending',attempts=attempts+1,lease_until=?,lease_token=? WHERE sender=? AND message_id=?",
                (now + LEASE_SECONDS, token, row["sender"], row["message_id"]),
            )
            return dict(row), token

    async def run_once(self):
        if os.environ.get("JAEGER_AGENT_BRIDGE", "1") == "0" or not self.allowed_host:
            return False
        try:
            validate_url("https://" + self.allowed_host + "/", self.allowed_host)
            pair = await asyncio.to_thread(self.credentials)
            if not pair or len(pair) != 2:
                return False
            url, key = pair
            validate_url(url, self.allowed_host)
            if (
                not isinstance(key, str)
                or not key
                or len(key) > 4096
                or any(ord(c) <= 32 or ord(c) >= 127 for c in key)
            ):
                return False
        except Exception:  # noqa: BLE001 -- adapters must not leak credential-bearing errors
            return False
        if os.environ.get("JAEGER_AGENT_BRIDGE", "1") == "0":
            return False
        claim = self._claim()
        if claim is None:
            return False
        row, token = claim
        status = None
        try:
            if os.environ.get("JAEGER_AGENT_BRIDGE", "1") != "0":
                status = await asyncio.wait_for(
                    self.transport(
                        url,
                        key,
                        bytes(row["payload"]),
                        row["sender"] + ":" + row["message_id"],
                    ),
                    REQUEST_TIMEOUT,
                )
        except asyncio.CancelledError:
            # Lease recovery handles shutdown/crash; do not claim delivery.
            raise
        except Exception:  # noqa: BLE001 -- transport errors may contain URL/key/body
            status = None
        now = self.clock()
        delivered = type(status) is int and 200 <= status < 300
        attempts = row["attempts"] + 1
        state = (
            "delivered"
            if delivered
            else ("failed" if attempts >= MAX_ATTEMPTS else "pending")
        )
        with self.store._get_conn() as conn:
            conn.execute(
                "UPDATE agent_webhook_outbox SET status=?,available_at=?,finished_at=?,lease_until=NULL,lease_token=NULL "
                "WHERE sender=? AND message_id=? AND lease_token=?",
                (
                    state,
                    now + min(300, 2**attempts),
                    now if state != "pending" else None,
                    row["sender"],
                    row["message_id"],
                    token,
                ),
            )
        return True

    async def run(self, stop):
        while not stop.is_set():
            try:
                await self.run_once()
            except sqlite3.Error:
                # Keep durable work queued; never log row data or exception text.
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass


def attach(gateway):
    """Register only task-owned lifecycle hooks; absent host means no credential reads."""

    async def lifecycle(app):
        host = os.environ.get("JAEGER_AGENT_WEBHOOK_HOST", "")
        if not host:
            yield
            return
        stop = asyncio.Event()
        task = asyncio.create_task(
            OutboxWorker(gateway.store, allowed_host=host).run(stop),
            name="agent-webhook-outbox",
        )
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    gateway.app.cleanup_ctx.append(lifecycle)
