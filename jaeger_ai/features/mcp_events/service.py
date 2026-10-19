"""Subscription lifecycle and bounded durable summary delivery. Single worker."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime

from .security import MAX_BYTES, PublicHTTPS, callback_url, secret_bytes, signed_headers


def encoded(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


class CallbackError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("Callback verification failed")


class Events:
    def __init__(
        self,
        store,
        secrets_store,
        gateway,
        *,
        transport=None,
        clock=time.time,
        per_thread=6,
        per_subscription=20,
        daily=100,
        max_subscriptions=32,
    ):
        self.store, self.secrets, self.gateway = store, secrets_store, gateway
        self.transport, self.clock = transport or PublicHTTPS(), clock
        self.per_thread, self.per_subscription, self.daily = (
            per_thread,
            per_subscription,
            daily,
        )
        self.max_subscriptions = max_subscriptions
        self.lock = asyncio.Lock()
        # Successful challenge cache is bounded and intentionally not persistent.
        self.verified = {}

    def authorize(self, principal):
        if self.store.revoked(principal.subject) or principal.expires <= self.clock():
            raise PermissionError("Account disconnected or expired")

    @staticmethod
    def identity(owner, params):
        if not isinstance(params, dict) or set(params) - {
            "name",
            "arguments",
            "delivery",
            "cursor",
            "ttlMs",
        }:
            raise ValueError("Invalid subscription fields")
        args, delivery = params.get("arguments", {}), params.get("delivery")
        if (
            params.get("name") != "message.created"
            or not isinstance(args, dict)
            or set(args) - {"recipient", "thread"}
            or args.get("recipient") != "ares"
            or not isinstance(delivery, dict)
            or delivery.get("mode") != "webhook"
            or set(delivery) - {"mode", "url", "secret"}
        ):
            raise ValueError("Invalid event or arguments")
        from jaeger_ai.features.agent_bridge.service import key

        if "thread" in args:
            key(args["thread"])
        callback_url(delivery.get("url"))
        if params.get("cursor") is not None:
            raise ValueError("Replay is not supported")
        sid = (
            "sub_"
            + hashlib.sha256(
                encoded([owner, delivery["url"], "message.created", args])
            ).hexdigest()
        )
        return sid, args, delivery

    async def post(self, sid, url, bundle, body, event_id):
        if len(body) > MAX_BYTES:
            raise ValueError("Payload too large")
        now = self.clock()
        headers = signed_headers(bundle["current"], sid, event_id, body, now)
        if bundle.get("previous") and bundle.get("until", 0) > now:
            headers["webhook-signature"] += (
                " "
                + signed_headers(bundle["previous"], sid, event_id, body, now)[
                    "webhook-signature"
                ]
            )
        # Entire injected transport is bounded too. Production independently caps
        # DNS+connect+TLS+response at ten seconds.
        async with asyncio.timeout(10):
            return await self.transport.post(url, body, headers)

    async def subscribe(self, principal, params):
        self.authorize(principal)
        sid, args, delivery = self.identity(principal.subject, params)
        secret = delivery.get("secret")
        secret_bytes(secret)
        ttl = params.get("ttlMs", 3600000)
        if ttl is not None and (type(ttl) is not int or ttl < 0):
            raise ValueError("Invalid ttlMs")
        ttl = max(60000, min(ttl if ttl is not None else 3600000, 86400000)) / 1000
        if "thread" in args:
            await self.gateway.get_thread(args["thread"], 0, 1)
        async with self.lock:
            now = self.clock()
            ttl = min(ttl, principal.expires - now)
            with self.store.conn() as c:
                old = c.execute(
                    "SELECT * FROM subscriptions WHERE id=?", (sid,)
                ).fetchone()
                count = c.execute(
                    "SELECT count(*) FROM subscriptions WHERE expires>?", (now,)
                ).fetchone()[0]
            if old is None and count >= self.max_subscriptions:
                raise ValueError("Subscription limit reached")
            previous = self.secrets.get(sid) if old else None
            bundle = {"current": secret}
            if previous and previous["current"] != secret:
                bundle.update(previous=previous["current"], until=now + 300)
            elif previous:
                bundle = previous
            cache_key = (
                principal.subject,
                delivery["url"],
                hashlib.sha256(secret.encode()).hexdigest(),
            )
            if self.verified.get(cache_key, 0) <= now:
                challenge = secrets.token_urlsafe(32)
                body = encoded({"type": "verification", "challenge": challenge})
                try:
                    status, raw = await self.post(
                        sid,
                        delivery["url"],
                        bundle,
                        body,
                        "verify_" + secrets.token_hex(16),
                    )
                    response = json.loads(raw)
                    echoed = (
                        response.get("challenge")
                        if isinstance(response, dict)
                        else None
                    )
                    if (
                        not 200 <= status < 300
                        or not isinstance(echoed, str)
                        or not hmac.compare_digest(challenge, echoed)
                    ):
                        raise CallbackError("challenge_failed")
                except TimeoutError:
                    raise CallbackError("timeout") from None
                except Exception as exc:
                    if isinstance(exc, CallbackError):
                        raise
                    raise CallbackError("challenge_failed") from None
                self.verified = {k: v for k, v in self.verified.items() if v > now}
                self.verified[cache_key] = now + 300
            self.authorize(principal)
            # Secret adapter failure leaves subscription unactivated.
            self.secrets.put(sid, bundle)
            with self.store.conn() as c:
                c.execute(
                    "INSERT INTO subscriptions VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET expires=excluded.expires, verified=excluded.verified, auth_until=excluded.auth_until",
                    (
                        sid,
                        principal.subject,
                        delivery["url"],
                        encoded(args).decode(),
                        now + ttl,
                        now,
                        old["created"] if old else now,
                        principal.expires,
                    ),
                )
            self.store.audit("subscribe", "verified", now, sid)
            return {
                "id": sid,
                "refreshBefore": iso(now + ttl),
                "cursor": None,
                "truncated": False,
            }

    async def unsubscribe(self, principal, params):
        self.authorize(principal)
        sid, _, _ = self.identity(principal.subject, params)
        async with self.lock:
            with self.store.conn() as c:
                c.execute(
                    "DELETE FROM subscriptions WHERE id=? AND owner=?",
                    (sid, principal.subject),
                )
                c.execute("DELETE FROM deliveries WHERE subscription=?", (sid,))
            self.secrets.delete(sid)
            self.store.audit("unsubscribe", "revoked", self.clock(), sid)
        return {}

    async def disconnect(self, owner):
        # Local operator/IdP revocation integration; never exposed as an MCP tool.
        async with self.lock:
            with self.store.conn() as c:
                ids = [
                    r[0]
                    for r in c.execute(
                        "SELECT id FROM subscriptions WHERE owner=?", (owner,)
                    )
                ]
            self.store.revoke(owner)  # deny first, even when key deletion fails
            for sid in ids:
                self.secrets.delete(sid)
            self.verified.clear()
            self.store.audit("disconnect", "revoked", self.clock())

    async def ingest(self, message):
        if message.get("to") != "ares" or message.get("from") == "ares":
            return
        # Input is already the authenticated Gateway's participant-scoped inbox.
        event_id = (
            "evt_"
            + hashlib.sha256(encoded([message["from"], message["id"]])).hexdigest()
        )
        summary = {
            "id": message["id"],
            "thread": message["thread"],
            "sender": message["from"],
            "title": message.get("title", "")[:256],
            "preview": message.get("body", "")[:240],
        }
        body = encoded(
            {
                "eventId": event_id,
                "name": "message.created",
                "timestamp": iso(message["created_at"]),
                "data": summary,
                "cursor": None,
            }
        )
        if len(body) > MAX_BYTES:
            raise ValueError("Event too large")
        async with self.lock:
            now = self.clock()
            with self.store.conn() as c:
                c.execute("BEGIN IMMEDIATE")
                for sub in c.execute(
                    "SELECT * FROM subscriptions WHERE expires>? AND auth_until>? AND owner NOT IN (SELECT owner FROM revoked)",
                    (now, now),
                ).fetchall():
                    args = json.loads(sub["arguments"])
                    if (
                        sub["created"] > message["created_at"]
                        or args.get("thread", message["thread"]) != message["thread"]
                    ):
                        continue
                    if c.execute(
                        "SELECT 1 FROM deliveries WHERE subscription=? AND event=?",
                        (sub["id"], event_id),
                    ).fetchone():
                        continue
                    day_start = int(now // 86400) * 86400
                    counts = c.execute(
                        "SELECT sum(created>=?),sum(created>? AND subscription=?),sum(created>? AND subscription=? AND thread=?) FROM deliveries WHERE state!='limited'",
                        (
                            day_start,
                            now - 60,
                            sub["id"],
                            now - 60,
                            sub["id"],
                            message["thread"],
                        ),
                    ).fetchone()
                    limited = (
                        (counts[0] or 0) >= self.daily
                        or (counts[1] or 0) >= self.per_subscription
                        or (counts[2] or 0) >= self.per_thread
                    )
                    c.execute(
                        "INSERT INTO deliveries(subscription,event,thread,body,state,due,created) VALUES(?,?,?,?,?,?,?)",
                        (
                            sub["id"],
                            event_id,
                            message["thread"],
                            body if not limited else b"",
                            "limited" if limited else "pending",
                            now,
                            now,
                        ),
                    )
                    c.execute(
                        "INSERT INTO audit(action,outcome,subscription,at) VALUES('enqueue',?,?,?)",
                        ("limited" if limited else "pending", sub["id"], now),
                    )

    async def deliver(self):
        # Serial single-process worker: crash after POST/before ACK can redeliver
        # the same eventId. Receivers must deduplicate, as Standard Webhooks expects.
        async with self.lock:
            now = self.clock()
            with self.store.conn() as c:
                rows = c.execute(
                    "SELECT d.*,s.url,s.owner,s.arguments,s.expires,s.auth_until FROM deliveries d JOIN subscriptions s ON s.id=d.subscription WHERE d.state='pending' AND d.due<=? ORDER BY d.created LIMIT 50",
                    (now,),
                ).fetchall()
            for row in rows:
                now = self.clock()
                sid = row["subscription"]
                state, status = "pending", 0
                attempts = row["attempts"] + 1
                if (
                    row["expires"] <= now
                    or row["auth_until"] <= now
                    or self.store.revoked(row["owner"])
                ):
                    state = "revoked"
                else:
                    try:
                        # Recheck Gateway thread access immediately before every attempt.
                        await self.gateway.get_thread(row["thread"], 0, 1)
                        bundle = self.secrets.get(sid)
                        status, _ = await self.post(
                            sid, row["url"], bundle, row["body"], row["event"]
                        )
                        if 200 <= status < 300:
                            state = "delivered"
                        elif status in (410, 413) or not (
                            status in (408, 429) or status >= 500
                        ):
                            state = "failed"
                    except PermissionError:
                        state = "revoked"
                    except Exception:  # noqa: BLE001 — bounded retries, secret-free audit
                        # No exception text/URLs/secrets in audit. Retrying errors
                        # is bounded; a revoked resource never reaches transport.
                        status = 0
                if attempts >= 5 and state == "pending":
                    state = "failed"
                with self.store.conn() as c:
                    c.execute(
                        "UPDATE deliveries SET attempts=?,state=?,due=? WHERE subscription=? AND event=?",
                        (
                            attempts,
                            state,
                            self.clock() + min(300, 2**attempts),
                            sid,
                            row["event"],
                        ),
                    )
                self.store.audit("deliver", state, self.clock(), sid)
                if status == 410:
                    with self.store.conn() as c:
                        c.execute("DELETE FROM subscriptions WHERE id=?", (sid,))
                        c.execute(
                            "UPDATE deliveries SET state='revoked' WHERE subscription=? AND state='pending'",
                            (sid,),
                        )
                    self.secrets.delete(sid)

    async def poll(self):
        # Poll internal Gateway only, not the ChatGPT Events protocol. No global
        # Gateway DB access and no live provider calls. No replay promised upstream.
        with self.store.conn() as c:
            row = c.execute(
                "SELECT at,page FROM watermark WHERE singleton=1"
            ).fetchone()
            since = row[0] if row else self.clock()
        started = self.clock()
        after = row[1] if row else 0
        checkpoint = after
        while True:
            page = await self.gateway.list_messages(after, 100)
            for message in page["messages"]:
                if message["created_at"] >= since:
                    await self.ingest(message)
            after = page.get("next_after")
            if after is None:
                break
            checkpoint = after
        with self.store.conn() as c:
            c.execute(
                "INSERT INTO watermark VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET at=excluded.at,page=excluded.page",
                (started, checkpoint),
            )
        await self.deliver()
