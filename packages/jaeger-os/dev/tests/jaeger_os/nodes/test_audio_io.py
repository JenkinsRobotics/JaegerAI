"""The audio driver — one owner for the mic and the speaker.

The property that motivated it: MORE THAN ONE consumer can have the
microphone. Before this, whisper_stt held the input stream inside its
own engine, so a wake-word detector or a level meter had nothing to
subscribe to and no way to get the device.

Runs headless. The audio hardware is replaced by a fake stream whose
callback we drive by hand, so these tests assert the node's wiring —
not PortAudio's.
"""

from __future__ import annotations

import threading
import time
import types
import sys

import numpy as np
import pytest

from jaeger_os.nodes.audio_io import AudioIONode
from jaeger_os.transport import InProcBus, topics


class _FakeStream:
    """Stands in for an InputStream/OutputStream. The node starts it;
    the test calls its callback whenever it wants a frame."""

    def __init__(self, **kw):
        self.callback = kw.get("callback")
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _node(bus, **kw):
    """A node with both devices faked out."""
    node = AudioIONode(bus=bus, audio_backend="fake", **kw)
    node._in_stream = _FakeStream(callback=node._on_captured)
    node._out_stream = _FakeStream(callback=node._fill_playback)
    node._open_input = lambda: node._in_stream.start()

    def _open_output():
        if node._out_stream is None:
            node._out_stream = _FakeStream(callback=node._fill_playback)
        node._out_stream.start()
        node._last_playback_callback_at = time.monotonic()

    node._open_output = _open_output
    return node


def _run(node):
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    time.sleep(0.25)
    return t


def _capture(node, value=0.5):
    """Push one frame in through the fake mic."""
    frame = np.full((node._frame_samples, 1), value, dtype=np.float32)
    node._on_captured(frame, node._frame_samples, None, None)


def _wait(predicate, timeout=3.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── the reason this node exists ──────────────────────────────────

def test_two_consumers_share_one_microphone(bus):
    """THE point. A wake-word detector and an STT engine both get every
    frame, from one device, neither aware of the other. Under the old
    shape the second one simply could not have the mic."""
    stt, wake_word = [], []
    bus.subscribe(topics.SENSE_MIC_PCM, stt.append)
    bus.subscribe(topics.SENSE_MIC_PCM, wake_word.append)

    node = _node(bus, playback=False)
    t = _run(node)
    try:
        for _ in range(3):
            _capture(node)
        assert _wait(lambda: len(stt) >= 3 and len(wake_word) >= 3)
        assert len(stt) == len(wake_word) == 3
    finally:
        node.stop()
        t.join(timeout=2)


def test_a_captured_frame_survives_the_round_trip(bus):
    """float32 mono in, float32 mono out, sample-for-sample."""
    got = []
    bus.subscribe(topics.SENSE_MIC_PCM, got.append)
    node = _node(bus, playback=False)
    t = _run(node)
    try:
        _capture(node, value=0.25)
        assert _wait(lambda: got)
        msg = got[0]
        samples = np.frombuffer(msg.samples, dtype=np.float32)
        assert samples.size == node._frame_samples
        assert np.allclose(samples, 0.25)
        assert msg.sample_rate == node._sample_rate
        assert msg.channels == 1
    finally:
        node.stop()
        t.join(timeout=2)


def test_frames_are_sequenced_so_a_consumer_can_detect_drops(bus):
    got = []
    bus.subscribe(topics.SENSE_MIC_PCM, got.append)
    node = _node(bus, playback=False)
    t = _run(node)
    try:
        for _ in range(5):
            _capture(node)
        assert _wait(lambda: len(got) >= 5)
        assert [m.seq for m in got[:5]] == [1, 2, 3, 4, 5]
    finally:
        node.stop()
        t.join(timeout=2)


# ── playback ─────────────────────────────────────────────────────

def test_idle_node_keeps_one_ready_speaker_stream(bus):
    """Production mode avoids hardware reopen latency and audible pops."""
    node = _node(bus, capture=False)
    t = _run(node)
    try:
        assert node._out_stream.started is True
        assert node._frames_played == 0
    finally:
        node.stop()
        t.join(timeout=2)


def test_speaker_frames_reach_the_output_stream(bus):
    """Published at the playback rate, so nothing is resampled and the
    samples must arrive bit-exact."""
    node = _node(bus, capture=False)
    t = _run(node)
    try:
        tone = np.full(240, 0.4, dtype=np.float32)
        bus.publish(topics.AudioOutFrame(
            samples=tone.tobytes(), sample_rate=node._playback_rate,
            channels=1))
        assert _wait(lambda: node._out_pending)
        assert node._out_stream.started is True

        out = np.zeros((240, 1), dtype=np.float32)
        node._fill_playback(out, 240, None, None)
        assert np.allclose(out[:, 0], 0.4)
    finally:
        node.stop()
        t.join(timeout=2)


def test_output_open_failure_is_reported_to_the_right_producer(bus):
    states = []
    bus.subscribe(topics.ACT_SPEAKER_STATE, states.append)
    node = _node(bus, capture=False)

    def fail_open():
        raise RuntimeError("speaker disconnected")

    node._out_stream = None
    node._open_output = fail_open
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=np.ones(240, dtype=np.float32).tobytes(),
        correlation_id="speech-11",
    ))

    assert _wait(lambda: any(s.state == "error" for s in states))
    failure = [s for s in states if s.state == "error"][-1]
    assert failure.correlation_id == "speech-11"
    assert "speaker disconnected" in failure.error
    assert not node._out_pending
    assert node.link_ok() is False


