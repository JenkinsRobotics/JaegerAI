"""Warm-up belongs to the node lifecycle and never blocks setup."""

from __future__ import annotations

import threading
import time

from jaeger_os.nodes.base import NodeState
from jaeger_os.transport import InProcBus

from jaeger_kokoro_tts.node import TTSNode


class _SlowSynth:
    WARM_S = 0.5

    def __init__(self) -> None:
        self.warmed = threading.Event()
        self.warm_calls = 0

    def warm(self) -> dict:
        self.warm_calls += 1
        time.sleep(self.WARM_S)
        self.warmed.set()
        return {"warmed": True}

    def speak(self, text: str) -> dict:
        return {"spoken": True}

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _run(*, warm: bool = True):
    bus = InProcBus()
    synth = _SlowSynth()
    node = TTSNode(bus=bus, synthesizer=synth, warm_on_start=warm)
    started = time.perf_counter()
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and node.state != NodeState.RUNNING:
        time.sleep(0.01)
    return bus, synth, node, thread, time.perf_counter() - started


def _close(bus, node, thread) -> None:
    node.stop()
    thread.join(timeout=2.0)
    bus.close()


def test_warms_by_default_without_blocking_node_start() -> None:
    bus, synth, node, thread, elapsed = _run()
    try:
        assert node.state == NodeState.RUNNING
        assert elapsed < _SlowSynth.WARM_S
        assert synth.warmed.wait(timeout=2.0)
        assert synth.warm_calls == 1
        assert node.health()["warm_status"] == "ready"
    finally:
        _close(bus, node, thread)


def test_warm_false_opts_out() -> None:
    bus, synth, node, thread, _ = _run(warm=False)
    try:
        assert not synth.warmed.wait(timeout=0.3)
        assert synth.warm_calls == 0
        assert node.health()["warm_status"] == "disabled"
    finally:
        _close(bus, node, thread)
