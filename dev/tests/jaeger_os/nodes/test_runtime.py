"""Tests for ``jaeger_os.nodes.runtime`` — Track B.2.1.

Runtime is the brain-side singleton that creates the bus and starts
the co-located TTS node.  These tests use injected factories so they
exercise the real runtime/thread path without loading Kokoro or
touching audio hardware.
"""

from __future__ import annotations

import uuid
import queue

from jaeger_os.transport import topics
from jaeger_os.core.audio import AudioSessionConfig
from jaeger_os.nodes import runtime
from jaeger_os.nodes.tts import TTSNode
from jaeger_os.transport import InProcBus


class _MockSynth:
    def __init__(self, *, warm_raises: bool = False):
        self.calls: list[str] = []
        self.warm_calls = 0
        self.shutdown_called = False
        self.warm_raises = warm_raises
        self.reference_buffer = None

    def speak(self, text: str):
        self.calls.append(text)
        return {"spoken": True, "elapsed_s": 0.01}

    def warm(self):
        self.warm_calls += 1
        if self.warm_raises:
            raise RuntimeError("warm failed")
        return {"warmed": True}

    def shutdown(self):
        self.shutdown_called = True


def _install_mock_runtime(monkeypatch, *, synth: _MockSynth | None = None):
    runtime.shutdown()
    synth = synth or _MockSynth()
    created: dict[str, object] = {"synth": synth}

    def synth_factory():
        return synth

    def node_factory(*, bus, synthesizer):
        node = TTSNode(
            bus=bus,
            synthesizer=synthesizer,
            name="tts",
            install_signal_handlers=False,
        )
        created["node"] = node
        return node

    monkeypatch.setattr(runtime, "_bus_factory", InProcBus)
    monkeypatch.setattr(runtime, "_synth_factory", synth_factory)
    monkeypatch.setattr(runtime, "_tts_node_factory", node_factory)
    return created


class _MockAudioSession:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.on_speech_detected = None
        self.phrases: "queue.Queue[str]" = queue.Queue()
        self.reference_buffer = None
        self.barge_in_live = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def next_phrase(self, timeout=1.0):
        try:
            return self.phrases.get(timeout=timeout)
        except queue.Empty:
            return None

    def set_on_speech_detected(self, callback):
        self.on_speech_detected = callback

    def feed(self, text):
        self.phrases.put(text)


def test_get_bus_returns_same_instance():
    """Repeated calls return the SAME Bus — it's a singleton."""
    runtime.shutdown()
    try:
        a = runtime.get_bus()
        b = runtime.get_bus()
        assert a is b
    finally:
        runtime.shutdown()


def test_get_bus_creates_inproc_bus():
    runtime.shutdown()
    try:
        bus = runtime.get_bus()
        assert isinstance(bus, InProcBus)
    finally:
        runtime.shutdown()


def test_shutdown_clears_bus_singleton():
    runtime.shutdown()
    bus1 = runtime.get_bus()
    runtime.shutdown()
    assert bus1 is not None
    assert runtime._bus is None


def test_shutdown_is_idempotent():
    runtime.shutdown()
    runtime.shutdown()
    runtime.shutdown()  # no raise


def test_shutdown_then_get_bus_creates_fresh_bus():
    """After shutdown, a subsequent get_bus() gets a NEW bus, not
    the closed one."""
    runtime.shutdown()
    bus1 = runtime.get_bus()
    runtime.shutdown()
    bus2 = runtime.get_bus()
    try:
        assert bus1 is not bus2
    finally:
        runtime.shutdown()


# ── bus injection (0.8 U3) ──────────────────────────────────────────


def test_set_bus_injects_and_get_bus_returns_it():
    """A chassis (or boot_for_tui) injects its OWN bus; get_bus() must
    hand that exact object back, not mint a second one."""
    runtime.shutdown()
    injected = InProcBus()
    try:
        runtime.set_bus(injected)
        assert runtime.get_bus() is injected
    finally:
        runtime.shutdown()
        injected.close()


def test_set_bus_is_idempotent_with_the_same_bus():
    runtime.shutdown()
    injected = InProcBus()
    try:
        runtime.set_bus(injected)
        runtime.set_bus(injected)   # no-op, doesn't raise or swap
        assert runtime.get_bus() is injected
    finally:
        runtime.shutdown()
        injected.close()


def test_get_bus_then_set_bus_same_object_is_a_noop():
    """The boot_for_tui pattern: get_bus() mints, then set_bus(get_bus())
    re-injects the SAME object — formalising it as owned-by-runtime
    without disturbing ownership."""
    runtime.shutdown()
    try:
        minted = runtime.get_bus()
        runtime.set_bus(minted)
        assert runtime.get_bus() is minted
        assert runtime._bus_owned is True   # still runtime's to close
    finally:
        runtime.shutdown()


