"""GET /v1/presence: the avatar reads what Jaeger is doing; Stop shows as stopped."""
import asyncio
import json


def _app(tmp_path, monkeypatch, block=None):
    from jaeger_ai.core.gateway import server as srv
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    monkeypatch.setattr(srv, "_control_plane_block", lambda: block)
    return JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))


def _get(app):
    resp = asyncio.run(app.handle_presence(object()))
    return json.loads(resp.body)


def test_presence_is_idle_before_any_state(tmp_path, monkeypatch):
    assert _get(_app(tmp_path, monkeypatch)) | {"session_id": None} == {
        "state": "idle", "display": "idle", "session_id": None, "event_id": None, "owner_needed": False}


def test_presence_reports_the_newest_state_across_sessions(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    app.event_bus.publish_state("a", "thinking")
    app.event_bus.publish_state("b", "needs_owner")
    got = _get(app)
    assert (got["state"], got["display"], got["session_id"], got["owner_needed"]) == (
        "needs_owner", "ask_owner", "b", True)


def test_global_stop_shows_the_avatar_as_safely_stopped(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, block="Global Stop engaged")
    app.event_bus.publish_state("a", "working")
    assert _get(app)["display"] == "safe_stopped"
