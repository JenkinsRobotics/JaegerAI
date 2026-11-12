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
        self.clock = time.time

    async def post(self, url, body, headers):
        self.calls.append((url, body, dict(headers)))
        stamp, event = headers["webhook-timestamp"], headers["webhook-id"]
        if abs(self.clock() - int(stamp)) > 300:
            return 401, b"{}"
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




















class DiskSecrets:
    """Test-only private files; never exported as a production secret adapter."""

    def __init__(self, root):
        self.root = root
        root.mkdir(mode=0o700, exist_ok=True)

    def get(self, name):
        return json.loads((self.root / name).read_text())

    def put(self, name, value):
        import os

        fd = os.open(self.root / name, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)

    def delete(self, name):
        (self.root / name).unlink(missing_ok=True)




































