"""Approvals inbox + notifications + Web Push (APPROVALS-NOTIFICATIONS-SPEC). Temp dirs only."""
import base64
import json
import os
import stat
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import approvals_inbox as ai
from jaeger_ai.core.gateway import push_routes, webpush
from jaeger_ai.core.gateway.caller_auth import client_headers, required_scope
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

PT = ZoneInfo("America/Los_Angeles")


@pytest.fixture(autouse=True)
def secrets(tmp_path, monkeypatch):
    d = tmp_path / "secrets"
    monkeypatch.setenv("JAEGER_SECRETS_DIR", str(d))
    return d


def gw(tmp_path):
    g = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    g.store.ensure_session("s1", metadata={"agent_id": "forge"})
    return g


def mk(g, aid, *, kind="owner_review", options=("once", "deny"), **meta):
    return g.store.create_approval(kind=kind, prompt=f"prompt {aid}", options=list(options), session_id="s1",
                                   approval_id=aid, metadata=meta)


def events(g, name):
    with g.store._immediate() as conn:
        rows = conn.execute("SELECT data_json FROM events WHERE event=? ORDER BY event_id", (name,)).fetchall()
    return [json.loads(r[0]) for r in rows]


# ── item model ───────────────────────────────────────────────────────
def test_projection_type_risk_expiry_payload():
    base = {"approval_id": "a", "kind": "tool_confirm", "prompt": "x", "options": ["once", "deny"], "status": "pending",
            "created_at": 1.0}
    spend = ai.project({**base, "metadata": {"type": "spend", "expires_at": 99.0, "on_expire": "escalate",
                                             "payload": {"amount": 60, "currency": "USD", "month_to_date": 50, "limit": 100,
                                                         "secret_extra": "dropped"}}})
    assert spend["type"] == "spend" and spend["risk"] == "critical" and "Over monthly limit" in spend["risk_reasons"]
    assert spend["payload"] == {"amount": 60, "currency": "USD", "month_to_date": 50, "limit": 100}
    assert spend["expires_at"] == 99.0 and spend["on_expire"] == "escalate" and spend["requires_step_up"]
    assert "changes" in spend["options"] and not spend["batchable"]
    # bot may raise but not lower; policy_risk wins outright
    assert ai.project({**base, "metadata": {"type": "send", "risk": "low"}})["risk"] == "high"
    assert ai.project({**base, "metadata": {"type": "design_review", "risk": "medium"}})["risk"] == "medium"
    assert ai.project({**base, "metadata": {"type": "send", "policy_risk": "low"}})["risk"] == "low"
    dep = ai.project({**base, "metadata": {"type": "code_change", "batch_group": "deps"}})
    assert dep["risk"] == "medium" and dep["batchable"]
    assert ai.project({**base, "kind": "handoff", "metadata": {}})["type"] == "permission"
    assert ai.project({**base, "metadata": {}})["on_expire"] == "deny"


@pytest.mark.asyncio
async def test_list_filters_counts_and_legacy_route(tmp_path):
    g = gw(tmp_path)
    now = time.time()
    mk(g, "low1", type="design_review", expires_at=now + 7200, agent_id="forge")
    mk(g, "hi1", type="send", expires_at=now + 600)
    mk(g, "legacy")
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        items = (await (await c.get("/v1/approvals?sort=expiry")).json())["approvals"]
        assert [i["approval_id"] for i in items][:2] == ["hi1", "low1"]
        assert {"type", "risk", "risk_reasons", "expires_at", "on_expire", "payload", "revision", "batchable"} <= set(items[0])
        assert [i["approval_id"] for i in (await (await c.get("/v1/approvals?risk=high")).json())["approvals"]] == ["hi1"]
        assert [i["approval_id"] for i in (await (await c.get("/v1/approvals?agent_id=forge")).json())["approvals"]] == ["low1"]
        cnt = await (await c.get("/v1/approvals/counts")).json()
        assert cnt["pending"] == 3 and cnt["by_risk"]["high"] == 1 and cnt["expiring_within_1h"] == 1
        # the pre-existing route still resolves through the shared core
        r = await c.post("/v1/approvals/legacy", json={"decision": "once"})
        assert r.status == 200 and (await r.json())["decision"] == "once"
        assert (await c.post("/v1/approvals/legacy", json={"decision": "once"})).status == 409
        n = await (await c.get("/v1/notifications")).json()
        assert n["pending_approvals"] == 2 and n["badge"] >= 2 and "unread_count" in n


