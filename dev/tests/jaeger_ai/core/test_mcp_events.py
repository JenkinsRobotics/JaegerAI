"""Isolated simulated ChatGPT lifecycle; never a provider/account acceptance test."""

import base64
import hashlib
import hmac
import json
import time
from copy import deepcopy

import jwt
import pytest
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric import rsa

from jaeger_ai.features.mcp_events.security import (
    OAuthVerifier,
    Principal,
    PublicHTTPS,
    callback_url,
    public_ip,
    secret_bytes,
    signed_headers,
)
from jaeger_ai.features.mcp_events.server import Facade
from jaeger_ai.features.mcp_events.service import CallbackError, Events
from jaeger_ai.features.mcp_events.store import Store

SECRET = "whsec_" + base64.b64encode(b"a" * 32).decode()
OTHER = "whsec_" + base64.b64encode(b"b" * 32).decode()
RESOURCE, ISSUER = "https://events.example.com", "https://auth.example.com"


class Secrets:
    """Temporary test-only store, survives simulated process reconstruction."""

    def __init__(self):
        self.values = {}

    def get(self, name):
        return deepcopy(self.values[name])

    def put(self, name, value):
        self.values[name] = deepcopy(value)

    def delete(self, name):
        self.values.pop(name, None)


class Gateway:
    """Fake participant-enforcing Gateway, not a provider or live bridge."""

    def __init__(self):
        self.messages, self.calls = [], []
        self.denied = False

    async def get_thread(self, thread, after=0, limit=50):
        if thread == "private" or self.denied:
            raise PermissionError("Thread unavailable")
        return {
            "messages": [
                m
                for m in self.messages
                if m["thread"] == thread and "ares" in (m["from"], m["to"])
            ]
        }

    async def list_messages(self, after=0, limit=50):
        return {
            "messages": [m for m in self.messages if "ares" in (m["from"], m["to"])],
            "next_after": None,
        }

    async def send_message(self, **args):
        self.calls.append(args)
        return {**args, "from": "ares"}


class Receiver:
    """Injected transport verifies independently using Standard Webhooks formula.

    No DNS or sockets. It cannot prove actual ChatGPT acceptance or public TLS.
    """

    def __init__(self):
        self.calls, self.accepted, self.codes = [], set(), []
        self.bad_challenge = False
        self.secret = SECRET

    async def post(self, url, body, headers):
        self.calls.append((url, body, dict(headers)))
        stamp, event = headers["webhook-timestamp"], headers["webhook-id"]
        expected = (
            "v1,"
            + base64.b64encode(
                hmac.new(
                    base64.b64decode(self.secret[6:]),
                    f"{event}.{stamp}.".encode() + body,
                    hashlib.sha256,
                ).digest()
            ).decode()
        )
        if not any(
            hmac.compare_digest(expected, part)
            for part in headers["webhook-signature"].split()
        ):
            return 401, b"{}"
        data = json.loads(body)
        if data.get("type") == "verification":
            return 200, json.dumps(
                {"challenge": "bad" if self.bad_challenge else data["challenge"]}
            ).encode()
        assert data["eventId"] == event
        assert len(body) <= 262144
        self.accepted.add(event)
        return (self.codes.pop(0) if self.codes else 200), b"{}"


@pytest.fixture
def setup(tmp_path):
    now = [time.time()]
    store, secrets, gateway, receiver = (
        Store(tmp_path / "events.sqlite"),
        Secrets(),
        Gateway(),
        Receiver(),
    )
    events = Events(store, secrets, gateway, transport=receiver, clock=lambda: now[0])
    principal = Principal(
        "matthew",
        frozenset({"messages:read", "messages:write", "events:read"}),
        now[0] + 86400,
    )
    params = {
        "name": "message.created",
        "arguments": {"recipient": "ares", "thread": "hello"},
        "delivery": {
            "mode": "webhook",
            "url": "https://receiver.example.com/callback",
            "secret": SECRET,
        },
    }
    return events, principal, params, now, receiver


