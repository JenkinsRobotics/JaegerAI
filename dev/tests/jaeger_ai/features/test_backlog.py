"""Backlog: store, importer, gateway routes (assign -> hub handoff -> result moves status), MCP tools."""
from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import agent_activity, caller_auth
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.backlog import importer, routes as bl_routes
from jaeger_ai.features.backlog.store import BacklogError, BacklogStore, record_hub_message, status_from_message, sweep


# ── store ────────────────────────────────────────────────────────────

def test_store_add_list_update_filters(tmp_path):
    s = BacklogStore(tmp_path / "b.sqlite3")
    a = s.add("Fix browser LAN guard", "block 192.168/16", priority="P0", worker="ares")
    b = s.add("Release notes", priority="p2", worker="Muse", status="needs_ok")
    s.add("Old thing", status="done")
    assert a["id"].startswith("bl-") and a["status"] == "open" and b["priority"] == "P2" and b["worker"] == "muse"
    assert [t["title"] for t in s.list()][:2] == ["Release notes", "Fix browser LAN guard"]  # needs_ok first
    assert [t["id"] for t in s.list(priority="P0")] == [a["id"]]
    assert {t["id"] for t in s.list(status="open,needs_ok")} == {a["id"], b["id"]}
    assert [t["id"] for t in s.list(worker="ares", q="LAN")] == [a["id"]]
    up = s.update(a["id"], status="in_progress", priority="P1")
    assert up["status"] == "in_progress" and up["updated_at"] >= a["updated_at"]
    assert s.counts() == {"in_progress": 1, "needs_ok": 1, "done": 1}


@pytest.mark.parametrize("kw", [{"title": ""}, {"title": "x", "status": "bogus"}, {"title": "x", "priority": "P9"},
                                {"title": "x", "worker": "Bad Name!"}, {"title": "x" * 400}])
def test_store_validation(tmp_path, kw):
    with pytest.raises(BacklogError):
        BacklogStore(tmp_path / "b.sqlite3").add(**kw)


def test_store_unknown_and_missing(tmp_path):
    s = BacklogStore(tmp_path / "b.sqlite3")
    t = s.add("x")
    with pytest.raises(BacklogError):
        s.update(t["id"], id="other")
    with pytest.raises(BacklogError) as e:
        s.get("bl-nope")
    assert e.value.status == 404


def test_status_from_message():
    assert status_from_message("status", "working") == "in_progress"
    assert status_from_message("status", "needs ok: plist change") == "needs_ok"
    assert status_from_message("result", "done, 3 commits") == "done"
    assert status_from_message("result", "failed: tests red") == "needs_ok"
    assert status_from_message("question") == "needs_ok" and status_from_message("task") is None


# ── importer ─────────────────────────────────────────────────────────

MD = """# Jaeger Backlog

## P0 — Release blockers
- [ ] **Block shared browser from home network** — private IP guard (ARES)
- [x] Fix Ollama loopback (rack PC)
- Reboot test of login items (needs your OK)
    - nested detail, not a task

## Integrations
| Task | Priority | Worker | Status |
|---|---|---|---|
| Release notes and onboarding text | P1 | Muse | in progress |
| Agency Agents roles | P2 | grokbot | waiting on you |
"""


REAL = """# Jaeger Master Backlog

## How to append
- Add new rows at the **bottom** of the table; never renumber.
- Priority: `P0` release blocker / `P1` / `P2`.

| id | task | source bot | status | suggested worker | priority |
|---|---|---|---|---|---|
| J-004 | First-run onboarding flow (UI + text) - copy by Muse | Supervisor | in progress | ares (code) + muse (copy) | P0 |
| J-005 | Mac app packaging + signing | Mac App | needs Matthew's OK | Jaeger Mac App | P0 |
| J-007 | Copyrighted art review (Matthew: leave in place) | Design | open | Supervisor | P1 |
"""


