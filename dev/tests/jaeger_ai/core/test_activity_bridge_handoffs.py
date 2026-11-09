"""Inbox handoffs between apps (handoff_task to a peer, post_result back) appear in
GET /v1/activity as handoff.sent / handoff.result; grokbot may read the feed."""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None):
        def deco(fn):
            self.tools[name or fn.__name__] = fn
            return fn
        return deco


@pytest_asyncio.fixture
async def hub(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_MCP_TOKEN_FILE", raising=False)
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    tokens = tmp_path / "tokens"
    tokens.mkdir(mode=0o700)
    for name in ("grokbot", "ares", "webui"):  # throwaway 0600 tokens in a temp dir, never the Keychain
        (tokens / f"{name}.token").write_text(f"test-{name}-token-{tmp_path.name}")
        (tokens / f"{name}.token").chmod(0o600)
    monkeypatch.setenv("JAEGER_CALLER_TOKEN_DIR", str(tokens))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "sessions.sqlite3"))
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app)) as client:
        loop = asyncio.get_running_loop()

        def app_client(name):
            class C:
                def _call(self, method, path, body=None):
                    async def go():
                        r = await client.request(method, path, json=body, headers=caller_auth.client_headers(name))
                        assert r.status < 400, (path, r.status, await r.text())
                        return await r.json()
                    return asyncio.run_coroutine_threadsafe(go(), loop).result(10)
            return C()

        from jaeger_ai.features.agent_bridge import mcp as bridge_mcp
        tools = {}
        for name in ("grokbot", "ares"):
            fake = _FakeMCP()
            bridge_mcp.register(fake, lambda ctx, n=name: app_client(n))
            tools[name] = fake.tools
        yield client, gateway, tools


async def _activity(client, who="webui", **q):
    r = await client.get("/v1/activity", params=q, headers=caller_auth.client_headers(who))
    assert r.status == 200, await r.text()
    return (await r.json())["items"]


@pytest.mark.asyncio
async def test_handoff_sent_and_result_rows(hub):
    client, gateway, tools = hub
    out = await tools["grokbot"]["handoff_task"](to="ares", task="build the thing", title="Build", thread="t-ga", id="h-ga")
    assert out["kind"] == "message"
    await tools["ares"]["post_result"](to="grokbot", thread="t-ga", body="built", title="Built")
    # idempotent redelivery of the same handoff adds no second row
    await tools["grokbot"]["handoff_task"](to="ares", task="build the thing", title="Build", thread="t-ga", id="h-ga")

    items = [i for i in await _activity(client) if i["kind"].startswith("handoff.")]
    by_kind = {i["kind"]: i for i in items}
    assert len(items) == 2 and set(by_kind) == {"handoff.sent", "handoff.result"}
    sent, res = by_kind["handoff.sent"], by_kind["handoff.result"]
    assert sent["data"]["caller"] == {"caller_id": "grokbot", "caller_kind": "mcp"}
    assert sent["data"]["recipient"] == "ares" and sent["data"]["handoff_id"] == "h-ga"
    assert sent["data"]["status"] == "handoff" and sent["actor_id"] == "grokbot" and sent["agent_id"] == "ares"
    assert sent["summary"] == "grokbot handed off h-ga to ares: Build"
    assert res["data"]["caller"]["caller_id"] == "ares" and res["data"]["recipient"] == "grokbot"
    assert res["data"]["handoff_id"] == "h-ga" and res["data"]["status"] == "done"
    assert res["refs"]["handoff_id"] == "h-ga" and res["refs"]["thread"] == "t-ga"
    assert res["session_id"] == "*"
    # event_id is the global "*" stream id
    with gateway.store._immediate() as conn:
        ev = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT event_id, event, session_id FROM events")}
    assert ev[sent["event_id"]] == ("handoff.sent", "*") and ev[res["event_id"]] == ("handoff.result", "*")
    # filter by app
    assert {i["kind"] for i in await _activity(client, agent_id="ares") if i["kind"].startswith("handoff.")} == {
        "handoff.sent", "handoff.result"}
    # handoff_task(to="jaeger") stays a goal row only (no duplicate handoff.sent for jaegerd)
    await tools["grokbot"]["send_message"](id="m-j", thread="t-j", to="jaegerd", kind="task", title="x", body="y")
    assert not [i for i in await _activity(client) if i["kind"] == "handoff.sent" and i["data"]["recipient"] == "jaegerd"]
    print("ROW handoff.sent", json.dumps(sent, indent=1))
    print("ROW handoff.result", json.dumps(res, indent=1))