# ── decisions ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_deny_requires_reason_and_audit_trail(tmp_path):
    g = gw(tmp_path)
    mk(g, "a1", type="code_change")
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        r = await c.post("/v1/approvals/a1/decide", json={"decision": "deny"})
        assert r.status == 400 and (await r.json())["code"] == "reason_required"
        assert (await c.post("/v1/approvals/a1/decide", json={"decision": "deny", "reason": "no"})).status == 400
        assert (await c.post("/v1/approvals/a1/viewed", json={"device": "iPhone"})).status == 200
        r = await c.post("/v1/approvals/a1/decide", json={"decision": "deny", "reason": "Wrong branch", "device": "Mac"})
        body = await r.json()
        assert r.status == 200 and body["decision"] == "deny" and body["approval"]["reason"] == "Wrong branch"
        assert body["approval"]["decided_by_device"] == "Mac"
        again = await c.post("/v1/approvals/a1/decide", json={"decision": "approve"})
        assert again.status == 409 and (await again.json())["code"] == "already_resolved"
        ev = (await (await c.get("/v1/approvals/a1/events")).json())["events"]
        assert [e["event"] for e in ev] == ["created", "viewed", "decided"]
        assert ev[2]["reason"] == "Wrong branch" and ev[2]["device"] == "Mac"
        csv_r = await c.get("/v1/approvals/a1/events?format=csv")
        assert csv_r.content_type == "text/csv" and "Wrong branch" in await csv_r.text()
        assert (await c.post("/v1/approvals/nope/decide", json={"decision": "approve"})).status == 404
    assert events(g, "approval.resolved")[-1]["reason"] == "Wrong branch"


@pytest.mark.asyncio
async def test_approve_scope_stale_revision_and_changes(tmp_path):
    g = gw(tmp_path)
    mk(g, "a1", options=("once", "always", "deny"), revision=3)
    mk(g, "a2", type="design_review", task_id="T1", agent_id="pixel", title="Hero art")
    mk(g, "a3", options=("allow", "deny"))
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        r = await c.post("/v1/approvals/a1/decide", json={"decision": "approve", "expected_revision": 2})
        assert r.status == 409 and (await r.json())["code"] == "stale"
        assert (await c.post("/v1/approvals/a1/decide", json={"decision": "approve", "scope": "session"})).status == 400
        r = await c.post("/v1/approvals/a1/decide", json={"decision": "approve", "scope": "always", "expected_revision": 3})
        assert (await r.json())["decision"] == "always"
        r = await c.post("/v1/approvals/a3/decide", json={"decision": "approve"})
        assert (await r.json())["decision"] == "allow"
        r = await c.post("/v1/approvals/a2/decide", json={"decision": "changes", "reason_chips": ["Contrast"], "reason": "too dark"})
        out = await r.json()
        assert r.status == 200 and out["decision"] == "changes" and out["approved"] is False
    ch = events(g, "approval.changes_requested")[-1]
    assert ch["reason"] == "Contrast; too dark" and ch["task_id"] == "T1" and "Hero art" in ch["message"]
    assert g.store.get_approval("a2")["metadata"]["changes_requested"] == "Contrast; too dark"


@pytest.mark.asyncio
async def test_batch_approves_low_only(tmp_path):
    g = gw(tmp_path)
    mk(g, "low", type="design_review")
    mk(g, "med_grp", type="code_change", batch_group="deps")
    mk(g, "med", type="code_change")
    mk(g, "high", type="send")
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        r = await c.post("/v1/approvals/batch", json={"ids": ["low", "med_grp", "med", "high", "missing"], "decision": "approve"})
        out = await r.json()
        res = {x["approval_id"]: x for x in out["results"]}
        assert res["low"]["ok"] and res["med_grp"]["ok"]
        assert res["med"]["code"] == "not_batchable" and res["high"]["code"] == "not_batchable"
        assert "high" in res["high"]["error"] and res["missing"]["status"] == 404
        assert out["approved"] == 2 and out["rejected"] == 3
        assert g.store.get_approval("high")["status"] == "pending"
        r = await c.post("/v1/approvals/batch", json={"ids": ["med", "high"], "decision": "deny"})
        assert all(not x["ok"] and x["code"] == "reason_required" for x in (await r.json())["results"])
        r = await c.post("/v1/approvals/batch", json={"ids": ["med", "high"], "decision": "deny", "reason": "not now"})
        assert (await r.json())["denied"] == 2
        assert (await c.post("/v1/approvals/batch", json={"ids": [], "decision": "approve"})).status == 400


