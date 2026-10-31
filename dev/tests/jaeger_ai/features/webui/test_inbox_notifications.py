"""WebUI side of approvals/notifications: proxy coverage and jobs-runner → Gateway push events."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

API = Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/inbox_api.py"


@pytest.fixture
def ib(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_inbox_api_test", API)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setenv("JAEGER_UNIFIED_STATE", str(tmp_path))
    st = SimpleNamespace(proxied=[], posted=[], jobs={"health": "ok", "jobs": []})
    fake = SimpleNamespace(_proxy=lambda h, method, path, body=None: st.proxied.append((method, path, body)) or True)
    m._sessions = lambda: fake
    m.ensure_poller = lambda: None
    m.jobs_snapshot = lambda: st.jobs
    m.post_job_event = lambda ev: st.posted.append(ev)
    m._st = st
    return m


def call(ib, method, path, body=None):
    return ib.route(object(), urlparse(path), method, lambda h: body, None)


def test_spec_routes_are_proxied_to_gateway(ib):
    assert call(ib, "GET", "/v1/approvals/counts")
    assert call(ib, "GET", "/v1/approvals/approval_9f/events?format=csv")
    assert call(ib, "GET", "/v1/notifications?category=approvals")
    assert call(ib, "PATCH", "/v1/notifications", {"expected_revision": 0, "preview": "hidden"})
    assert call(ib, "GET", "/v1/push/vapid-public-key")
    assert call(ib, "POST", "/v1/push/subscriptions", {"endpoint": "https://web.push.apple.com/x"})
    assert call(ib, "DELETE", "/v1/push/subscriptions/psub_abc")
    assert call(ib, "POST", "/v1/push/test", {})
    assert [p[:2] for p in ib._st.proxied] == [
        ("GET", "/v1/approvals/counts"), ("GET", "/v1/approvals/approval_9f/events?format=csv"),
        ("GET", "/v1/notifications?category=approvals"), ("PATCH", "/v1/notifications"),
        ("GET", "/v1/push/vapid-public-key"), ("POST", "/v1/push/subscriptions"),
        ("DELETE", "/v1/push/subscriptions/psub_abc"), ("POST", "/v1/push/test")]
    assert json.loads(ib._st.proxied[3][2]) == {"expected_revision": 0, "preview": "hidden"}
    # not ours: the generic POST /v1/approvals/<suffix> proxy and unrelated paths
    assert not ib.handles("/v1/approvals/batch") and not ib.handles("/v1/approvals")
    assert not call(ib, "PUT", "/v1/notifications") and not ib.handles("/v1/notifications/../../x")


def test_job_finished_stuck_and_runner_down_forwarded_once(ib):
    st = ib._st
    st.jobs = {"health": "ok", "jobs": [{"task_id": "T1", "state": "running", "title": "Crawl"}]}
    assert ib.poll_once()["events"] == []
    st.jobs = {"health": "ok", "jobs": [{"task_id": "T1", "state": "running", "stuck": True, "last_progress_s": 3700, "title": "Crawl"}]}
    assert ib.poll_once()["events"] == [{"task_id": "T1", "state": "stuck", "title": "Crawl"}]
    assert ib.poll_once()["events"] == []
    st.jobs = {"health": "down", "jobs": [{"task_id": "T1", "state": "done", "title": "Crawl"}]}
    evs = ib.poll_once()["events"]
    assert {"task_id": "runner", "state": "runner_down", "title": "Job runner is not responding"} in evs
    assert {"task_id": "T1", "state": "done", "title": "Crawl"} in evs
    assert ib.poll_once()["events"] == []
    assert len(st.posted) == 3


def test_gateway_failure_is_reported_not_raised(ib):
    def boom(ev):
        raise OSError("refused")
    ib.post_job_event = boom
    ib._st.jobs = {"health": "ok", "jobs": [{"task_id": "T1", "state": "running"}]}
    ib.poll_once()
    ib._st.jobs = {"health": "ok", "jobs": [{"task_id": "T1", "state": "error"}]}
    out = ib.poll_once()
    assert out["events"] == [] and out["errors"] == [{"source": "gateway", "error": "OSError"}]


def _inbox_fixture(ib):
    st = ib._st
    st.gw = [{"approval_id": "g1", "status": "pending", "created_at": 2, "risk": "low", "type": "design_review"}]
    st.local = [{"approval_id": "w1", "session_id": "s", "tool": "read_file", "description": "Read a file", "created_at": 3},
                {"approval_id": "w2", "session_id": "s", "tool": "rm -rf build", "created_at": 1}]
    st.responded = []
    ib.gateway_approvals = lambda: list(st.gw)
    ib.local_approvals = lambda: list(st.local)
    ib.respond_local = lambda h, sid, aid, choice: st.responded.append((aid, choice))
    out = {}
    j = lambda h, payload, status=200: out.update(status=status, body=payload)
    return st, out, j


def test_one_inbox_merges_webui_approvals_with_same_fields(ib):
    st, out, j = _inbox_fixture(ib)
    ib.route(object(), urlparse("/v1/approvals/inbox"), "GET", lambda h: {}, j)
    items = {i["approval_id"]: i for i in out["body"]["approvals"]}
    assert [i["approval_id"] for i in out["body"]["approvals"]] == ["w1", "g1", "w2"]
    assert items["g1"]["backend"] == "gateway" and items["w1"]["backend"] == "webui"
    for k in ("type", "risk", "expires_at", "options", "batchable", "requires_step_up", "approve_on_mac"):
        assert k in items["w1"]
    assert items["w1"]["risk"] == "low" and items["w2"]["risk"] == "high"


def test_decisions_route_to_the_right_backend(ib):
    st, out, j = _inbox_fixture(ib)
    call_ = lambda path, body: ib.route(object(), urlparse(path), "POST", lambda h: body, j)
    call_("/v1/approvals/inbox/w1/decide", {"decision": "deny"})
    assert out["status"] == 400 and out["body"]["code"] == "reason_required"
    call_("/v1/approvals/inbox/w1/decide", {"decision": "approve"})
    assert st.responded == [("w1", "once")]
    call_("/v1/approvals/inbox/g1/decide", {"decision": "approve"})
    assert st.proxied[-1][:2] == ("POST", "/v1/approvals/g1/decide")
    st.responded.clear()
    call_("/v1/approvals/inbox/batch", {"ids": ["w1", "w2"], "decision": "approve"})
    res = {r["approval_id"]: r for r in out["body"]["results"]}
    assert res["w1"]["ok"] and res["w2"]["code"] == "not_batchable"
