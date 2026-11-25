"""Standalone tests for jaeger-gateway (auth, WAL store, single-fiber coordinator, fenced SSE, HTTP)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import (
    GatewayAuthPolicy,
    GatewayStore,
    RequestConflictError,
    RunCoordinator,
    SessionEventHub,
    StaleWriterError,
    format_sse,
)
from jaeger_gateway.server import create_gateway_app


def test_fail_closed_http_and_websocket_auth() -> None:
    policy = GatewayAuthPolicy(tokens={"secret-tok": "owner:matt"})
    assert not policy.verify_http({}, remote_addr="127.0.0.1").allowed
    assert not policy.verify_http({"Authorization": "Bearer wrong"}, remote_addr="127.0.0.1").allowed
    ok = policy.verify_http({"Authorization": "Bearer secret-tok"}, remote_addr="10.0.0.5")
    assert ok.allowed and ok.actor == "owner:matt"

    # Cross-site WebSocket origin rejected even with valid token
    bad_origin = policy.verify_websocket(
        {"Authorization": "Bearer secret-tok", "Origin": "https://evil.example"},
        remote_addr="127.0.0.1",
    )
    assert not bad_origin.allowed and "origin" in bad_origin.reason
    good_ws = policy.verify_websocket(
        {"Authorization": "Bearer secret-tok", "Origin": "http://127.0.0.1:8790"},
        remote_addr="127.0.0.1",
    )
    assert good_ws.allowed


def test_coordinator_single_fiber_idempotency_and_fenced_sse(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "gw.sqlite3")
    hub = SessionEventHub()
    sess = store.create_session(title="Build", workspace=str(tmp_path))
    sid = sess["session_id"]

    active = [0]
    max_concurrent = [0]

    def executor(session_id: str, prompt: str, gen: int, event_hub: SessionEventHub):
        active[0] += 1
        max_concurrent[0] = max(max_concurrent[0], active[0])
        event_hub.publish(session_id, "text.delta", {"delta": f"reply:{prompt}"}, generation=gen)
        time.sleep(0.03)
        active[0] -= 1
        return {"verdict": "complete", "content": f"done:{prompt}"}

    coord = RunCoordinator(store=store, hub=hub, executor=executor)
    try:
        rid1, f1 = coord.submit(sid, "first", request_id="req-1")
        rid2, f2 = coord.submit(sid, "second", request_id="req-2")
        assert f1.result(timeout=5.0)["content"] == "done:first"
        assert f2.result(timeout=5.0)["content"] == "done:second"
        # Single-fiber guarantee: same session never ran concurrently
        assert max_concurrent[0] == 1

        # Idempotent replay with same request_id + payload succeeds without re-running
        rid_replay, f_replay = coord.submit(sid, "first", request_id="req-1")
        assert rid_replay == rid1 and f_replay.result(timeout=2.0)["content"] == "done:first"

        # Conflict on same request_id + different payload raises RequestConflictError
        with pytest.raises(RequestConflictError):
            coord.submit(sid, "TAMPERED", request_id="req-1")

        # Zombie writer from generation 1 is fenced out after generation 2 opened
        with pytest.raises(StaleWriterError):
            hub.publish(sid, "zombie.delta", {"x": 1}, generation=1)

        events = hub.replay_after(sid, after_seq=0)
        assert len(events) >= 4
        sse = format_sse(event=events[0]["event"], data=events[0]["payload"], seq=events[0]["seq"])
        assert f"id: {events[0]['seq']}" in sse and f"event: {events[0]['event']}" in sse
    finally:
        coord.close()


@pytest.mark.asyncio
async def test_gateway_http_and_sse_endpoints(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "http_gw.sqlite3")
    hub = SessionEventHub()
    coord = RunCoordinator(
        store=store,
        hub=hub,
        executor=lambda sid, prompt, gen, h: {"verdict": "complete", "content": f"echo:{prompt}"},
    )
    app = create_gateway_app(
        store=store,
        coordinator=coord,
        hub=hub,
        auth=GatewayAuthPolicy(tokens={"tok-1": "owner:test"}),
    )
    try:
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/health")).status == 200
            assert (await client.get("/v1/sessions")).status == 401

            headers = {"Authorization": "Bearer tok-1"}
            created = await client.post("/v1/sessions", json={"title": "Demo"}, headers=headers)
            assert created.status == 201
            sid = (await created.json())["session"]["session_id"]

            run_resp = await client.post(
                f"/v1/sessions/{sid}/runs",
                json={"prompt": "hello", "wait": True},
                headers=headers,
            )
            assert run_resp.status == 200
            assert (await run_resp.json())["result"]["content"] == "echo:hello"

            sse_resp = await client.get(f"/v1/sessions/{sid}/events?once=1", headers=headers)
            assert sse_resp.status == 200
            body = await sse_resp.text()
            assert "event: run.started" in body and "event: run.completed" in body

            apr = store.create_approval(sid, "shell", "Run deploy?")
            res = await client.post(
                f"/v1/approvals/{apr['approval_id']}/resolve",
                json={"decision": "approve", "note": "lgtm"},
                headers=headers,
            )
            assert res.status == 200
            assert (await res.json())["approval"]["status"] == "approved"
    finally:
        coord.close()
