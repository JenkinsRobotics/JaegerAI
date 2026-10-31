"""Agents tab gaps G1-G6 (shapes: /workspace/jaeger-agents-tab-api-shapes.md). Temp stores only."""
import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.fixture(autouse=True)
def _secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_SECRETS_DIR", str(tmp_path / "secrets"))


def gw(tmp_path):
    g = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    g.store.ensure_session("chat1", metadata={"agent_id": "native:jaeger"})
    return g


def H(hid, status="running", **kw):
    return {"id": hid, "from_agent_id": "native:jaeger", "to_agent_id": "specialist:coder", "task": "Fix login",
            "status": status, "result": {}, "metadata": {}, **kw}


# ── G1 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_g1_activity_ids_equal_global_stream_ids_and_dedupe(tmp_path):
    g = gw(tmp_path)
    glob = g.event_bus.publish("*", "agent.handoff", {"handoff": H("h1")})
    g.event_bus.publish("chat1", "agent.handoff", {"handoff": H("h1"), "request_id": "r1"})
    # origin copy first, then global: the global id still wins
    g.event_bus.publish("chat1", "agent.handoff.finished", {"handoff": H("h1", "completed"), "request_id": "r1"})
    glob2 = g.event_bus.publish("*", "agent.handoff.finished", {"handoff": H("h1", "completed")})
    g._publish_approval_request("chat1", None, {"approval_id": "ap1", "prompt": "Run rm?"})
    g.store.create_approval(kind="x", prompt="p", options=["once", "deny"], approval_id="ap1", session_id="chat1")
    g.event_bus.publish("*", "project.checked", {"project_id": "p1", "result": {"ok": True}})
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        out = await (await c.get("/v1/activity")).json()
        kinds = [i["kind"] for i in out["items"]]
        assert kinds == ["project.checked", "approval.request", "agent.handoff.finished", "agent.handoff"]
        by = {i["kind"]: i for i in out["items"]}
        assert by["agent.handoff"]["event_id"] == glob.event_id and by["agent.handoff"]["session_id"] == "*"
        assert by["agent.handoff.finished"]["event_id"] == glob2.event_id
        assert by["agent.handoff"]["agent_id"] == "specialist:coder" and by["agent.handoff"]["actor_id"] == "native:jaeger"
        ap = by["approval.request"]
        assert ap["data"]["agent_id"] == "native:jaeger" and ap["agent_id"] == "native:jaeger" and ap["needs_me"]
        assert by["project.checked"]["summary"] == "project p1 check passed" and by["project.checked"]["refs"]["project_id"] == "p1"
        page = await (await c.get("/v1/activity?limit=2")).json()
        assert len(page["items"]) == 2 and page["has_more"] and page["next_before"] == page["items"][-1]["event_id"]
        rest = await (await c.get(f"/v1/activity?limit=5&before={page['next_before']}")).json()
        assert [i["kind"] for i in rest["items"]] == kinds[2:] and not rest["has_more"]
        assert [i["kind"] for i in (await (await c.get("/v1/activity?kind=agent.handoff*")).json())["items"]] == kinds[2:]
        assert [i["approval_id"] if False else i["kind"] for i in (await (await c.get("/v1/activity?needs_me=1")).json())["items"]] == ["approval.request"]
        assert [i["kind"] for i in (await (await c.get("/v1/activity?agent_id=specialist:coder")).json())["items"]] == kinds[2:]
        assert (await c.get("/v1/activity?before=abc")).status == 400
        assert (await c.get("/v1/activity?limit=999")).status == 400
    reopened = GatewaySessionStore(g.store.path)
    assert len(reopened.agent_activity()["items"]) == 4  # durable


def test_g1_backfill_from_existing_events(tmp_path):
    from jaeger_ai.core.gateway import agent_activity
    s = GatewaySessionStore(tmp_path / "g.sqlite3")
    with s._immediate() as conn:
        conn.execute("DROP TABLE IF EXISTS agent_activity")
    agent_activity._ready.clear()
    s.append_event("*", "agent.handoff", {"handoff": H("h9")})
    assert s.agent_activity()["items"][0]["refs"]["handoff_id"] == "h9"


# ── G2 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_g2_check_defaults_route_and_event(tmp_path):
    g = gw(tmp_path)
    s = g.store
    assert s.save_handoff(H("run"))["check"]["state"] == "unchecked"
    assert s.save_handoff(H("bad", "failed"))["check"] == {**s.get_handoff("bad")["check"], "state": "failed",
                                                           "checked_by": "gateway", "evidence_ref": "handoff:bad"}
    assert s.save_handoff(H("done", "completed"))["check"]["state"] == "pending"
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        s.save_handoff(H("run2"))  # after startup recovery, which settles interrupted runs
        assert (await c.post("/v1/handoffs/run2/check", json={"state": "passed"})).status == 409
        assert (await c.post("/v1/handoffs/nope/check", json={"state": "passed"})).status == 404
        assert (await c.post("/v1/handoffs/done/check", json={"state": "maybe"})).status == 400
        assert (await c.post("/v1/handoffs/done/check", json={"state": "passed", "evidence_ref": "ftp:x"})).status == 400
        r = await c.post("/v1/handoffs/done/check", json={"state": "passed", "evidence_ref": "task:T1", "note": "green",
                                                           "expected_state": "pending"})
        body = await r.json()
        assert r.status == 200 and body["check"]["state"] == "passed" and body["check"]["evidence_ref"] == "task:T1"
        assert body["check"]["checked_by"].startswith("owner") and body["check"]["checked_at"]
        stale = await c.post("/v1/handoffs/done/check", json={"state": "failed", "expected_state": "pending"})
        assert stale.status == 409 and (await stale.json())["check"]["state"] == "passed"
        listed = (await (await c.get("/v1/handoffs")).json())["handoffs"]
        assert {h["id"]: h["check"]["state"] for h in listed}["done"] == "passed"
        acts = (await (await c.get("/v1/activity?kind=agent.handoff.checked")).json())["items"]
        assert len(acts) == 1 and acts[0]["data"]["handoff"]["check"]["state"] == "passed"


