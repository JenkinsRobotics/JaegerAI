"""The blackbox, the recording, and the replay.

Three questions, one tap point — a bus subscriber that writes what it
hears, and a publisher that reads it back.

The property that makes replay worth having: a recording holds the
same bytes the wire carried, so playing it back produces messages a
consumer cannot distinguish from the originals. Feed the audio that
broke the STT into the real STT, as many times as it takes.
"""

from __future__ import annotations

import pathlib
import time

import pytest

from jaeger_os.transport import InProcBus, topics
from jaeger_os.transport.recorder import (
    MAGIC, Recorder, header, read, replay,
)


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _wait(predicate, timeout=3.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── blackbox: costs nothing until it matters ─────────────────────

def test_blackbox_writes_nothing_until_asked(bus, tmp_path):
    """The point of a ring: an app can leave it on forever."""
    rec = Recorder(bus, capacity=100).start()
    try:
        time.sleep(0.15)
        for i in range(50):
            bus.publish(topics.Transcript(text=f"line {i}"))
        assert _wait(lambda: rec.recorded >= 50)
        assert list(tmp_path.iterdir()) == [], "wrote to disk unprompted"
    finally:
        rec.stop()


def test_the_ring_keeps_the_MOST_RECENT(bus, tmp_path):
    """A fault asks 'what just happened', so the newest wins."""
    rec = Recorder(bus, capacity=10).start()
    try:
        time.sleep(0.15)
        for i in range(40):
            bus.publish(topics.Transcript(text=f"line {i}"))
        assert _wait(lambda: rec.recorded >= 40)
        out = rec.dump(tmp_path / "bb.jbox", reason="test")
        texts = [m.text for _, _, m in read(out)]
        assert len(texts) == 10
        assert texts[-1] == "line 39", "kept the oldest, not the newest"
    finally:
        rec.stop()


def test_a_trigger_dumps_the_run_up_to_the_fault(bus, tmp_path):
    """The insight worth restating: when an e-stop fires the question
    is what the robot was doing JUST BEFORE, and a log you started
    afterwards cannot answer it."""
    rec = Recorder(bus, capacity=200).start()
    rec.on_trigger(topics.ACT_ESTOP_TRIGGER, tmp_path, reason="estop")
    try:
        time.sleep(0.15)
        for i in range(20):
            bus.publish(topics.MotionCommand(linear_x_mps=float(i)))
        assert _wait(lambda: rec.recorded >= 20)
        bus.publish(topics.EStop(engaged=True, reason="button"))
        assert _wait(lambda: list(tmp_path.glob("blackbox-*.jbox")))

        dump = list(tmp_path.glob("blackbox-*.jbox"))[0]
        assert header(dump)["reason"] == "estop"
        speeds = [m.linear_x_mps for _, t, m in read(dump)
                  if t == topics.ACT_MOTOR_COMMAND]
        assert speeds[:3] == [0.0, 1.0, 2.0], "lost the run-up"
    finally:
        rec.stop()


def test_dumping_never_raises(bus, tmp_path):
    """It runs when something has already gone wrong. A recorder that
    fails while dumping fails exactly when it is needed."""
    rec = Recorder(bus).start()
    try:
        out = rec.dump("/nonexistent-root/nope/bb.jbox")
        assert isinstance(out, pathlib.Path)
    finally:
        rec.stop()


# ── continuous ───────────────────────────────────────────────────

def test_a_session_is_recorded_and_readable(bus, tmp_path):
    path = tmp_path / "s.jbox"
    rec = Recorder(bus, path=path, app="test-app").start()
    try:
        time.sleep(0.15)
        for i in range(30):
            bus.publish(topics.Transcript(text=f"heard {i}"))
        assert _wait(lambda: rec.recorded >= 30)
    finally:
        rec.stop()

    assert path.read_bytes()[:len(MAGIC)] == MAGIC
    meta = header(path)
    assert meta["app"] == "test-app" and meta["mode"] == "continuous"
    assert [m.text for _, _, m in read(path)][:3] == \
        ["heard 0", "heard 1", "heard 2"]


def test_the_tail_survives_a_clean_stop(bus, tmp_path):
    """A recording is buffered; if stop() did not drain, every session
    would lose its last second — the part you were watching."""
    path = tmp_path / "s.jbox"
    rec = Recorder(bus, path=path).start()
    time.sleep(0.15)
    for i in range(20):
        bus.publish(topics.Transcript(text=f"t{i}"))
    time.sleep(0.3)
    rec.stop()
    assert len(list(read(path))) == 20


# ── the expensive default ────────────────────────────────────────

def test_binary_topics_are_excluded_by_default(bus, tmp_path):
    """Measured: recording 720p30 plus a mic is 4.5 GB/hour; skipping
    the pixels is 3 MB/hour. A recorder you cannot afford to leave on
    is one that is off when you need it."""
    path = tmp_path / "s.jbox"
    rec = Recorder(bus, path=path).start()
    try:
        time.sleep(0.15)
        bus.publish(topics.Transcript(text="keep me"))
        bus.publish(topics.CameraFrame(frame_bytes=b"\x00" * 5000,
                                       camera_id="cam0"))
        assert _wait(lambda: rec.recorded >= 1)
        time.sleep(0.3)
    finally:
        rec.stop()
    kept = [t for _, t, _ in read(path)]
    assert topics.SENSE_STT_TRANSCRIPT in kept
    assert topics.SENSE_CAMERA_IMAGE_RAW not in kept


def test_binary_can_be_opted_into(bus, tmp_path):
    path = tmp_path / "s.jbox"
    rec = Recorder(bus, path=path, include_binary=True).start()
    try:
        time.sleep(0.15)
        bus.publish(topics.CameraFrame(frame_bytes=b"\x00" * 500,
                                       camera_id="cam0"))
        assert _wait(lambda: rec.recorded >= 1)
        time.sleep(0.3)
    finally:
        rec.stop()
    assert topics.SENSE_CAMERA_IMAGE_RAW in [t for _, t, _ in read(path)]


# ── replay: the half that makes it repeatable ────────────────────

def test_a_recording_replays_into_a_live_bus(bus, tmp_path):
    """The whole point. A consumer cannot tell replayed traffic from
    the original, because it IS the original bytes."""
    path = tmp_path / "s.jbox"
    rec = Recorder(bus, path=path).start()
    try:
        time.sleep(0.15)
        for word in ("alpha", "beta", "gamma"):
            bus.publish(topics.Transcript(text=word))
        assert _wait(lambda: rec.recorded >= 3)
    finally:
        rec.stop()

    fresh = InProcBus()
    heard = []
    try:
        fresh.subscribe(topics.SENSE_STT_TRANSCRIPT, heard.append)
        time.sleep(0.15)
        n = replay(fresh, path, speed=0)
        assert n == 3
        assert _wait(lambda: len(heard) == 3)
        assert [m.text for m in heard] == ["alpha", "beta", "gamma"]
    finally:
        fresh.close()


def test_replay_preserves_the_original_emit_time(bus, tmp_path):
    """A consumer measuring latency against replayed traffic sees the
    ORIGINAL timings. Usually what you want, occasionally surprising —
    so it is asserted rather than left to be discovered."""
    path = tmp_path / "s.jbox"
    rec = Recorder(bus, path=path).start()
    try:
        time.sleep(0.15)
        original = topics.Transcript(text="x")
        bus.publish(original)
        assert _wait(lambda: rec.recorded >= 1)
    finally:
        rec.stop()
    assert list(read(path))[0][2].t_emit_ns == original.t_emit_ns


def test_replay_can_be_filtered(bus, tmp_path):
    path = tmp_path / "s.jbox"
    rec = Recorder(bus, path=path).start()
    try:
        time.sleep(0.15)
        bus.publish(topics.Transcript(text="words"))
        bus.publish(topics.MotionCommand(linear_x_mps=1.0))
        assert _wait(lambda: rec.recorded >= 2)
    finally:
        rec.stop()

    fresh = InProcBus()
    try:
        assert replay(fresh, path, speed=0, prefixes=("/sense/",)) == 1
    finally:
        fresh.close()


# ── robustness ───────────────────────────────────────────────────

def test_a_truncated_recording_reads_what_survived(tmp_path):
    """A killed process leaves a partial frame. The readable prefix is
    still the most valuable file you have."""
    path = tmp_path / "s.jbox"
    bus = InProcBus()
    rec = Recorder(bus, path=path).start()
    try:
        time.sleep(0.15)
        for i in range(10):
            bus.publish(topics.Transcript(text=f"t{i}"))
        assert _wait(lambda: rec.recorded >= 10)
    finally:
        rec.stop()
        bus.close()

    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) - 12])          # chop a frame in half
    assert 0 < len(list(read(path))) < 10