@pytest.mark.asyncio
async def test_grokbot_reads_activity_read_only(hub):
    client, gateway, tools = hub
    h = caller_auth.client_headers("grokbot")
    saved = caller_auth.CALLER_READ_ROUTES
    caller_auth.CALLER_READ_ROUTES = {}  # before this change
    try:
        assert (await client.get("/v1/activity", headers=h)).status == 403
    finally:
        caller_auth.CALLER_READ_ROUTES = saved
    assert (await client.get("/v1/activity", headers=h)).status == 200
    # only grokbot, only GET /v1/activity
    assert (await client.get("/v1/activity", headers=caller_auth.client_headers("ares"))).status == 403
    assert (await client.get("/v1/approvals", headers=h)).status == 403
    assert (await client.post("/v1/handoffs/x/check", json={"state": "passed"}, headers=h)).status == 403
    assert caller_auth.prefixed_route_allowed("GET", "/v1/activity", "grokbot")
    assert not caller_auth.prefixed_route_allowed("GET", "/v1/activity")
    assert not caller_auth.prefixed_route_allowed("POST", "/v1/activity", "grokbot")


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["done", "failed", "timeout", "error"])
async def test_ares_execution_outcome_reaches_activity(hub, tmp_path, monkeypatch, outcome):
    """Actual job/tick/MCP/HTTP/store/activity chain; only execution is synthetic."""
    from types import SimpleNamespace
    from jaeger_ai.features.agent_bridge import ares_worker as worker
    client, gateway, tools = hub
    await tools["grokbot"]["handoff_task"](
        to="ares", task="synthetic task", thread="outcome-thread", id="outcome-task")
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(worker, "WORKSPACE", tmp_path / "work")
    monkeypatch.setattr(worker, "WORKER_DIR", tmp_path / "work" / ".worker")
    monkeypatch.setattr(worker, "_token", lambda: "synthetic-unused-token")
    monkeypatch.setattr(worker, "device_ok", lambda: [])
    executions = []

    def execute(cmd, **kwargs):
        executions.append(cmd)
        if outcome == "timeout":
            raise worker.subprocess.TimeoutExpired(cmd, 1)
        if outcome == "error":
            raise OSError("synthetic execution error")
        return SimpleNamespace(returncode=0 if outcome == "done" else 1)

    def call(tool, args):
        return asyncio.run_coroutine_threadsafe(tools["ares"][tool](**args), loop).result(10)

    monkeypatch.setattr(worker.subprocess, "run", execute)
    monkeypatch.setattr(worker, "call", call)
    state = worker.State(tmp_path / "worker-state.json")
    assert await asyncio.to_thread(worker.tick, state) == 1
    assert await asyncio.to_thread(worker.tick, worker.State(state.path)) == 0
    assert len(executions) == 1  # unsuccessful reports never re-run execution
    events = [i for i in await _activity(client) if i["kind"] == "handoff.result"]
    assert len(events) == 1
    data = events[0]["data"]
    assert data["status"] == outcome
    assert data["caller"] == {"caller_id": "ares", "caller_kind": "mcp"}
    assert data["handoff_id"] == "outcome-task" and data["recipient"] == "grokbot"
    assert "check" not in data and "verified" not in data
    mirrored = gateway.backlog_store.by_handoff("outcome-task", "outcome-thread")
    assert mirrored["status"] == ("done" if outcome == "done" else "needs_ok")
    assert mirrored["handoff_result"] == ("done" if outcome == "done" else "failed")
    # Optional cross-language trace uses the actual bridge payload, outside source.
    import os
    from pathlib import Path
    if dest := os.environ.get("JAEGER_AGENT_OUTCOME_EVENTS"):
        with Path(dest).open("a") as stream:
            stream.write(json.dumps({"event": "handoff.result", "payload": data}) + "\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "timeout", "error", "cancelled", "execution_unknown"])
async def test_late_peer_report_cannot_reopen_owner_cancellation(hub, status):
    client, gateway, tools = hub
    store = gateway.store
    store.ensure_session("owner-cancelled")
    store.admit_request("owner-cancelled", "synthetic cancelled work", request_id="owner-request",
                        requested={"caller": "owner:webui", "attachment_ids": []})
    store.complete_request("owner-request", status="cancelled", result={"reason": "owner cancellation"})
    cancelled = store.save_handoff({"id": "cancelled-task", "request_id": "owner-request",
        "from_agent_id": "native:jaeger", "to_agent_id": "native:builder", "session_id": "owner-cancelled",
        "task": "synthetic cancelled work", "status": "cancelled", "result": {},
        "metadata": {"caller_actor": "owner:webui"}})
    requests = store.list_requests()
    await tools["grokbot"]["handoff_task"](to="ares", task="synthetic peer work", thread="late-thread", id="cancelled-task")
    mirrored = gateway.backlog_store.by_handoff("cancelled-task", "late-thread")
    # Backlog has no cancellation state; its existing owner terminal state is done.
    gateway.backlog_store.update(mirrored["id"], status="done")
    await tools["ares"]["post_result"](to="grokbot", thread="late-thread", body="late peer report",
                                       reply_to="cancelled-task", status=status)
    assert store.get_handoff("cancelled-task") == cancelled
    assert store.list_requests() == requests  # no retry admission or status mutation
    assert gateway.backlog_store.get(mirrored["id"])["status"] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["unsupported", "unknown", "timed_out", " ", "done-ish", "completed_unverified", "pending", "execution-unknown"])