def test_speaker_preserves_waveform_across_published_chunk_boundaries(bus):
    """A bus hop may split one utterance into many frames; joining them at
    the device must neither drop nor duplicate samples at the seams."""
    node = _node(bus, capture=False)
    first = np.linspace(-0.8, 0.3, 731, dtype=np.float32)
    second = np.linspace(0.3, -0.6, 997, dtype=np.float32)
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=first.tobytes(), sample_rate=node._playback_rate))
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=second.tobytes(), sample_rate=node._playback_rate))

    rendered = []
    for frames in (480, 480, 480, 288):
        out = np.zeros((frames, 1), dtype=np.float32)
        node._fill_playback(out, frames, None, None)
        rendered.append(out[:, 0].copy())

    assert np.array_equal(np.concatenate(rendered),
                          np.concatenate((first, second)))


def test_speaker_closes_again_after_the_audio_drains(bus):
    """Battery-sensitive deployments may explicitly use demand mode."""
    node = _node(bus, capture=False, keep_output_open=False)
    stream = node._out_stream
    t = _run(node)
    try:
        node._on_speaker_frame(topics.AudioOutFrame(
            samples=np.full(240, 0.4, dtype=np.float32).tobytes(),
            sample_rate=node._playback_rate))
        out = np.zeros((480, 1), dtype=np.float32)
        node._fill_playback(out, 480, None, None)
        assert _wait(lambda: node._out_stream is None)
        assert stream.closed is True
    finally:
        node.stop()
        t.join(timeout=2)


def test_a_producer_at_another_rate_is_resampled_not_repitched(bus):
    """Capture is 16 kHz (Whisper + AEC); playback is 24 kHz (Kokoro and
    the chimes both synthesise there). A producer declares its own rate
    and the driver converts — play 16 kHz audio through a 24 kHz stream
    untouched and it comes out a third too fast, and chipmunked."""
    node = _node(bus, capture=False)
    half_second = np.zeros(8000, dtype=np.float32)   # 0.5 s @ 16 kHz
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=half_second.tobytes(), sample_rate=16000))
    queued = node._out_pending[0]
    expected = int(round(8000 * node._playback_rate / 16000))
    assert abs(queued.size - expected) <= 2, (
        f"0.5s at 16kHz became {queued.size / node._playback_rate:.3f}s "
        f"at {node._playback_rate}Hz — wrong duration means wrong pitch")


def test_the_echo_reference_is_kept_at_the_capture_rate(bus):
    """The reference is subtracted from mic frames, so it has to live in
    the MIC's time base, not the speaker's. Getting this wrong does not
    raise — it just cancels nothing, which is a bug you chase by ear."""
    node = _node(bus, aec=_SubtractingAEC())
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=np.zeros(2400, dtype=np.float32).tobytes(),
        sample_rate=24000))                       # 0.1 s of playback
    popped = node.reference.pop_frame(1600)       # 0.1 s at capture rate
    assert popped.size == 1600
    assert np.count_nonzero(popped) == 0