def test_expiry_on_expire_policies(tmp_path):
    g = gw(tmp_path)
    past = time.time() - 5
    mk(g, "deny_me", expires_at=past)
    mk(g, "esc", type="design_review", expires_at=past, on_expire="escalate")
    mk(g, "keep", expires_at=past, on_expire="keep")
    swept = ai.sweep_expired(g)
    assert set(swept) == {"deny_me", "esc"}
    assert g.store.get_approval("deny_me")["decision"] == "expired"
    assert [e["event"] for e in ai.audit_events(g.store, "deny_me")] == ["created", "expired"]
    esc = ai.project(g.store.get_approval("esc"))
    assert esc["status"] == "pending" and esc["risk"] == "high" and "Escalated after expiry" in esc["risk_reasons"]
    assert ai.sweep_expired(g) == []  # escalate is recorded once
    assert g.store.get_approval("keep")["status"] == "pending"
    with pytest.raises(ai.DecisionError) as exc:
        ai.decide(g, "esc", {"decision": "approve"})
    assert exc.value.status == 409 and exc.value.code == "expired"


@pytest.mark.asyncio
async def test_scopes_owner_only(tmp_path):
    for route in ("/v1/approvals/{id}/decide", "/v1/approvals/batch", "/v1/approvals/{id}/viewed"):
        assert required_scope("POST", route) == "approve"
    assert required_scope("POST", "/v1/push/subscriptions") == "admin"
    g = gw(tmp_path)
    mk(g, "a1")
    async with TestClient(TestServer(g.app), headers=client_headers("a2a")) as c:
        assert (await c.post("/v1/approvals/a1/decide", json={"decision": "approve"})).status == 403
        assert (await c.get("/v1/approvals/a1/events")).status == 403
        assert (await c.get("/v1/push/subscriptions")).status == 403
    assert g.store.get_approval("a1")["status"] == "pending"


# ── notification settings ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_notification_categories_quiet_hours_preview(tmp_path):
    g = gw(tmp_path)
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        prefs = (await (await c.get("/v1/notifications")).json())["preferences"]
        assert prefs["quiet_hours"] == {"enabled": True, "start": "22:00", "end": "07:30", "tz": "America/Los_Angeles",
                                        "allow": ["critical", "expiring"]}
        assert prefs["preview"] == "title_only" and prefs["categories"]["bot_finished"]["push"] is False
        r = await c.patch("/v1/notifications", json={"expected_revision": 0, "categories": {"code_merged": {"push": True}},
                                                     "quiet_hours": {"start": "23:00"}, "preview": "hidden"})
        p = (await r.json())["preferences"]
        assert r.status == 200 and p["revision"] == 1 and p["categories"]["code_merged"]["push"] is True
        assert p["quiet_hours"]["start"] == "23:00" and p["quiet_hours"]["end"] == "07:30" and p["preview"] == "hidden"
        for bad in ({"quiet_hours": {"tz": "Mars/Base"}}, {"quiet_hours": {"start": "25:00"}}, {"preview": "loud"},
                    {"categories": {"nope": {"push": True}}}, {"categories": {"code_merged": {"push": "yes"}}}):
            assert (await c.patch("/v1/notifications", json={"expected_revision": 1, **bad})).status == 400
        # legacy body shape is still accepted
        assert (await c.patch("/v1/notifications", json={"expected_revision": 1, "enabled": True, "muted_agent_ids": []})).status == 200


# ── web push ─────────────────────────────────────────────────────────
def _device():
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    return key, auth, {"p256dh": webpush.b64u(webpush._raw_pub(key.public_key())), "auth": webpush.b64u(auth)}


def _decrypt(body, ua_key, auth):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    salt, idlen = body[:16], body[20]
    as_raw = body[21:21 + idlen]
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_raw))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + webpush._raw_pub(ua_key.public_key()) + as_raw).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    pt = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    return json.loads(pt[:-1])


