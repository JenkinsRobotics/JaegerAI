"""Chat-study gaps: reasoning duration and persisted response parts."""
from __future__ import annotations

import pytest

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def _gateway(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    gateway.store.ensure_session("s1")
    return gateway


def _events(gateway, name=None):
    rows = gateway.store.replay_events("s1", 0)["events"]
    return [e for e in rows if name is None or e["event"] == name]


def test_reasoning_done_once_per_run_with_duration(tmp_path):
    gateway = _gateway(tmp_path)
    callbacks, finish = gateway._turn_stream_callbacks("s1", "r1")
    callbacks.reasoning("thinking a")
    callbacks.reasoning("thinking b")
    callbacks.stream_delta("Answer")
    callbacks.reasoning("again")
    finish()
    done = _events(gateway, "turn.reasoning.done")
    assert len(done) == 2
    assert all(d["data"]["request_id"] == "r1" and d["data"]["duration_ms"] >= 0 for d in done)
    names = [e["event"] for e in _events(gateway)]
    assert names.index("turn.reasoning.done") < names.index("turn.delta")


def test_project_parts_folds_events_in_order():
    from jaeger_ai.core.gateway.turn_parts import project_parts

    parts = project_parts([
        {"event": "turn.reasoning", "data": {"text": "a"}, "timestamp": 1.0},
        {"event": "turn.reasoning", "data": {"text": "b"}, "timestamp": 1.5},
        {"event": "turn.reasoning.done", "data": {"started_at": 1.0, "duration_ms": 900}},
        {"event": "tool.started", "data": {"call_id": "c1", "tool": "read_file", "input": "x.py"}},
        {"event": "tool.done", "data": {"call_id": "c1", "tool": "read_file", "elapsed_s": 0.2}},
        {"event": "turn.delta", "data": {"delta": "Hel"}},
        {"event": "turn.delta", "data": {"delta": "lo"}},
    ])
    assert parts == [
        {"type": "reasoning", "text": "ab", "started_at": 1.0, "duration_ms": 900},
        {"type": "tool", "call_id": "c1", "tool": "read_file", "status": "done", "input": "x.py", "elapsed_s": 0.2},
        {"type": "text", "text": "Hello"},
    ]


def test_completed_turn_persists_parts_on_the_assistant_message(tmp_path):
    gateway = _gateway(tmp_path)
    store = gateway.store
    store.admit_request("s1", "hello", request_id="r1")
    rid = "r1"
    callbacks, finish = gateway._turn_stream_callbacks("s1", rid)
    callbacks.reasoning("plan")
    callbacks.stream_delta("Hi there")
    finish()
    store.complete_request(rid, status="completed", result={}, assistant_text="Hi there")
    message = store.get_session("s1")["messages"][-1]
    assert message["role"] == "assistant"
    assert [p["type"] for p in message["parts"]] == ["reasoning", "text"]
    assert message["parts"][0]["duration_ms"] >= 0 and message["parts"][1]["text"] == "Hi there"


@pytest.mark.asyncio
async def test_patch_session_model_is_validated_and_drives_turn_defaults(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.runtime import truth

    monkeypatch.setattr(truth, "provider_model_inventory", lambda *a, **k: {"providers": [
        {"id": "ollama", "reachable": True, "models": [{"id": "qwen3:4b"}]},
        {"id": "lmstudio", "reachable": False, "models": [{"id": "offline-model"}]},
    ]})
    gateway = _gateway(tmp_path)
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        ok = await client.patch("/v1/sessions/s1", json={"model": "@ollama:qwen3:4b"})
        assert ok.status == 200
        assert (await ok.json())["metadata"]["model"] == "qwen3:4b"
        assert (await client.patch("/v1/sessions/s1", json={"model": "offline-model"})).status == 400
        assert (await client.patch("/v1/sessions/s1", json={"model": "nope"})).status == 400
        assert (await client.patch("/v1/sessions/s1", json={"model": 3})).status == 400
    meta = gateway.store.get_session("s1")["metadata"]
    assert (meta["model"], meta["provider"]) == ("qwen3:4b", "ollama")
    admitted = gateway.store.admit_request("s1", "hi", request_id="rm")
    assert "qwen3:4b" in str(admitted)  # the frozen execution input uses the session model
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        cleared = await client.patch("/v1/sessions/s1", json={"model": None})
        assert cleared.status == 200 and (await cleared.json())["metadata"].get("model") is None
