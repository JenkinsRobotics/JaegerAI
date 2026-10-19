from __future__ import annotations

import threading

from jaeger_os.contract import topics
from jaeger_os.nodes import runtime

from jaeger_ai.core.ui_speech import UISpeech


class _Bus:
    def __init__(self) -> None:
        self.commands = []
        self.published = []
        self.callbacks = []
        self.chunk_callbacks = []
        self.changed = threading.Condition()
        self.fail_stop = False

    def subscribe(self, topic, callback):
        assert topic in (topics.ACT_SPEECH_SPOKEN, topics.ACT_SPEECH_CHUNK)
        (self.callbacks if topic == topics.ACT_SPEECH_SPOKEN else self.chunk_callbacks).append(callback)

    def unsubscribe(self, topic, callback):
        (self.callbacks if topic == topics.ACT_SPEECH_SPOKEN else self.chunk_callbacks).remove(callback)

    def publish(self, message):
        if isinstance(message, topics.SpeechStop) and self.fail_stop:
            raise RuntimeError("transport closed")
        with self.changed:
            self.published.append(message)
            if isinstance(message, topics.SpeechCommand):
                self.commands.append(message)
            self.changed.notify_all()

    def wait_commands(self, count):
        with self.changed:
            assert self.changed.wait_for(lambda: len(self.commands) >= count, 2)

    def ack(self, command, *, ok=True):
        ack = topics.SpokenAck(ok=ok, duration_s=0.25,
                               correlation_id=command.correlation_id)
        for callback in list(self.callbacks):
            callback(ack)


def _setup(monkeypatch):
    bus = _Bus()
    monkeypatch.setattr(runtime, "ensure_tts_node", lambda: object())
    monkeypatch.setattr(runtime, "get_bus", lambda: bus)
    return bus, UISpeech(timeout_s=2)


def _speak(speech, text, result):
    worker = threading.Thread(target=lambda: result.update(
        speech.speak(text, voice="am_adam", rate=0.95)))
    worker.start()
    return worker


def test_ui_speech_uses_framework_voice_rate_and_matching_ack(monkeypatch):
    bus, speech = _setup(monkeypatch)
    result = {}
    worker = _speak(speech, "System online.", result)
    bus.wait_commands(1)
    command = bus.commands[0]
    assert command.voice == "am_adam"
    assert command.rate == 0.95
    assert command.node_id == "jaeger-ai-interface"
    # An unrelated producer's acknowledgement must not settle this lane.
    bus.ack(topics.SpeechCommand(text="other", correlation_id="unrelated"))
    assert worker.is_alive()
    bus.ack(command)
    worker.join(2)
    assert not worker.is_alive()
    assert result["spoken"] is True
    assert result["acknowledged"] is True
    assert not bus.callbacks


def test_stop_discards_pending_lane_and_preserves_active_identity(monkeypatch):
    bus, speech = _setup(monkeypatch)
    first, queued, new = {}, {}, {}
    active = _speak(speech, "first", first)
    bus.wait_commands(1)
    waiting = _speak(speech, "discard me", queued)
    with speech._lock:
        assert speech._lock.wait_for(lambda: len(speech._pending) == 1, 2)
    stopped = speech.stop()
    waiting.join(2)
    assert not waiting.is_alive()
    assert queued["cancelled"] is True
    assert len(bus.commands) == 1
    assert stopped["stopped"] is False  # publication is not an audio receipt
    assert stopped["stop_requested"] is True
    assert stopped["discarded"] == 1
    assert bus.published[-1].correlation_id == bus.commands[0].correlation_id
    followup = _speak(speech, "new", new)
    assert speech.active_correlation_id == bus.commands[0].correlation_id
    bus.ack(bus.commands[0])  # late successful ack cannot revive cancelled work
    active.join(2)
    bus.wait_commands(2)
    assert first["spoken"] is False
    assert first["acknowledged"] is True
    assert [c.text for c in bus.commands] == ["first", "new"]
    bus.ack(bus.commands[1])
    followup.join(2)
    assert new["spoken"] is True
    assert not bus.callbacks


def test_idle_stop_never_publishes_global_stop(monkeypatch):
    bus, speech = _setup(monkeypatch)
    assert speech.stop() == {"stopped": True, "active": False, "discarded": 0}
    assert bus.published == []