@pytest.mark.asyncio
async def test_subscriptions_vapid_0600_and_test_push(tmp_path, secrets):
    g = gw(tmp_path)
    key, auth, keys = _device()
    sent = []
    g.push_dispatcher.poster = lambda url, data, headers: sent.append((url, data, headers)) or 201
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        assert not secrets.exists()  # nothing is created until used
        pub = (await (await c.get("/v1/push/vapid-public-key")).json())["public_key"]
        assert len(base64.urlsafe_b64decode(pub + "==")) == 65
        vapid = secrets / "vapid.json"
        assert stat.S_IMODE(vapid.stat().st_mode) == 0o600 and stat.S_IMODE(secrets.stat().st_mode) == 0o700
        assert (await c.post("/v1/push/subscriptions", json={"endpoint": "https://evil.example/x", "keys": keys})).status == 400
        assert (await c.post("/v1/push/subscriptions", json={"endpoint": "https://web.push.apple.com/abc", "keys": {}})).status == 400
        r = await c.post("/v1/push/subscriptions", json={"endpoint": "https://web.push.apple.com/abc", "keys": keys,
                                                          "device_label": "iPhone", "platform": "ios", "standalone": True})
        sub = (await r.json())["subscription"]
        assert r.status == 201 and sub["push_service"] == "web.push.apple.com" and "keys" not in sub and "endpoint" not in sub
        assert stat.S_IMODE((secrets / "push_subscriptions.json").stat().st_mode) == 0o600
        listed = await (await c.get("/v1/push/subscriptions")).json()
        assert "abc" not in json.dumps(listed) and keys["auth"] not in json.dumps(listed)
        out = await (await c.post("/v1/push/test", json={})).json()
        assert out["delivered"] == 1
        url, data, headers = sent[-1]
        assert headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith("vapid t=")
        assert _decrypt(data, key, auth)["title"] == "Jaeger test notification"
        pem = json.loads(vapid.read_text())["private_key_pem"]
        assert pem not in json.dumps(out) and pem not in json.dumps(listed)
        assert (await c.delete(f"/v1/push/subscriptions/{sub['id']}")).status == 200
        assert (await c.delete(f"/v1/push/subscriptions/{sub['id']}")).status == 404


def _setup_push(tmp_path, clock):
    g = gw(tmp_path)
    key, auth, keys = _device()
    webpush.add_subscription({"endpoint": "https://web.push.apple.com/d1", "keys": keys})
    sent = []
    d = g.push_dispatcher
    d.poster = lambda url, data, headers: sent.append(_decrypt(data, key, auth)) or 201
    d.clock = clock
    return g, d, sent


def _at(h, m, day=2):
    return datetime(2026, 11, day, h, m, tzinfo=PT).timestamp()


def test_push_policy_batching_privacy_and_resolved(tmp_path):
    now = [_at(12, 0)]
    g, d, sent = _setup_push(tmp_path, lambda: now[0])
    mk(g, "low1", type="design_review", title="SECRET TITLE")  # design_reviews → immediate
    mk(g, "r1", type="tool_confirm")   # low tool_confirm → routine, batched
    mk(g, "r2", type="tool_confirm")
    mk(g, "crit", type="spend", payload={"amount": 500, "limit": 100})
    for aid in ("low1", "r1", "r2", "crit"):
        g.event_bus.publish("s1", "approval.request", {"approval_id": aid})
        g.event_bus.publish("*", "approval.request", {"approval_id": aid})  # parent stream duplicate
    d.tick()
    titles = [p["title"] for p in sent]
    assert titles == ["Approval needed · Low", "Approval needed · Critical"]
    assert all("SECRET" not in json.dumps(p) and p["privacy"] == "title_only" and p["body"] == "" for p in sent)
    assert sent[1]["url"] == "/work/approvals/crit?src=push" and sent[1]["badge"] == 4
    now[0] += 31 * 60
    d.tick()
    assert sent[-1]["title"] == "2 low-risk approvals"
    assert [e["event"] for e in ai.audit_events(g.store, "crit")] == ["created", "pushed"]
    ai.decide(g, "crit", {"decision": "deny", "reason": "too much"})
    d.tick()
    assert sent[-1]["title"] == "Resolved" and sent[-1]["tag"] == "crit" and sent[-1]["silent"] is True