def message(now, mid="one", **changes):
    return {
        "id": mid,
        "thread": "hello",
        "from": "grokbot",
        "to": "ares",
        "title": "Hello",
        "body": "Untrusted message " * 200,
        "created_at": now,
        **changes,
    }


@pytest.mark.asyncio
async def test_lifecycle_restart_refresh_unsubscribe(setup):
    events, p, params, now, receiver = setup
    sub = await events.subscribe(p, params)
    assert sub["cursor"] is None and sub["truncated"] is False
    assert await events.subscribe(p, params) == sub
    assert len(receiver.calls) == 1
    await events.ingest(message(now[0]))
    await events.ingest(message(now[0]))
    await events.deliver()
    assert len(receiver.accepted) == 1
    data = json.loads(receiver.calls[-1][1])
    assert set(data["data"]) == {"id", "thread", "sender", "title", "preview"}
    assert len(data["data"]["preview"]) == 240
    restart = Events(
        Store(events.store.path),
        events.secrets,
        events.gateway,
        transport=receiver,
        clock=lambda: now[0],
    )
    now[0] += 10
    params["delivery"]["secret"] = OTHER
    receiver.secret = OTHER
    refreshed = await restart.subscribe(p, params)
    assert (
        refreshed["id"] == sub["id"]
        and refreshed["refreshBefore"] > sub["refreshBefore"]
    )
    await restart.ingest(message(now[0], "two"))
    await restart.deliver()
    assert len(receiver.calls[-1][2]["webhook-signature"].split()) == 2
    await restart.unsubscribe(p, params)
    await restart.unsubscribe(p, params)
    await restart.ingest(message(now[0], "three"))
    await restart.deliver()
    assert len(receiver.accepted) == 2
    assert not events.secrets.values


@pytest.mark.asyncio
async def test_scoping_expiry_disconnect(setup):
    events, p, params, now, receiver = setup
    sub = await events.subscribe(p, {**params, "ttlMs": 60000})
    for changes in (
        {"from": "ares", "to": "grokbot"},
        {"to": "cli"},
        {"thread": "elsewhere"},
    ):
        await events.ingest(message(now[0], **changes))
    await events.deliver()
    assert len(receiver.calls) == 1
    now[0] += 61
    await events.ingest(message(now[0]))
    await events.deliver()
    assert len(receiver.calls) == 1
    await events.subscribe(p, params)
    await events.ingest(message(now[0]))
    await events.disconnect(p.subject)
    await events.deliver()
    assert not events.secrets.values
    assert Store(events.store.path).revoked(p.subject)
    with pytest.raises(PermissionError):
        await events.subscribe(p, params)
    assert sub["id"].startswith("sub_")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,attempts", [(500, 5), (429, 5), (410, 1), (413, 1), (302, 1), (400, 1)]
)
async def test_bounded_retry(setup, code, attempts):
    events, p, params, now, receiver = setup
    await events.subscribe(p, params)
    receiver.codes = [code] * 10
    await events.ingest(message(now[0]))
    for _ in range(7):
        await events.deliver()
        now[0] += 301
    deliveries = receiver.calls[1:]
    assert len(deliveries) == attempts
    assert len({r[2]["webhook-id"] for r in deliveries}) == 1
    assert len({r[2]["webhook-timestamp"] for r in deliveries}) == attempts


@pytest.mark.asyncio
async def test_limits_and_access_recheck(setup):
    events, p, params, now, receiver = setup
    events.per_thread, events.per_subscription, events.daily = 1, 2, 3
    await events.subscribe(p, params)
    for n in range(5):
        await events.ingest(message(now[0], str(n)))
    await events.deliver()
    assert len(receiver.accepted) == 1
    now[0] += 61
    await events.ingest(message(now[0], "six"))
    events.gateway.denied = True
    await events.deliver()
    assert len(receiver.accepted) == 1
    with events.store.conn() as c:
        assert (
            c.execute(
                "SELECT count(*) FROM deliveries WHERE state='limited'"
            ).fetchone()[0]
            >= 4
        )
        audit = str([tuple(r) for r in c.execute("SELECT * FROM audit")])
    assert (
        SECRET not in audit
        and "receiver.example" not in audit
        and "Untrusted" not in audit
    )


