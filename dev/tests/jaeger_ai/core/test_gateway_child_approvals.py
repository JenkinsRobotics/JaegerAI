"""A background worker's card (filed under ``task:<id>``) shows up in the
parent chat: in ``GET /v1/approvals?session_id=<parent>``, on the parent's
stream as ``approval.request`` with ``origin``, and answering it there resolves
the worker's own card."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.server import JaegerGatewayApp, _GatewayToolConfirmationProvider
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.fixture
def running_app(tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "child.sqlite3"))
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    app._loop = loop
    app.store.ensure_session("chat-1", title="parent", profile="jaeger")
    app.store.ensure_session("task:task_abc", title="worker", profile="jaeger",
                             metadata={"task_id": "task_abc", "parent_session_id": "chat-1", "actionable": True})
    app.store.ensure_session("chat-2", title="other", profile="jaeger")
    yield app
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


@pytest.fixture(autouse=True)
def ask_mode():
    from jaeger_ai.core.runtime import autonomy
    before = dict(autonomy._state)
    autonomy.set_autonomy("ask")
    yield
    autonomy._state.clear()
    autonomy._state.update(before)


def _write():
    from jaeger_os.core.safety.permissions import PermissionTier
    return SimpleNamespace(tier=PermissionTier.WRITE_LOCAL, skill="files", operation="write_file",
                           summary="write a report", arguments={"path": "/tmp/x/report.md", "content": "x"})


def _call(app, coro):
    return asyncio.run_coroutine_threadsafe(coro, app._loop).result(timeout=5)


def _list(app, sid=None):
    req = SimpleNamespace(query={"session_id": sid} if sid else {})
    return json.loads(_call(app, app.handle_list_approvals(req)).text)["approvals"]


def _resolve(app, aid, decision):
    async def body():
        return {"decision": decision}
    req = SimpleNamespace(match_info={"id": aid}, can_read_body=True, json=body)
    return json.loads(_call(app, app.handle_resolve_approval(req)).text)


def _park(app):
    provider = _GatewayToolConfirmationProvider(app, "task:task_abc", "task_abc:0")
    out = {}
    worker = threading.Thread(target=lambda: out.setdefault("ok", provider.confirm(_write())), daemon=True)
    worker.start()
    for _ in range(100):
        if app.store.list_pending_approvals():
            break
        time.sleep(0.02)
    return worker, out


@pytest.mark.parametrize("decision,expected", [("once", True), ("deny", False)])
def test_parent_sees_and_resolves_the_workers_card(running_app, decision, expected):
    worker, out = _park(running_app)
    origin = {"task_id": "task_abc", "child_session_id": "task:task_abc",
              "agent_id": "native:jaeger", "parent_session_id": "chat-1"}

    rows = _list(running_app, "chat-1")
    assert len(rows) == 1 and rows[0]["session_id"] == "task:task_abc"
    assert rows[0]["origin"] == origin
    assert _list(running_app, "chat-2") == []
    assert len(_list(running_app)) == 1                      # unfiltered list unchanged

    parent_events = [e for e in running_app.event_bus.get_replay_events("chat-1")
                     if e.event == "approval.request"]
    assert len(parent_events) == 1
    assert parent_events[0].data["approval_id"] == rows[0]["approval_id"]
    assert parent_events[0].data["origin"] == origin
    child_events = [e for e in running_app.event_bus.get_replay_events("task:task_abc")
                    if e.event == "approval.request" and e.session_id == "task:task_abc"]
    assert len(child_events) == 1

    resolved = _resolve(running_app, rows[0]["approval_id"], decision)
    worker.join(timeout=5)
    assert out["ok"] is expected
    assert resolved["origin"] == origin and resolved["session_id"] == "task:task_abc"
    assert _list(running_app, "chat-1") == []
    assert running_app.store.get_approval(rows[0]["approval_id"])["decision"] == decision


def test_top_level_cards_have_no_origin(running_app):
    provider = _GatewayToolConfirmationProvider(running_app, "chat-2", "r1")
    worker = threading.Thread(target=lambda: provider.confirm(_write()), daemon=True)
    worker.start()
    for _ in range(100):
        if running_app.store.list_pending_approvals():
            break
        time.sleep(0.02)
    rows = _list(running_app, "chat-2")
    assert len(rows) == 1 and "origin" not in rows[0]
    assert _list(running_app, "chat-1") == []
    _resolve(running_app, rows[0]["approval_id"], "deny")
    worker.join(timeout=5)
