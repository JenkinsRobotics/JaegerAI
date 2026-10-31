"""Widgets API (plan step 1) + machine/servers/robots/progress/automations read endpoints. Fakes only."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

API = Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/widgets_api.py"


@pytest.fixture
def wg(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_widgets_api_test", API)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setenv("JAEGER_UNIFIED_STATE", str(tmp_path))
    monkeypatch.delenv("JAEGER_N8N_API_KEY", raising=False)
    st = SimpleNamespace(calls=[], approvals={}, decide_status=200, n=0)

    def gw(method, path, body=None):
        st.calls.append((method, path, body))
        if path == "/v1/approvals/requests":
            st.n += 1; aid = f"approval_w{st.n}"
            st.approvals[aid] = {"approval_id": aid, "status": "pending", "decision": None}
            return 201, {"approval": {"approval_id": aid, **body}}
        if path.endswith("/decide"):
            aid = path.split("/")[3]
            if st.decide_status == 200:
                st.approvals[aid].update(status="resolved", decision="once")
            return st.decide_status, {"error": "step_up_required"} if st.decide_status != 200 else {"decision": "once"}
        if path.startswith("/v1/approvals/") and method == "GET":
            aid = path.split("/")[3]
            return (200, st.approvals[aid]) if aid in st.approvals else (404, {"error": "nf"})
        if path.startswith("/v1/tasks"):
            return 200, {"tasks": [{"task_id": "T1", "state": "running"}, {"task_id": "T2", "state": "done"}], "ok": True}
        return 200, {"ok": True, "path": path}
    m.gateway_call = gw
    m._st = st
    return m


def call(wg, method, path, body=None, handler=object()):
    out = {}
    j = lambda h, payload, status=200: out.update(status=status, body=payload) or True
    assert wg.route(handler, urlparse(path), method, lambda h: body or {}, j)
    return out["status"], out["body"]


def test_definitions_follow_plan_schema(wg):
    s, out = call(wg, "GET", "/v1/widgets")
    ids = [w["id"] for w in out["widgets"]]
    assert {"machine.health", "tasks.running", "approvals.waiting", "agents.presence", "research.youtube",
            "servers.status", "robots.estop", "automations.n8n"} <= set(ids)
    for w in out["widgets"]:
        assert set(w) == {"id", "version", "title", "source", "view", "refresh", "size", "actions", "surfaces"}
        assert w["view"] in ("stat", "list", "chart", "timeline", "status", "control")
        assert all(a["approval_tier"] in ("none", "confirm", "owner", "safety_stop") for a in w["actions"])
    tiers = {(w["id"], a["id"]): a["approval_tier"] for w in out["widgets"] for a in w["actions"]}
    assert [k for k, t in tiers.items() if t == "safety_stop"] == [("robots.estop", "estop")]  # the one exemption
    assert tiers[("robots.estop", "rearm")] == "owner" and tiers[("servers.status", "restart")] == "owner"
    assert tiers[("automations.n8n", "run")] == "confirm"
    s, ctl = call(wg, "GET", "/v1/widgets?surface=control")
    assert {w["id"] for w in ctl["widgets"]} == {"machine.health", "robots.estop"}
    assert call(wg, "GET", "/v1/widgets?surface=tv")[0] == 400


def test_data_resolves_source(wg):
    s, out = call(wg, "GET", "/v1/widgets/tasks.running/data")
    assert out["data"] == {"count": 1, "tasks": [{"task_id": "T1", "state": "running"}]} and out["stale"] is False
    s, out = call(wg, "GET", "/v1/widgets/robots.estop/data")
    assert out["data"]["stub"] is True
    assert call(wg, "GET", "/v1/widgets/nope/data")[0] == 404


def test_confirm_action_creates_audited_auto_decided_approval_then_runs(wg, tmp_path):
    s, out = call(wg, "POST", "/v1/widgets/tasks.running/actions/cancel", {"item": "T1", "host": "widgetkit"})
    assert s == 200 and out["executed"] and out["approval_id"] == "approval_w1"
    seq = [(m, p) for m, p, _ in wg._st.calls]
    assert seq == [("POST", "/v1/approvals/requests"), ("POST", "/v1/approvals/approval_w1/decide"),
                   ("POST", "/v1/tasks/T1/cancel")]
    req = wg._st.calls[0][2]
    assert req["source"] == "widget" and req["risk"] == "low" and req["host"] == "widgetkit"
    log = [json.loads(l) for l in (tmp_path / "audit" / "widget_actions.jsonl").read_text().splitlines()]
    assert log[-1]["event"] == "executed" and log[-1]["approval_id"] == "approval_w1"
    assert call(wg, "POST", "/v1/widgets/tasks.running/actions/cancel", {})[0] == 400  # item required
    assert call(wg, "POST", "/v1/widgets/tasks.running/actions/cancel", {"item": "../x"})[0] == 400


def test_confirm_refused_by_inbox_does_not_run(wg):
    wg._st.decide_status = 403
    s, out = call(wg, "POST", "/v1/widgets/tasks.running/actions/cancel", {"item": "T1"})
    assert s == 403 and not out["executed"]
    assert not any(p.endswith("/cancel") for _, p, _ in wg._st.calls)


def test_owner_action_waits_for_approval_and_runs_once(wg):
    s, out = call(wg, "POST", "/v1/widgets/tasks.running/actions/approve", {"item": "T1"})
    assert s == 202 and out["status"] == "awaiting_approval" and out["open"] == "/work/approvals/approval_w1"
    assert not any(p == "/v1/tasks/T1/approve" for _, p, _ in wg._st.calls)
    assert wg.settle() == []  # still pending
    wg._st.approvals["approval_w1"].update(status="resolved", decision="once")
    done = wg.settle()
    assert done[0]["event"] == "executed" and any(p == "/v1/tasks/T1/approve" for _, p, _ in wg._st.calls)
    assert wg.settle() == []  # never twice
    call(wg, "POST", "/v1/widgets/tasks.running/actions/approve", {"item": "T2"})
    wg._st.approvals["approval_w2"].update(status="resolved", decision="deny")
    assert wg.settle()[0]["event"] == "not_run"
    assert not any(p == "/v1/tasks/T2/approve" for _, p, _ in wg._st.calls)


def test_estop_is_the_one_exemption_and_audited(wg, tmp_path):
    s, out = call(wg, "POST", "/v1/widgets/robots.estop/actions/estop", {"item": "arm1", "host": "control_center"})
    assert s == 200 and out["executed"] and out["tier"] == "safety_stop"
    assert not any(p.startswith("/v1/approvals") for _, p, _ in wg._st.calls)
    s, direct = call(wg, "POST", "/v1/robots/arm1/estop", {"host": "page"})
    assert direct["estopped"] is True and direct["delivered"] is False
    events = [json.loads(l)["event"] for l in (tmp_path / "audit" / "widget_actions.jsonl").read_text().splitlines()]
    assert events.count("estop") == 1 and events.count("estop_request") == 2
    s, out = call(wg, "POST", "/v1/widgets/robots.estop/actions/rearm", {"item": "arm1"})
    assert s == 202  # re-arm is not exempt


def test_n8n_is_loopback_only_and_key_never_returned(wg, monkeypatch):
    monkeypatch.setattr(wg, "n8n_key", lambda: None)
    monkeypatch.setattr(wg, "_probe_http", lambda url, timeout=1.5: {"up": False, "status": None, "latency_ms": None})
    s, out = call(wg, "GET", "/v1/automations/n8n/status")
    assert out == {"connected": False, "running": False, "url": "http://127.0.0.1:5678", "api_key": "missing", "pinned_version": "2.14.2"}
    s, out = call(wg, "GET", "/v1/automations/n8n/workflows")
    assert s == 503 and out["code"] == "n8n_no_key"
    monkeypatch.setenv("N8N_URL", "http://n8n.example.com:5678")
    assert call(wg, "GET", "/v1/automations/n8n/status")[0] == 400
    monkeypatch.delenv("N8N_URL")
    monkeypatch.setattr(wg, "n8n_key", lambda: "SECRET-KEY")
    monkeypatch.setattr(wg, "n8n_request", lambda m, p, b=None: (200, {"data": [
        {"id": "w1", "name": "Spend alert", "active": True, "nodes": [{"type": "n8n-nodes-base.webhook", "name": "Hook"}]}]}))
    s, out = call(wg, "GET", "/v1/automations/n8n/workflows")
    assert out["workflows"][0]["can_run"] and "SECRET" not in json.dumps(out)
    # mutations are not directly reachable from HTTP; only via the confirm action
    assert call(wg, "POST", "/v1/automations/n8n/workflows/w1/activate")[0] == 403


def test_read_endpoints_are_read_only(wg, tmp_path, monkeypatch):
    monkeypatch.setattr(wg, "_probe_http", lambda url, timeout=1.5: {"up": True, "status": 200, "latency_ms": 1})
    s, out = call(wg, "GET", "/v1/machine/servers")
    assert {x["id"] for x in out["servers"]} >= {"gateway", "ollama", "comfyui", "n8n", "webui"}
    assert all(urlparse(x["url"]).hostname in ("127.0.0.1", "localhost") for x in out["servers"])
    assert call(wg, "GET", "/v1/robots")[1]["robots"] == []
    assert call(wg, "GET", "/v1/automations/cron")[0] == 200
    assert not list(tmp_path.iterdir())  # no GET wrote anything
