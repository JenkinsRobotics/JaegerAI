"""Gateway-owned session archive state."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def test_store_archive_metadata_preserves_updated_at(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "archive.sqlite3")
    session = store.ensure_session("a", title="Plan")
    before = session["updated_at"]
    archived = store.set_session_archived("a", True)
    assert archived is not None
    assert archived["metadata"]["archived"] is True
    assert archived["updated_at"] == before
    unarchived = store.set_session_archived("a", False)
    assert unarchived["metadata"]["archived"] is False
    assert unarchived["updated_at"] == before


def test_store_archive_unknown_session_is_none(tmp_path: Path):
    assert GatewaySessionStore(tmp_path / "archive.sqlite3").set_session_archived("missing", True) is None


class _PatchRequest:
    def __init__(self, session_id: str, body: dict) -> None:
        self.match_info = {"id": session_id}
        self._body = body
        self.can_read_body = True

    async def json(self):
        return self._body


def _body(response) -> dict:
    return json.loads(response.text)


class TestSessionArchiveRoute:
    def _app(self, tmp_path):
        app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "archive.sqlite3"))
        return app

    def _create_session(self, app) -> str:
        session = app.store.ensure_session("archive-session", title="Archive me")
        return str(session["session_id"])

    def test_patch_archive_publishes_and_persists(self, tmp_path):
        app = self._app(tmp_path)
        sid = self._create_session(app)
        response = asyncio.run(app.handle_patch_session(_PatchRequest(sid, {"archived": True})))
        assert response.status == 200
        session = _body(response)
        assert session["metadata"]["archived"] is True
        listed = app.store.list_sessions()
        assert listed[0]["metadata"]["archived"] is True
        assert any(e.event == "session.updated" for e in app.event_bus.get_replay_events(sid))

    def test_invalid_combined_patch_changes_neither_title_nor_archive(self, tmp_path):
        app = self._app(tmp_path)
        sid = self._create_session(app)
        before = app.store.get_session(sid)
        response = asyncio.run(app.handle_patch_session(_PatchRequest(sid, {
            "title": "Should not change", "archived": "true",
        })))
        assert response.status == 400
        after = app.store.get_session(sid)
        assert after["title"] == before["title"]
        assert after["metadata"].get("archived") == before["metadata"].get("archived")

    def test_patch_rejects_bad_archived_and_unknown_session(self, tmp_path):
        app = self._app(tmp_path)
        sid = self._create_session(app)
        for value in ("true", 1, None, []):
            response = asyncio.run(app.handle_patch_session(_PatchRequest(sid, {"archived": value})))
            assert response.status == 400
        response = asyncio.run(app.handle_patch_session(_PatchRequest("missing", {"archived": True})))
        assert response.status == 404
        response = asyncio.run(app.handle_patch_session(_PatchRequest(sid, {})))
        assert response.status == 400