def test_stop_publication_failure_is_visible(monkeypatch):
    bus, speech = _setup(monkeypatch)
    result = {}
    worker = _speak(speech, "first", result)
    bus.wait_commands(1)
    bus.fail_stop = True
    stopped = speech.stop()
    assert stopped["stopped"] is False
    assert stopped["stop_requested"] is False
    assert stopped["error"] == "transport closed"
    bus.ack(bus.commands[0])
    worker.join(2)
    assert result["spoken"] is False


def test_timeout_retains_ownership_until_matching_receipt(monkeypatch):
    bus, speech = _setup(monkeypatch)
    speech.timeout_s = 0.01
    result = speech.speak("hello", voice="am_adam")
    assert result["execution_unknown"] is True
    assert result["acknowledged"] is False
    assert bus.callbacks
    assert speech.active_correlation_id == bus.commands[0].correlation_id
    blocked = speech.speak("must not submit", voice="am_adam")
    assert blocked["execution_unknown"] is True
    assert len(bus.commands) == 1
    stopped = speech.stop()
    assert stopped["stopped"] is False
    assert stopped["execution_unknown"] is True
    assert stopped["correlation_id"] == result["correlation_id"]
    # No receipt: repeated Stop still cannot report idle/success.
    assert speech.stop()["stopped"] is False
    bus.ack(topics.SpeechCommand(text="other", correlation_id="unrelated"))
    assert speech.active_correlation_id == result["correlation_id"]
    bus.ack(bus.commands[0], ok=False)
    assert speech.active_correlation_id is None
    assert not bus.callbacks
    assert speech.stop()["active"] is False


def test_stop_during_prepare_prevents_later_publication(monkeypatch):
    bus, speech = _setup(monkeypatch)
    preparing, release = threading.Event(), threading.Event()

    def prepare():
        preparing.set()
        assert release.wait(2)

    monkeypatch.setattr(runtime, "ensure_tts_node", prepare)
    result = {}
    worker = _speak(speech, "old", result)
    assert preparing.wait(2)
    speech.stop()
    release.set()
    worker.join(2)
    assert result["cancelled"] is True
    assert bus.published == []


def test_ui_speech_rejects_invalid_input_without_starting_runtime(monkeypatch):
    monkeypatch.setattr(runtime, "ensure_tts_node", lambda: (_ for _ in ()).throw(
        AssertionError("runtime started")))
    speech = UISpeech()
    assert speech.speak("  ")["spoken"] is False
    assert speech.speak("hello", rate=3.0)["spoken"] is False
    assert speech.stop()["active"] is False


def test_stop_does_not_cancel_another_lane_on_shared_bus(monkeypatch):
    bus, first_lane = _setup(monkeypatch)
    other_lane = UISpeech(timeout_s=2)
    first, other = {}, {}
    first_worker = _speak(first_lane, "interface one", first)
    bus.wait_commands(1)
    other_worker = _speak(other_lane, "unrelated producer", other)
    bus.wait_commands(2)
    first_lane.stop()
    stops = [message for message in bus.published if isinstance(message, topics.SpeechStop)]
    assert len(stops) == 1
    assert stops[0].correlation_id == bus.commands[0].correlation_id
    assert stops[0].correlation_id != bus.commands[1].correlation_id
    bus.ack(bus.commands[1])
    other_worker.join(2)
    assert other["spoken"] is True
    bus.ack(bus.commands[0], ok=False)
    first_worker.join(2)
    assert first["cancelled"] is True
    assert not bus.callbacks


class _NodeBus(_Bus):
    """Synchronous fake transport; the real node owns queue/Stop/ack code."""
    node = None

    def publish(self, message):
        super().publish(message)
        if isinstance(message, topics.SpeechCommand):
            self.node._on_speech_command(message)
        elif isinstance(message, topics.SpeechStop):
            self.node._on_speech_stop(message)
        elif isinstance(message, topics.SpokenAck):
            for callback in list(self.callbacks):
                callback(message)


class _Audio:
    def __init__(self, *, block=False):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.stop_count = 0
        self.block = block

    def speak(self, text, **kwargs):
        self.calls.append(text)
        self.started.set()
        if self.block:
            assert self.release.wait(2)
        return {"spoken": self.stop_count == 0,
                "reason": "fake playback interrupted" if self.stop_count else None}

    def stop(self):
        self.stop_count += 1
        self.release.set()


