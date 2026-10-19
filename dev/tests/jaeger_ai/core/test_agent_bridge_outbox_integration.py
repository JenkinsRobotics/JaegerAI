"""Transactional REST -> durable outbox -> task-owned fake receiver, no live credentials."""

import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.agent_bridge import outbox
from jaeger_ai.features.agent_bridge.service import AgentMessages, BridgeError


def msg(**updates):
    return {
        "id": "delivery1",
        "thread": "thread1",
        "to": "grokbot",
        "kind": "status",
        "title": "Test delivery",
        "body": "status data",
        **updates,
    }


def records(store):
    with store._get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM agent_webhook_outbox")]


def test_v13_upgrade_preserves_messages_without_backfill_and_atomic_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JAEGER_AGENT_WEBHOOK_HOST", "")
    path = tmp_path / "sessions.sqlite3"
    store = GatewaySessionStore(path)
    AgentMessages(store).send("ares", msg())
    with store._get_conn() as conn:
        conn.execute("DROP TABLE agent_webhook_outbox")
        conn.execute("UPDATE schema_meta SET value='13' WHERE key='version'")
    upgraded = GatewaySessionStore(path)
    assert upgraded.schema_version() == 14
    assert len(AgentMessages(upgraded).list("ares")["messages"]) == 1
    assert records(upgraded) == []  # Upgrades do not forward historical conversations.
    service = AgentMessages(upgraded)
    current = msg(id="new", thread="new-thread")
    first = service.send("ares", current)
    assert service.send("ares", current) == first
    assert len(records(upgraded)) == 1
    assert records(upgraded)[0]["status"] == "pending"
    assert not records(upgraded)[0]["attempts"]
    with pytest.raises(BridgeError) as failure:
        service.send(
            "ares", msg(id="too-big", thread="rollback-thread", body="é" * 8192)
        )
    assert failure.value.status == 413
    with upgraded._get_conn() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM agent_threads WHERE thread='rollback-thread'"
            ).fetchone()
            is None
        )
        assert (
            conn.execute("SELECT 1 FROM agent_messages WHERE id='too-big'").fetchone()
            is None
        )
    assert len(records(upgraded)) == 1


@pytest.mark.asyncio
async def test_authenticated_rest_delivery_retry_restart_and_no_redirect(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    monkeypatch.setenv("JAEGER_AGENT_WEBHOOK_HOST", "")

    def forbidden_credentials(*args, **kwargs):
        pytest.fail("live Keychain reads forbidden")

    monkeypatch.setattr(outbox.subprocess, "run", forbidden_credentials)
    store = GatewaySessionStore(tmp_path / "sessions.sqlite3")
    gateway = JaegerGatewayApp(store=store)
    gateway.app.on_startup.clear()
    received, forwarded = [], []
    response_status = [503]

    async def sink(request):
        payload = await request.read()
        received.append(
            (
                request.headers["Authorization"],
                request.headers["Idempotency-Key"],
                payload,
            )
        )
        assert len(payload) <= 16 * 1024
        return web.Response(status=response_status[0], headers={"Location": "/other"})

    async def other(request):
        forwarded.append(await request.read())
        return web.Response(status=204)

    receiver = web.Application()
    receiver.router.add_post("/sink", sink)
    receiver.router.add_post("/other", other)
    async with (
        TestServer(receiver) as local,
        TestClient(TestServer(gateway.app)) as client,
    ):
        assert ":33418" not in str(client.make_url(""))
        sent = await client.post(
            "/v1/agent-messages", headers=caller_auth.client_headers("ares"), json=msg()
        )
        assert sent.status == 200
        assert records(store)[0]["status"] == "pending"
        assert not received
        assert (
            await client.post(
                "/v1/agent-messages",
                headers=caller_auth.client_headers("ares"),
                json=msg(),
            )
        ).status == 200
        assert len(records(store)) == 1
        clock = [records(store)[0]["available_at"] + 1]

        async def isolated_transport(url, key, payload, identifier):
            # This fixture adapter cannot weaken production validation: validation
            # has already required the configured exact HTTPS host before this call.
            assert url == "https://hooks.example.com/sink"
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    local.make_url("/sink"),
                    data=payload,
                    allow_redirects=False,
                    headers={
                        "Authorization": "Bearer " + key,
                        "Idempotency-Key": identifier,
                    },
                ) as result,
            ):
                return result.status

        def make_worker():
            return outbox.OutboxWorker(
                GatewaySessionStore(store.path),
                allowed_host="hooks.example.com",
                credentials=lambda: ("https://hooks.example.com/sink", "fixture-key"),
                transport=isolated_transport,
                clock=lambda: clock[0],
            )

        assert await make_worker().run_once()
        assert records(store)[0]["status"] == "pending"
        response_status[0] = 307
        clock[0] += 100
        assert await make_worker().run_once()
        assert not forwarded
        assert records(store)[0]["status"] == "pending"
        monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "0")
        clock[0] += 100
        assert not await make_worker().run_once()
        assert len(received) == 2
        monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
        response_status[0] = 204
        assert await make_worker().run_once()
        assert records(store)[0]["status"] == "delivered"
        assert len({item[1] for item in received}) == 1
        assert received[0][:2] == ("Bearer fixture-key", "ares:delivery1")
        assert json.loads(received[-1][2])["from"] == "ares"
        assert not forwarded
        assert not await make_worker().run_once()
