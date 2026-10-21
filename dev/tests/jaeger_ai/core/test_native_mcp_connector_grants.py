"""GB-032: native_mcp.call_tool enforces connector grants before dispatch."""
from __future__ import annotations

import pytest

from jaeger_ai.core.gateway import native_mcp as nm
from jaeger_ai.core.gateway.connector_grants import ConnectorGrantStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    store = ConnectorGrantStore(tmp_path / "grants.sqlite3")
    monkeypatch.setattr(nm, "_grant_store", None)
    nm.set_connector_grant_store(store)
    client = nm.MCPClient("http://127.0.0.1:1/mcp", "", "127.0.0.1:1")
    client._session_id = "fixture"
    calls = []
    monkeypatch.setattr(client, "initialize", lambda: (_ for _ in ()).throw(AssertionError("no init")))
    monkeypatch.setattr(client, "_execute_call", lambda n, a: calls.append((n, a)) or {"ok": True})
    g, _ = store.create(connector="gmail", account_id="work", tools=["send"], scopes=["mail.send"])
    yield store, client, calls, g
    nm.set_connector_grant_store(None)


def test_allowed(env):
    store, client, calls, g = env
    out = client.call_tool("send", {"to": "x"}, grant={"grant_id": g.grant_id, "required_scopes": ["mail.send"],
                                                      "expected_revision": g.revision})
    assert out == {"ok": True} and calls == [("send", {"to": "x"})]


def test_account_lookup_and_reserved_argument_is_stripped(env):
    store, client, calls, g = env
    client.call_tool("send", {"to": "x", "_connector_grant": {"connector": "gmail", "account_id": "work"}})
    assert calls == [("send", {"to": "x"})]


def _denied(client, calls, grant, tool="send"):
    with pytest.raises(nm.ConnectorGrantDenied) as exc:
        client.call_tool(tool, {"to": "x"}, grant=grant)
    assert calls == []
    return exc.value


def test_revoked(env):
    store, client, calls, g = env
    store.revoke(g.grant_id)
    e = _denied(client, calls, {"grant_id": g.grant_id})
    assert e.result["reason"] == "grant_revoked" and "reauthorize gmail account work" in str(e)


def test_missing_scope(env):
    store, client, calls, g = env
    e = _denied(client, calls, {"grant_id": g.grant_id, "required_scopes": ["mail.delete"]})
    assert e.result["missing_scopes"] == ["mail.delete"] and "missing scope: mail.delete" in str(e)


def test_stale_revision(env):
    store, client, calls, g = env
    e = _denied(client, calls, {"grant_id": g.grant_id, "expected_revision": g.revision + 7})
    assert e.result["reason"] == "stale_grant_revision" and e.result["reconnect"]["account_id"] == "work"


def test_tool_not_granted(env):
    store, client, calls, g = env
    assert _denied(client, calls, {"grant_id": g.grant_id}, tool="delete").result["reason"] == "tool_not_granted"


def test_other_account_never_substituted(env):
    store, client, calls, g = env
    store.create(connector="gmail", account_id="personal", tools=["send"], scopes=["mail.send"])
    e = _denied(client, calls, {"connector": "gmail", "account_id": "nobody"})
    assert e.result["reason"] == "no_active_grant"
    e = _denied(client, calls, {"grant_id": g.grant_id, "account_id": "personal"})
    assert e.result["reason"] == "grant_account_mismatch"


def test_no_grant_path_unchanged(env, tmp_path):
    store, client, calls, g = env
    nm.set_connector_grant_store(None)
    assert client.call_tool("agent_info", {}) == {"ok": True}
    assert client.call_tool("send", {"a": 1}) == {"ok": True}
    assert calls == [("agent_info", {}), ("send", {"a": 1})]
    assert nm._grant_store is None  # store never resolved for ungranted calls
