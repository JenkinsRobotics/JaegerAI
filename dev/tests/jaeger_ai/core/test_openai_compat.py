"""OpenAI-compatible Gateway surface: request mapping and stream shape.

The adapter only translates; it must reach Jaeger through the Gateway's own
session/turn/stream API with the caller's own token, and its routes sit
behind the same caller auth as everything else.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import openai_compat as oc
from jaeger_ai.core.gateway.caller_auth import client_headers, prefixed_route_allowed, required_scope
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

RUNTIME_MODELS = {
    "providers": [],
    "webui_catalog": {"groups": [
        {"provider_id": "ollama", "provider": "Ollama", "models": [{"id": "qwen3:8b"}, {"id": "glm-5.3-flash:cloud"}]},
        {"provider_id": "lmstudio", "provider": "LM Studio", "models": [{"id": "qwen3:8b"}]},
    ]},
}


# ── pure mapping ───────────────────────────────────────────────────────────


def test_models_payload_lists_jaeger_then_prefixed_reachable_models():
    payload = oc.models_payload(RUNTIME_MODELS, created=7)
    assert payload["object"] == "list"
    ids = [m["id"] for m in payload["data"]]
    assert ids == ["jaeger", "jaeger/qwen3:8b", "jaeger/glm-5.3-flash:cloud"]
    for entry in payload["data"]:
        assert entry["object"] == "model" and entry["created"] == 7
        assert entry["capabilities"]["toolCalling"] is False


def test_models_payload_without_catalog_still_offers_jaeger():
    assert [m["id"] for m in oc.models_payload({}, created=1)["data"]] == ["jaeger"]


@pytest.mark.parametrize("model,expected", [
    ("jaeger", None), ("", None), (None, None), ("jaeger/qwen3:8b", "qwen3:8b"),
    ("jaeger/@lmstudio:qwen3:8b", "@lmstudio:qwen3:8b"),
])
def test_requested_model(model, expected):
    assert oc.requested_model(model) == expected


def test_foreign_model_is_refused():
    with pytest.raises(oc.CompatError) as err:
        oc.requested_model("gpt-4o")
    assert err.value.status == 404


def test_message_text_handles_string_and_parts():
    assert oc.message_text("hi") == "hi"
    assert oc.message_text([{"type": "text", "text": "a"}, {"type": "image_url", "image_url": {}},
                            {"type": "text", "text": "b"}]) == "a\nb"
    assert oc.message_text(None) == ""


def test_single_message_without_key_gets_fresh_session_and_plain_text():
    plan = oc.map_chat_request({"model": "jaeger", "messages": [{"role": "user", "content": "say ok"}]})
    assert plan.text == "say ok" and plan.model is None and plan.stream is False
    assert plan.reuse is False and plan.session_id.startswith(oc.SESSION_PREFIX)
    other = oc.map_chat_request({"messages": [{"role": "user", "content": "say ok"}]})
    assert other.session_id != plan.session_id


def test_history_without_key_is_folded_into_the_turn():
    plan = oc.map_chat_request({"messages": [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ], "stream": True})
    assert plan.stream is True
    assert plan.text.startswith("Conversation so far:")
    assert plan.text.index("be brief") < plan.text.index("first") < plan.text.index("answer")
    assert plan.text.endswith("[user]\nsecond")


def test_session_key_reuses_one_session_and_sends_only_newest_message():
    body = {"user": "vscode-window-1", "messages": [
        {"role": "user", "content": "first"}, {"role": "assistant", "content": "a"},
        {"role": "user", "content": "second"},
    ]}
    a = oc.map_chat_request(body)
    b = oc.map_chat_request(body)
    assert a.reuse and a.session_id == b.session_id == oc.session_id_for_key("vscode-window-1")
    assert a.text == "second"
    header = oc.map_chat_request(body, {oc.SESSION_HEADER: "chat-42"})
    assert header.session_id == oc.session_id_for_key("chat-42")


@pytest.mark.parametrize("body", [
    [], {}, {"messages": []}, {"messages": ["x"]},
    {"messages": [{"role": "robot", "content": "x"}]},
    {"messages": [{"role": "assistant", "content": "only me"}]},
])
def test_bad_requests_are_400(body):
    with pytest.raises(oc.CompatError) as err:
        oc.map_chat_request(body)
    assert err.value.status == 400


def test_chunk_and_completion_shapes():
    c = oc.chunk("id1", "jaeger", 3, content="hi")
    assert c == {"id": "id1", "object": "chat.completion.chunk", "created": 3, "model": "jaeger",
                 "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}]}
    end = oc.chunk("id1", "jaeger", 3, finish_reason="stop")
    assert end["choices"][0] == {"index": 0, "delta": {}, "finish_reason": "stop"}
    assert oc.sse(c).startswith(b"data: {") and oc.sse(c).endswith(b"\n\n")
    done = oc.completion("id1", "jaeger", 3, "ok")
    assert done["object"] == "chat.completion"
    assert done["choices"][0]["message"] == {"role": "assistant", "content": "ok"}


@pytest.mark.parametrize("streamed,final,tail", [
    ("", "ok", "ok"), ("o", "ok", "k"), ("ok", "ok", ""), ("draft", "ok", ""), ("x", "", ""),
])
def test_remaining_text(streamed, final, tail):
    assert oc.remaining_text(streamed, final) == tail


def test_chat_completions_needs_turn_scope_and_is_closed_to_prefixed_callers():
    assert required_scope("POST", "/v1/chat/completions") == "turn"
    assert required_scope("GET", "/v1/models") == "read"
    assert not prefixed_route_allowed("POST", "/v1/chat/completions")
    assert not prefixed_route_allowed("GET", "/v1/models")


# ── handlers over a fake Gateway ───────────────────────────────────────────


class FakeUpstream:
    def __init__(self, deltas: list[str], final: str, status: str = "completed",
                 terminal: str = "turn.finish") -> None:
        self.deltas, self.final, self.status, self.terminal = deltas, final, status, terminal
        self.calls: list[tuple[Any, ...]] = []
        self.authorization = ""

    async def runtime_models(self):
        self.calls.append(("models",))
        return RUNTIME_MODELS

    async def ensure_session(self, session_id, title):
        self.calls.append(("session", session_id, title))

    async def send_turn(self, session_id, text, model):
        self.calls.append(("turn", session_id, text, model))
        return {"request_id": "rid-1", "start_event_id": 10}

    async def events(self, session_id, since):
        self.calls.append(("stream", session_id, since))
        yield 10, "turn.start", {"request_id": "rid-1"}
        yield 11, "turn.delta", {"request_id": "other", "delta": "NOT MINE"}
        for i, piece in enumerate(self.deltas):
            yield 12 + i, "turn.delta", {"request_id": "rid-1", "delta": piece, "channel": "provisional"}
        yield 50, self.terminal, {"request_id": "rid-1"}
        yield 51, "turn.delta", {"request_id": "rid-1", "delta": "AFTER END"}

    async def request_result(self, session_id, request_id):
        return {"status": self.status, "result": {"output": self.final, "error": "boom"}}

    async def cancel(self, session_id, request_id):
        self.calls.append(("cancel", session_id, request_id))

    async def close(self):
        pass


def _app(upstream: FakeUpstream) -> web.Application:
    app = web.Application()
    oc.register(app)

    def factory(request, authorization):
        upstream.authorization = authorization
        return upstream
    app[oc.UPSTREAM_FACTORY_KEY] = factory
    return app


def _events(raw: str) -> list[Any]:
    out = []
    for block in raw.split("\n\n"):
        if block.startswith("data: "):
            body = block[len("data: "):]
            out.append(body if body == "[DONE]" else json.loads(body))
    return out


@pytest.mark.asyncio
async def test_stream_shape_ends_in_done_and_only_carries_this_request():
    upstream = FakeUpstream(["o", "k"], "ok!")
    async with TestClient(TestServer(_app(upstream))) as client:
        resp = await client.post("/v1/chat/completions", headers={"Authorization": "Bearer t"}, json={
            "model": "jaeger", "stream": True, "messages": [{"role": "user", "content": "say ok"}]})
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/event-stream")
        assert resp.headers[oc.SESSION_HEADER].startswith(oc.SESSION_PREFIX)
        events = _events(await resp.text())
    assert events[-1] == "[DONE]"
    chunks = events[:-1]
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    assert len({c["id"] for c in chunks}) == 1
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "ok!"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert [c for c in chunks[:-1] if c["choices"][0]["finish_reason"]] == []
    assert upstream.authorization == "Bearer t"
    kinds = [c[0] for c in upstream.calls]
    assert kinds == ["session", "turn", "stream"]
    assert upstream.calls[2][2] == 9  # follows from start_event_id - 1


@pytest.mark.asyncio
async def test_failed_turn_streams_an_error_then_done():
    upstream = FakeUpstream([], "", status="failed", terminal="turn.failed")
    async with TestClient(TestServer(_app(upstream))) as client:
        resp = await client.post("/v1/chat/completions", json={
            "stream": True, "messages": [{"role": "user", "content": "x"}]})
        events = _events(await resp.text())
    assert events[-1] == "[DONE]"
    assert any(isinstance(e, dict) and e.get("error", {}).get("message") == "boom" for e in events)


@pytest.mark.asyncio
async def test_non_stream_returns_one_completion_and_passes_model():
    upstream = FakeUpstream(["draft"], "final answer")
    async with TestClient(TestServer(_app(upstream))) as client:
        resp = await client.post("/v1/chat/completions", json={
            "model": "jaeger/qwen3:8b", "user": "u1", "messages": [{"role": "user", "content": "q"}]})
        assert resp.status == 200
        body = await resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "final answer"
    assert body["model"] == "jaeger/qwen3:8b"
    turn = next(c for c in upstream.calls if c[0] == "turn")
    assert turn == ("turn", oc.session_id_for_key("u1"), "q", "qwen3:8b")


@pytest.mark.asyncio
async def test_non_stream_failure_is_502_openai_error():
    upstream = FakeUpstream([], "", status="failed", terminal="turn.failed")
    async with TestClient(TestServer(_app(upstream))) as client:
        resp = await client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
        assert resp.status == 502
        assert (await resp.json())["error"]["message"] == "boom"


@pytest.mark.asyncio
async def test_models_route_and_bad_request():
    upstream = FakeUpstream([], "")
    async with TestClient(TestServer(_app(upstream))) as client:
        models = await (await client.get("/v1/models")).json()
        bad = await client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [
            {"role": "user", "content": "x"}]})
        assert bad.status == 404
        assert (await bad.json())["error"]["type"] == "invalid_request_error"
    assert models["data"][0]["id"] == "jaeger"


# ── LoopbackGateway against a stand-in Gateway API ─────────────────────────


@pytest.mark.asyncio
async def test_loopback_gateway_speaks_the_gateway_api():
    seen: list[tuple[str, str, Any]] = []

    async def create(request):
        seen.append(("POST", request.path, await request.json()))
        return web.json_response({"session_id": "s"}, status=201)

    async def turns(request):
        body = await request.json()
        seen.append(("POST", request.path, body))
        return web.json_response({"request_id": body["request_id"], "start_event_id": 5})

    async def stream(request):
        seen.append(("GET", request.path, request.query.get("last_event_id")))
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        rid = seen[1][2]["request_id"]
        for eid, name, data in [(5, "turn.start", {}), (6, "turn.delta", {"delta": "o"}),
                                (7, "turn.finish", {})]:
            record = {"event_id": eid, "session_id": "s", "event": name,
                      "data": {"request_id": rid, **data}, "timestamp": 0}
            await resp.write(f"id: {eid}\nevent: {name}\ndata: {json.dumps(record)}\n\n".encode())
        return resp

    async def result(request):
        return web.json_response({"status": "completed", "result": {"output": "ok"}})

    app = web.Application()
    app.router.add_post("/v1/sessions", create)
    app.router.add_post("/v1/sessions/{id}/turns", turns)
    app.router.add_get("/v1/sessions/{id}/stream", stream)
    app.router.add_get("/v1/sessions/{id}/requests/{rid}", result)
    async with TestServer(app) as server:
        gw = oc.LoopbackGateway(str(server.make_url("")), "Bearer t")
        try:
            await gw.ensure_session("s", "title")
            receipt = await gw.send_turn("s", "hello", "qwen3:8b")
            events = [e async for e in gw.events("s", 4)]
            final = await gw.request_result("s", receipt["request_id"])
        finally:
            await gw.close()
    assert seen[0][2]["source"] == "api" and seen[0][2]["profile"] == "jaeger"
    assert seen[1][2]["text"] == "hello" and seen[1][2]["model"] == "qwen3:8b"
    assert seen[2] == ("GET", "/v1/sessions/s/stream", "4")
    assert [name for _, name, _ in events] == ["turn.start", "turn.delta", "turn.finish"]
    assert final["result"]["output"] == "ok"


# ── behind the real Gateway's auth ─────────────────────────────────────────


@pytest_asyncio.fixture
async def gateway_client(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "oc.sqlite3"))
    gateway.app.on_startup.clear()
    upstream = FakeUpstream(["ok"], "ok")
    gateway.app[oc.UPSTREAM_FACTORY_KEY] = lambda request, authorization: upstream
    async with TestClient(TestServer(gateway.app)) as c:
        yield c


@pytest.mark.asyncio
async def test_gateway_routes_need_a_token(gateway_client):
    for method, path in [("GET", "/v1/models"), ("POST", "/v1/chat/completions")]:
        resp = await gateway_client.request(method, path, json={"messages": [{"role": "user", "content": "x"}]})
        assert resp.status == 401, (method, path)


@pytest.mark.asyncio
async def test_gateway_routes_work_for_the_ide_caller(gateway_client):
    headers = client_headers("ide")
    models = await gateway_client.get("/v1/models", headers=headers)
    assert models.status == 200
    assert (await models.json())["data"][0]["capabilities"]["toolCalling"] is False
    chat = await gateway_client.post("/v1/chat/completions", headers=headers, json={
        "stream": True, "messages": [{"role": "user", "content": "say ok"}]})
    assert chat.status == 200
    assert (await chat.text()).rstrip().endswith("data: [DONE]")


@pytest.mark.asyncio
async def test_gateway_refuses_prefixed_callers(gateway_client):
    resp = await gateway_client.post("/v1/chat/completions", headers=client_headers("mcp"), json={
        "messages": [{"role": "user", "content": "x"}]})
    assert resp.status == 403