def test_importer_real_master_backlog_shape(tmp_path):
    items = importer.parse(REAL)
    assert [i["ref"] for i in items] == ["J-004", "J-005", "J-007"]  # "How to append" bullets skipped
    a, b, c = items
    assert (a["worker"], a["status"], a["priority"]) == ("ares", "in_progress", "P0")
    assert (b["worker"], b["status"]) == ("mac-app", "needs_ok")
    assert c["worker"] == "grokbot" and c["title"] == "Copyrighted art review (Matthew: leave in place)"
    f = tmp_path / "Jaeger-Backlog.md"
    f.write_text(REAL)
    s = BacklogStore(tmp_path / "b.sqlite3")
    assert importer.import_file(s, f)["added"] == 3
    f.write_text(REAL.replace("Mac app packaging + signing", "Mac app packaging and signing (renamed)"))
    assert importer.import_file(s, f)["added"] == 0  # stable J-### ids dedupe
    assert s.list(q="packaging")[0]["source"] == "Jaeger-Backlog.md: J-005 · Mac App"


def test_importer_parses_bullets_tables_and_is_insert_only(tmp_path):
    items = importer.parse(MD)
    by = {i["title"]: i for i in items}
    assert len(items) == 5
    b = by["Block shared browser from home network"]
    assert (b["priority"], b["worker"], b["status"], b["detail"]) == ("P0", "ares", "open", "private IP guard (ARES)")
    assert by["Fix Ollama loopback"]["status"] == "done" and by["Fix Ollama loopback"]["worker"] == "rackpc"
    assert by["Reboot test of login items"]["status"] == "needs_ok"
    assert by["Release notes and onboarding text"]["worker"] == "muse"
    assert by["Release notes and onboarding text"]["status"] == "in_progress"
    assert by["Agency Agents roles"]["status"] == "needs_ok" and by["Agency Agents roles"]["priority"] == "P2"

    f = tmp_path / "Jaeger-Backlog.md"
    f.write_text(MD)
    s = BacklogStore(tmp_path / "b.sqlite3")
    assert importer.import_file(s, f)["added"] == 5
    t = s.list(q="Block shared")[0]
    s.update(t["id"], priority="P2")  # DB is the source of truth
    again = importer.import_file(s, f)
    assert again["added"] == 0 and again["skipped"] == 5 and s.get(t["id"])["priority"] == "P2"
    assert importer.import_file(s, tmp_path / "missing.md")["ok"] is False
    assert importer.main([str(f), "--db", str(tmp_path / "c.sqlite3")]) == 0


# ── gateway routes ───────────────────────────────────────────────────

class _Bus:
    def __init__(self):
        self.events = []

    def publish(self, sid, kind, data):
        self.events.append((kind, data))


class _GW:
    def __init__(self, tmp_path):
        self.app = web.Application(middlewares=[self._auth])
        self.store = GatewaySessionStore(tmp_path / "gateway_sessions.sqlite3")
        self.event_bus = _Bus()
        self.caller = "webui"

    @web.middleware
    async def _auth(self, request, handler):
        request["caller"] = caller_auth.CALLERS[request.headers.get("X-Caller", self.caller)]
        return await handler(request)


