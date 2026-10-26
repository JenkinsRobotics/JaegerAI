"""GB-033: server-produced clarify forms are revisioned entities resolved exactly once.

Isolated store/app in tmp_path; no live gateway, model or credentials."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import server as gw
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class _Req:
    can_read_body = True

    def __init__(self, sid: str, cid: str, body: dict):
        self.match_info = {"id": sid, "clarify_id": cid}
        self.query = {}
        self._body = body

    def get(self, key, default=None):  # aiohttp Request is a mapping; no authenticated caller
        return default

    async def json(self):
        return self._body


def _app(tmp_path: Path, monkeypatch) -> JaegerGatewayApp:
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    return JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "clarify.sqlite3"))


def test_store_resolves_once_and_rejects_stale_revision(tmp_path):
    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    row = store.create_clarify(session_id="s1", request_id="r1", question="Which file?", choices=["a", "b"])
    assert row["status"] == "pending" and row["revision"] == 1 and row["choices"] == ["a", "b"]
    assert store.resolve_clarify(row["clarify_id"], revision=2, status="answered", answer="a") is None
    done = store.resolve_clarify(row["clarify_id"], revision=1, status="answered", answer="a")
    assert done and done["status"] == "answered" and done["answer"] == "a"
    assert store.resolve_clarify(row["clarify_id"], revision=1, status="cancelled") is None   # terminal: one winner
    assert store.get_clarify(row["clarify_id"])["answer"] == "a"
    other = store.create_clarify(session_id="s1", request_id="r2", question="Q2")
    assert store.expire_orphaned_clarify() == 1
    assert store.get_clarify(other["clarify_id"])["status"] == "expired"
    assert store.list_clarify("s1") == []


@pytest.mark.asyncio
async def test_parked_turn_receives_exactly_one_answer(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    app._loop = asyncio.get_running_loop()
    sink = app._clarify_sink("s1", "r1")
    waiter = asyncio.create_task(asyncio.to_thread(sink, "clarify", "Deploy to staging or prod?", ("staging", "prod")))
    for _ in range(100):
        forms = app.store.list_clarify("s1")
        if forms:
            break
        await asyncio.sleep(0.02)
    (form,) = forms
    events = [e.event for e in app.event_bus.get_replay_events("s1", since_event_id=0)]
    assert "clarify.request" in events
    cid = form["clarify_id"]
    stale = await app.handle_answer_clarify(_Req("s1", cid, {"revision": 7, "response": "prod"}))
    assert stale.status == 409 and json.loads(stale.body)["stale"] is True
    foreign = await app.handle_answer_clarify(_Req("other", cid, {"revision": 1, "response": "prod"}))
    assert foreign.status == 404
    empty = await app.handle_answer_clarify(_Req("s1", cid, {"revision": 1, "response": "  "}))
    assert empty.status == 400
    ok = await app.handle_answer_clarify(_Req("s1", cid, {"revision": 1, "response": "staging"}))
    assert ok.status == 200 and json.loads(ok.body)["delivered"] is True
    again = await app.handle_answer_clarify(_Req("s1", cid, {"revision": 1, "response": "prod"}))
    assert again.status == 409 and json.loads(again.body)["status"] == "answered"
    assert await asyncio.wait_for(waiter, 5) == "staging"
    assert app.store.get_clarify(cid)["answer"] == "staging"
    assert [e.event for e in app.event_bus.get_replay_events("s1", since_event_id=0)].count("clarify.resolved") == 1


@pytest.mark.asyncio
async def test_exact_status_lookup_recovers_only_a_form_from_its_session(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    form = app.store.create_clarify(session_id="s1", request_id="r1", question="Where?")
    app.store.resolve_clarify(form["clarify_id"], revision=1, status="answered", answer="staging")
    request = _Req("s1", form["clarify_id"], {})
    request.query = {"clarify_id": form["clarify_id"]}
    recovered = await app.handle_list_clarify(request)
    assert recovered.status == 200
    assert json.loads(recovered.body)["form"]["status"] == "answered"
    assert json.loads(recovered.body)["form"]["answer"] == "staging"
    request.match_info["id"] = "other"
    assert (await app.handle_list_clarify(request)).status == 404


@pytest.mark.asyncio
async def test_session_list_includes_terminal_forms_only_when_requested(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    form = app.store.create_clarify(session_id="s1", request_id="r1", question="Where?")
    app.store.resolve_clarify(form["clarify_id"], revision=1, status="answered", answer="staging")
    request = _Req("s1", form["clarify_id"], {})
    pending = await app.handle_list_clarify(request)
    request.query = {"include_resolved": "true"}
    complete = await app.handle_list_clarify(request)
    assert json.loads(pending.body)["forms"] == []
    assert json.loads(complete.body)["forms"][0]["answer"] == "staging"


@pytest.mark.asyncio
async def test_http_reload_answer_and_original_status_roundtrip(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway.caller_auth import TOKEN_DIR_ENV, client_headers, ensure_tokens

    monkeypatch.setenv(TOKEN_DIR_ENV, str(tmp_path / "tokens"))
    ensure_tokens()
    app = _app(tmp_path, monkeypatch)
    app._loop = asyncio.get_running_loop()
    app.app.on_startup.clear()
    monkeypatch.setattr(gw, "CLARIFY_WAIT_S", 1)
    async with TestClient(TestServer(app.app), headers=client_headers("webui")) as client:
        waiter = asyncio.create_task(asyncio.to_thread(app._clarify_sink("s1", "r1"), "clarify", "Which environment?", ("staging", "prod")))
        for _ in range(100):
            if app.store.list_clarify("s1"):
                break
            await asyncio.sleep(0.02)
        (form,) = app.store.list_clarify("s1")
        listed = await client.get("/v1/sessions/s1/clarify?include_resolved=true")
        assert listed.status == 200
        assert (await listed.json())["forms"][0]["clarify_id"] == form["clarify_id"]
        answered = await client.post(f"/v1/sessions/s1/clarify/{form['clarify_id']}", json={"revision": form["revision"], "response": "staging"})
        assert answered.status == 200 and (await answered.json())["status"] == "answered"
        assert await asyncio.wait_for(waiter, 5) == "staging"
        receipt = await client.get(f"/v1/sessions/s1/clarify?clarify_id={form['clarify_id']}")
        assert receipt.status == 200 and (await receipt.json())["form"]["answer"] == "staging"
        assert (await client.post(f"/v1/sessions/s1/clarify/{form['clarify_id']}", json={"revision": form["revision"], "response": "prod"})).status == 409


@pytest.mark.asyncio
async def test_unanswered_form_expires_and_the_tool_falls_back_to_plain_text(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    app._loop = asyncio.get_running_loop()
    monkeypatch.setattr(gw, "CLARIFY_WAIT_S", 0.2)
    answer = await asyncio.to_thread(app._clarify_sink("s1", "r1"), "clarify", "Which one?", ())
    assert answer == ""
    (form,) = app.store.list_clarify("s1", pending_only=False)
    assert form["status"] == "expired"
    late = await app.handle_answer_clarify(_Req("s1", form["clarify_id"], {"revision": 1, "response": "x"}))
    assert late.status == 409
    assert await asyncio.to_thread(app._clarify_sink("s1", "r1"), "secret", "API key?", ()) == ""
    assert len(app.store.list_clarify("s1", pending_only=False)) == 1   # secrets are never parked as forms


def test_clarify_tool_uses_the_answer_or_falls_back_to_plain_text():
    from unittest.mock import MagicMock

    import jaeger_ai.main as m
    from jaeger_os.core.tools import tool_registry as reg
    snap = reg.snapshot_registry()
    try:
        reg.clear_registry()
        m._register_builtins(MagicMock())
        clarify = reg.get_tool("clarify").fn
        with m.interaction_request_sink(lambda kind, prompt, opts: "staging"):
            assert clarify(question="Where?") == {"asked": True, "question": "Where?", "answer": "staging"}
        with m.interaction_request_sink(lambda kind, prompt, opts: ""):
            assert clarify(question="Where?") == {"asked": True, "question": "Where?"}   # plain-text fallback
        assert clarify(question="Where?") == {"asked": True, "question": "Where?"}       # no surface bound
    finally:
        reg.restore_registry(snap)


def test_answer_route_needs_owner_approve_scope():
    from jaeger_ai.core.gateway import caller_auth
    route = "/v1/sessions/{id}/clarify/{clarify_id}"
    assert caller_auth.required_scope("POST", route) == "approve"
    assert caller_auth.prefixed_route_allowed("POST", route) is False
    assert caller_auth.required_scope("GET", "/v1/sessions/{id}/clarify") == "read"


def test_handoff_record_states_the_effective_tool_scope():
    """D3: an empty grant means standing specialist tools, and the record must say so."""
    from jaeger_ai.core.gateway.server import _handoff_tool_scope

    class Agent:
        name = "custom"
        metadata = {"allowed_tools": ["read_file", "web_search"]}

    class Bare:
        name = "bare"
        metadata = {}

    assert _handoff_tool_scope(Agent(), []) == {"tool_scope": "standing", "effective_tools": ["read_file", "web_search"]}
    assert _handoff_tool_scope(Agent(), ["web_search", "terminal"]) == {"tool_scope": "granted_subset", "effective_tools": ["web_search"]}
    assert _handoff_tool_scope(Bare(), ["terminal"]) == {"tool_scope": "model_only", "effective_tools": []}


def test_existing_store_without_clarify_table_gains_it_on_open(tmp_path):
    """A store created before GB-033 (live gateway DB) must not crash startup."""
    import sqlite3
    db = tmp_path / "s.sqlite3"
    GatewaySessionStore(db)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE clarify_forms")
    store = GatewaySessionStore(db)
    assert store.expire_orphaned_clarify() == 0