def _real_node(monkeypatch, *, block=False):
    from jaeger_kokoro_tts.node import TTSNode

    bus, audio = _NodeBus(), _Audio(block=block)
    node = TTSNode(bus=bus, synthesizer=audio, warm_on_start=False,
                   install_signal_handlers=False)
    bus.node = node
    monkeypatch.setattr(runtime, "ensure_tts_node", lambda: node)
    monkeypatch.setattr(runtime, "get_bus", lambda: bus)
    return bus, audio, node


def test_real_node_cancels_queued_ui_before_first_tick(monkeypatch):
    bus, audio, node = _real_node(monkeypatch)
    speech = UISpeech(timeout_s=0.01)
    unknown = speech.speak("cancel before first tick", voice="am_adam")
    assert unknown["execution_unknown"] is True
    stopped = speech.stop()
    assert stopped["stop_requested"] is True
    assert speech.active_correlation_id is None  # node issued matching negative ack
    node.tick()
    assert audio.calls == []
    assert audio.stop_count == 0
    receipts = [m for m in bus.published if isinstance(m, topics.SpokenAck)]
    assert len(receipts) == 1
    assert receipts[0].ok is False
    assert receipts[0].correlation_id == unknown["correlation_id"]


def test_real_node_queued_ui_stop_preserves_other_active_and_queue_order(monkeypatch):
    bus, audio, node = _real_node(monkeypatch, block=True)
    bus.publish(topics.SpeechCommand(text="other active", correlation_id="other"))
    worker = threading.Thread(target=node.tick)
    worker.start()
    assert audio.started.wait(2)
    bus.publish(topics.SpeechCommand(text="keep first", correlation_id="keep-1"))
    speech = UISpeech(timeout_s=0.01)
    unknown = speech.speak("discard UI", voice="am_adam")
    bus.publish(topics.SpeechCommand(text="keep second", correlation_id="keep-2"))
    speech.stop()
    assert speech.active_correlation_id is None
    assert node._active_correlation_id == "other"
    assert audio.stop_count == 0
    assert worker.is_alive()
    audio.release.set()
    worker.join(2)
    assert not worker.is_alive()
    audio.block = False
    node.tick()
    node.tick()
    assert audio.calls == ["other active", "keep first", "keep second"]
    receipts = [m for m in bus.published if isinstance(m, topics.SpokenAck)
                and m.correlation_id == unknown["correlation_id"]]
    assert len(receipts) == 1 and receipts[0].ok is False


def test_real_node_timeout_then_stop_targets_active_request(monkeypatch):
    bus, audio, node = _real_node(monkeypatch, block=True)
    speech = UISpeech(timeout_s=0.01)
    result = {}
    caller = _speak(speech, "active UI", result)
    bus.wait_commands(1)
    worker = threading.Thread(target=node.tick)
    worker.start()
    assert audio.started.wait(2)
    caller.join(2)
    assert result["execution_unknown"] is True
    assert speech.speak("blocked", voice="am_adam")["execution_unknown"] is True
    assert len(bus.commands) == 1
    stopped = speech.stop()
    assert stopped["stopped"] is False  # publication alone is never confirmation
    assert stopped["correlation_id"] == result["correlation_id"]
    worker.join(2)
    assert not worker.is_alive()
    assert audio.stop_count == 1
    assert speech.active_correlation_id is None
    assert not bus.callbacks


def test_real_node_scoped_stop_before_say_delivery_does_not_revive_speech(monkeypatch):
    bus, audio, node = _real_node(monkeypatch)
    bus.publish(topics.SpeechStop(correlation_id="late-ui"))
    bus.publish(topics.SpeechCommand(text="late say", correlation_id="late-ui"))
    node.tick()
    assert audio.calls == []
    receipts = [m for m in bus.published if isinstance(m, topics.SpokenAck)]
    assert len(receipts) == 1 and receipts[0].ok is False
    assert audio.stop_count == 0


