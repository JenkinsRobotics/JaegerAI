"""Always-on voice — pure-logic tests.

The live mic loop needs hardware + Whisper + a model, so it can't be
unit-tested. What CAN be tested is the logic around it: the VoiceConfig
defaults, wake-phrase derivation, stop-phrase detection, the typed
trigger, VoiceController construction, and /voice argument parsing.
"""

from __future__ import annotations

from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from rich.console import Console

from jaeger_os import topics
from jaeger_os.core.instance.schemas import VoiceConfig
from jaeger_os.interfaces.tui import slash_commands as slash
from jaeger_os.interfaces.tui.app import _wants_voice_mode
from jaeger_os.interfaces.tui.voice_session import (
    VoiceController,
    _wake_phrases,
    is_exit_phrase,
)


# ── VoiceConfig defaults ─────────────────────────────────────────────


def test_voice_config_defaults_match_voicellm_proven_pattern() -> None:
    """``enabled`` defaults OFF so a fresh install doesn't surprise
    the user with an open mic (VOICE-1 / docs/ROADMAP_0.2.0.md).

    0.4.x: when enabled IS flipped, the defaults match the proven
    VoiceLLM continuous-listening pattern (validated 2026-06-06):
      - wake_word ON    — the wake phrase is the addressed-to-me gate
                          (the in-brain LLM <reply>/<ignore> gate was
                          removed 2026-06-16; wake word replaces it)
      - barge_in  OFF   — mic-pause during TTS (VoiceLLM's reference
                          self-speech rejection strategy)
      - follow_up ON, follow_up_seconds=10.0 (reference value)
      - self_speech_filter ON, threshold=0.75
    """
    vc = VoiceConfig()
    assert vc.enabled is False
    assert vc.wake_word is True
    assert vc.barge_in is False
    assert vc.follow_up is True
    assert vc.follow_up_seconds == 10.0
    assert vc.self_speech_filter is True
    assert vc.self_speech_threshold == 0.75


def test_voice_config_enabled_can_be_turned_on_explicitly() -> None:
    """The wizard sets ``enabled=True`` only when the user explicitly
    picks voice as the default interaction mode AND opts in to the
    always-on mic. Confirm the field still accepts the truthy value."""
    vc = VoiceConfig(enabled=True)
    assert vc.enabled is True


# ── wake-phrase derivation ───────────────────────────────────────────


def test_wake_phrases_cover_both_persona_and_system_names() -> None:
    """'Erin Jaeger' must wake on either name — the persona ('hey erin') for
    natural address, the system ('hey jaeger' + phonetic variants) because
    JaegerOS is the platform regardless of the per-instance name."""
    phrases = _wake_phrases("Erin Jaeger")
    # persona
    for prefix in ("ok", "okay", "hey"):
        assert f"{prefix} erin" in phrases
    # system + a phonetic variant Whisper commonly mishears
    assert "hey jaeger" in phrases
    assert "hey yeager" in phrases
    # banner-facing phrase shows the persona, not a phonetic variant
    assert phrases[-1] == "hey erin"


def test_wake_phrases_single_name_still_includes_system_default() -> None:
    phrases = _wake_phrases("Jarvis")
    assert "hey jarvis" in phrases
    assert "hey jaeger" in phrases   # system always reachable
    assert phrases[-1] == "hey jarvis"


def test_wake_phrases_empty_or_jaeger_falls_back_to_defaults() -> None:
    assert len(_wake_phrases("")) == 12
    assert "hey jaeger" in _wake_phrases("jaeger")


# ── stop-phrase detection ────────────────────────────────────────────


def test_exit_phrase_matches_mic_off_commands() -> None:
    for p in ("stop", "Stop.", " mic off ", "stop listening",
              "turn off the mic", "go to sleep"):
        assert is_exit_phrase(p), p


def test_exit_phrase_ignores_embedded_stop() -> None:
    for p in ("should I stop the server",
              "what does the exit code mean",
              "turn off the lights in the kitchen"):
        assert not is_exit_phrase(p), p


# ── typed natural-language trigger ───────────────────────────────────


def test_wants_voice_mode_on_activation_phrases() -> None:
    for p in ("mic on", "turn on mic", "turn on the microphone",
              "voice mode", "enable the mic"):
        assert _wants_voice_mode(p), p


def test_wants_voice_mode_ignores_long_coding_requests() -> None:
    long_req = ("write code to turn on the microphone via applescript "
                "and document the whole flow in the README please")
    assert not _wants_voice_mode(long_req)
    assert not _wants_voice_mode("tell me a joke")


# ── VoiceController construction ─────────────────────────────────────


def test_voice_controller_constructs_without_starting() -> None:
    # Construction must not touch hardware — start() does that.
    c = VoiceController(Console(file=open("/dev/null", "w")),
                        wake_name="Erin Jaeger")
    assert c.running is False
    assert c.barge_in_live is False  # only true after start() with speexdsp
    assert c.wake_word_phrase == "hey erin"


def test_voice_controller_carries_settings() -> None:
    c = VoiceController(Console(file=open("/dev/null", "w")),
                        wake_word=False, follow_up=False, barge_in=False)
    assert (c.wake_word, c.follow_up, c.barge_in) == (False, False, False)


def test_arm_interrupt_is_safe_before_start() -> None:
    # arm/disarm with no live STT must be no-ops, never raise — the REPL
    # calls them around every turn whether or not the mic came up.
    import threading
    c = VoiceController(Console(file=open("/dev/null", "w")))
    ev = threading.Event()
    c.arm_interrupt(ev)
    c.disarm_interrupt()