async def test_unknown_status_result_backlog_is_unresolved(hub, status):
    client, gateway, tools = hub
    await tools["grokbot"]["handoff_task"](to="ares", task="synthetic", thread="unknown-thread", id="unknown-task")
    before = gateway.store.list_requests()
    await tools["ares"]["send_message"](id="unknown-result", to="grokbot", thread="unknown-thread",
        kind="result", title="Successful prose is not a status", body="Done successfully",
        reply_to="unknown-task", status_line=status)
    mirrored = gateway.backlog_store.by_handoff("unknown-task", "unknown-thread")
    assert mirrored["status"] == "needs_ok" and mirrored["handoff_result"] == "failed"
    assert gateway.store.list_requests() == before
    assert gateway.store.get_handoff("unknown-task") is None
    data = next(i["data"] for i in await _activity(client) if i["kind"] == "handoff.result")
    assert data["status"] == status and "check" not in data


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, 42, [], {}])
async def test_malformed_generic_result_status_cannot_finish_backlog(hub, status):
    client, gateway, tools = hub
    await tools["grokbot"]["handoff_task"](to="ares", task="synthetic", thread="malformed-thread", id="malformed-task")
    response = await client.post("/v1/agent-messages", headers=caller_auth.client_headers("ares"), json={
        "id": "malformed-result", "to": "grokbot", "thread": "malformed-thread", "kind": "result",
        "title": "Result", "body": "Done", "reply_to": "malformed-task", "status_line": status})
    assert response.status == 400
    assert gateway.backlog_store.by_handoff("malformed-task", "malformed-thread")["status"] == "in_progress"
    assert not [i for i in await _activity(client) if i["kind"] == "handoff.result"]
    assert gateway.store.list_requests() == []