@pytest.mark.asyncio
async def test_bad_challenge_and_signature(setup):
    events, p, params, _now, receiver = setup
    receiver.bad_challenge = True
    with pytest.raises(CallbackError):
        await events.subscribe(p, params)
    assert not events.secrets.values
    receiver.bad_challenge = False
    receiver.secret = OTHER
    with pytest.raises(CallbackError):
        await events.subscribe(p, params)
    assert not events.secrets.values


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "198.18.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "2001:db8::1",
        "::ffff:8.8.8.8",
        "2002:0808:0808::1",
    ],
)
def test_real_address_policy(ip):
    with pytest.raises(ValueError):
        public_ip(ip)


@pytest.mark.parametrize(
    "url",
    [
        "http://receiver.example.com",
        "https://127.0.0.1",
        "https://2130706433",
        "https://[::1]",
        "https://a@receiver.example.com",
        "https://receiver.example.com:80",
        "https://receiver.example.com/#fragment",
        "https://receiver.example.com\\@evil.com",
        "https://receiver.example.com/\n",
    ],
)
def test_real_url_policy(url):
    with pytest.raises(ValueError):
        callback_url(url)


@pytest.mark.parametrize("size", [0, 23, 65, 100])
def test_secret_sizes(size):
    with pytest.raises(ValueError):
        secret_bytes("whsec_" + base64.b64encode(b"a" * size).decode())


def test_secret_good_and_payload_cap():
    for size in (24, 32, 64):
        assert (
            len(secret_bytes("whsec_" + base64.b64encode(b"a" * size).decode())) == size
        )
    with pytest.raises(ValueError):
        signed_headers(SECRET, "sub", "event", b"a" * 262145, 100)
    assert public_ip("8.8.8.8") == "8.8.8.8"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key, **changes):
    now = int(time.time())
    claims = {
        "sub": "matthew",
        "iss": ISSUER,
        "aud": RESOURCE,
        "exp": now + 3600,
        "iat": now,
        "scope": "messages:read messages:write events:read",
        **changes,
    }
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "elsewhere"},
        {"iss": "https://evil.example.com"},
        {"sub": "other"},
        {"exp": 1},
        {"nbf": 9999999999},
        {"scope": None},
        {"token_use": "id"},
    ],
)
def test_oauth_rejects(rsa_key, claims):
    v = OAuthVerifier(ISSUER, RESOURCE, rsa_key.public_key(), "matthew")
    with pytest.raises(PermissionError):
        v.verify("Bearer " + token(rsa_key, **claims))


