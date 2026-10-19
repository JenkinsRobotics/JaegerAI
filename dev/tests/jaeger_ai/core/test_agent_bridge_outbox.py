"""Only temporary stores, injected credentials and test-owned transport state."""

import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.agent_bridge import outbox


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    monkeypatch.delenv("JAEGER_AGENT_WEBHOOK_HOST", raising=False)
    monkeypatch.setattr(
        outbox.subprocess, "run", lambda *a, **k: pytest.fail("live Keychain forbidden")
    )
    result = GatewaySessionStore(tmp_path / "sessions.db")
    with result._get_conn() as conn:
        outbox.migrate(conn)
    return result


def message(**updates):
    return {
        "id": "m1",
        "thread": "t1",
        "from": "ares",
        "to": "grokbot",
        "kind": "task",
        "body": "hello",
        **updates,
    }


def put(store, **updates):
    with store._get_conn() as conn:
        outbox.enqueue(conn, message(**updates))


def rows(store):
    with store._get_conn() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM agent_webhook_outbox")]


def worker(store, transport, **kwargs):
    return outbox.OutboxWorker(
        store,
        allowed_host="hooks.example.com",
        credentials=lambda: ("https://hooks.example.com/in", "fixture-key"),
        transport=transport,
        **kwargs,
    )


def test_enqueue_atomic_bounded_namespace_projection(store):
    put(store, attachments=["secret"])
    put(store)
    put(store, **{"from": "mcp"})
    assert len(rows(store)) == 2
    assert rows(store)[0]["status"] == "pending"
    assert "attachments" not in json.loads(rows(store)[0]["payload"])
    with pytest.raises(outbox.OutboxPayloadError), store._get_conn() as conn:
        conn.execute("INSERT INTO agent_threads VALUES('rollback','ares','grokbot')")
        outbox.enqueue(conn, message(id="large", body="é" * 8192))
    with store._get_conn() as conn:
        assert (
            conn.execute(
                "SELECT * FROM agent_threads WHERE thread='rollback'"
            ).fetchone()
            is None
        )
    put(store, id="elsewhere", to="mcp")
    assert len(rows(store)) == 2


@pytest.mark.parametrize(
    "url,host",
    [
        ("http://hooks.example.com/x", "hooks.example.com"),
        ("https://hooks.example.com.evil/x", "hooks.example.com"),
        ("https://user:pass@hooks.example.com/x", "hooks.example.com"),
        ("https://hooks.example.com:443/x", "hooks.example.com"),
        ("https://HOOKS.example.com/x", "hooks.example.com"),
        ("https://hooks.example.com./x", "hooks.example.com"),
        ("https://hooks.example.com/#token", "hooks.example.com"),
        ("https://hooks.example.com\\@evil.example/x", "hooks.example.com"),
        ("https://hooks.example.com/\n", "hooks.example.com"),
        ("https://127.0.0.1/x", "127.0.0.1"),
        ("https://hooks.example.com/x", "*example.com"),
    ],
)
def test_url_denied(url, host):
    with pytest.raises(ValueError, match="Invalid webhook configuration"):
        outbox.validate_url(url, host)


def test_url_valid():
    assert outbox.validate_url("https://hooks.example.com/in?q=ok", "hooks.example.com")


@pytest.mark.asyncio
async def test_fake_local_receiver_delivery(store):
    received = []

    async def receive(request):
        received.append(
            (
                request.headers.get("Authorization"),
                request.headers.get("Idempotency-Key"),
                await request.read(),
            )
        )
        return web.Response(status=204)

    app = web.Application()
    app.router.add_post("/in", receive)
    async with TestServer(app) as server:

        async def transport(url, key, payload, identifier):
            # Test adapter rewrites only after production worker URL validation.
            assert url == "https://hooks.example.com/in"
            async with (
                aiohttp.ClientSession() as client,
                client.post(
                    server.make_url("/in"),
                    data=payload,
                    headers={
                        "Authorization": "Bearer " + key,
                        "Idempotency-Key": identifier,
                    },
                    allow_redirects=False,
                ) as response,
            ):
                return response.status

        put(store)
        assert await worker(store, transport).run_once()
    assert received[0][:2] == ("Bearer fixture-key", "ares:m1")
    assert json.loads(received[0][2])["id"] == "m1"
    assert rows(store)[0]["status"] == "delivered"
    assert "fixture-key" not in str(rows(store)) and "hooks.example.com" not in str(
        rows(store)
    )


@pytest.mark.asyncio
async def test_retry_exhaustion_redirect_and_crash_lease(store):
    now = [1000.0]
    calls = []

    async def redirect(*args):
        calls.append(args)
        return 302

    put(store)
    with store._get_conn() as conn:
        conn.execute("UPDATE agent_webhook_outbox SET available_at=0")
    service = worker(store, redirect, clock=lambda: now[0])
    for attempt in range(outbox.MAX_ATTEMPTS):
        assert await service.run_once()
        assert rows(store)[0]["status"] == ("failed" if attempt == 4 else "pending")
        assert not await service.run_once()
        now[0] += 400
    assert len(calls) == 5
    assert rows(store)[0]["attempts"] == 5


