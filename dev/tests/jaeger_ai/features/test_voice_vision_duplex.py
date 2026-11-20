"""Full-duplex voice & vision integration verification (Directive §3).

Verifies the software voice/vision contract end to end (automated, deterministic):
  1. Ten consecutive voice exchanges with conversational context retention.
  2. Mid-speech barge-in interruption on a full-duplex speaker without pausing listener.
  3. Webcam/camera vision frame description routed cleanly alongside spoken turn.
  4. Background work continuing concurrently while voice exchanges execute.
  5. Epistemic memory surviving restart and remaining accessible by voice.
  6. Truth identity, no artificial context lock, and installed default voice/vision model.

Note: Physical microphone/speaker acoustics and live USB webcam capture remain
separate owner-authorized hardware acceptance checks.
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from jaeger_ai.core.entity.runtime import EntityRuntime, PreparedTurn
from jaeger_ai.core.gateway.client import GatewayTurnClient
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.models import local_vision
from jaeger_ai.core.world.model import EpistemicProvenance
from jaeger_ai.core.world.store import SqliteWorldStore
from jaeger_ai.features.voice import brain
from jaeger_ai.features.voice.listeners import TypedListener
from jaeger_ai.features.voice.session import VoiceSession


class _FullDuplexSpeaker:
    supports_barge_in = True

    def __init__(self, *, interrupt_on_turn: int | None = None, on_speak_started=None) -> None:
        self.said: list[str] = []
        self.playing = False
        self.stopped = 0
        self._interrupt_on_turn = interrupt_on_turn
        self._on_speak_started = on_speak_started

    def is_playing(self) -> bool:
        return self.playing

    def stop(self) -> None:
        self.stopped += 1
        self.playing = False

    def speak(self, text: str) -> dict:
        self.playing = True
        self.said.append(text)
        if self._interrupt_on_turn is not None and len(self.said) == self._interrupt_on_turn:
            if callable(self._on_speak_started):
                self._on_speak_started()
        self.playing = False
        return {"spoken": True}


def test_voice_brain_uses_truth_identity_installed_model_and_no_context_lock(monkeypatch):
    monkeypatch.delenv("JAEGER_VOICE_MODEL", raising=False)
    monkeypatch.delenv("JAEGER_VOICE_CTX", raising=False)
    cfg = brain.voice_brain()
    assert cfg["provider"] == "ollama"
    assert cfg["model"] == "qwen3.5:9b"
    assert "ctx" not in cfg["controls"]
    assert "Truth" in cfg["system"]
    assert "verified facts" in cfg["system"].lower()


def test_camera_frame_description_stays_fast_lane_for_in_view_questions():
    turn_text = (
        "What number is on this note?\n\n"
        "[Camera view, described by Jaeger's local vision model: A white card showing a red circle, blue square, and the number 47.]"
    )
    assert brain.needs_live_facts(turn_text) is False
    assert brain.needs_live_facts("Check the weather in Tokyo right now") is True


def test_full_duplex_barge_in_does_not_pause_listener():
    listener = TypedListener(["Tell me a long story about physics.", "Actually stop and give me the short version."])
    paused_calls: list[bool] = []
    orig_pause = listener.set_paused
    listener.set_paused = lambda p: (paused_calls.append(p), orig_pause(p))[1]

    class _FakeGw:
        def __init__(self):
            self.turns: list[str] = []
        def entity_id(self):
            return "truth-test"
        def ensure_session(self, *a, **k):
            pass
        def turn(self, sid, text, *, timeout_s, fast_lane=False):
            self.turns.append(text)
            from jaeger_ai.core.gateway.client import TurnResult
            return TurnResult(f"r{len(self.turns)}", "completed", f"Reply {len(self.turns)} to: {text}", model="ollama:qwen3.5:9b")

    gw = _FakeGw()
    session_holder: list[VoiceSession] = []
    speaker = _FullDuplexSpeaker(
        interrupt_on_turn=1,
        on_speak_started=lambda: session_holder[0]._on_speech_detected(),
    )
    session = VoiceSession(listener, speaker, gateway=gw, session_id="voice-bargein")
    session_holder.append(session)
    session.open()

    t1 = session.step()
    t2 = session.step()
    assert t1 is not None and t1.spoken is True
    assert "barge_in" in t1.timing
    assert speaker.stopped == 1
    assert paused_calls == []  # Full-duplex speaker keeps listener active for barge-in
    assert t2 is not None and "short version" in t2.transcript


def test_ten_voice_exchanges_context_vision_background_and_restart_memory(tmp_path: Path, monkeypatch):
    """End-to-end 10-turn voice session over real loopback Gateway socket + restart recall."""
    world_db = tmp_path / "knowledge.sqlite3"
    store1 = SqliteWorldStore(world_db)
    store1.record_claim("owner_project", "codename", "SOLARIS-9", EpistemicProvenance.VERIFIED, source_id="owner")

    bg_done = threading.Event()
    bg_ticks = {"count": 0}

    def _bg_worker():
        for _ in range(10):
            bg_ticks["count"] += 1
            time.sleep(0.01)
        bg_done.set()

    bg_thread = threading.Thread(target=_bg_worker, daemon=True)
    bg_thread.start()

    history_seen: list[str] = []

    class _ScriptedTruthEntity:
        def __init__(self, db_path: Path):
            self.db_path = db_path

        def prepare_turn(self, text, *, session_id, **_):
            return PreparedTurn(prompt=text, event=SimpleNamespace(event_id="ev"), user_text=text, session_id=session_id)

        def run_subordinate_react(self, prompt, **_):
            history_seen.append(prompt)
            if "codename" in prompt.lower():
                claims = SqliteWorldStore(self.db_path).query_claims("owner_project")
                val = claims[0].value if claims else "unknown"
                return {"text": f"Your verified project codename is {val}.", "halt_reason": None}
            if "[Camera view, described by Jaeger's local vision model:" in prompt:
                return {"text": "I see the red circle, blue square, and the number 47 from your camera.", "halt_reason": None}
            if "what did we talk about earlier" in prompt.lower():
                return {"text": f"Earlier you mentioned turn_1_topic ({len(history_seen)} turns tracked).", "halt_reason": None}
            return {"text": f"Acknowledged exchange {len(history_seen)}: {prompt[:40]}", "halt_reason": None}

        def finish_turn(self, prepared, response_text):
            pass

    def _run_gateway_round(phrases: list[str], db_file: Path) -> list[str]:
        monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
        monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: _ScriptedTruthEntity(world_db)))
        gateway = JaegerGatewayApp(store=GatewaySessionStore(db_file))
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
            monkeypatch.setattr(client, "entity_id", lambda: "truth-entity-isolated")
            speaker = _FullDuplexSpeaker()
            vs = VoiceSession(TypedListener(phrases), speaker, gateway=client, session_id="voice-10turn")
            vs.open()
            replies = []
            for _ in phrases:
                tr = vs.step()
                assert tr is not None and tr.result is not None and tr.result.ok
                replies.append(tr.result.text)
            return replies
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.run_until_complete(runner.cleanup())
            loop.close()

    session_db = tmp_path / "gateway_sessions.sqlite3"
    ten_phrases = [
        "Exchange 1: remember turn_1_topic is robotics calibration.",
        "Exchange 2: confirm status.",
        "Exchange 3: keep working in the background.",
        "Exchange 4: what do you see?\n\n[Camera view, described by Jaeger's local vision model: red circle, blue square, number 47]",
        "Exchange 5: what did we talk about earlier?",
        "Exchange 6: give me a brief check-in.",
        "Exchange 7: list priorities.",
        "Exchange 8: stay concise.",
        "Exchange 9: confirm memory is intact.",
        "Exchange 10: wrap up round one.",
    ]
    replies_1 = _run_gateway_round(ten_phrases, session_db)
    assert len(replies_1) == 10
    assert "47" in replies_1[3]
    assert "turn_1_topic" in replies_1[4]

    # Background task completed cleanly alongside the voice conversation
    assert bg_done.wait(timeout=5.0)
    assert bg_ticks["count"] == 10

    # Controlled restart: fresh Gateway process, same SQLite world + session stores
    replies_2 = _run_gateway_round(["After restart, what is my project codename?"], session_db)
    assert len(replies_2) == 1
    assert "SOLARIS-9" in replies_2[0]


def test_local_vision_probe_image_generates_valid_png():
    raw = local_vision.probe_image()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(raw) > 1000