def test_playback_underrun_is_silence_not_a_crash(bus):
    """Nothing queued must produce zeros. An exception in this callback
    is a dropout you can hear, and on some backends a dead stream."""
    node = _node(bus, capture=False)
    out = np.full((240, 1), 9.0, dtype=np.float32)
    node._fill_playback(out, 240, None, None)
    assert np.allclose(out[:, 0], 0.0)


def test_a_natural_final_partial_buffer_is_not_an_underrun(bus):
    node = _node(bus, capture=False)
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=np.full(100, 0.3, dtype=np.float32).tobytes()))
    out = np.zeros((240, 1), dtype=np.float32)
    node._fill_playback(out, 240, None, None)
    assert np.allclose(out[:100, 0], 0.3)
    assert np.allclose(out[100:, 0], 0.0)
    assert node._underruns == 0


def test_sounddevice_reports_real_backend_underruns(bus):
    node = _node(bus, capture=False)
    out = np.zeros((240, 1), dtype=np.float32)
    node._fill_playback_sd(out, 240, None, "output underflow")
    assert node._underruns == 1


def test_playback_spanning_several_frames_is_not_lost(bus):
    """A TTS chunk is far longer than one playback block."""
    node = _node(bus, capture=False)
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=np.arange(1000, dtype=np.float32).tobytes()))
    seen = []
    for _ in range(3):
        out = np.zeros((240, 1), dtype=np.float32)
        node._fill_playback(out, 240, None, None)
        seen.append(out[:, 0].copy())
    played = np.concatenate(seen)
    assert np.allclose(played[:720], np.arange(720, dtype=np.float32))


# ── the AEC seam ─────────────────────────────────────────────────

class _SubtractingAEC:
    """Not a real canceller — just proves near and far arrive aligned
    and in the right order."""

    def __init__(self):
        self.calls = 0

    def process(self, near, far):
        self.calls += 1
        return near - far


def test_playback_feeds_the_echo_reference(bus):
    """Why one node owns both directions: the canceller needs the mic
    frame and what is playing TOGETHER, per frame. Split across two
    drivers, this reference crosses a boundary 100 times a second."""
    aec = _SubtractingAEC()
    node = _node(bus, aec=aec)
    got = []
    bus.subscribe(topics.SENSE_MIC_PCM, got.append)
    t = _run(node)
    try:
        # The AI starts speaking. Published at the CAPTURE rate so the
        # reference is 1:1 and the assertion below is about the seam,
        # not about resampler fidelity.
        node._on_speaker_frame(topics.AudioOutFrame(
            samples=np.full(node._frame_samples, 0.5,
                            dtype=np.float32).tobytes(),
            sample_rate=node._sample_rate))
        # ...and the mic hears exactly that, echoed back.
        _capture(node, value=0.5)
        assert _wait(lambda: got)
        cleaned = np.frombuffer(got[0].samples, dtype=np.float32)
        assert aec.calls == 1
        assert np.allclose(cleaned, 0.0), (
            "the AI's own voice was not cancelled out of the mic")
    finally:
        node.stop()
        t.join(timeout=2)


def test_a_failing_aec_passes_audio_through(bus):
    """A broken canceller must cost barge-in, never the microphone."""
    class _Broken:
        def process(self, near, far):
            raise RuntimeError("speexdsp exploded")

    node = _node(bus, aec=_Broken(), playback=False)
    got = []
    bus.subscribe(topics.SENSE_MIC_PCM, got.append)
    t = _run(node)
    try:
        _capture(node, value=0.3)
        assert _wait(lambda: got), "a failing AEC silenced the mic"
        assert np.allclose(np.frombuffer(got[0].samples, dtype=np.float32), 0.3)
    finally:
        node.stop()
        t.join(timeout=2)


