"""Per-app MCP hub callers, collaboration tools and token CLI (2026-10-31)."""
from __future__ import annotations

import asyncio
import os
import stat

import pytest

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.caller_auth import APP_CALLERS, CALLERS


def test_app_callers_are_untrusted_and_prefixed():
    for name in APP_CALLERS:
        spec = CALLERS[name]
        assert spec.session_prefix == f"{name}:"
        assert spec.actor == f"mcp:{name}"
        assert spec.scopes == frozenset({"read", "turn", "handoff", "search"})
        assert not spec.scopes & {"approve", "delegate", "admin", "stop", "ide"}


def test_app_callers_cannot_approve_or_delegate_routes():
    assert caller_auth.required_scope("POST", "/v1/approvals/{id}/decide") == "approve"
    assert caller_auth.required_scope("POST", "/v1/agents/{id}/handoff") == "delegate"
    assert caller_auth.prefixed_route_allowed("POST", "/v1/agent-goals")
    assert caller_auth.prefixed_route_allowed("POST", "/v1/agent-messages")
    assert caller_auth.prefixed_route_allowed("GET", "/v1/agents")
    assert caller_auth.prefixed_route_allowed("GET", "/v1/approvals/counts")
    assert not caller_auth.prefixed_route_allowed("GET", "/v1/approvals")
    assert not caller_auth.prefixed_route_allowed("POST", "/v1/agents/{id}/handoff")


def test_mcp_server_accepts_app_callers_inbound():
    from jaeger_ai.interfaces import mcp_server

    for name in APP_CALLERS:
        assert name in mcp_server.MCP_INBOUND_CALLERS


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None):
        def deco(fn):
            self.tools[name or fn.__name__] = fn
            return fn
        return deco


class _FakeClient:
    def __init__(self):
        self.calls = []

    def _call(self, method, path, body=None):
        self.calls.append((method, path, body))
        return {"ok": True, "path": path}


def _register():
    from jaeger_ai.features.agent_bridge import mcp as bridge_mcp

    fake, client = _FakeMCP(), _FakeClient()
    bridge_mcp.register(fake, lambda ctx: client)
    return fake.tools, client


def _run(fn, **kw):
    return asyncio.run(fn(**kw))


def test_collaboration_tools_registered():
    tools, _ = _register()
    for name in ("list_agents", "handoff_task", "task_status", "task_result",
                 "post_result", "list_approvals", "receipts", "send_message",
                 "start_goal", "goal_status"):
        assert name in tools


def test_handoff_to_peer_is_inbox_task_message():
    tools, client = _register()
    out = _run(tools["handoff_task"], to="claude", task="review diff", thread="t1", id="h1")
    method, path, body = client.calls[-1]
    assert (method, path) == ("POST", "/v1/agent-messages")
    assert body["to"] == "claude" and body["kind"] == "task" and body["thread"] == "t1"
    assert out["kind"] == "message"


def test_handoff_to_jaeger_is_goal_through_gateway_approvals(tmp_path):
    tools, client = _register()
    _run(tools["handoff_task"], to="jaeger", task="summarise", thread="t2", id="g1",
         workspace_folder=str(tmp_path))
    assert client.calls[-2][1] == "/v1/agent-messages"
    assert client.calls[-2][2]["to"] == "jaegerd"
    method, path, body = client.calls[-1]
    assert (method, path) == ("POST", "/v1/agent-goals")
    assert body["workspace_folder"] == str(tmp_path)
    assert body["source_message_id"] == client.calls[-2][2]["id"]


def test_handoff_rejects_unknown_recipient():
    tools, _ = _register()
    with pytest.raises(ValueError):
        _run(tools["handoff_task"], to="nobody", task="x")


def test_post_result_and_approvals_routes():
    tools, client = _register()
    _run(tools["post_result"], to="codex", thread="t1", body="done", artifacts=["/tmp/a.md"])
    assert client.calls[-1][2]["kind"] == "result"
    assert client.calls[-1][2]["refs"] == ["/tmp/a.md"]
    _run(tools["list_approvals"])
    assert client.calls[-1][1] == "/v1/approvals/counts"


def test_token_cli_issues_private_file_without_printing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(caller_auth.TOKEN_DIR_ENV, str(tmp_path / "tokens"))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    from jaeger_ai.cli import mcp_tokens

    assert mcp_tokens.main(["issue", "codex"]) == 0
    value = caller_auth.read_token("codex")
    out = capsys.readouterr().out
    assert value and value not in out
    path = mcp_tokens.token_file("codex")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert path.read_text() == value
    assert mcp_tokens.main(["issue", "notanapp"]) == 2


def test_mcp_backend_wait_returns_when_bridge_ok(monkeypatch):
    from jaeger_ai.core.gateway import client as gw_client
    from jaeger_ai.interfaces.mcp_server import _wait_for_backend

    class NoGateway:
        def __init__(self, *a, **k):
            pass

        def probe(self):
            raise OSError("down")

    monkeypatch.setattr(gw_client, "GatewayTurnClient", NoGateway)

    class B:
        n = 0

        def health(self):
            B.n += 1
            return {"ok": B.n >= 2}

    assert _wait_for_backend(B(), wait_s=5, poll_s=0.01)["ok"]


def test_whoami_reports_caller_and_grants(monkeypatch, tmp_path):
    from jaeger_ai.features.agent_bridge import mcp as bridge_mcp

    class C(_FakeClient):
        caller = "codex"

    monkeypatch.setenv("JAEGER_AGENT_WORKSPACES", '{"codex": ["%s"]}' % tmp_path)
    fake = _FakeMCP()
    bridge_mcp.register(fake, lambda ctx: C())
    out = _run(fake.tools["whoami"])
    assert out["caller"] == "codex" and out["session_prefix"] == "codex:"
    assert out["workspace_roots"] == [str(tmp_path)]
    assert "approve" not in out["scopes"]


@pytest.mark.parametrize("status", ["done", "failed", "timeout", "error", "cancelled", "execution_unknown"])
def test_reported_execution_status_is_explicit(status):
    tools, client = _register()
    _run(tools["post_result"], to="ares", thread="t", body="arbitrary successful prose", status=status)
    assert client.calls[-1][2]["status_line"] == status


@pytest.mark.parametrize("status", ["", "completed", "unknown", "DONE", "failed (exit 1)", None, 0, [], {}])
def test_invalid_reported_execution_status_never_posts(status):
    tools, client = _register()
    with pytest.raises((ValueError, TypeError)):
        _run(tools["post_result"], to="ares", thread="t", body="done", status=status)
    assert client.calls == []