@pytest.mark.asyncio
async def test_http_allowlist_and_auth(setup, rsa_key):
    events, _p, params, _now, _receiver = setup
    verifier = OAuthVerifier(ISSUER, RESOURCE, rsa_key.public_key(), "matthew")
    facade = Facade(events, verifier, resource=RESOURCE, issuer=ISSUER)
    async with TestClient(TestServer(facade.app)) as client:

        async def rpc(method, params=None, bearer=None):
            headers = {
                "Authorization": "Bearer " + (bearer or token(rsa_key)),
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": method,
            }
            if method == "tools/call":
                headers["Mcp-Name"] = params["name"]
            return await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": {
                        **(params or {}),
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                            "io.modelcontextprotocol/clientInfo": {
                                "name": "fake-chatgpt",
                                "version": "1",
                            },
                            "io.modelcontextprotocol/clientCapabilities": {},
                        },
                    },
                },
                headers=headers,
            )

        assert (await client.get("/.well-known/oauth-protected-resource")).status == 200
        assert (await client.post("/mcp", json={})).status == 401
        assert (await client.get("/health")).status == 404
        d = await (await rpc("server/discover")).json()
        assert d["result"]["supportedVersions"] == ["2026-07-28"]
        d = await (await rpc("tools/list")).json()
        assert {t["name"] for t in d["result"]["tools"]} == {
            "list_messages",
            "get_thread",
            "send_message",
        }
        for name in ("start_goal", "shell", "read_file", "approve", "handoff", "admin"):
            assert (await (await rpc("tools/call", {"name": name})).json())["error"][
                "code"
            ] == -32601
        assert (
            await rpc("events/list", bearer=token(rsa_key, scope="messages:read"))
        ).status == 403
        assert (
            await rpc("tools/list", bearer=token(rsa_key, aud="wrong"))
        ).status == 401
        d = await (await rpc("events/subscribe", params)).json()
        assert d["result"]["id"].startswith("sub_")
        d = await (
            await rpc(
                "tools/call", {"name": "get_thread", "arguments": {"thread": "private"}}
            )
        ).json()
        assert "result" not in d
        args = {
            "id": "reply",
            "thread": "hello",
            "to": "grokbot",
            "kind": "answer",
            "title": "hello",
            "body": "reply",
        }
        assert (
            "result"
            in await (
                await rpc("tools/call", {"name": "send_message", "arguments": args})
            ).json()
        )
        for changes in ({"from": "cli"}, {"to": "cli"}, {"caller": "grokbot"}):
            d = await (
                await rpc(
                    "tools/call",
                    {"name": "send_message", "arguments": {**args, **changes}},
                )
            ).json()
            assert "error" in d
        assert len(events.gateway.calls) == 1


@pytest.mark.asyncio
async def test_transport_rejects_mixed_dns_and_pins_public_answer(monkeypatch):
    import asyncio
    import socket

    import aiohttp

    calls = []
    loop = asyncio.get_running_loop()

    async def mixed(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ("8.8.8.8", "127.0.0.1")
        ]

    monkeypatch.setattr(loop, "getaddrinfo", mixed)
    with pytest.raises(ValueError):
        await PublicHTTPS().post("https://receiver.example.com/cb", b"{}", {})

    async def public(*args, **kwargs):
        calls.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", public)

    class Content:
        async def readexactly(self, maximum):
            assert maximum == 262145
            raise asyncio.IncompleteReadError(b"{}", maximum)

    class Response:
        status, content = 200, Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Connector:
        def __init__(self, **kwargs):
            assert kwargs["force_close"] is True
            assert kwargs["use_dns_cache"] is False
            self.resolver = kwargs["resolver"]

    class Session:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            self.connector = kwargs["connector"]

        async def __aenter__(self):
            records = await self.connector.resolver.resolve("receiver.example.com", 443)
            assert [r["host"] for r in records] == ["8.8.8.8"]
            with pytest.raises(ValueError):
                await self.connector.resolver.resolve("evil.example.com", 443)
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, url, **kwargs):
            assert url == "https://receiver.example.com/cb"  # TLS hostname retained
            assert kwargs["allow_redirects"] is False
            return Response()

    monkeypatch.setattr(aiohttp, "TCPConnector", Connector)
    monkeypatch.setattr(aiohttp, "ClientSession", Session)
    assert await PublicHTTPS().post("https://receiver.example.com/cb", b"{}", {}) == (
        200,
        b"{}",
    )
    assert len(calls) == 1  # resolver returns pinned values, never a second DNS lookup


@pytest.mark.asyncio
async def test_ttl_identity_limits_and_poll_restart(setup):
    events, p, params, now, receiver = setup
    assert Events.identity(p.subject, params)[0] != Events.identity("other", params)[0]
    ordered = {**params, "arguments": {"thread": "hello", "recipient": "ares"}}
    assert (
        Events.identity(p.subject, params)[0] == Events.identity(p.subject, ordered)[0]
    )
    sub = await events.subscribe(p, {**params, "ttlMs": 1000})
    from datetime import datetime

    assert datetime.fromisoformat(sub["refreshBefore"]).timestamp() == now[0] + 60
    assert (await events.subscribe(p, {**params, "ttlMs": None}))[
        "refreshBefore"
    ] is not None
    await events.poll()
    now[0] += 1
    events.gateway.messages.append(message(now[0]))
    await events.poll()
    assert len(receiver.accepted) == 1
    restart = Events(
        Store(events.store.path),
        events.secrets,
        events.gateway,
        transport=receiver,
        clock=lambda: now[0],
    )
    await restart.poll()
    assert len(receiver.accepted) == 1
    events.max_subscriptions = 1
    with pytest.raises(ValueError):
        await events.subscribe(p, {**params, "arguments": {"recipient": "ares"}})
    assert sum(events.store.admit(now[0]) for _ in range(65)) == 60