def test_no_aec_means_no_call_at_all(bus):
    """The fast path stays free of a pointless passthrough call."""
    node = _node(bus, aec=None, playback=False)
    got = []
    bus.subscribe(topics.SENSE_MIC_PCM, got.append)
    t = _run(node)
    try:
        _capture(node, value=0.7)
        assert _wait(lambda: got)
        assert np.allclose(np.frombuffer(got[0].samples, dtype=np.float32), 0.7)
    finally:
        node.stop()
        t.join(timeout=2)


# ── audio-thread safety ──────────────────────────────────────────

def test_a_wedged_subscriber_never_blocks_the_audio_thread(bus):
    """A blocked audio callback is a glitch you can hear. The bus hands
    off with put_nowait, so a stuck consumer sheds frames instead of
    stalling capture."""
    gate = threading.Event()
    bus.subscribe(topics.SENSE_MIC_PCM, lambda m: gate.wait(timeout=5.0))
    node = _node(bus, playback=False)
    t = _run(node)
    try:
        started = time.perf_counter()
        for _ in range(50):
            _capture(node)
        elapsed = time.perf_counter() - started
        assert elapsed < 0.5, (
            f"capture blocked for {elapsed:.2f}s behind a wedged subscriber")
        assert node._frames_captured == 50
    finally:
        gate.set()
        node.stop()
        t.join(timeout=2)