@pytest.fixture
def gw(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSE_FOLDER", str(tmp_path / "nomuse"))
    g = _GW(tmp_path)
    bl_routes.register(g, BacklogStore(tmp_path / "b.sqlite3"))
    from jaeger_ai.features.agent_bridge import routes as ab_routes
    ab_routes.register(g)
    return g


def _run(gw, coro_fn):
    async def go():
        async with TestClient(TestServer(gw.app)) as c:
            return await coro_fn(c)
    return asyncio.run(go())


def test_routes_crud_assign_and_result_moves_status(gw):
    async def flow(c):
        r = await c.post("/v1/backlog", json={"title": "Fix tests", "priority": "P0"})
        assert r.status == 200
        tid = (await r.json())["task"]["id"]
        assert (await (await c.get("/v1/backlog?priority=P0")).json())["tasks"][0]["id"] == tid
        assert (await c.post("/v1/backlog", json={"title": "x", "evil": 1})).status == 400
        assert (await c.post(f"/v1/backlog/{tid}", json={"handoff_id": "x"})).status == 400
        assert (await c.post(f"/v1/backlog/{tid}/assign", json={"worker": "nobody"})).status == 400
        r = await c.post(f"/v1/backlog/{tid}/assign", json={"worker": "rackpc"})
        out = await r.json()
        assert r.status == 200, out
        assert out["task"]["status"] == "in_progress" and out["task"]["worker"] == "rackpc"
        h = out["handoff"]
        assert h["from"] == "webui" and h["to"] == "rackpc" and out["task"]["handoff_id"] == h["id"]
        # the worker sees a real hub task in its inbox
        inbox = await (await c.get("/v1/agent-messages", headers={"X-Caller": "rackpc"})).json()
        assert any(m.get("id") == h["id"] and m["kind"] == "task" for m in inbox.get("messages", inbox if isinstance(inbox, list) else []))
        # an unrelated caller can't move it; the worker's result can
        r = await c.post("/v1/agent-messages", headers={"X-Caller": "rackpc"},
                         json={"id": "r1", "thread": h["thread"], "to": "webui", "kind": "result", "title": "done",
                               "body": "3 tests fixed", "status_line": "done", "reply_to": h["id"]})
        assert r.status == 200, await r.text()
        task = (await (await c.get("/v1/backlog")).json())["tasks"][0]
        assert task["status"] == "done" and task["last_note"] == "done"
        return tid
    _run(gw, flow)
    kinds = [k for k, _ in gw.event_bus.events]
    assert "handoff.sent" in kinds and "handoff.result" in kinds and kinds.count("backlog.updated") >= 3


def test_only_owner_approves_and_imports(gw, tmp_path):
    async def flow(c):
        tid = (await (await c.post("/v1/backlog", json={"title": "Sign app", "status": "needs_ok"})).json())["task"]["id"]
        r = await c.post(f"/v1/backlog/{tid}", headers={"X-Caller": "grokbot"}, json={"status": "open"})
        assert r.status == 403
        r = await c.post(f"/v1/backlog/{tid}", headers={"X-Caller": "grokbot"}, json={"priority": "P0"})
        assert r.status == 200
        r = await c.post(f"/v1/backlog/{tid}", json={"status": "open"})
        assert r.status == 200 and (await r.json())["task"]["status"] == "open"
        assert (await c.post("/v1/backlog/import", headers={"X-Caller": "grokbot"}, json={})).status == 403
        assert (await c.post("/v1/backlog/import", json={"path": "/etc/hosts"})).status == 403
        # grokbot creates; its own assign to itself is sent by jaegerd
        g = await (await c.post("/v1/backlog", headers={"X-Caller": "grokbot"}, json={"title": "self"})).json()
        assert g["task"]["source"] == "grokbot"
        r = await c.post(f"/v1/backlog/{g['task']['id']}/assign", headers={"X-Caller": "grokbot"}, json={"worker": "grokbot"})
        assert r.status == 200 and (await r.json())["handoff"]["from"] == "jaegerd"
    _run(gw, flow)
    assert any(d.get("action") == "approved" for k, d in gw.event_bus.events if k == "backlog.updated")


def test_auth_tables_and_activity_kind():
    for m, r in bl_routes.ROUTES:
        assert caller_auth.required_scope(m, r) == "search"
        for name in ("grokbot", "ares"):
            assert caller_auth.prefixed_route_allowed(m, r, name)
        # J-063: muse is confined to backlog read/add/update/assign; bulk import stays off.
        assert caller_auth.prefixed_route_allowed(m, r, "muse") == ((m, r) != ("POST", "/v1/backlog/import"))
        assert not caller_auth.prefixed_route_allowed(m, r, "rackpc")
    for name in ("grokbot", "ares", "muse"):
        assert caller_auth.prefixed_route_allowed("GET", "/v1/backlog", name)
    d = {"caller": {"caller_id": "webui", "caller_kind": "owner"}, "action": "approved", "title": "Sign", "status": "open"}
    assert agent_activity.classify("backlog.updated", d)["actor_id"] == "webui"
    assert "approved backlog task: Sign" in agent_activity._summary("backlog.updated", d)


def test_webui_passthrough():
    from jaeger_ai.features.webui.api.jaeger_sessions import passthrough_match
    assert passthrough_match("/v1/backlog", "GET") and passthrough_match("/v1/backlog", "POST")
    assert passthrough_match("/v1/backlog/bl-0123456789/assign", "POST")
    assert passthrough_match("/v1/backlog/import", "POST")
    assert not passthrough_match("/v1/backlog/../x", "POST")


# ── MCP tools ────────────────────────────────────────────────────────

def test_mcp_backlog_tools_relay(monkeypatch):
    import jaeger_ai.features.agent_bridge.mcp as mod

    class M:
        tools = {}
        def tool(self, name=None):
            def deco(fn):
                self.tools[name or fn.__name__] = fn
                return fn
            return deco

    class C:
        calls = []
        def _call(self, m, p, b=None):
            self.calls.append((m, p, b))
            return {"ok": True}

    monkeypatch.setattr(mod, "enabled", lambda: None)
    m, c = M(), C()
    mod.register(m, lambda ctx: c)
    asyncio.run(m.tools["jaeger.backlog_list"](status="open", worker="ares"))
    asyncio.run(m.tools["jaeger.backlog_add"]("New", priority="P0"))
    asyncio.run(m.tools["jaeger.backlog_update"]("bl-0123456789", status="done"))
    asyncio.run(m.tools["jaeger.backlog_update"]("bl-0123456789", assign_to="muse"))
    assert c.calls[0][0] == "GET" and c.calls[0][1].startswith("/v1/backlog?") and "worker=ares" in c.calls[0][1]
    assert c.calls[1] == ("POST", "/v1/backlog", {"title": "New", "detail": "", "priority": "P0", "status": "open", "worker": ""})
    assert c.calls[2] == ("POST", "/v1/backlog/bl-0123456789", {"status": "done"})
    assert c.calls[3] == ("POST", "/v1/backlog/bl-0123456789/assign", {"worker": "muse"})


def test_sweep_flags_without_mutating(tmp_path):
    store = BacklogStore(tmp_path / "sweep.sqlite3")
    stale = store.add("Work", status="in_progress")
    waiting = store.add("Sign", status="needs_ok")
    blocked = store.add("Blocked by device", status="open")
    finished = store.add("Needs reconciliation", status="open")
    store.update(finished["id"], handoff_id="h1", handoff_result="done")
    now = max(row["updated_at"] for row in store.list()) + 101
    flags = {item["task"]["id"]: item["reasons"] for item in sweep(store, now, 100)}
    assert flags[stale["id"]] == ["stale"]
    assert flags[waiting["id"]] == ["waiting_on_matthew"]
    assert flags[blocked["id"]] == ["blocked"]
    assert flags[finished["id"]] == ["finished_not_marked"]
    assert store.get(finished["id"])["status"] == "open"


def test_record_hub_message_is_idempotent_and_links_existing(tmp_path):
    store = BacklogStore(tmp_path / "hub.sqlite3")
    task = {"id": "h1", "thread": "t1", "to": "ares", "kind": "task",
            "title": "Do work", "body": "Details", "refs": []}
    first = record_hub_message(store, "grokbot", task)
    assert record_hub_message(store, "grokbot", task)["id"] == first["id"]
    assert len(store.list()) == 1
    record_hub_message(store, "ares", {"kind": "status", "thread": "t1", "status_line": "needs ok"})
    assert store.get(first["id"])["status"] == "needs_ok"
    record_hub_message(store, "ares", {"kind": "result", "thread": "t1", "status_line": "done"})
    assert store.get(first["id"])["status"] == "done"
    existing = store.add("Preexisting")
    linked = record_hub_message(store, "grokbot", {**task, "id": "h2", "thread": "t2",
                                               "refs": [f"backlog:{existing['id']}"]})
    assert linked["id"] == existing["id"] and len(store.list()) == 2


def test_sweep_route_and_mcp(gw, monkeypatch):
    async def flow(c):
        await c.post("/v1/backlog", json={"title": "Wait", "status": "needs_ok"})
        response = await c.get("/v1/backlog/sweep", headers={"X-Caller": "ares"})
        assert response.status == 200
        assert (await response.json())["flagged"][0]["reasons"] == ["waiting_on_matthew"]
    _run(gw, flow)
    import jaeger_ai.features.agent_bridge.mcp as mod
    class M:
        tools = {}
        def tool(self, name=None):
            def deco(fn):
                self.tools[name or fn.__name__] = fn
                return fn
            return deco
    class C:
        def _call(self, method, path, body=None):
            assert method == "GET" and path.startswith("/v1/backlog/sweep?")
            return {"ok": True}
    monkeypatch.setattr(mod, "enabled", lambda: None)
    m = M()
    mod.register(m, lambda ctx: C())
    assert asyncio.run(m.tools["jaeger.backlog_sweep"]()) == {"ok": True}
