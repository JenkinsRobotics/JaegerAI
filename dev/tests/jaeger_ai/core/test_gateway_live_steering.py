"""Gateway-owned live steering for an active ReAct request."""

from __future__ import annotations

import asyncio
import json

from jaeger_ai.core.gateway.event_bus import EVENT_TYPES
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class _FakeAgent:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.seen: list[str] = []

    def steer(self, text: str) -> bool:
        self.seen.append(text)
        return self.accepted


class _Request:
    def __init__(self, *, session_id: str, request_id: str, body: dict):
        self.match_info = {"id": session_id, "request_id": request_id}
        self._body = body
        self.can_read_body = True

    async def json(self):
        return self._body


class TestGatewayLiveSteering:
    def _app(self, tmp_path):
        app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
        app.store.admit_request("session", "work", request_id="steer-1")
        app.store.mark_request_status("steer-1", "running")
        return app

    def test_steer_event_is_first_class(self):
        assert "turn.steer" in EVENT_TYPES

    def test_live_steer_reaches_the_active_agent_and_publishes_an_event(self, tmp_path):
        app = self._app(tmp_path)
        agent = _FakeAgent()
        app._active_agents["steer-1"] = agent

        response = asyncio.run(app.handle_steer_request(_Request(
            session_id="session", request_id="steer-1", body={"text": "use metric units"},
        )))

        assert response.status == 200
        payload = json.loads(response.text)
        assert payload == {"request_id": "steer-1", "steered": True, "queued": True}
        assert agent.seen == ["use metric units"]
        steering = [e for e in app.event_bus.get_replay_events("session") if e.event == "turn.steer"]
        assert len(steering) == 1
        assert steering[0].data == {
            "request_id": "steer-1", "text": "use metric units", "queued": True,
        }

    def test_text_only_or_unbound_request_returns_honest_409(self, tmp_path):
        app = self._app(tmp_path)
        response = asyncio.run(app.handle_steer_request(_Request(
            session_id="session", request_id="steer-1", body={"text": "try again"},
        )))
        assert response.status == 409
        assert "no active ReAct agent" in json.loads(response.text)["error"]

    def test_agent_refusal_is_409_not_a_second_turn(self, tmp_path):
        app = self._app(tmp_path)
        app._active_agents["steer-1"] = _FakeAgent(accepted=False)
        response = asyncio.run(app.handle_steer_request(_Request(
            session_id="session", request_id="steer-1", body={"text": "not now"},
        )))
        assert response.status == 409
        assert json.loads(response.text)["error"] == "Agent did not accept steering"

    def test_terminal_request_cannot_be_steered(self, tmp_path):
        app = self._app(tmp_path)
        app.store.complete_request(
            "steer-1", status="completed", result={"output": "done"}, assistant_text="done",
        )
        response = asyncio.run(app.handle_steer_request(_Request(
            session_id="session", request_id="steer-1", body={"text": "late"},
        )))
        assert response.status == 409
        assert json.loads(response.text)["error"] == "Request is already terminal"

    def test_empty_text_is_rejected_before_agent_lookup(self, tmp_path):
        app = self._app(tmp_path)
        app._active_agents["steer-1"] = _FakeAgent()
        response = asyncio.run(app.handle_steer_request(_Request(
            session_id="session", request_id="steer-1", body={"text": "   "},
        )))
        assert response.status == 400
        assert json.loads(response.text)["error"] == "Steering text is required"

    def test_wrong_session_is_404(self, tmp_path):
        app = self._app(tmp_path)
        response = asyncio.run(app.handle_steer_request(_Request(
            session_id="other", request_id="steer-1", body={"text": "wrong session"},
        )))
        assert response.status == 404
