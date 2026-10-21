"""GB-032 connector grants + the blueprint router (GB-031 preview), isolated fixtures."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from jaeger_ai.core.gateway.blueprint_routes import mount_blueprint_routes
from jaeger_ai.core.gateway.connector_grants import ConnectorGrantStore


@pytest.fixture
def store(tmp_path):
    return ConnectorGrantStore(tmp_path / "g.sqlite3")


def test_revoke_while_call_pending_fails_closed_with_reconnect(store):
    g, _ = store.create(connector="gmail", account_id="work", tools=["send"], scopes=["mail.send"])
    pending_rev = g.revision
    assert store.authorize_call(g.grant_id, tool="send", required_scopes=["mail.send"],
                                expected_revision=pending_rev)["allowed"] is True
    store.revoke(g.grant_id, reason="owner revoked")
    out = store.authorize_call(g.grant_id, tool="send", required_scopes=["mail.send"],
                               expected_revision=pending_rev)
    assert out["allowed"] is False and out["reason"] == "grant_revoked"
    assert out["reconnect"] == {"action": "reauthorize", "connector": "gmail", "account_id": "work"}


def test_regrant_supersedes_and_queued_call_on_old_revision_is_refused(store):
    old, _ = store.create(connector="gmail", account_id="work", tools=["send"], scopes=["a"])
    new, created = store.create(connector="gmail", account_id="work", tools=["send"], scopes=["a", "b"])
    assert created and new.revision == old.revision + 1
    assert store.authorize_call(old.grant_id, tool="send")["reason"] == "grant_superseded"


def test_duplicate_callback_makes_one_revision(store):
    a, c1 = store.create(connector="gh", account_id="me", tools=["issues"], scopes=["repo"], callback_id="cb-1")
    b, c2 = store.create(connector="gh", account_id="me", tools=["issues"], scopes=["repo"], callback_id="cb-1")
    assert (c1, c2) == (True, False) and a.grant_id == b.grant_id
    assert len(store.list(include_inactive=True)) == 1


def test_out_of_scope_denied_naming_scope_never_other_account(store):
    work, _ = store.create(connector="gmail", account_id="work", tools=["read"], scopes=["mail.read"])
    store.create(connector="gmail", account_id="personal", tools=["read"], scopes=["mail.read", "mail.send"])
    out = store.authorize_call(work.grant_id, tool="read", required_scopes=["mail.send"])
    assert out["allowed"] is False and out["missing_scopes"] == ["mail.send"]
    assert out["account_id"] == "work"


def test_reads_never_create_db(tmp_path):
    s = ConnectorGrantStore(tmp_path / "none.sqlite3")
    assert s.list() == [] and s.get("x") is None and not s.path.exists()


def test_wildcards_rejected(store):
    with pytest.raises(ValueError):
        store.create(connector="c", account_id="a", tools=["*"], scopes=[])


# ── routes ──────────────────────────────────────────────────────────────
def _gateway(tmp_path, caller, actor):
    events = []

    @web.middleware
    async def auth(request, handler):
        request["caller"], request["caller_actor"] = caller, actor
        return await handler(request)

    gw = SimpleNamespace(app=web.Application(middlewares=[auth]),
                         store=SimpleNamespace(path=tmp_path / "sessions.sqlite3"),
                         event_bus=SimpleNamespace(publish=lambda s, e, d: events.append((s, e, d))))
    mount_blueprint_routes(gw)
    return gw, events


OWNER = SimpleNamespace(scopes=frozenset({"admin", "read"}), session_prefix=None)


def _run(gw, fn):
    async def go():
        async with TestClient(TestServer(gw.app)) as c:
            return await fn(c)
    return asyncio.run(go())


def test_routes_forbid_non_owner(tmp_path):
    for caller, actor in [(OWNER, "agent:x"),
                          (SimpleNamespace(scopes=frozenset({"read"}), session_prefix=None), "owner:m"),
                          (SimpleNamespace(scopes=frozenset({"admin"}), session_prefix="mcp:"), "owner:m"),
                          (None, "")]:
        gw, _ = _gateway(tmp_path, caller, actor)

        async def f(c):
            return [(await c.get("/v1/connector-grants")).status,
                    (await c.post("/v1/authority/preview", json={"tool_name": "x"})).status]
        assert _run(gw, f) == [403, 403]


def test_grant_routes_roundtrip(tmp_path):
    gw, events = _gateway(tmp_path, OWNER, "owner:matthew")

    async def f(c):
        body = {"connector": "gmail", "account_id": "work", "tools": ["send"], "scopes": ["mail.send"],
                "callback_id": "cb9"}
        r1 = await c.post("/v1/connector-grants", json=body)
        r2 = await c.post("/v1/connector-grants", json=body)
        g = (await r1.json())["grant"]
        got = await c.get(f"/v1/connector-grants/{g['grant_id']}")
        chk = await (await c.post(f"/v1/connector-grants/{g['grant_id']}/check",
                                  json={"tool": "send", "required_scopes": ["mail.read"]})).json()
        rv = await c.post(f"/v1/connector-grants/{g['grant_id']}/revoke", json={"reason": "x"})
        lst = await (await c.get("/v1/connector-grants")).json()
        missing = await c.get("/v1/connector-grants/nope")
        bad = await c.post("/v1/connector-grants", json={"connector": "gmail"})
        return (r1.status, r2.status, got.status, chk, (await rv.json())["grant"]["status"], lst,
                missing.status, bad.status)
    s1, s2, sg, chk, st, lst, miss, bad = _run(gw, f)
    assert (s1, s2, sg, st, miss, bad) == (201, 200, 200, "revoked", 404, 400)
    assert chk["missing_scopes"] == ["mail.read"]
    assert lst == {"grants": []}
    assert [e[1] for e in events] == ["connector_grant.updated"] * 2 and events[0][0] == "*"


def test_preview_route_no_resident(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(tmp_path / "gs.json"))
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(tmp_path / "ll.json"))
    from jaeger_ai.core.entity.runtime import EntityRuntime
    monkeypatch.setattr(EntityRuntime, "_instance", None, raising=False)
    gw, _ = _gateway(tmp_path, OWNER, "owner:matthew")

    async def f(c):
        ok = await c.post("/v1/authority/preview", json={"tool_name": "read_file", "arguments": {"path": "a"},
                                                         "pending_rules": [{"scope": "local", "subject": "read_file",
                                                                            "effect": "deny"}]})
        bad = await c.post("/v1/authority/preview", json={"tool_name": "x", "pending_rules": [{"scope": "z"}]})
        rules = await c.get("/v1/authority/review-rules")
        return ok.status, await ok.json(), bad.status, await rules.json()
    st, body, bad, rules = _run(gw, f)
    assert st == 200 and body["dry_run"] is True and body["decision"] == "deny"
    assert body["winning_rule"]["pending"] is True and bad == 400
    assert rules["bound"] is False


def test_preview_route_with_live_runtime_layout(tmp_path, monkeypatch):
    """A bound runtime exposes an InstanceLayout (not a str); preview must use its root."""
    from jaeger_ai.core.authority.kernel import PolicyKernel, ProposedAction, ReviewRuleStore
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.instance.instance import InstanceLayout

    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(tmp_path / "gs.json"))
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(tmp_path / "ll.json"))
    (tmp_path / "inst").mkdir()
    layout = InstanceLayout(root=tmp_path / "inst")
    ReviewRuleStore.for_instance(layout).save({"scope": "team", "subject": "write_file", "effect": "deny"})
    monkeypatch.setattr(EntityRuntime, "_instance", SimpleNamespace(layout=layout), raising=False)
    gw, _ = _gateway(tmp_path, OWNER, "owner:matthew")

    async def f(c):
        p = await c.post("/v1/authority/preview", json={"tool_name": "write_file", "arguments": {"path": "a"}})
        r = await c.get("/v1/authority/review-rules")
        return p.status, await p.json(), await r.json()
    st, body, rules = _run(gw, f)
    assert st == 200 and body["decision"] == "deny"
    assert body["policy_name"] == "review_rules:team" and "fail-closed" not in body["reason"]
    assert rules["bound"] is True and rules["revisions"]["team"] == 1
    out = PolicyKernel().preview(ProposedAction(tool_name="write_file", arguments={}, actor="owner:m"),
                                 instance_root=layout)
    assert out["policy_name"] == "review_rules:team"