def test_shutdown_does_not_close_an_injected_bus():
    """runtime.shutdown() must never close a chassis-owned bus — only
    the chassis that minted it may close it."""
    runtime.shutdown()
    injected = InProcBus()
    try:
        runtime.set_bus(injected)
        runtime.shutdown()
        assert runtime._bus is None          # singleton cleared
        assert injected._closed is False     # NOT closed by runtime
    finally:
        injected.close()


def test_shutdown_closes_a_self_minted_bus():
    """The bare TUI/daemon path: nothing ever injected a foreign bus, so
    shutdown() DOES close the one runtime minted for itself."""
    runtime.shutdown()
    bus = runtime.get_bus()
    runtime.shutdown()
    assert runtime._bus is None
    assert bus._closed is True
    fresh = runtime.get_bus()
    try:
        assert fresh is not bus
    finally:
        runtime.shutdown()


def test_ensure_tts_node_starts_node_and_installs_subscriber(monkeypatch):
    created = _install_mock_runtime(monkeypatch)
    try:
        node = runtime.ensure_tts_node()
        bus = runtime.get_bus()

        cid = uuid.uuid4().hex
        ack = bus.request(
            topics.SpeechCommand(text="ready", correlation_id=cid),
            ack_topic=topics.SENSE_SPOKEN,
            timeout_s=1.0,
        )

        assert node is created["node"]
        assert ack is not None
        assert ack.ok is True
        assert ack.correlation_id == cid
        assert created["synth"].calls == ["ready"]
    finally:
        runtime.shutdown()


def test_ensure_tts_node_warm_failure_is_nonfatal(monkeypatch, capsys):
    synth = _MockSynth(warm_raises=True)
    _install_mock_runtime(monkeypatch, synth=synth)
    try:
        node = runtime.ensure_tts_node(warm=True)
        assert node is runtime._tts_node
        assert synth.warm_calls == 1
        assert "warm at ensure_tts_node failed" in capsys.readouterr().err
    finally:
        runtime.shutdown()


def test_shutdown_stops_node_thread_and_synth(monkeypatch):
    created = _install_mock_runtime(monkeypatch)
    runtime.ensure_tts_node()
    synth = created["synth"]

    runtime.shutdown()

    assert runtime._tts_node is None
    assert runtime._tts_thread is None
    assert runtime._bus is None
    assert synth.shutdown_called is True


def test_ensure_audio_session_node_publishes_transcript(monkeypatch):
    created = _install_mock_runtime(monkeypatch)
    session = _MockAudioSession()
    monkeypatch.setattr(
        runtime,
        "_audio_session_factory",
        lambda _config: session,
    )
    try:
        node = runtime.ensure_audio_session_node(
            config=AudioSessionConfig(require_wake_word=False),
        )
        bus = runtime.get_bus()
        got = []

        def on_transcript(msg):
            got.append(msg)

        bus.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
        session.feed("hello via audio node")
        import time
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not got:
            time.sleep(0.01)

        assert node is runtime._audio_session_node
        assert session.started is True
        assert got
        assert got[0].text == "hello via audio node"
        assert got[0].node_id == "audio_session"
        assert created["synth"] is runtime.get_synth()
    finally:
        runtime.shutdown()


def test_shutdown_audio_session_node_leaves_tts_running(monkeypatch):
    _install_mock_runtime(monkeypatch)
    session = _MockAudioSession()
    monkeypatch.setattr(
        runtime,
        "_audio_session_factory",
        lambda _config: session,
    )
    try:
        runtime.ensure_audio_session_node(
            config=AudioSessionConfig(require_wake_word=False),
        )
        assert runtime._tts_node is not None

        runtime.shutdown_audio_session_node()

        assert session.stopped is True
        assert runtime._audio_session_node is None
        assert runtime._audio_session_thread is None
        assert runtime._tts_node is not None
    finally:
        runtime.shutdown()


# ── supervisor-backed ensure_* delegation (0.8 U3b) ──────────────────
#
# A duck-typed fake stands in for jaeger_os.app.supervisor.Supervisor
# here — these tests exercise ONLY runtime.py's delegation logic
# (has/enabled/is_running/node/start), not the real Supervisor/
# ThreadHandle machinery (that's covered end-to-end in
# dev/tests/jaeger_os/app/test_app_format.py's supervisor-backed
# JaegerApp tests).


class _FakeSupervisorNode:
    """Duck-types jaeger_os.app.supervisor.Supervisor just enough for
    runtime.py's ensure_*_node delegation branch: has/enabled/
    is_running/node/start. ``factory`` is whatever runtime._build_*
    function the real make_*_node would call — start() invokes it
    fresh each time, mirroring ThreadHandle.start()/.restart()'s "never
    reuse a torn-down node object" contract."""

    def __init__(self, node_id: str, factory, *, enabled: bool = True):
        self.node_id = node_id
        self.factory = factory
        self._enabled = enabled
        self._running = False
        self._node = None
        self.start_calls = 0

    def has(self, node_id: str) -> bool:
        return node_id == self.node_id

    def enabled(self, node_id: str) -> bool:
        return node_id == self.node_id and self._enabled

    def is_running(self, node_id: str) -> bool:
        return node_id == self.node_id and self._running

    def start(self, node_id: str) -> None:
        assert node_id == self.node_id
        self.start_calls += 1
        self._node = self.factory()
        self._running = True

    def node(self, node_id: str):
        return self._node if node_id == self.node_id else None

    def crash_and_prepare_restart(self) -> None:
        """Simulate the Supervisor's watch thread observing a dead
        node: alive() goes False so the next ensure_* call re-starts
        it (via a FRESH factory() call, per ThreadHandle.restart())."""
        self._running = False


