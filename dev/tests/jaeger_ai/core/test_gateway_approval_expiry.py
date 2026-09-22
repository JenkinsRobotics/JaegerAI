"""An approval nobody answered must stop looking answerable.

Live defect (2026-09-21 audit): the tool-confirm waiter gave up after 300 s
and refused the tool call, but the approval row stayed ``pending``. The phone
kept offering it, and approving it then did nothing at all.
"""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway import server as gateway_server
from jaeger_ai.core.gateway.server import JaegerGatewayApp, _GatewayToolConfirmationProvider
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.fixture
def running_app(tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "approvals.sqlite3"))
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    app._loop = loop
    yield app
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _write_request():
    from jaeger_os.core.safety.permissions import PermissionTier

    return SimpleNamespace(
        tier=PermissionTier.WRITE_LOCAL, skill="files", operation="write_file",
        summary="write a file in the skills workspace",
        arguments={"path": "workspace/audit/a.txt", "content": "x" * 5000},
    )


def test_unanswered_approval_is_expired_when_the_tool_is_refused(running_app, monkeypatch):
    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.3)
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    created = []
    original = running_app.store.create_approval

    def record(**kwargs):
        created.append(kwargs["approval_id"])
        return original(**kwargs)

    monkeypatch.setattr(running_app.store, "create_approval", record)

    assert provider.confirm(_write_request()) is False

    assert running_app.store.list_pending_approvals() == []
    row = running_app.store.get_approval(created[0])
    assert row["status"] == "resolved"
    assert row["decision"] == "expired"
    assert not running_app.pending_approvals


def test_answer_that_lands_first_is_honoured(running_app, monkeypatch):
    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.3)
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    original = running_app.store.resolve_approval

    def operator_wins(approval_id, *, approved, decision=None):
        if decision == "expired":
            original(approval_id, approved=True, decision="once")
        return original(approval_id, approved=approved, decision=decision)

    monkeypatch.setattr(running_app.store, "resolve_approval", operator_wins)

    assert provider.confirm(_write_request()) is True


def test_prompt_names_the_target_not_just_the_operation(running_app, monkeypatch):
    """The phone showed "write a file in the skills workspace" for a write
    aimed at ~/JaegerAuditWorkspace, and ``reason: "1"`` for the tier."""
    monkeypatch.setattr(gateway_server, "APPROVAL_WAIT_S", 0.3)
    provider = _GatewayToolConfirmationProvider(running_app, "s", "r")
    created = []
    original = running_app.store.create_approval
    monkeypatch.setattr(
        running_app.store, "create_approval",
        lambda **kw: created.append(kw) or original(**kw),
    )

    provider.confirm(_write_request())

    [kw] = created
    assert kw["prompt"] == "Allow files.write_file? path=workspace/audit/a.txt"
    assert kw["metadata"]["reason"] == "WRITE_LOCAL"
    assert "content" not in kw["prompt"]


def test_restart_expires_tool_confirms_but_keeps_handoff_approvals(tmp_path):
    store = GatewaySessionStore(tmp_path / "restart.sqlite3")
    store.create_approval(kind="tool_confirm", prompt="p", options=["once", "deny"],
                          session_id="s", request_id="r", approval_id="approval_tool")
    store.create_approval(kind="handoff", prompt="p", options=["once", "deny"],
                          session_id="s", request_id="r", approval_id="approval_handoff")

    assert store.expire_orphaned_tool_confirms() == 1

    assert store.get_approval("approval_tool")["decision"] == "expired"
    assert [a["approval_id"] for a in store.list_pending_approvals()] == ["approval_handoff"]