def test_quiet_hours_hold_critical_expiring_and_morning_summary(tmp_path):
    now = [_at(23, 0)]
    g, d, sent = _setup_push(tmp_path, lambda: now[0])
    mk(g, "q1", type="design_review")
    mk(g, "crit", type="spend", payload={"amount": 500, "limit": 100})
    mk(g, "exp", type="design_review", expires_at=_at(3, 0, day=3))
    for aid in ("q1", "crit", "exp"):
        g.event_bus.publish("s1", "approval.request", {"approval_id": aid})
    g.event_bus.publish("s1", "task.updated", {"task": {"task_id": "T9", "state": "failed", "title": "Build"}})
    d.tick()
    assert [p["id"] for p in sent] == ["crit"]
    assert d.status()["held"] == 2 and d.status()["scheduled"] == 1
    now[0] = _at(2, 31, day=3)
    d.tick()
    assert sent[-1]["id"] == "exp"
    now[0] = _at(7, 31, day=3)
    d.tick()
    assert sent[-1]["title"] == "While quiet hours were on" and sent[-1]["body"] == "1 approval waiting · 1 update"
    assert d.status()["held"] == 0


def test_quiet_window_crosses_midnight():
    q = {"enabled": True, "start": "22:00", "end": "07:30", "tz": "America/Los_Angeles"}
    assert push_routes.quiet_window(q, _at(23, 0))
    assert push_routes.quiet_window(q, _at(6, 0))
    assert push_routes.quiet_window(q, _at(12, 0)) is None
    assert push_routes.quiet_window({**q, "enabled": False}, _at(23, 0)) is None


def test_init_vapid_command_prints_public_only(secrets, capsys):
    assert webpush.main(["init-vapid"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"public_key", "stored_in"} and "PRIVATE" not in json.dumps(out)
    assert stat.S_IMODE((secrets / "vapid.json").stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_job_events_ingest_pushes_stuck(tmp_path):
    g, d, sent = _setup_push(tmp_path, lambda: _at(12, 0))
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        assert (await c.post("/v1/push/job-events", json={"task_id": "T1", "state": "weird"})).status == 400
        assert (await c.post("/v1/push/job-events", json={"task_id": "T1", "state": "stuck", "title": "Crawl"})).status == 202
        assert (await c.post("/v1/push/job-events", json={"task_id": "T2", "state": "done"})).status == 202
    d.tick()
    assert [p["title"] for p in sent] == ["Task needs attention"]  # bot_finished is in-app only by default


@pytest.mark.asyncio
async def test_step_up_items_refused_for_api_approve_but_deny_works(tmp_path):
    g = gw(tmp_path)
    mk(g, "pay", type="spend", payload={"amount": 5, "limit": 100})
    mk(g, "perm", type="permission", payload={"duration": "always"})
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        items = {i["approval_id"]: i for i in (await (await c.get("/v1/approvals")).json())["approvals"]}
        assert items["pay"]["approve_on_mac"] and items["perm"]["approve_on_mac"]
        r = await c.post("/v1/approvals/pay/decide", json={"decision": "approve"})
        assert r.status == 403 and (await r.json())["code"] == "step_up_required"
        assert g.store.get_approval("pay")["status"] == "pending"
        assert (await c.post("/v1/approvals/pay/decide", json={"decision": "deny", "reason": "not this month"})).status == 200
        assert (await c.post("/v1/approvals/perm/decide", json={"decision": "changes", "reason": "one hour only"})).status == 200


def test_changes_reason_is_posted_to_agent_session(tmp_path):
    g = gw(tmp_path)
    mk(g, "d1", type="design_review", title="Hero art")
    ai.decide(g, "d1", {"decision": "changes", "reason": "contrast too low"})
    last = g.store.get_session("s1")["messages"][-1]
    assert last["role"] == "user" and "contrast too low" in last["content"] and "Hero art" in last["content"]


@pytest.mark.asyncio
async def test_widget_action_request_creates_projected_approval(tmp_path):
    g = gw(tmp_path)
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        r = await c.post("/v1/approvals/requests", json={"source": "widget", "title": "Cancel task T1", "risk": "low",
                                                         "action": {"widget": "tasks.running", "id": "cancel"}, "host": "page"})
        assert r.status == 201
        aid = (await r.json())["approval"]["approval_id"]
        row = g.store.get_approval(aid)
        assert row["kind"] == "widget_action" and row["status"] == "pending"
        assert events(g, "approval.request")[-1]["approval_id"] == aid
        assert (await c.post("/v1/approvals/requests", json={"source": "evil", "title": "x", "risk": "low"})).status == 400
        assert (await c.post("/v1/approvals/requests", json={"source": "widget", "title": "x", "risk": "bogus"})).status == 400
        r = await c.post(f"/v1/approvals/{aid}/decide", json={"decision": "approve"})
        assert r.status == 200 and g.store.get_approval(aid)["status"] == "resolved"
