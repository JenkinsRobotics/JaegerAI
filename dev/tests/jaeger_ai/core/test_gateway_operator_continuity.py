"""Gateway-owned agent peer identities and cross-device session continuity."""

from __future__ import annotations

import asyncio
import json

import pytest

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import (
    SCHEMA_VERSION,
    GatewaySessionStore,
    StateConflict,
)


def _body(response) -> dict:
    return json.loads(response.text)


class _OwnerRequest(dict):
    def __init__(self, method: str, body: dict | None = None, session_id: str | None = None):
        super().__init__(
            caller=caller_auth.CALLERS["webui"],
            caller_actor="owner:webui",
        )
        self.method = method
        self._body = body or {}
        self.can_read_body = body is not None
        self.match_info = {"id": session_id} if session_id is not None else {}

    async def json(self):
        return self._body


def test_peer_catalog_uses_authenticated_agent_identities():
    peers = caller_auth.agent_peer_catalog()
    by_id = {peer["id"]: peer for peer in peers}

    assert len(by_id) == len(peers)
    assert by_id["grokbot"] == {
        "id": "grokbot",
        "display_name": "Grok Bot",
        "kind": "external_agent",
        "actor": "mcp:grokbot",
        "transport": "agent_bridge",
        "framework_id": "grok",
        "session_prefix": "grokbot:",
        "scopes": ["read", "search", "turn"],
    }
    assert by_id["muse"]["session_prefix"] == "muse:"
    assert by_id["muse"]["transport"] == "mcp"
    assert by_id["hermes"]["transport"] == "message_hub"
    assert "webui" not in by_id
    assert caller_auth.prefixed_route_allowed("GET", "/v1/agent-peers", "grokbot")
    assert not caller_auth.prefixed_route_allowed(
        "GET", "/v1/operator/session-state", "grokbot",
    )


def test_active_session_survives_restart_and_rejects_stale_revision(tmp_path):
    path = tmp_path / "gateway.sqlite3"
    store = GatewaySessionStore(path)
    assert store.schema_version() == SCHEMA_VERSION
    store.ensure_session("shared-chat", title="Shared")

    selected = store.save_active_session(
        "shared-chat", actor="owner:webui", surface="webui", expected_revision=0,
    )
    assert selected["revision"] == 1
    assert GatewaySessionStore(path).active_session_state() == selected

    with pytest.raises(StateConflict):
        store.save_active_session(
            None, actor="owner:ide", surface="ide", expected_revision=0,
        )
    assert store.active_session_state()["active_session_id"] == "shared-chat"


def test_operator_state_route_is_revisioned_and_delete_clears_selection(tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("phone-and-mac", title="Same chat")

    response = asyncio.run(app.handle_operator_session_state(_OwnerRequest("PATCH", {
        "active_session_id": "phone-and-mac",
        "surface": "iphone",
        "expected_revision": 0,
    })))
    assert response.status == 200
    selected = _body(response)
    assert selected["active_session_id"] == "phone-and-mac"
    assert selected["surface"] == "iphone"

    stale = asyncio.run(app.handle_operator_session_state(_OwnerRequest("PATCH", {
        "active_session_id": None,
        "expected_revision": 0,
    })))
    assert stale.status == 409
    assert _body(stale)["state"]["active_session_id"] == "phone-and-mac"

    deleted = asyncio.run(app.handle_delete_session(
        _OwnerRequest("DELETE", session_id="phone-and-mac"),
    ))
    assert deleted.status == 200
    cleared = app.store.active_session_state()
    assert cleared["active_session_id"] is None
    assert cleared["revision"] == selected["revision"] + 1
    assert any(event.event == "session.active.changed"
               for event in app.event_bus.get_replay_events("*"))


def test_owner_create_and_queue_select_the_same_shared_conversation(tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    created = asyncio.run(app.handle_create_session(_OwnerRequest("POST", {
        "session_id": "shared-owner-chat",
        "title": "Shared owner chat",
        "source": "app",
    })))
    assert created.status == 201
    assert app.store.active_session_state()["active_session_id"] == "shared-owner-chat"

    queued = asyncio.run(app.handle_add_queue(_OwnerRequest(
        "POST", {"text": "Continue this on the next turn", "source": "webui"},
        session_id="shared-owner-chat",
    )))
    assert queued.status == 202
    state = app.store.active_session_state()
    assert state["active_session_id"] == "shared-owner-chat"
    assert state["surface"] == "webui"


def test_deleting_old_selection_does_not_clear_newer_device_choice(tmp_path, monkeypatch):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("old-chat")
    app.store.ensure_session("new-chat")
    app.store.save_active_session("old-chat", actor="owner:webui", surface="webui")
    delete_session = app.store.delete_session

    def select_on_other_device_then_delete(session_id: str) -> bool:
        app.store.save_active_session("new-chat", actor="owner:ide", surface="ide")
        return delete_session(session_id)

    monkeypatch.setattr(app.store, "delete_session", select_on_other_device_then_delete)
    deleted = asyncio.run(app.handle_delete_session(
        _OwnerRequest("DELETE", session_id="old-chat"),
    ))

    assert deleted.status == 200
    assert app.store.active_session_state()["active_session_id"] == "new-chat"


def test_non_owner_cannot_read_or_change_operator_session_state(tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    request = _OwnerRequest("GET")
    request["caller"] = caller_auth.CALLERS["grokbot"]
    request["caller_actor"] = "mcp:grokbot"

    response = asyncio.run(app.handle_operator_session_state(request))
    assert response.status == 403
