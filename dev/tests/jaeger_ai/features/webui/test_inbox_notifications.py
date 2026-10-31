"""Approvals inbox + Web Push notifications (inbox_api). Isolated state, fake Gateway/WebUI hooks."""
from __future__ import annotations

import base64
import datetime as dt
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import pytest

API = Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/inbox_api.py"
LA = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def ib(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_inbox_api_test", API)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "state_root", lambda: tmp_path)
    monkeypatch.setenv("JAEGER_NOTIFY_POLLER", "0")
    st = SimpleNamespace(gw=[], local=[], responded=[], gw_answer=None, jobs={"health": "ok", "jobs": []},
                         posts=[], post_status=201, clock=dt.datetime(2026, 10, 31, 12, 0, tzinfo=LA).timestamp())
    m.gateway_approvals = lambda: list(st.gw)
    m.local_approvals = lambda: list(st.local)

    def rg(sid, aid, choice):
        st.responded.append(("gateway", sid, aid, choice))
        return st.gw_answer if st.gw_answer is not None else ({"ok": True, "approval_id": aid, "choice": choice}, 200)
    m.respond_gateway = rg
    m.respond_local = lambda h, sid, aid, choice: st.responded.append(("local", sid, aid, choice)) or h.reply({"ok": True}, 200)
    m.jobs_snapshot = lambda: st.jobs
    m.http_post = lambda url, data, headers: st.posts.append((url, data, headers)) or st.post_status
    m.now = lambda: st.clock
    m._st = st
    return m


class H:
    def __init__(self, body=None):
        self.body, self.out = body or {}, None

    def reply(self, payload, status):
        self.out = (status, payload)


def call(ib, method, path, body=None):
    h = H(body)
    parsed = urlparse(path)
    ib.route(h, parsed, method, lambda hh: hh.body, lambda hh, payload, status=200: hh.reply(payload, status))
    return h.out


GW_CHILD = {"approval_id": "approval_c1", "session_id": "child-1", "kind": "tool_confirm", "prompt": "Run shell?",
            "created_at": 200.0, "status": "pending", "metadata": {"tool": "shell", "target": "rm x"},
            "origin": {"parent_session_id": "chat-1", "agent_id": "specialist:coder", "child_session_id": "child-1"}}
GW_JOB = {"approval_id": "approval_j1", "session_id": "task-s", "kind": "tool_confirm", "prompt": "Send email?",
          "created_at": 300.0, "status": "pending", "metadata": {"tool": "email.send", "task_id": "T1"}}
LOCAL = {"approval_id": "loc-1", "command": "git push", "description": "Push to origin", "session_id": "chat-2"}


# ── 1. approvals inbox ───────────────────────────────────────────────
def test_inbox_lists_every_source_with_fields(ib):
    ib._st.gw = [GW_CHILD, GW_JOB]
    ib._st.local = [LOCAL, {**LOCAL, "approval_id": "approval_c1", "_gateway_mirror": True}]  # mirror deduped
    status, out = call(ib, "GET", "/v1/inbox/approvals")
    assert status == 200 and out["count"] == 3 and out["sources_unavailable"] == []
    by = {a["approval_id"]: a for a in out["approvals"]}
    assert by["approval_c1"]["source"] == "child_worker" and by["approval_c1"]["agent"] == "specialist:coder"
    assert by["approval_c1"]["tool"] == "shell" and by["approval_c1"]["parent_session_id"] == "chat-1"
    assert by["approval_j1"]["source"] == "job" and by["approval_j1"]["task_id"] == "T1"
    assert by["loc-1"]["origin"] == "webui" and by["loc-1"]["summary"] == "Push to origin"
    assert [a["approval_id"] for a in out["approvals"]][:2] == ["approval_j1", "approval_c1"]  # newest first
    assert all({"source", "agent", "tool", "summary", "created_at"} <= set(a) for a in out["approvals"])


def test_approve_and_deny_reuse_existing_respond_paths(ib):
    ib._st.gw, ib._st.local = [GW_CHILD], [LOCAL]
    status, out = call(ib, "POST", "/v1/inbox/approvals/approval_c1/approve", {"choice": "session"})
    assert status == 200 and out["ok"] and out["inbox_item"]["source"] == "child_worker"
    status, _ = call(ib, "POST", "/v1/inbox/approvals/loc-1/deny")
    assert status == 200
    assert ib._st.responded == [("gateway", "child-1", "approval_c1", "session"), ("local", "chat-2", "loc-1", "deny")]


def test_stale_or_resolved_is_409(ib):
    status, out = call(ib, "POST", "/v1/inbox/approvals/approval_gone/approve")
    assert status == 409 and out["code"] == "approval_not_pending" and ib._st.responded == []
    # lost race: Gateway refuses and the card is gone on re-check
    ib._st.gw = [GW_CHILD]
    ib._st.gw_answer = ({"ok": False, "code": "gateway_approval_relay_failed"}, 502)
    orig = ib.respond_gateway

    def resolve_then_vanish(*a):
        ib._st.gw = []
        return orig(*a)
    ib.respond_gateway = resolve_then_vanish
    status, out = call(ib, "POST", "/v1/inbox/approvals/approval_c1/approve")
    assert status == 409 and out["code"] == "approval_not_pending"


def test_bad_choice_and_unavailable_sources(ib):
    ib._st.gw = [GW_CHILD]
    assert call(ib, "POST", "/v1/inbox/approvals/approval_c1/approve", {"choice": "deny"})[0] == 400

    def boom():
        raise OSError("down")
    ib.gateway_approvals = boom
    status, out = call(ib, "POST", "/v1/inbox/approvals/approval_c1/approve")
    assert status == 503 and out["code"] == "approvals_unavailable"


# ── 2. notifications ─────────────────────────────────────────────────
def _browser_sub():
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return key, auth, {"endpoint": "https://web.push.apple.com/QAbc123", "keys": {
        "p256dh": b64(ib_raw(key.public_key())), "auth": b64(auth)}}


def ib_raw(pub):
    from cryptography.hazmat.primitives import serialization
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _decrypt(body, ua_key, auth):
    """RFC 8291 receiver side, to prove the payload is standard aes128gcm."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    salt, idlen = body[:16], body[20]
    as_raw = body[21:21 + idlen]
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_raw))
    ikm = HKDF(hashes.SHA256(), 32, auth, b"WebPush: info\x00" + ib_raw(ua_key.public_key()) + as_raw).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    pt = AESGCM(cek).decrypt(nonce, body[21 + idlen:], None)
    assert pt.endswith(b"\x02")
    return json.loads(pt[:-1])


def test_vapid_key_is_private_0600_and_never_returned(ib, tmp_path):
    status, out = call(ib, "GET", "/v1/notifications/vapid-public-key")
    assert status == 200 and len(base64.urlsafe_b64decode(out["public_key"] + "==")) == 65
    f = tmp_path / "notifications" / "vapid.json"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    pem = json.loads(f.read_text())["private_key_pem"]
    assert "PRIVATE KEY" in pem and pem not in json.dumps(out)
    assert call(ib, "GET", "/v1/notifications/vapid-public-key")[1] == out   # stable


def test_subscribe_unsubscribe_and_validation(ib, tmp_path):
    _, _, sub = _browser_sub()
    status, out = call(ib, "POST", "/v1/notifications/subscribe", {"subscription": sub, "label": "iPhone"})
    assert status == 201 and out["push_service"] == "web.push.apple.com" and "endpoint" not in out
    assert stat.S_IMODE((tmp_path / "notifications" / "subscriptions.json").stat().st_mode) == 0o600
    assert len(call(ib, "GET", "/v1/notifications/subscriptions")[1]["subscriptions"]) == 1
    assert call(ib, "POST", "/v1/notifications/subscribe", {"subscription": {**sub, "endpoint": "http://evil.test/x"}})[0] == 400
    assert call(ib, "POST", "/v1/notifications/subscribe", {"subscription": {**sub, "keys": {"p256dh": "x", "auth": "y"}}})[0] == 400
    assert call(ib, "POST", "/v1/notifications/unsubscribe", {"endpoint": sub["endpoint"]})[1] == {"removed": 1}


def test_push_is_standard_webpush_and_decrypts(ib):
    key, auth, sub = _browser_sub()
    call(ib, "POST", "/v1/notifications/subscribe", {"subscription": sub})
    call(ib, "PUT", "/v1/notifications/settings", {"deliver_push": True, "quiet_hours": {"enabled": False}})
    ib._st.gw = [GW_JOB]
    out = call(ib, "POST", "/v1/notifications/poll")[1]
    assert [e["kind"] for e in out["events"]] == ["approval_needed"]
    url, body, headers = ib._st.posts[0]
    assert url == sub["endpoint"] and headers["Content-Encoding"] == "aes128gcm" and headers["Urgency"] == "high"
    assert headers["Authorization"].startswith("vapid t=") and ", k=" in headers["Authorization"]
    msg = _decrypt(body, key, base64.urlsafe_b64decode(sub["keys"]["auth"] + "=="))
    assert msg["kind"] == "approval_needed" and "Send email" in msg["body"]
    # JWT verifies with the published VAPID key, audience is the push origin
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    tok = headers["Authorization"].split("t=")[1].split(",")[0]
    h, c, s = tok.split(".")
    raw = base64.urlsafe_b64decode(s + "==")
    pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), base64.urlsafe_b64decode(call(ib, "GET", "/v1/notifications/vapid-public-key")[1]["public_key"] + "=="))
    pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
               f"{h}.{c}".encode(), ec.ECDSA(hashes.SHA256()))
    assert json.loads(base64.urlsafe_b64decode(c + "=="))["aud"] == "https://web.push.apple.com"
    # second poll: no duplicate event for the same approval
    assert call(ib, "POST", "/v1/notifications/poll")[1]["events"] == []


def test_gone_subscription_is_dropped(ib):
    _, _, sub = _browser_sub()
    call(ib, "POST", "/v1/notifications/subscribe", {"subscription": sub})
    call(ib, "PUT", "/v1/notifications/settings", {"deliver_push": True, "quiet_hours": {"enabled": False}})
    ib._st.post_status = 410
    ib._st.gw = [GW_JOB]
    ev = call(ib, "POST", "/v1/notifications/poll")[1]["events"][0]
    assert ev["delivery"]["dropped"] == 1 and ib.subscriptions() == []


def test_quiet_hours_la_and_approval_bypass(ib):
    _, _, sub = _browser_sub()
    call(ib, "POST", "/v1/notifications/subscribe", {"subscription": sub})
    call(ib, "PUT", "/v1/notifications/settings", {"deliver_push": True, "quiet_hours": {"enabled": True, "start": "22:00", "end": "07:00"}})
    ib._st.clock = dt.datetime(2026, 10, 31, 23, 30, tzinfo=LA).timestamp()    # 23:30 PT, inside window
    assert call(ib, "GET", "/v1/notifications/settings")[1]["quiet_now"] is True
    ib._st.gw = [GW_JOB]
    ib._st.jobs = {"health": "ok", "jobs": [{"task_id": "T9", "state": "running", "stuck": True, "last_progress_s": 4000}]}
    evs = {e["kind"]: e for e in call(ib, "POST", "/v1/notifications/poll")[1]["events"]}
    assert evs["approval_needed"]["delivery"]["push"] == "sent"          # bypasses quiet hours
    assert evs["job_stuck"]["delivery"] == {"push": "suppressed_quiet_hours"}
    call(ib, "PUT", "/v1/notifications/settings", {"approvals_bypass_quiet": False})
    ib._st.gw = [{**GW_JOB, "approval_id": "approval_j2"}]
    ev = call(ib, "POST", "/v1/notifications/poll")[1]["events"][0]
    assert ev["delivery"] == {"push": "suppressed_quiet_hours"}
    ib._st.clock = dt.datetime(2026, 11, 1, 7, 0, tzinfo=LA).timestamp()
    assert ib.in_quiet_hours(ib.settings()) is False
    assert call(ib, "PUT", "/v1/notifications/settings", {"quiet_hours": {"start": "25:00"}})[0] == 400
    assert call(ib, "PUT", "/v1/notifications/settings", {"timezone": "Mars/Base"})[0] == 400


def test_job_finished_stuck_runner_down_and_feed(ib):
    st = ib._st
    st.jobs = {"health": "ok", "jobs": [{"task_id": "T1", "title": "Playlist", "state": "running", "stuck": False}]}
    assert call(ib, "POST", "/v1/notifications/poll")[1]["events"] == []
    st.clock += 10
    st.jobs = {"health": "ok", "jobs": [{"task_id": "T1", "title": "Playlist", "state": "running", "stuck": True, "last_progress_s": 3700}]}
    assert [e["kind"] for e in call(ib, "POST", "/v1/notifications/poll")[1]["events"]] == ["job_stuck"]
    assert call(ib, "POST", "/v1/notifications/poll")[1]["events"] == []           # once per stuck episode
    st.clock += 10
    st.jobs = {"health": "down", "heartbeat_age_s": 900,
               "jobs": [{"task_id": "T1", "title": "Playlist", "state": "done", "stuck": False, "videos_done": 40}]}
    kinds = sorted(e["kind"] for e in call(ib, "POST", "/v1/notifications/poll")[1]["events"])
    assert kinds == ["job_finished", "job_stuck"]                                  # finished + runner down
    feed = call(ib, "GET", "/v1/notifications/feed?limit=2")[1]
    assert len(feed["items"]) == 2 and feed["items"][0]["created_at"] >= feed["items"][1]["created_at"]
    assert all(e["delivery"] == {"push": "disabled"} for e in feed["items"])        # delivery off by default
    assert call(ib, "GET", f"/v1/notifications/feed?since={st.clock}")[1]["items"] == []
    assert call(ib, "GET", "/v1/notifications/feed?since=x")[0] == 400


def test_event_toggle_off(ib):
    call(ib, "PUT", "/v1/notifications/settings", {"events": {"approval_needed": False}})
    ib._st.gw = [GW_JOB]
    assert call(ib, "POST", "/v1/notifications/poll")[1]["events"] == []
