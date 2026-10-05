"""Per-caller authentication on the real Gateway app and middleware.

Before Phase 1b the Gateway had no credentials: any local process (or a
DNS-rebinding page that slipped past the cross-site check) could approve tool
calls, raise the tier, set autonomy or run owner turns. Now every non-public
route needs a caller token from ``caller_auth`` (Keychain in production, a
0600 token dir here), scopes are fixed per caller, outside callers (MCP, A2A)
are held to their own session prefix, and the authenticated actor - never a
body field - reaches the tool executor and PolicyKernel.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import CALLER_AUTH_KEY, JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def H(caller: str) -> dict[str, str]:
    headers = caller_auth.client_headers(caller)
    assert headers, f"test token for {caller} missing"
    return headers


@pytest_asyncio.fixture
async def gw(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "auth.sqlite3"))
    gateway.app.on_startup.clear()
    seen: list[dict] = []

    async def fake_inner(session_id, turn_id, text, *, request_id=None, execution=None):
        from jaeger_agent.tool_executor import active_caller_identity
        from jaeger_ai.core.authority.kernel import PolicyKernel, ProposedAction
        actor = active_caller_identity()
        decision = PolicyKernel().evaluate(ProposedAction(
            tool_name="terminal", arguments={"command": "ls"}, actor=actor, tier="write_local"))
        seen.append({"actor": actor, "execution_caller": (execution or {}).get("caller"),
                     "shell_decision": decision.decision.value, "policy": decision.policy_name})

    gateway._execute_turn_inner = fake_inner
    gateway.seen = seen
    async with TestClient(TestServer(gateway.app)) as client:
        client.gateway = gateway
        yield client


@pytest.mark.asyncio
async def test_public_health_needs_no_token(gw):
    # Health may report 503 (no runtime in this harness); it must not be 401.
    assert (await gw.get("/health")).status != 401


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("GET", "/v1/sessions"), ("GET", "/v1/approvals"), ("POST", "/v1/approvals/x"),
    ("POST", "/v1/runtime/autonomy"), ("POST", "/v1/runtime/tier"), ("POST", "/v1/sessions"),
    ("GET", "/v1/runtime/status"), ("POST", "/v1/tasks"), ("GET", "/v1/no-such-route"),
])
async def test_unauthenticated_requests_are_rejected(gw, method, path):
    resp = await gw.request(method, path, json={})
    assert resp.status == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Bearer")


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["Bearer wrong", "Bearer ", "Basic abc", "wrong", ""])
async def test_wrong_tokens_are_rejected(gw, value):
    resp = await gw.get("/v1/sessions", headers={"Authorization": value})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_token_of_one_caller_with_suffix_is_rejected(gw):
    good = H("menubar")["Authorization"]
    assert (await gw.get("/v1/sessions", headers={"Authorization": good + "x"})).status == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", ["menubar", "cli", "webui", "ide", "bridge", "jaegerd"])
async def test_owner_class_callers_read(gw, caller):
    assert (await gw.get("/v1/sessions", headers=H(caller))).status == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("caller,expected", [
    ("menubar", 404), ("cli", 404), ("webui", 404), ("ide", 404),
    ("bridge", 404), ("mcp", 403), ("a2a", 403), ("jaegerd", 403),
])
async def test_approve_scope(gw, caller, expected):
    resp = await gw.post("/v1/approvals/nope", json={"decision": "once"}, headers=H(caller))
    assert resp.status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("caller,allowed", [
    ("menubar", True), ("cli", True), ("webui", True), ("ide", True),
    ("bridge", False), ("jaegerd", False), ("mcp", False), ("a2a", False),
])
async def test_admin_routes_need_owner(gw, caller, allowed):
    resp = await gw.post("/v1/agents", json={}, headers=H(caller))
    if allowed:
        assert resp.status != 403 and resp.status != 401
    else:
        assert resp.status == 403


@pytest.mark.asyncio
async def test_ide_result_route_needs_ide_scope(gw):
    assert (await gw.post("/v1/sessions/s/ide/r", json={}, headers=H("menubar"))).status == 403
    assert (await gw.post("/v1/sessions/s/ide/r", json={}, headers=H("ide"))).status != 403


@pytest.mark.asyncio
@pytest.mark.parametrize("caller,prefix", [("mcp", "mcp:"), ("a2a", "a2a:")])
async def test_outside_callers_are_held_to_their_session_prefix(gw, caller, prefix):
    h = H(caller)
    assert (await gw.get("/v1/sessions", headers=h)).status == 403
    assert (await gw.get("/v1/approvals", headers=h)).status == 403
    assert (await gw.post("/v1/sessions", json={"session_id": "owner-chat"}, headers=h)).status == 403
    owner = await gw.post("/v1/sessions", json={"session_id": "owner-chat"}, headers=H("cli"))
    assert owner.status == 201
    assert (await gw.get("/v1/sessions/owner-chat", headers=h)).status == 403
    assert (await gw.post("/v1/sessions/owner-chat/turns", json={"text": "hi"}, headers=h)).status == 403
    mine = await gw.post("/v1/sessions", json={"session_id": prefix + "x"}, headers=h)
    assert mine.status == 201
    assert (await gw.get(f"/v1/sessions/{prefix}x", headers=h)).status == 200
    auto = await gw.post("/v1/sessions", json={}, headers=h)
    assert auto.status == 201
    assert (await auto.json())["session_id"].startswith(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize("caller,actor,shell", [
    ("menubar", "owner:menubar", None), ("cli", "owner:cli", None),
    ("mcp", "mcp", "deny"), ("a2a", "a2a", "deny"),
])
async def test_authenticated_actor_reaches_policy_kernel(gw, caller, actor, shell):
    sid = {"mcp": "mcp:t", "a2a": "a2a:t"}.get(caller, "owner-t")
    h = H(caller)
    assert (await gw.post("/v1/sessions", json={"session_id": sid}, headers=h)).status == 201
    # A forged body field must not change who the turn runs as.
    resp = await gw.post(f"/v1/sessions/{sid}/turns",
                         json={"text": "run ls", "caller": "owner:menubar"}, headers=h)
    assert resp.status == 200, await resp.text()
    import asyncio
    for _ in range(50):
        if gw.gateway.seen:
            break
        await asyncio.sleep(0.02)
    record = gw.gateway.seen[-1]
    assert record["actor"] == actor
    assert record["execution_caller"] == actor
    if shell == "deny":
        assert record["shell_decision"] == "deny"
        assert record["policy"] == "identity_trust"
    else:
        assert record["policy"] != "identity_trust"


@pytest.mark.asyncio
async def test_jaegerd_may_delegate_only_known_actors(gw):
    h = {**H("jaegerd"), "X-Jaeger-Actor": "mcp"}
    assert (await gw.post("/v1/sessions", json={"session_id": "inner"}, headers=h)).status == 201
    assert (await gw.post("/v1/sessions/inner/turns", json={"text": "x"}, headers=h)).status == 200
    import asyncio
    for _ in range(50):
        if gw.gateway.seen:
            break
        await asyncio.sleep(0.02)
    assert gw.gateway.seen[-1]["actor"] == "mcp"
    bad = {**H("jaegerd"), "X-Jaeger-Actor": "root"}
    assert (await gw.get("/v1/sessions", headers=bad)).status == 403
    # Only jaegerd may delegate; for anyone else the header is ignored.
    other = {**H("mcp"), "X-Jaeger-Actor": "owner:menubar"}
    assert (await gw.get("/v1/sessions", headers=other)).status == 403


@pytest.mark.asyncio
async def test_no_tokens_configured_fails_closed(gw, tmp_path, monkeypatch):
    empty = tmp_path / "empty-tokens"
    empty.mkdir()
    monkeypatch.setenv(caller_auth.TOKEN_DIR_ENV, str(empty))
    gw.gateway.app[CALLER_AUTH_KEY]["auth"] = caller_auth.CallerAuthenticator()
    assert (await gw.get("/v1/sessions", headers={"Authorization": "Bearer anything"})).status == 401


@pytest.mark.asyncio
async def test_authenticator_failure_is_503_not_open(gw, monkeypatch):
    def boom():
        raise RuntimeError("keychain exploded")
    monkeypatch.setattr(caller_auth, "CallerAuthenticator", boom)
    gw.gateway.app[CALLER_AUTH_KEY]["auth"] = None
    assert (await gw.get("/v1/sessions", headers=H("cli"))).status == 503


def test_token_files_must_be_private(tmp_path, monkeypatch):
    monkeypatch.setenv(caller_auth.TOKEN_DIR_ENV, str(tmp_path))
    path = tmp_path / "cli.token"
    path.write_text("abc")
    os.chmod(path, 0o644)
    with pytest.raises(caller_auth.TokenStoreError):
        caller_auth.read_token("cli")
    auth = caller_auth.CallerAuthenticator()
    assert "cli" not in auth.configured_callers
    assert auth.authenticate("Bearer abc") is None


def test_ensure_tokens_creates_missing_and_keeps_existing(tmp_path, monkeypatch):
    monkeypatch.setenv(caller_auth.TOKEN_DIR_ENV, str(tmp_path))
    first = caller_auth.ensure_tokens(["cli", "mcp"])
    assert first == {"cli": "created", "mcp": "created"}
    value = caller_auth.read_token("cli")
    assert caller_auth.ensure_tokens(["cli"]) == {"cli": "existing"}
    assert caller_auth.read_token("cli") == value
    assert oct(os.stat(tmp_path / "cli.token").st_mode & 0o777) == "0o600"
    assert caller_auth.read_token("cli") != caller_auth.read_token("mcp")


def test_unknown_caller_names_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv(caller_auth.TOKEN_DIR_ENV, str(tmp_path))
    with pytest.raises(caller_auth.TokenStoreError):
        caller_auth.read_token("admin")
    assert caller_auth.default_caller() in caller_auth.CALLERS
    monkeypatch.setenv("JAEGER_GATEWAY_CALLER", "admin")
    assert caller_auth.default_caller() == "cli"


def test_scopes_are_fixed_and_outside_callers_never_get_owner_scopes():
    for name in ("mcp", "a2a"):
        spec = caller_auth.CALLERS[name]
        assert not spec.scopes & {"admin", "approve", "ide"}
        assert spec.session_prefix == f"{name}:"
        from jaeger_ai.core.authority.kernel import is_untrusted_actor
        assert is_untrusted_actor(spec.actor)
    assert caller_auth.required_scope("POST", "/v1/runtime/autonomy") == "admin"
    assert caller_auth.required_scope("POST", "/v1/some/new/route") == "admin"
    assert caller_auth.required_scope("GET", "/health") is None
