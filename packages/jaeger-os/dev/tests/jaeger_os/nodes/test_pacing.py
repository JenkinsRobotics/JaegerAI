"""A node that asks for a rate should get it.

The naive loop — do the work, then sleep the period — runs at
``1/(period+work)``, not ``1/period``. Measured: a node asking for
100 Hz with 4 ms of work per tick runs at 58.6 Hz. That is a 41%
shortfall nobody sees, because the code says 100 and the sleep says
10 ms and both look right.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os import Node
from jaeger_os.transport import InProcBus


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


class _Paced(Node):
    tick_period_s = 0.010
    work_s = 0.004

    def setup(self):
        self.stamps: list[float] = []

    def tick(self):
        time.sleep(self.work_s)
        self.stamps.append(time.perf_counter())


class _Unpaced(Node):
    def setup(self):
        self.stamps: list[float] = []

    def tick(self):
        time.sleep(0.004)
        self.stamps.append(time.perf_counter())


def _run(node, seconds):
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    time.sleep(seconds)
    node.stop()
    t.join(timeout=2)
    return node.stamps


def _rate(stamps):
    return (len(stamps) - 1) / (stamps[-1] - stamps[0])


def test_a_paced_node_hits_the_rate_it_asked_for(bus):
    """The whole point. Work time must not eat the period."""
    node = _Paced(bus=bus, name="paced", install_signal_handlers=False)
    hz = _rate(_run(node, 2.0))
    assert 92 <= hz <= 104, f"asked 100 Hz, got {hz:.1f}"


def test_an_unpaced_node_is_unchanged(bus):
    """tick_period_s is opt-in. A node that blocks on a queue or a
    device callback must not have a sleep inserted under it."""
    node = _Unpaced(bus=bus, name="unpaced", install_signal_handlers=False)
    assert node.tick_period_s is None
    hz = _rate(_run(node, 1.0))
    assert hz > 150, f"an unpaced node was throttled to {hz:.1f} Hz"


def test_an_overrun_does_not_produce_catch_up_ticks(bus):
    """A tick slower than its period must cause a SLOW TICK, not a
    burst of catch-up ticks hammering a device already struggling."""
    class _Slow(_Paced):
        tick_period_s = 0.010
        work_s = 0.030            # 3x its own period

    node = _Slow(bus=bus, name="slow", install_signal_handlers=False)
    stamps = _run(node, 1.0)
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    assert min(gaps) >= 0.025, (
        f"caught up in a burst: shortest gap {min(gaps)*1000:.1f} ms")
    assert node._tick_overruns > 0, "overruns went uncounted"


def test_overruns_are_counted(bus):
    """A rising count is a node asking for a rate its work cannot
    sustain — a fact rather than an impression."""
    class _Slow(_Paced):
        tick_period_s = 0.005
        work_s = 0.020

    node = _Slow(bus=bus, name="over", install_signal_handlers=False)
    _run(node, 0.6)
    assert node._tick_overruns >= 5


def test_a_slow_period_still_stops_promptly(bus):
    """Pacing waits on the stop event, not sleep(). A node with a 5 s
    period must not take 5 s to shut down."""
    class _Lazy(Node):
        tick_period_s = 5.0

        def tick(self):
            pass

    node = _Lazy(bus=bus, name="lazy", install_signal_handlers=False)
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    time.sleep(0.3)
    t0 = time.perf_counter()
    node.stop()
    t.join(timeout=3)
    assert time.perf_counter() - t0 < 1.0, "shutdown waited out the period"