def test_ensure_tts_node_delegates_to_registered_supervisor(monkeypatch):
    created = _install_mock_runtime(monkeypatch)
    bus = runtime.get_bus()
    fake = _FakeSupervisorNode(
        "tts", lambda: runtime._build_tts_node(bus, {}),
    )
    runtime.set_supervisor(fake)
    try:
        node = runtime.ensure_tts_node()
        assert fake.start_calls == 1
        assert node is fake.node("tts")
        assert node is runtime._tts_node
        assert runtime._synth is created["synth"]

        # Idempotent: a second call must NOT re-start the supervised
        # node (no double-spawn) — it just reads the live object again.
        node_again = runtime.ensure_tts_node()
        assert fake.start_calls == 1
        assert node_again is node
    finally:
        runtime.set_supervisor(None)
        runtime.shutdown()


def test_ensure_tts_node_reflects_a_supervisor_restart(monkeypatch):
    """The seam this delegation adds: after the supervisor restarts a
    crashed node (fresh object from a fresh factory() call),
    ensure_tts_node() must return the NEW live object, not a stale
    cached one — get_synth()/get_audio_session() depend on this."""
    _install_mock_runtime(monkeypatch)
    bus = runtime.get_bus()
    fake = _FakeSupervisorNode(
        "tts", lambda: runtime._build_tts_node(bus, {}),
    )
    runtime.set_supervisor(fake)
    try:
        node1 = runtime.ensure_tts_node()
        fake.crash_and_prepare_restart()
        node2 = runtime.ensure_tts_node()
        assert fake.start_calls == 2
        assert node2 is not node1
        assert node2 is fake.node("tts")
    finally:
        runtime.set_supervisor(None)
        runtime.shutdown()


def test_ensure_tts_node_falls_back_when_no_supervisor_registered(monkeypatch):
    """Default state (no chassis ever called set_supervisor — the
    TUI/bridge/daemon boot roots) — byte-identical thread-spawn path."""
    created = _install_mock_runtime(monkeypatch)
    assert runtime._supervisor is None
    try:
        node = runtime.ensure_tts_node()
        assert node is created["node"]
        assert runtime._tts_node is node
    finally:
        runtime.shutdown()


def test_ensure_tts_node_ignores_an_undeclared_supervisor():
    """A supervisor IS registered, but its manifest never declared a
    "tts" node (e.g. a manifest without the tts entry) — falls back to
    the legacy path rather than erroring."""
    class _NothingDeclared:
        def has(self, node_id):
            return False
    runtime.shutdown()
    runtime.set_supervisor(_NothingDeclared())
    try:
        bus = runtime.get_bus()
        assert isinstance(bus, InProcBus)
    finally:
        runtime.set_supervisor(None)
        runtime.shutdown()


def test_ensure_tts_node_ignores_a_disabled_supervised_node(monkeypatch):
    """The node is declared but enabled = false (e.g. root jaeger.toml's
    still-parked entries) — delegation must not force-start it; falls
    back to the legacy spawn instead."""
    created = _install_mock_runtime(monkeypatch)
    fake = _FakeSupervisorNode(
        "tts", lambda: runtime._build_tts_node(runtime.get_bus(), {}),
        enabled=False,
    )
    runtime.set_supervisor(fake)
    try:
        node = runtime.ensure_tts_node()
        assert fake.start_calls == 0          # never force-started
        assert node is created["node"]        # legacy path built it
    finally:
        runtime.set_supervisor(None)
        runtime.shutdown()


def test_ensure_animation_node_delegates_to_registered_supervisor(monkeypatch):
    """Same delegation shape for the animation node — also exercises
    _build_animation_node's bridge/auto-driver rebuild-fresh-each-call
    path (enable_bridge=False so no real socket is bound)."""
    runtime.shutdown()
    bus = runtime.get_bus()
    fake = _FakeSupervisorNode(
        "animation",
        lambda: runtime._build_animation_node(bus, enable_bridge=False),
    )
    runtime.set_supervisor(fake)
    try:
        node = runtime.ensure_animation_node(enable_bridge=False)
        assert fake.start_calls == 1
        assert node is fake.node("animation")
        assert node is runtime._animation_node
        node_again = runtime.ensure_animation_node(enable_bridge=False)
        assert fake.start_calls == 1
        assert node_again is node
    finally:
        runtime.set_supervisor(None)
        runtime.shutdown()