@pytest.mark.asyncio
async def test_concurrency_expired_lease_stale_ack(store):
    now = [1000.0]
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(*args):
        entered.set()
        await release.wait()
        return 200

    async def fail(*args):
        return 500

    put(store)
    with store._get_conn() as conn:
        conn.execute("UPDATE agent_webhook_outbox SET available_at=0")
    first = worker(store, slow, clock=lambda: now[0])
    second = worker(store, fail, clock=lambda: now[0])
    pending = asyncio.create_task(first.run_once())
    await entered.wait()
    assert not await second.run_once()
    now[0] += outbox.LEASE_SECONDS + 1
    assert await second.run_once()
    release.set()
    await pending
    assert (
        rows(store)[0]["status"] == "pending"
    )  # stale success cannot acknowledge newer lease
    assert rows(store)[0]["attempts"] == 2


@pytest.mark.asyncio
async def test_off_missing_invalid_kill_and_error_secrecy(store, monkeypatch, caplog):
    async def forbidden(*args):
        pytest.fail("transport must not run")

    put(store)
    service = outbox.OutboxWorker(store, allowed_host="", transport=forbidden)
    assert not await service.run_once()
    for pair in (
        None,
        ("https://evil.example/in", "secret"),
        ("https://hooks.example.com/in", "bad\nkey"),
    ):
        service = outbox.OutboxWorker(
            store,
            allowed_host="hooks.example.com",
            credentials=lambda pair=pair: pair,
            transport=forbidden,
        )
        assert not await service.run_once()
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "0")
    service = worker(store, forbidden)
    assert not await service.run_once()
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")

    def disable():
        monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "0")
        return ("https://hooks.example.com/in", "fixture-key")

    service.credentials = disable
    assert not await service.run_once()
    assert rows(store)[0]["attempts"] == 0
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")

    async def error(*args):
        raise RuntimeError("fixture-key https://hooks.example.com/private body")

    assert await worker(store, error).run_once()
    assert "fixture-key" not in caplog.text and "private" not in str(rows(store))


@pytest.mark.asyncio
async def test_cancelled_worker_recovery_and_final_claim(store):
    started = asyncio.Event()

    async def hang(*args):
        started.set()
        await asyncio.Event().wait()

    put(store)
    service = worker(store, hang)
    task = asyncio.create_task(service.run_once())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rows(store)[0]["status"] == "sending"
    with store._get_conn() as conn:
        conn.execute(
            "UPDATE agent_webhook_outbox SET lease_until=0,attempts=?",
            (outbox.MAX_ATTEMPTS,),
        )
    assert not await service.run_once()
    assert rows(store)[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_default_lifecycle_off_without_host(store):
    from types import SimpleNamespace

    gateway = SimpleNamespace(store=store, app=web.Application())
    outbox.attach(gateway)
    await gateway.app.cleanup_ctx._on_startup(gateway.app)
    await gateway.app.cleanup_ctx._on_cleanup(gateway.app)


@pytest.mark.asyncio
async def test_timeout_and_lease_survive_store_reopen(store, monkeypatch):
    put(store)

    async def timeout(*args):
        raise TimeoutError("credential-bearing-url-must-not-be-logged")

    assert await worker(store, timeout).run_once()
    assert rows(store)[0]["status"] == "pending"
    reopened = GatewaySessionStore(store.path)
    assert rows(reopened)[0]["attempts"] == 1


@pytest.mark.asyncio
async def test_invalid_host_never_reads_credentials(store):
    def forbidden():
        pytest.fail("credentials must not be read for invalid host")

    service = outbox.OutboxWorker(store, allowed_host="bad host", credentials=forbidden)
    assert not await service.run_once()


@pytest.mark.asyncio
async def test_production_transport_disallows_redirect_proxy_tls_override(monkeypatch):
    captured = {}

    class Response:
        status = 302

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Session:
        def __init__(self, **kwargs):
            captured["session"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, url, **kwargs):
            captured["post"] = kwargs
            return Response()

    monkeypatch.setattr(outbox.aiohttp, "ClientSession", Session)
    assert (
        await outbox.https_post(
            "https://hooks.example.com/in", "fixture", b"{}", "ares:m1"
        )
        == 302
    )
    assert captured["session"]["trust_env"] is False
    assert captured["session"]["timeout"].total == outbox.REQUEST_TIMEOUT
    assert captured["post"]["allow_redirects"] is False
    assert "ssl" not in captured["post"] and "connector" not in captured["session"]


def test_keychain_adapter_contract_only_mock_process(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def fake(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=b"https://hooks.example.com/in\n"
            if len(calls) == 1
            else b"fixture-key\n",
        )

    monkeypatch.setattr(outbox.subprocess, "run", fake)
    assert outbox.KeychainCredentials()() == (
        "https://hooks.example.com/in",
        "fixture-key",
    )
    assert [call[0] for call in calls] == [
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            "ai.jaeger.bridge.webhook",
            "-a",
            account,
            "-w",
        ]
        for account in ("grokbot-url", "grokbot-key")
    ]
    assert all(call[1]["timeout"] == 3 and call[1]["capture_output"] for call in calls)