def test_a_wrong_sized_frame_is_ignored(bus):
    """speexdsp requires exact frame lengths; a short frame from a
    backend hiccup must be dropped, not fed to the canceller."""
    node = _node(bus, playback=False)
    got = []
    bus.subscribe(topics.SENSE_MIC_PCM, got.append)
    t = _run(node)
    try:
        short = np.zeros((node._frame_samples // 2, 1), dtype=np.float32)
        node._on_captured(short, short.shape[0], None, None)
        time.sleep(0.3)
        assert got == []
        assert node._frames_captured == 0
    finally:
        node.stop()
        t.join(timeout=2)


# ── it is a well-behaved node ────────────────────────────────────

def test_health_reports_the_audio_path(bus):
    node = _node(bus)
    t = _run(node)
    try:
        h = node.health()
        assert h["state"] == "running"
        assert h["capture"] is True and h["playback"] is True
        assert h["capture_rate"] == node._sample_rate
        assert "frames_captured" in h and "underruns" in h
        assert h["output_open"] is True
        assert h["keep_output_open"] is True
        assert "queued_ms" in h and "output_restarts" in h
        assert "input_restarts" in h and "last_input_error" in h
    finally:
        node.stop()
        t.join(timeout=2)


def test_teardown_closes_both_devices(bus):
    node = _node(bus)
    t = _run(node)
    in_stream, out_stream = node._in_stream, node._out_stream
    node.stop()
    t.join(timeout=2)
    assert in_stream.closed and out_stream.closed, "leaked an audio device"


def test_capture_only_never_opens_a_speaker(bus):
    """A body with a mic and no speaker must not fail to boot."""
    node = _node(bus, playback=False)
    t = _run(node)
    try:
        assert not node._out_stream.started
    finally:
        node.stop()
        t.join(timeout=2)


def test_a_stalled_playback_callback_restarts_without_losing_audio(bus):
    node = _node(bus, capture=False)
    node._on_speaker_frame(topics.AudioOutFrame(
        samples=np.full(4800, 0.2, dtype=np.float32).tobytes(),
        correlation_id="speech-1",
    ))
    queued_before = sum(chunk.size for chunk in node._out_pending)
    node._last_playback_callback_at = time.monotonic() - 10.0

    old_stream = node._out_stream
    replacement = _FakeStream(callback=node._fill_playback)

    def close_output():
        old_stream.stop()
        old_stream.close()
        node._out_stream = None

    def open_output():
        node._out_stream = replacement
        replacement.start()
        node._last_playback_callback_at = time.monotonic()

    node._close_output = close_output
    node._open_output = open_output
    node._recover_output_if_stalled()

    assert old_stream.closed is True
    assert replacement.started is True
    assert sum(chunk.size for chunk in node._out_pending) == queued_before
    assert node._output_restarts == 1


def test_a_stalled_input_schedules_recovery_without_blocking_tick(bus):
    node = AudioIONode(bus=bus, playback=False, audio_backend="fake")
    old = _FakeStream(callback=node._on_captured)
    old.start()
    node._in_stream = old
    node._input_backend_active = "avaudio"
    node._opened_at = time.monotonic() - 10.0
    node._frames_at_open = node._frames_captured
    replacement = _FakeStream(callback=node._on_captured)

    node._close_input_bounded = lambda stream: stream.close()

    def open_input():
        node._in_stream = replacement
        replacement.start()
        node._opened_at = time.monotonic()
        node._frames_at_open = node._frames_captured
        node._input_backend_active = "portaudio"

    node._open_input = open_input
    before = time.monotonic()
    node._recover_input_if_stalled()
    assert time.monotonic() - before < 0.1
    assert _wait(lambda: node._input_restarts == 1)
    assert old.closed is True
    assert replacement.started is True
    assert node._force_portaudio_input is True


def test_native_input_close_has_a_deadline(bus):
    node = AudioIONode(bus=bus, capture=False, playback=False)
    release = threading.Event()

    class Wedged:
        def stop(self):
            release.wait()

        def close(self):
            pass

    before = time.monotonic()
    node._close_input_bounded(Wedged(), timeout_s=0.05)
    elapsed = time.monotonic() - before
    release.set()
    assert elapsed < 0.5
    assert "native audio call wedged" in node._last_input_error


def test_explicit_input_device_is_not_ignored_by_avaudio(bus, monkeypatch):
    made = []

    class PortAudioInput(_FakeStream):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            made.append(kwargs)

    monkeypatch.setitem(
        sys.modules, "sounddevice",
        types.SimpleNamespace(InputStream=PortAudioInput),
    )
    node = AudioIONode(
        bus=bus, playback=False, audio_backend="avaudio",
        input_device="USB microphone",
    )
    node._open_input()
    assert made and made[0]["device"] == "USB microphone"
    assert node._input_backend_active == "portaudio"
    node._close_input_bounded(node._in_stream)


# ── the speaker reports on itself ────────────────────────────────

def test_the_speaker_says_when_it_starts_and_finishes(bus):
    """A publisher cannot otherwise tell "my audio finished being SENT"
    from "my audio finished PLAYING". The second is what a done-ack
    needs, and only the device knows it."""
    states = []
    bus.subscribe(topics.ACT_SPEAKER_STATE, states.append)
    node = _node(bus, capture=False)
    t = _run(node)
    try:
        bus.publish(topics.AudioOutFrame(
            samples=np.full(240, 0.2, dtype=np.float32).tobytes(),
            sample_rate=node._playback_rate, correlation_id="utterance-7"))
        assert _wait(lambda: any(s.state == "playing" for s in states))

        # Drain it through the device.
        out = np.zeros((480, 1), dtype=np.float32)
        node._fill_playback(out, 480, None, None)
        assert _wait(lambda: any(s.state == "idle" for s in states))

        done = [s for s in states if s.state == "idle"][-1]
        assert done.correlation_id == "utterance-7", (
            "a publisher must be able to tell its own audio finishing "
            "from someone else's")
    finally:
        node.stop()
        t.join(timeout=2)


def test_every_producer_in_a_shared_burst_gets_a_drain_signal(bus):
    """A chime queued after TTS must not make the TTS request time out."""
    states = []
    bus.subscribe(topics.ACT_SPEAKER_STATE, states.append)
    node = _node(bus, capture=False)
    t = _run(node)
    try:
        for correlation_id in ("speech-1", "chime-1"):
            bus.publish(topics.AudioOutFrame(
                samples=np.full(240, 0.2, dtype=np.float32).tobytes(),
                correlation_id=correlation_id,
            ))
        assert _wait(lambda: len(node._out_pending) == 2)

        out = np.zeros((480, 1), dtype=np.float32)
        node._fill_playback(out, 480, None, None)
        assert _wait(lambda: len([s for s in states if s.state == "idle"]) == 2)
        completed = {
            state.correlation_id for state in states if state.state == "idle"
        }
        assert completed == {"speech-1", "chime-1"}
    finally:
        node.stop()
        t.join(timeout=2)


def test_stop_drops_audio_already_queued(bus):
    """Barge-in. A TTS engine can stop synthesising on its own but
    cannot stop the sentence already handed to the device — that half
    second is what makes an assistant feel deaf."""
    node = _node(bus, capture=False)
    t = _run(node)
    try:
        bus.publish(topics.AudioOutFrame(
            samples=np.full(48000, 0.5, dtype=np.float32).tobytes(),
            sample_rate=node._playback_rate))          # 2 seconds of speech
        assert _wait(lambda: node._out_pending)

        original_stream = node._out_stream
        bus.publish(topics.SpeakerStop())
        assert _wait(lambda: not node._out_pending), "audio kept playing"
        assert _wait(lambda: original_stream.closed), (
            "backend-prefetched audio was not flushed"
        )
        assert node._out_stream is not None and node._out_stream.started
        assert node._output_flushes == 1

        out = np.full((240, 1), 9.0, dtype=np.float32)
        node._fill_playback(out, 240, None, None)
        assert np.allclose(out[:, 0], 0.0), "still emitting after stop"
    finally:
        node.stop()
        t.join(timeout=2)


def test_stop_clears_the_echo_reference_too(bus):
    """The reference describes audio that will now never be played.
    Leaving it makes the canceller subtract a voice the room never
    heard — cancelling real speech instead of an echo."""
    node = _node(bus, aec=_SubtractingAEC())
    t = _run(node)
    try:
        node._on_speaker_frame(topics.AudioOutFrame(
            samples=np.full(1600, 0.5, dtype=np.float32).tobytes(),
            sample_rate=node._sample_rate))
        node._on_speaker_stop(topics.SpeakerStop())
        assert np.count_nonzero(node.reference.pop_frame(160)) == 0
    finally:
        node.stop()
        t.join(timeout=2)


def test_state_is_not_republished_every_block(bus):
    """It is an edge signal, not a heartbeat. Publishing per callback
    would put a message on the bus every 20 ms forever."""
    states = []
    bus.subscribe(topics.ACT_SPEAKER_STATE, states.append)
    node = _node(bus, capture=False)
    t = _run(node)
    try:
        bus.publish(topics.AudioOutFrame(
            samples=np.full(240, 0.2, dtype=np.float32).tobytes(),
            sample_rate=node._playback_rate))
        assert _wait(lambda: states)
        for _ in range(20):
            out = np.zeros((240, 1), dtype=np.float32)
            node._fill_playback(out, 240, None, None)
        time.sleep(0.3)
        assert len(states) <= 3, f"chattered {len(states)} states"
    finally:
        node.stop()
        t.join(timeout=2)


# ── the driver actually gets started ─────────────────────────────

def test_starting_a_listening_session_starts_the_driver(monkeypatch):
    """The last mile. A driver nothing starts is a system where STT
    subscribes successfully and hears silence forever while reporting
    healthy — the exact failure the whole split had to avoid."""
    from jaeger_os.nodes import runtime

    monkeypatch.setattr(runtime, "_audio_io_node", None)
    monkeypatch.setattr(runtime, "_audio_io_thread", None)
    built = []

    def _fake_make(bus, config):
        node = AudioIONode(bus=bus, audio_backend="fake",
                           capture=False, playback=False)
        built.append(node)
        return node

    import jaeger_os.nodes.audio_io as audio_io_pkg
    monkeypatch.setattr(audio_io_pkg, "make_audio_io_node", _fake_make)

    node = runtime.ensure_audio_io_node()
    try:
        assert built, "the driver was never constructed"
        assert node is built[0]
        # Idempotent: a second caller must not open the device twice.
        assert runtime.ensure_audio_io_node() is node
        assert len(built) == 1
    finally:
        node.stop()
        monkeypatch.setattr(runtime, "_audio_io_node", None)


def test_playback_only_driver_enables_capture_without_replacing_speaker(bus):
    node = _node(bus, capture=False)
    node.setup()
    speaker = node._out_stream
    assert not node._in_stream.started
    node.enable_capture()
    assert node._capture
    assert node._input_retry_at > 0
    assert node._out_stream is speaker and speaker.started
    node.teardown()