# ── G3 ───────────────────────────────────────────────────────────────
def _repo(tmp_path):
    import subprocess
    ws = tmp_path / "ws"; ws.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(ws), *a], check=True, capture_output=True, text=True).stdout.strip()
    run("init", "-q"); run("config", "user.email", "t@t"); run("config", "user.name", "t")
    (ws / "out.txt").write_text("hello")
    run("add", "out.txt"); run("commit", "-qm", "x")
    run("remote", "add", "origin", "https://user:SECRET@github.com/acme/app.git")
    return ws, run("rev-parse", "HEAD")


def test_g3_artifact_refs_typed_verified_with_safe_urls(tmp_path):
    ws, sha = _repo(tmp_path)
    s = GatewaySessionStore(tmp_path / "g.sqlite3")
    s.task_lookup = lambda tid: tid == "T1"
    s.save_handoff(H("h1", metadata={"workspace": str(ws), "task_id": "T1"}))
    rec = s.save_handoff(H("h1", "completed", metadata={"workspace": str(ws), "task_id": "T1"}, result={
        "summary": f"Fixed it, committed {sha[:10]}. See https://example.com/pr/1",
        "worker_session_id": "specialist:coder:r1", "evidence": ["out.txt", "../../etc/passwd"],
        "artifact_refs": [{"kind": "commit", "ref": "deadbeef0"}, {"kind": "bogus", "ref": "x"}]}))
    refs = rec["result"]["artifact_refs"]
    by = {(r["kind"], r["ref"][:10]): r for r in refs}
    assert by[("session", "specialist")]["ref"] == "specialist:coder:r1" and by[("session", "specialist")]["verified"]
    assert by[("task", "T1")]["verified"] is True
    c = by[("commit", sha[:10])]
    assert c["ref"] == sha and c["verified"] and c["url"] == f"https://github.com/acme/app/commit/{sha}"
    assert by[("commit", "deadbeef0")]["verified"] is False and "url" not in by[("commit", "deadbeef0")]
    f = by[("file", "out.txt")]
    import hashlib
    assert f["sha"] == hashlib.sha256(b"hello").hexdigest() and f["verified"]
    assert by[("url", "https://ex")]["verified"] is False
    assert not any("SECRET" in str(r) for r in refs) and not any(r["kind"] == "bogus" for r in refs)
    assert not any("passwd" in r["ref"] for r in refs)


def test_g3_ssh_remote_url():
    from jaeger_ai.core.gateway import handoff_outputs as ho
    ho_git = ho._git
    try:
        ho._git = lambda ws, *a: "git@gitlab.com:team/proj.git"
        assert ho.web_base("/x") == "https://gitlab.com/team/proj"
        ho._git = lambda ws, *a: "/local/path/repo"
        assert ho.web_base("/x") is None
    finally:
        ho._git = ho_git


# ── G5 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_g5_handoff_task_link_and_filter(tmp_path):
    g = gw(tmp_path)
    g.store.save_handoff(H("h1", metadata={"task_id": "T1"}))
    g.store.save_handoff(H("h2"))
    assert g.store.get_handoff("h1")["task_id"] == "T1" and g.store.get_handoff("h2")["task_id"] is None
    assert g.store.handoff_for_task("T1") == "h1" and g.store.handoff_for_task("T9") is None
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        out = await (await c.get("/v1/handoffs?task_id=T1")).json()
        assert [h["id"] for h in out["handoffs"]] == ["h1"]


# ── G4 ───────────────────────────────────────────────────────────────
def test_g4_runner_on_agent_records():
    from jaeger_ai.core.agent_registry.types import AgentKind, AgentRecord, runner_of
    assert runner_of(AgentKind.NATIVE, "native:jaeger", {}) == "native"
    assert runner_of(AgentKind.THIRD_PARTY, "tp:codex", {"cli": "codex"}) == "delegate:codex"
    assert runner_of(AgentKind.THIRD_PARTY, "tp:x", {"adapter": "openclaw"}) == "delegate:openclaw"
    assert runner_of(AgentKind.THIRD_PARTY, "tp:x", {}) == "delegate:tp:x"
    assert runner_of(AgentKind.NATIVE, "a", {"runner": "delegate:claude"}) == "delegate:claude"
    assert runner_of(AgentKind.NATIVE, "a", {"runner": "rm -rf /"}) == "native"
    rec = AgentRecord.from_dict({"id": "tp:codex", "name": "Codex", "kind": "third_party", "metadata": {"cli": "codex"}})
    assert rec.to_dict()["runner"] == "delegate:codex"


@pytest.mark.asyncio
async def test_g4_agents_endpoint_carries_runner(tmp_path):
    g = gw(tmp_path)
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        agents = (await (await c.get("/v1/agents")).json())
        rows = agents.get("agents", agents) if isinstance(agents, dict) else agents
        assert rows and all(a.get("runner") in ("native",) or str(a.get("runner")).startswith("delegate:") for a in rows)