class _FakeSpeechBus:
    def __init__(self, *, ack_ok: bool = True, fire_barge_in=None):
        self.ack_ok = ack_ok
        self.fire_barge_in = fire_barge_in
        self.requests = []
        self.published = []

    def request(self, request_msg, *, ack_topic, timeout_s):
        self.requests.append((request_msg, ack_topic, timeout_s))
        if self.fire_barge_in is not None:
            self.fire_barge_in()
        return SimpleNamespace(
            ok=self.ack_ok,
            reason="interrupted" if not self.ack_ok else None,
        )

    def publish(self, msg):
        self.published.append(msg)


class _FakeSTT:
    def __init__(self):
        self.paused = []
        self.on_speech_detected = None
        self.drained = False

    def set_paused(self, value):
        self.paused.append(value)

    def set_on_speech_detected(self, callback):
        self.on_speech_detected = callback

    def drain_pending(self):
        self.drained = True

    def remember_reply(self, text):
        self.last_reply = text


def test_voice_controller_speaks_through_tts_node_bus() -> None:
    c = VoiceController(Console(file=open("/dev/null", "w")))
    c._bus = _FakeSpeechBus()
    c._audio_session = _FakeSTT()

    interrupted = c.speak("hello from the bus")

    assert interrupted is False
    request, ack_topic, timeout_s = c._bus.requests[0]
    assert isinstance(request, topics.SpeechCommand)
    assert request.topic == topics.ACT_SPEECH
    assert request.text == "hello from the bus"
    assert request.node_id == "tui_voice"
    assert request.correlation_id
    assert ack_topic == topics.SENSE_SPOKEN
    assert timeout_s == 180.0
    assert c._audio_session.paused == [True, False]


def test_voice_controller_does_not_speak_non_speech_marker_reply() -> None:
    c = VoiceController(Console(file=open("/dev/null", "w")))
    c._bus = _FakeSpeechBus()
    c._audio_session = _FakeSTT()

    interrupted = c.speak("(beeping)")

    assert interrupted is False
    assert c._bus.requests == []


def test_voice_controller_drops_non_speech_transcripts_before_queue() -> None:
    c = VoiceController(Console(file=open("/dev/null", "w")))
    handler = c._make_transcript_handler()

    handler(SimpleNamespace(text="[BLANK_AUDIO]"))
    handler(SimpleNamespace(text="hey jaeger what time is it"))

    assert c._transcripts.qsize() == 1
    queued, _queued_at = c._transcripts.get_nowait()
    assert queued == "hey jaeger what time is it"


def test_voice_controller_poll_drops_stale_transcripts() -> None:
    c = VoiceController(
        Console(file=open("/dev/null", "w")),
        pending_turn_max_age_s=0.01,
    )
    c._audio_session = object()
    c._transcripts.put_nowait(("what time is it", time.time() - 1.0))

    assert c.poll(timeout=0.01) is None


def test_voice_controller_barge_in_publishes_correlated_speech_stop() -> None:
    c = VoiceController(Console(file=open("/dev/null", "w")),
                        barge_in=True)
    stt = _FakeSTT()
    bus = _FakeSpeechBus(
        ack_ok=False,
        fire_barge_in=lambda: stt.on_speech_detected(),
    )
    c._bus = bus
    c._audio_session = stt
    c._barge_in_live = True

    interrupted = c.speak("long answer")

    assert interrupted is True
    request = bus.requests[0][0]
    stop = bus.published[0]
    assert isinstance(stop, topics.SpeechStop)
    assert stop.topic == topics.ACT_SPEECH_STOP
    assert stop.correlation_id == request.correlation_id
    assert stop.node_id == "tui_voice"
    # The interruption phrase should survive as the next user turn.
    assert stt.drained is False


# ── /voice slash command ─────────────────────────────────────────────


def _ctx_with_tui() -> tuple[slash.SlashContext, MagicMock]:
    tui = MagicMock()
    ctx = slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=80),
        instance_dir=Path("/tmp/fake_instance"),
        tui=tui,
    )
    return ctx, tui


def test_voice_command_no_args_shows_settings() -> None:
    ctx, tui = _ctx_with_tui()
    slash.dispatch("/voice", ctx)
    tui.voice_status_text.assert_called_once()


def test_voice_command_on_off_toggles_enabled() -> None:
    ctx, tui = _ctx_with_tui()
    slash.dispatch("/voice off", ctx)
    tui.apply_voice_setting.assert_called_with("enabled", False)
    slash.dispatch("/voice on", ctx)
    tui.apply_voice_setting.assert_called_with("enabled", True)


def test_voice_command_feature_toggles() -> None:
    ctx, tui = _ctx_with_tui()
    slash.dispatch("/voice bargein off", ctx)
    tui.apply_voice_setting.assert_called_with("barge_in", False)
    slash.dispatch("/voice wake on", ctx)
    tui.apply_voice_setting.assert_called_with("wake_word", True)
    slash.dispatch("/voice followup off", ctx)
    tui.apply_voice_setting.assert_called_with("follow_up", False)


def test_voice_command_without_tui_is_safe() -> None:
    ctx = slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=80),
        instance_dir=Path("/tmp/fake_instance"),
    )
    result = slash.dispatch("/voice", ctx)  # must not raise
    assert result.quit is False
