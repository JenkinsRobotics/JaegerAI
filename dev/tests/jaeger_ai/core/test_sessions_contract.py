"""Sessions contract: home chats, paged typed messages, message.created /
session.summarized, results as messages, rolling summary, staged uploads."""
from __future__ import annotations

import base64
import hashlib
import json

import pytest
import pytest_asyncio
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.context_compiler.compiler import ContextCompiler
from jaeger_ai.core.gateway.event_bus import EVENT_TYPES
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest_asyncio.fixture
async def gw(tmp_path):
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.sqlite3"))
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as c:
        yield gateway, c


def test_events_registered_and_schema_migrated(tmp_path):
    assert {"message.created", "session.summarized"} <= EVENT_TYPES
    store = GatewaySessionStore(tmp_path / "m.sqlite3")
    assert store.schema_version() >= 12


def test_append_emits_message_created_on_session_and_global(tmp_path):
    from jaeger_ai.core.gateway.event_bus import GatewayEventBus
    store = GatewaySessionStore(tmp_path / "e.sqlite3")
    bus = GatewayEventBus(store=store)
    seen = []
    store.event_listener = lambda rec: seen.append((rec["session_id"], rec["event"]))
    store.ensure_session("s1")
    mid = store.append_message("s1", "assistant", "done", kind="handoff_result",
                               sender_agent_id="native:builder", links={"handoff_id": "h1"})
    assert ("s1", "message.created") in seen and ("*", "message.created") in seen
    evts = bus.get_replay_events("s1")
    msg = [e for e in evts if e.event == "message.created"][-1].data["message"]
    assert msg["id"] == mid and msg["kind"] == "handoff_result" and msg["sender_agent_id"] == "native:builder"
    assert msg["links"] == {"handoff_id": "h1"} and msg["role"] == "assistant" and msg["session_id"] == "s1"
    with pytest.raises(ValueError):
        store.append_message("s1", "assistant", "x", kind="bogus")


def test_paging_newest_first(tmp_path):
    store = GatewaySessionStore(tmp_path / "p.sqlite3")
    store.ensure_session("s")
    ids = [store.append_message("s", "user" if i % 2 == 0 else "assistant", f"m{i}") for i in range(7)]
    page = store.list_messages("s", limit=3)
    assert [m["id"] for m in page["messages"]] == ids[::-1][:3] and page["next_before"] == ids[4]
    page2 = store.list_messages("s", before=page["next_before"], limit=3)
    assert [m["id"] for m in page2["messages"]] == [ids[3], ids[2], ids[1]]
    last = store.list_messages("s", before=ids[1], limit=3)
    assert [m["id"] for m in last["messages"]] == [ids[0]] and last["next_before"] is None
    assert store.list_messages("s", limit=999)["messages"].__len__() == 7  # capped at 200


def test_projection_uses_summary_for_covered_rows():
    rows = [{"id": i, "role": "user" if i % 2 else "assistant", "content": f"m{i}"} for i in range(1, 31)]
    rows.append({"id": 31, "role": "system", "kind": "summary", "content": "The code word is PELICAN-7.",
                 "summary": {"covers_from": 1, "covers_to": 20, "message_count": 20}})
    out = json.loads(ContextCompiler.project_conversation_history(rows, max_messages=24))
    assert out[0]["role"] == "system" and "PELICAN-7" in out[0]["content"]
    assert [r["content"] for r in out[1:]] == [f"m{i}" for i in range(21, 31)]
    plain = json.loads(ContextCompiler.project_conversation_history(rows[:30], max_messages=24))
    assert plain[0]["content"] == "m7"  # unchanged without a summary


@pytest.mark.asyncio
async def test_home_and_messages_endpoints(gw):
    gateway, client = gw
    agents = (await (await client.get("/v1/agents")).json())
    agents = agents.get("agents", agents) if isinstance(agents, dict) else agents
    aid = agents[0]["id"]
    r1 = await (await client.get(f"/v1/agents/{aid}/home")).json()
    r2 = await (await client.get(f"/v1/agents/{aid}/home")).json()
    assert r1["created"] is True and r2["created"] is False and r1["session_id"] == r2["session_id"]
    assert r1["agent_id"] == aid
    meta = gateway.store.get_session(r1["session_id"])["metadata"]
    assert meta["home"] is True and meta["agent_id"] == aid
    assert (await client.get("/v1/agents/nope:none/home")).status == 404
    gateway.store.append_message(r1["session_id"], "user", "hello")
    body = await (await client.get(f"/v1/sessions/{r1['session_id']}/messages?limit=50")).json()
    assert body["next_before"] is None and body["messages"][0]["content"] == "hello"
    assert set(body["messages"][0]) >= {"id", "session_id", "role", "kind", "sender_agent_id", "created_at",
                                        "content", "parts", "links"}
    assert (await client.get(f"/v1/sessions/{r1['session_id']}/messages?limit=500")).status == 400