@pytest.mark.asyncio
async def test_real_gateway_adapter_fixed_ares_consumer(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway import caller_auth, client
    from jaeger_ai.features.mcp_events.gateway import AresGateway

    seen = []
    monkeypatch.setenv("JAEGER_CALLER_TOKEN_DIR", str(tmp_path))
    path = tmp_path / "ares.token"
    path.write_text("test-only-ares-credential")
    path.chmod(0o600)

    class Client:
        def __init__(self, base_url, *, caller, token):
            assert caller == "ares" and token == "test-only-ares-credential"

        def _call(self, method, path, body):
            seen.append((method, path, body))
            return {"messages": []}

    monkeypatch.setattr(client, "GatewayTurnClient", Client)
    monkeypatch.setattr(
        caller_auth,
        "client_token",
        lambda *a: pytest.fail("Must not provision credentials"),
    )
    gateway = AresGateway("http://127.0.0.1:33333")
    await gateway.list_messages()
    await gateway.get_thread("hello")
    await gateway.send_message(id="one", thread="hello", to="grokbot")
    assert len(seen) == 3
    with pytest.raises(ValueError):
        AresGateway("https://remote.example.com")
    with pytest.raises(ValueError):
        await gateway.get_thread("../admin")
    path.unlink()
    with pytest.raises(PermissionError):
        await gateway.list_messages()


def test_real_gateway_message_thread_isolation(tmp_path):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.features.agent_bridge.service import AgentMessages, BridgeError

    inbox = AgentMessages(GatewaySessionStore(tmp_path / "gateway.sqlite"))
    base = {
        "id": "one",
        "thread": "private",
        "to": "cli",
        "kind": "status",
        "title": "hi",
        "body": "private",
    }
    inbox.send("grokbot", base)
    inbox.send("grokbot", {**base, "id": "two", "thread": "shared", "to": "ares"})
    assert [m["id"] for m in inbox.list("ares")["messages"]] == ["two"]
    with pytest.raises(BridgeError):
        inbox.list("ares", thread="private")
    with pytest.raises(BridgeError):
        inbox.send("ares", {**base, "id": "reply", "to": "grokbot"})


@pytest.mark.asyncio
async def test_protocol_errors_caps_and_size(setup, rsa_key):
    events, _p, _params, _now, _receiver = setup
    facade = Facade(
        events,
        OAuthVerifier(ISSUER, RESOURCE, rsa_key.public_key(), "matthew"),
        resource=RESOURCE,
        issuer=ISSUER,
    )
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    async with TestClient(TestServer(facade.app)) as client:
        headers = {
            "Authorization": "Bearer " + token(rsa_key),
            "Mcp-Method": "tools/list",
            "MCP-Protocol-Version": "2026-07-28",
        }
        body = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/list",
            "params": {"_meta": meta},
        }
        assert (
            await client.post("/mcp", json=body, headers=headers)
        ).status == 200  # clientInfo is optional
        bad = {**headers, "Mcp-Method": "events/list"}
        r = await client.post("/mcp", json=body, headers=bad)
        assert r.status == 400 and (await r.json())["error"]["code"] == -32020
        r = await client.post("/mcp", json={**body, "params": {}}, headers=headers)
        assert r.status == 400
        legacy = {
            **body,
            "params": {
                "_meta": {
                    **meta,
                    "io.modelcontextprotocol/protocolVersion": "2025-11-25",
                }
            },
        }
        r = await client.post(
            "/mcp",
            json=legacy,
            headers={**headers, "MCP-Protocol-Version": "2025-11-25"},
        )
        assert r.status == 400 and (await r.json())["error"]["code"] == -32022
        assert (
            await client.post(
                "/mcp", json=body, headers={**headers, "Origin": "https://evil.example"}
            )
        ).status == 403
        assert (
            await client.post(
                "/mcp", json={**body, "padding": "a" * 40000}, headers=headers
            )
        ).status == 413
        body["params"] = {
            "name": "get_thread",
            "arguments": {"thread": "hello"},
            "_meta": meta,
        }
        body["method"] = "tools/call"
        encoded_name = "=?base64?" + base64.b64encode(b"get_thread").decode() + "?="
        r = await client.post(
            "/mcp",
            json=body,
            headers={**headers, "Mcp-Method": "tools/call", "Mcp-Name": encoded_name},
        )
        assert r.status == 200