def test_a_foreign_file_is_refused(tmp_path):
    bad = tmp_path / "not-ours.bin"
    bad.write_bytes(b"just some bytes")
    with pytest.raises(ValueError, match="not a JaegerOS recording"):
        list(read(bad))


# ── the one-liner an app actually wants ──────────────────────────

def test_crash_reports_is_one_call(bus, tmp_path):
    """ROS keeps no always-on recorder at all — `ros2 bag record` is
    something you run once you know there is a problem. A small ring
    that costs nothing and answers "what happened just before" is
    already past that baseline; everything else in this module is for
    when you know what you are looking for."""
    from jaeger_os.transport.recorder import crash_reports

    rec = crash_reports(bus, tmp_path, app="demo")
    try:
        time.sleep(0.15)
        for i in range(15):
            bus.publish(topics.MotionCommand(linear_x_mps=float(i)))
        assert _wait(lambda: rec.recorded >= 15)
        assert list(tmp_path.iterdir()) == [], "wrote before any fault"

        bus.publish(topics.EStop(engaged=True, reason="button"))
        assert _wait(lambda: list(tmp_path.glob("*.jbox")))

        dump = list(tmp_path.glob("*.jbox"))[0]
        assert header(dump)["reason"] == "estop"
        assert len(list(read(dump))) >= 15
    finally:
        rec.stop()


def test_the_default_window_is_small_on_purpose(bus):
    """A crash window, not an archive. Growing it is a decision an app
    takes later, with evidence."""
    from jaeger_os.transport.recorder import DEFAULT_CAPACITY

    assert DEFAULT_CAPACITY <= 2000