@pytest.mark.asyncio
async def test_handoff_result_posted_as_specialist_message(gw):
    gateway, client = gw
    gateway.store.ensure_session("origin")
    record = {"id": "h_1", "to_agent_id": "native:builder", "from_agent_id": "native:jaeger",
              "session_id": "origin", "task": "build it", "status": "completed",
              "result": {"summary": "Built and checked.", "worker_session_id": "specialist:builder:abc"}}
    gateway._post_handoff_request(record)
    gateway._post_handoff_result(record)
    origin = gateway.store.list_messages("origin")["messages"]
    assert origin[0]["kind"] == "handoff_result" and origin[0]["role"] == "assistant"
    assert origin[0]["sender_agent_id"] == "native:builder"
    assert origin[0]["links"] == {"handoff_id": "h_1", "child_session_id": "specialist:builder:abc"}
    home = gateway.store.list_messages("agent-native:builder")["messages"]
    assert [m["kind"] for m in home] == ["handoff_result", "handoff_request"]


@pytest.mark.asyncio
async def test_rolling_summary(gw, monkeypatch):
    gateway, _ = gw
    gateway.store.ensure_session("long")
    for i in range(1, 31):
        gateway.store.append_message("long", "user" if i % 2 else "assistant",
                                     "my code word is PELICAN-7" if i == 1 else f"m{i}")
    prompts = []

    async def fake(prompt, **kw):
        prompts.append(prompt)
        return "User's first message set code word PELICAN-7."
    monkeypatch.setattr(gateway, "_ollama_chat", fake)
    out = await gateway._maybe_summarize("long")
    assert out and out["summary"]["covers_from"] == 1 and out["summary"]["message_count"] == 18
    assert "PELICAN-7" in prompts[0]
    msgs = gateway.store.list_messages("long", limit=200)["messages"]
    assert msgs[0]["kind"] == "summary" and msgs[0]["role"] == "system"
    assert msgs[0]["summary"]["covers_to"] == out["covers_to"] and len(msgs) == 31  # originals kept
    evts = [e.event for e in gateway.event_bus.get_replay_events("long")]
    assert "session.summarized" in evts
    assert await gateway._maybe_summarize("long") is None  # nothing new to fold
    projected = gateway.store.get_session("long")["messages"]
    hist = json.loads(ContextCompiler.project_conversation_history(projected))
    assert "PELICAN-7" in hist[0]["content"]


@pytest.mark.asyncio
async def test_upload_json_multipart_idempotency_and_limit(gw, monkeypatch):
    gateway, client = gw
    gateway.store.ensure_session("u")
    data = b"hello attachment"
    r = await client.post("/v1/sessions/u/attachments/upload", headers={"Idempotency-Key": "k1"},
                          json={"name": "../../note.txt", "mime": "text/plain",
                                "data_base64": base64.b64encode(data).decode()})
    assert r.status == 201, await r.text()
    a = await r.json()
    assert a["name"] == "note.txt" and a["size"] == len(data) and a["sha256"] == hashlib.sha256(data).hexdigest()
    again = await (await client.post("/v1/sessions/u/attachments/upload", headers={"Idempotency-Key": "k1"},
                                     json={"name": "x", "data_base64": "eA=="})).json()
    assert again["attachment_id"] == a["attachment_id"]
    form = FormData()
    form.add_field("file", b"\x89PNG....", filename="shot.png", content_type="image/png")
    form.add_field("name", "screen.png")
    m = await client.post("/v1/sessions/u/attachments/upload", data=form)
    assert m.status == 201, await m.text()
    mj = await m.json()
    assert mj["name"] == "screen.png" and mj["mime"] == "image/png" and mj["size"] == 8
    monkeypatch.setattr(type(gateway), "UPLOAD_MAX_BYTES", 10)
    big = await client.post("/v1/sessions/u/attachments/upload",
                            json={"name": "b", "data_base64": base64.b64encode(b"x" * 11).decode()})
    assert big.status == 413
    # Omitted attachment_ids → no staged attachments; named ones are frozen.
    none = gateway.store.admit_request("u", "hi", request_id="r-none")
    assert none["execution"]["attachments"] == []
    with gateway.store._get_conn() as conn:  # let the next turn admit
        conn.execute("UPDATE sessions SET status='idle' WHERE session_id='u'")
    named = gateway.store.admit_request("u", "see", request_id="r-named",
                                        requested={"attachment_ids": [a["attachment_id"]]})
    assert [x["attachment_id"] for x in named["execution"]["attachments"]] == [a["attachment_id"]]