@pytest.mark.parametrize(
    "ip", ["192.0.0.8", "192.0.0.9", "192.88.99.1", "2001:20::1", "3fff::1", "5f00::1"]
)
def test_reserved_ranges_across_python_versions(ip):
    with pytest.raises(ValueError):
        public_ip(ip)


@pytest.mark.asyncio
async def test_timeout_is_categorized_without_activation(setup):
    events, p, params, _now, _receiver = setup

    class Timeout:
        async def post(self, *args):
            raise TimeoutError("must not log URL or secret")

    events.transport = Timeout()
    with pytest.raises(CallbackError) as exc:
        await events.subscribe(p, params)
    assert exc.value.reason == "timeout"
    assert not events.secrets.values


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"arguments": {"recipient": "grokbot"}},
        {"arguments": {"recipient": "ares", "caller": "cli"}},
        {"arguments": {"recipient": "ares", "thread": "private"}},
        {"name": "goal.completed"},
        {"ttlMs": -1},
        {"ttlMs": True},
        {"cursor": "replay"},
    ],
)
async def test_rejects_unscoped_subscriptions(setup, changes):
    events, p, params, _now, receiver = setup
    with pytest.raises((ValueError, PermissionError)):
        await events.subscribe(p, {**params, **changes})
    assert not events.secrets.values and not receiver.calls


def test_keychain_adapter_is_explicit_and_secret_safe(monkeypatch):
    from jaeger_ai.features.mcp_events.security import KeychainSecrets

    values = {}

    class Backend:
        def get_password(self, service, account):
            assert service == "ai.jaeger.events"
            return values.get(account)

        def set_password(self, service, account, value):
            assert service == "ai.jaeger.events"
            values[account] = value

    monkeypatch.setattr(KeychainSecrets, "backend", staticmethod(lambda: Backend()))
    store = KeychainSecrets()
    store.put("sub_test", {"current": SECRET})
    assert store.get("sub_test") == {"current": SECRET}
    with pytest.raises(RuntimeError, match="Events secret unavailable"):
        store.get("missing")


@pytest.mark.asyncio
async def test_persistent_pending_delivery_survives_restart(setup):
    events, p, params, now, receiver = setup
    await events.subscribe(p, params)
    await events.ingest(message(now[0]))
    restarted = Events(
        Store(events.store.path),
        events.secrets,
        events.gateway,
        transport=receiver,
        clock=lambda: now[0],
    )
    await restarted.deliver()
    assert len(receiver.accepted) == 1
    await restarted.ingest(message(now[0]))
    await restarted.deliver()
    assert len(receiver.calls) == 2


def test_idp_metadata_requires_s256_and_valid_endpoints(rsa_key):
    v = OAuthVerifier(ISSUER, RESOURCE, rsa_key.public_key(), "matthew")
    metadata = {
        "issuer": ISSUER,
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
    }
    v.check_metadata(metadata)
    for changes in (
        {"issuer": RESOURCE},
        {"code_challenge_methods_supported": ["plain"]},
        {"token_endpoint_auth_methods_supported": []},
        {"token_endpoint": "http://insecure.example"},
    ):
        with pytest.raises(ValueError):
            v.check_metadata({**metadata, **changes})


