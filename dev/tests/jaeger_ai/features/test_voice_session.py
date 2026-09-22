"""Voice is a way into the Entity, and its failures stay on its side.

Unit tests of :class:`VoiceSession` with scripted listener/speaker/gateway,
plus one integration test of :class:`GatewayTurnClient` against the real
Gateway app over a real socket (Entity scripted).
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from jaeger_ai.core.gateway.client import GatewayTurnClient, GatewayUnavailable, TurnResult
from jaeger_ai.features.voice.listeners import TypedListener
from jaeger_ai.features.voice.session import PrintSpeaker, VoiceSession


class _Gateway:
    def __init__(self, reply: str = "ORION-4812", *, down: bool = False) -> None:
        self.reply, self.down, self.turns, self.sessions = reply, down, [], []

    def entity_id(self) -> str:
        if self.down:
            raise GatewayUnavailable("connection refused")
        return "jaeger-entity-test"

    def ensure_session(self, session_id, *, title, source):
        self.sessions.append((session_id, source))

    def turn(self, session_id, text, *, timeout_s):
        if self.down:
            raise GatewayUnavailable("connection refused")
        self.turns.append((session_id, text))
        return TurnResult("r1", "completed", self.reply, model="ollama:test")


class _Speaker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail, self.said, self.stopped, self.playing = fail, [], 0, False

    def speak(self, text):
        if self.fail:
            raise RuntimeError("no output device")
        self.said.append(text)
        return {"spoken": True}

    def is_playing(self):
        return self.playing

    def stop(self):
        self.stopped += 1


def test_a_spoken_phrase_is_a_gateway_turn_on_a_voice_session():
    gateway, speaker = _Gateway(), _Speaker()
    session = VoiceSession(TypedListener(["What is my text audit token?"]), speaker,
                           gateway=gateway, session_id="voice-t")

    assert session.open() == "jaeger-entity-test"
    turn = session.step()

    assert gateway.sessions == [("voice-t", "voice")]
    assert gateway.turns == [("voice-t", "What is my text audit token?")]
    assert speaker.said == ["ORION-4812"]
    assert turn.spoken and turn.result.model == "ollama:test"
    assert set(turn.latencies_ms()) >= {"entity_turn", "speech_end_to_first_audio"}


def test_no_speech_output_degrades_to_printed_text():
    printed = []
    session = VoiceSession(TypedListener(["hi"]), _Speaker(fail=True), gateway=_Gateway("hello"))
    session.open()
    import jaeger_ai.features.voice.session as mod

    original = mod.PrintSpeaker
    mod.PrintSpeaker = lambda: PrintSpeaker(printed.append)
    try:
        turn = session.step()
    finally:
        mod.PrintSpeaker = original

    assert printed == ["jaeger> hello"]
    assert "speech output failed" in turn.error


def test_unreachable_entity_is_reported_and_the_session_keeps_listening():
    gateway = _Gateway()
    session = VoiceSession(TypedListener(["one", "two"]), _Speaker(), gateway=gateway)
    session.open()
    gateway.down = True

    first = session.step()
    gateway.down = False
    second = session.step()

    assert "not reachable" in first.error and first.result is None
    assert second.result.ok


def test_open_refuses_to_start_without_an_entity():
    with pytest.raises(GatewayUnavailable):
        VoiceSession(TypedListener([]), _Speaker(), gateway=_Gateway(down=True)).open()


def test_silence_is_not_a_turn():
    gateway = _Gateway()
    session = VoiceSession(TypedListener(["", "   "]), _Speaker(), gateway=gateway)
    session.open()

    assert session.step() is None and session.step() is None
    assert gateway.turns == []


def test_speech_during_playback_interrupts_a_speaker_that_can_stop():
    speaker = _Speaker()
    session = VoiceSession(TypedListener([]), speaker, gateway=_Gateway())
    speaker.playing = True

    session._on_speech_detected()

    assert speaker.stopped == 1


def test_gateway_client_round_trip_against_the_real_gateway(tmp_path, monkeypatch):
    """Client ↔ server contract over a socket; only the Entity is scripted."""
    from aiohttp import web

    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    class _Entity:
        def execute_turn(self, text, **_):
            return {"text": f"heard: {text}", "error": None,
                    "verification": {"status": "objective_unverified"}}

    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: _Entity()))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "voice.sqlite3"))
    gateway.app.on_startup.clear()
    monkeypatch.setattr(gateway, "_resolve_session_agent", lambda sid: None)

    loop = asyncio.new_event_loop()
    runner = web.AppRunner(gateway.app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "127.0.0.1", 0)
    loop.run_until_complete(site.start())
    port = site._server.sockets[0].getsockname()[1]
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        client = GatewayTurnClient(f"http://127.0.0.1:{port}")
        client.ensure_session("voice-rt", title="Voice", source="voice")
        result = client.turn("voice-rt", "what is my token", timeout_s=20)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.run_until_complete(runner.cleanup())
        loop.close()

    assert result.ok
    assert result.text == "heard: what is my token"
    assert result.verification == {"status": "objective_unverified"}