def test_stop_in_node_to_engine_entry_gap_survives_kokoro_startup(monkeypatch):
    """Pause after node cancellation check, before Kokoro adopts its token."""
    from types import SimpleNamespace

    import numpy as np
    from jaeger_kokoro_tts.engine import KokoroTTS
    from jaeger_kokoro_tts.node import TTSNode

    entry, resume = threading.Event(), threading.Event()

    class PausedEngine(KokoroTTS):
        def speak(self, text, **kwargs):
            if text == "cancel at entry":
                entry.set()
                assert resume.wait(2)
            return super().speak(text, **kwargs)

    class Player:
        device_name = "fake audio"

        def __init__(self):
            self.samples = []
            self.begun = []

        def begin(self, correlation_id):
            self.begun.append(correlation_id)

        def enqueue(self, audio):
            self.samples.append(audio)

        def mark_end(self):
            pass

        def wait_until_drained(self):
            return True

    bus, player = _NodeBus(), Player()
    engine = PausedEngine(bus=bus)
    node = TTSNode(bus=bus, synthesizer=engine, warm_on_start=False,
                   install_signal_handlers=False)
    bus.node = node
    monkeypatch.setattr(engine, "_ensure_player", lambda: player)

    def pipeline(text, **kwargs):
        yield SimpleNamespace(audio=np.ones(4, dtype=np.float32))

    monkeypatch.setattr(engine, "_ensure_pipeline", lambda: pipeline)
    bus.publish(topics.SpeechCommand(text="cancel at entry", correlation_id="entry-ui"))
    worker = threading.Thread(target=node.tick)
    worker.start()
    assert entry.wait(2)
    # If playback held the claim lock, this thread could not finish until
    # entry was resumed. It must deliver Stop while engine entry is paused.
    stopper = threading.Thread(target=lambda: bus.publish(
        topics.SpeechStop(correlation_id="entry-ui")))
    stopper.start()
    stopper.join(1)
    try:
        assert not stopper.is_alive()
        assert node._active_cancel.is_set()
    finally:
        resume.set()
        worker.join(2)
        stopper.join(2)
    assert not worker.is_alive()
    assert player.begun == []
    assert player.samples == []
    receipts = [m for m in bus.published if isinstance(m, topics.SpokenAck)
                and m.correlation_id == "entry-ui"]
    assert len(receipts) == 1
    assert receipts[0].ok is False
    assert receipts[0].reason == "interrupted"
    # The cancelled token is request-local; another producer still plays.
    bus.publish(topics.SpeechCommand(text="next producer", correlation_id="next"))
    node.tick()
    assert player.begun == ["next"]
    assert len(player.samples) == 1
    next_ack = [m for m in bus.published if isinstance(m, topics.SpokenAck)
                and m.correlation_id == "next"]
    assert len(next_ack) == 1 and next_ack[0].ok is True


def test_node_terminal_receipt_rejects_success_from_engine_after_stop(monkeypatch):
    bus, audio, node = _real_node(monkeypatch, block=True)

    def returns_success_despite_stop(text, **kwargs):
        audio.started.set()
        assert audio.release.wait(2)
        return {"spoken": True}

    monkeypatch.setattr(audio, "speak", returns_success_despite_stop)
    bus.publish(topics.SpeechCommand(text="legacy engine", correlation_id="terminal-ui"))
    worker = threading.Thread(target=node.tick)
    worker.start()
    assert audio.started.wait(2)
    bus.publish(topics.SpeechStop(correlation_id="terminal-ui"))
    worker.join(2)
    assert not worker.is_alive()
    receipts = [m for m in bus.published if isinstance(m, topics.SpokenAck)]
    assert len(receipts) == 1
    assert receipts[0].ok is False
    assert receipts[0].reason == "interrupted"


def test_ui_playback_telemetry_is_correlated_measured_and_expires(monkeypatch):
    bus, speech = _setup(monkeypatch)
    result = {}
    worker = _speak(speech, "measured", result)
    bus.wait_commands(1)
    command = bus.commands[0]
    assert speech.status()["amplitude"] == 0
    for callback in bus.chunk_callbacks:
        callback(topics.TtsChunk(amplitude=0.8, correlation_id="foreign"))
    assert speech.status()["amplitude"] == 0
    for callback in bus.chunk_callbacks:
        callback(topics.TtsChunk(amplitude=0.42, correlation_id=command.correlation_id))
    assert speech.status()["amplitude"] == 0.42
    assert speech.status()["measured"]
    speech._sample_at -= 1
    assert speech.status()["amplitude"] == 0
    bus.ack(command)
    worker.join(2)
    assert not speech.status()["active"]
    assert not bus.chunk_callbacks