@pytest.mark.asyncio
async def test_owned_gateway_facade_receiver_e2e(tmp_path, rsa_key):
    """Real loopback HTTP on both sides of facade + real Gateway message store.

    Gateway background/model startup is disabled. Receiver transport is simulated.
    No external DNS, webhooks, providers, operator state or credentials are used.
    """
    from jaeger_ai.core.gateway.caller_auth import read_token
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.features.mcp_events.gateway import AresGateway

    gateway = JaegerGatewayApp(
        store=GatewaySessionStore(tmp_path / "owned-gateway.sqlite")
    )
    gateway.app.on_startup.clear()
    receiver, secrets_store = Receiver(), Secrets()
    async with TestClient(TestServer(gateway.app)) as gw_client:
        events = Events(
            Store(tmp_path / "events.sqlite"),
            secrets_store,
            AresGateway(str(gw_client.make_url("")).rstrip("/")),
            transport=receiver,
        )
        facade = Facade(
            events,
            OAuthVerifier(ISSUER, RESOURCE, rsa_key.public_key(), "matthew"),
            resource=RESOURCE,
            issuer=ISSUER,
        )
        async with TestClient(TestServer(facade.app)) as mcp:

            async def call(method, params):
                meta = {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
                headers = {
                    "Authorization": "Bearer " + token(rsa_key),
                    "MCP-Protocol-Version": "2026-07-28",
                    "Mcp-Method": method,
                }
                if method == "tools/call":
                    headers["Mcp-Name"] = params["name"]
                response = await mcp.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": {**params, "_meta": meta},
                    },
                    headers=headers,
                )
                return await response.json()

            subscription = {
                "name": "message.created",
                "arguments": {"recipient": "ares"},
                "delivery": {
                    "mode": "webhook",
                    "url": "https://receiver.example.com/cb",
                    "secret": SECRET,
                },
            }
            assert "result" in await call("events/subscribe", subscription)
            await events.poll()  # initialize durable internal poll position
            msg = {
                "id": "hello",
                "thread": "owned",
                "to": "ares",
                "kind": "status",
                "title": "Hello",
                "body": "Controlled test data",
            }
            response = await gw_client.post(
                "/v1/agent-messages",
                json=msg,
                headers={"Authorization": "Bearer " + read_token("grokbot")},
            )
            assert response.status == 200
            await events.poll()
            assert len(receiver.accepted) == 1
            retrieved = await call(
                "tools/call", {"name": "get_thread", "arguments": {"thread": "owned"}}
            )
            assert (
                retrieved["result"]["structuredContent"]["messages"][0]["body"]
                == msg["body"]
            )
            await gw_client.post(
                "/v1/agent-messages",
                json={**msg, "id": "private", "thread": "private", "to": "cli"},
                headers={"Authorization": "Bearer " + read_token("grokbot")},
            )
            assert "error" in await call(
                "tools/call", {"name": "get_thread", "arguments": {"thread": "private"}}
            )
            reply = {**msg, "id": "reply", "to": "grokbot"}
            for _ in range(2):
                sent = await call(
                    "tools/call", {"name": "send_message", "arguments": reply}
                )
                assert sent["result"]["structuredContent"]["from"] == "ares"
            await events.poll()
            assert len(receiver.accepted) == 1
            with gateway.store._get_conn() as c:
                assert (
                    c.execute(
                        "SELECT count(*) FROM agent_messages WHERE sender='ares' AND id='reply'"
                    ).fetchone()[0]
                    == 1
                )
            assert "result" in await call("events/unsubscribe", subscription)


@pytest.mark.asyncio
async def test_expiry_rechecked_between_deliveries(setup):
    events, principal, params, now, receiver = setup
    await events.subscribe(principal, {**params, "ttlMs": 60000})
    await events.ingest(message(now[0], "first"))
    await events.ingest(message(now[0], "second"))
    original = receiver.post

    async def slow_receiver(*args):
        result = await original(*args)
        now[0] += 61
        return result

    receiver.post = slow_receiver
    await events.deliver()
    assert len(receiver.accepted) == 1
