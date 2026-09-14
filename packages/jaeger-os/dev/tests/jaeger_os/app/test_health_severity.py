"""Health severity and measured telemetry.

Two gaps from the parity review:

**2a — no severity.** `NodeHealth` carried `state` and a `detail`
string. A node RUNNING but dropping 40% of its frames reported exactly
what a healthy one did, so a supervisor could not tell them apart.

**2c — telemetry had no home.** `health()` is a pull returning an opaque
dict; anything a host wanted to watch continuously had nowhere to go.
Mochi 3.0 put `fps_target` / `memory_mb` / `tx_rate_mbps` in its NODE
BASE, which is the right home: any node can then be asked whether it is
keeping up, without each module inventing its own answer.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.app.health import STALE_AFTER_S, HealthCache
from jaeger_os.nodes.base import Node
from jaeger_os.transport import InProcBus, topics


class _Busy(Node):
    """Publishes every tick, so tx_rate is non-zero."""

    def tick(self):
        self.publish(topics.DisplayState(
            state="idle", progress=1.0, elapsed_ms=0))
        time.sleep(0.02)


class _Broken(Node):
    def tick(self):
        time.sleep(0.02)
        raise ValueError("every tick fails")


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _run(node):
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    return t


def _wait_health(seen, timeout=4.0, n=1):
    deadline = time.monotonic() + timeout
    while len(seen) < n and time.monotonic() < deadline:
        time.sleep(0.02)
    return len(seen) >= n


# ── measured telemetry, for every node ───────────────────────────

def test_health_carries_measured_rates(bus):
    seen = []
    bus.subscribe(topics.SYS_NODE_HEALTH, seen.append)
    node = _Busy(bus=bus, name="busy", install_signal_handlers=False)
    thread = _run(node)
    try:
        assert _wait_health(seen, n=2), "no heartbeats"
        h = seen[-1]
        assert h.tick_rate_hz > 0, "tick rate never measured"
        assert h.tx_rate_hz > 0, "publish rate never measured"
        assert h.msgs_out > 0
        assert h.uptime_s > 0
    finally:
        node.stop()
        thread.join(timeout=2)


def test_no_module_had_to_ask_for_telemetry(bus):
    """_Busy declares nothing about telemetry — it is a plain Node. That
    is the point: the base measures it for everyone."""
    seen = []
    bus.subscribe(topics.SYS_NODE_HEALTH, seen.append)
    node = _Busy(bus=bus, name="busy", install_signal_handlers=False)
    thread = _run(node)
    try:
        assert _wait_health(seen)
        assert seen[-1].memory_mb > 0
    finally:
        node.stop()
        thread.join(timeout=2)


# ── severity ─────────────────────────────────────────────────────

def test_a_healthy_node_reports_ok(bus):
    seen = []
    bus.subscribe(topics.SYS_NODE_HEALTH, seen.append)
    node = _Busy(bus=bus, name="busy", install_signal_handlers=False)
    thread = _run(node)
    try:
        assert _wait_health(seen)
        assert seen[-1].level == topics.HEALTH_OK
    finally:
        node.stop()
        thread.join(timeout=2)


def test_a_node_erroring_every_tick_reports_warn(bus):
    """RUNNING but unwell. Without a level this is indistinguishable
    from healthy, which is exactly gap 2a."""
    seen = []
    bus.subscribe(topics.SYS_NODE_HEALTH, seen.append)
    node = _Broken(bus=bus, name="broken", install_signal_handlers=False)
    thread = _run(node)
    try:
        assert _wait_health(seen, n=2)
        warned = [h for h in seen if h.level == topics.HEALTH_WARN]
        assert warned, f"levels seen: {[h.level for h in seen]}"
        assert warned[-1].tick_errors > 0
        assert warned[-1].state == "running", "still RUNNING, just unwell"
    finally:
        node.stop()
        thread.join(timeout=2)


def test_warn_clears_when_ticks_stop_failing(bus):
    """WARN reflects NEW failures. Latching forever on one bad tick at
    boot would make the level useless."""
    node = _Busy(bus=bus, name="busy", install_signal_handlers=False)
    node._tick_errors = 1
    node._reported_tick_errors = 0
    assert node.health_level() == topics.HEALTH_WARN
    node._reported_tick_errors = 1
    assert node.health_level() == topics.HEALTH_OK


def test_a_fatal_error_reports_error(bus):
    node = _Busy(bus=bus, name="busy", install_signal_handlers=False)
    node._error = RuntimeError("fatal")
    assert node.health_level() == topics.HEALTH_ERROR


# ── the level a node cannot report ───────────────────────────────

def test_stale_is_decided_by_the_consumer(bus):
    """A node that stopped heartbeating cannot say so. Only something
    watching the clock can."""
    cache = HealthCache(bus)
    bus.publish(topics.NodeHealth(node="ghost", state="running",
                                  level=topics.HEALTH_OK))
    deadline = time.monotonic() + 2.0
    while cache.latest("ghost") is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert cache.level_for("ghost") == topics.HEALTH_OK
    # Same message, judged against a stricter clock.
    assert cache.level_for("ghost", stale_after_s=-1) == topics.HEALTH_STALE


def test_an_unknown_node_is_stale_not_ok(bus):
    assert HealthCache(bus).level_for("never-seen") == topics.HEALTH_STALE


def test_a_node_never_reports_stale_itself(bus):
    node = _Busy(bus=bus, name="busy", install_signal_handlers=False)
    node._error = RuntimeError("x")
    assert node.health_level() != topics.HEALTH_STALE
    node._error = None
    assert node.health_level() != topics.HEALTH_STALE


# ── the rollup ───────────────────────────────────────────────────

def _seed(cache, bus, **levels):
    for node, level in levels.items():
        bus.publish(topics.NodeHealth(node=node, state="running", level=level))
    deadline = time.monotonic() + 2.0
    while len(cache.snapshot()) < len(levels) and time.monotonic() < deadline:
        time.sleep(0.02)


def test_system_level_is_the_worst_node(bus):
    """"Is the robot healthy?" had no single answer before this — every
    caller had to fetch all nodes and invent its own aggregate."""
    cache = HealthCache(bus)
    _seed(cache, bus, a=topics.HEALTH_OK, b=topics.HEALTH_WARN,
          c=topics.HEALTH_OK)
    assert cache.system_level() == topics.HEALTH_WARN


def test_error_outranks_warn(bus):
    cache = HealthCache(bus)
    _seed(cache, bus, a=topics.HEALTH_WARN, b=topics.HEALTH_ERROR)
    assert cache.system_level() == topics.HEALTH_ERROR


def test_all_ok_rolls_up_to_ok(bus):
    cache = HealthCache(bus)
    _seed(cache, bus, a=topics.HEALTH_OK, b=topics.HEALTH_OK)
    assert cache.system_level() == topics.HEALTH_OK


def test_a_system_with_no_nodes_is_stale_not_healthy(bus):
    """Nothing reporting is not the same as everything fine."""
    assert HealthCache(bus).system_level() == topics.HEALTH_STALE


def test_unhealthy_lists_only_the_problems(bus):
    cache = HealthCache(bus)
    _seed(cache, bus, good=topics.HEALTH_OK, bad=topics.HEALTH_ERROR)
    bad = cache.unhealthy()
    assert bad == {"bad": topics.HEALTH_ERROR}


def test_severity_levels_match_the_ros_vocabulary():
    assert topics.HEALTH_LEVELS == ("OK", "WARN", "ERROR", "STALE")
