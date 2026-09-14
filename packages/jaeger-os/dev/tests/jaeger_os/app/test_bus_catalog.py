"""The bus catalog — what is running, and what does it talk to?

The gap this closes: JaegerOS had no way to ask a LIVE system what was
publishing what. Debugging a running graph meant reading source. ROS
answers this with `ros2 node list` / `ros2 topic info`; the parity review
ranked it the biggest ergonomics gap.

Mochi 3.0 solved it in ~10 lines by having every node announce itself,
because a node already knows its own topics. Same approach here.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.app.catalog import BusCatalog
from jaeger_os.nodes.base import Node
from jaeger_os.transport import InProcBus, topics


class _Face(Node):
    def setup(self):
        self.subscribe(topics.ACT_DISPLAY_PLAY, lambda m: None)

    def tick(self):
        self.publish(topics.DisplayState(
            state="idle", progress=1.0, elapsed_ms=0))
        time.sleep(0.02)


class _Renderer(Node):
    def setup(self):
        self.subscribe(topics.ACT_DISPLAY_STATE, lambda m: None)

    def tick(self):
        time.sleep(0.02)


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


@pytest.fixture
def running(bus):
    """Two nodes wired producer -> consumer, actually running."""
    nodes = [_Face(bus=bus, name="animation", install_signal_handlers=False),
             _Renderer(bus=bus, name="window", install_signal_handlers=False)]
    threads = [threading.Thread(target=n.run, daemon=True) for n in nodes]
    for t in threads:
        t.start()
    time.sleep(0.5)
    yield nodes
    for n in nodes:
        n.stop()
    for t in threads:
        t.join(timeout=2)


def _settle(catalog, expect: int, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(catalog.nodes()) >= expect:
            return True
        time.sleep(0.02)
    return False


# ── announcement ─────────────────────────────────────────────────

def test_a_node_announces_itself_on_reaching_running(bus):
    catalog = BusCatalog(bus).attach()
    node = _Face(bus=bus, name="animation", install_signal_handlers=False)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        assert _settle(catalog, 1), "node never announced"
        meta = catalog.nodes()["animation"]
        assert meta.node_class == "_Face"
        assert meta.state == "running"
        assert meta.pid > 0
    finally:
        node.stop()
        thread.join(timeout=2)


def test_subscriptions_are_observed_not_declared(bus, running):
    """A module.yaml declares intent; this reports what the node
    actually subscribed to. The two disagreeing is worth knowing."""
    catalog = BusCatalog(bus).attach()
    catalog.request_announce()
    assert _settle(catalog, 2)
    assert topics.ACT_DISPLAY_PLAY in catalog.nodes()["animation"].subscribes


def test_publishes_are_observed_too(bus, running):
    catalog = BusCatalog(bus).attach()
    time.sleep(0.3)          # let the node publish at least once
    catalog.request_announce()
    assert _settle(catalog, 2)
    assert topics.ACT_DISPLAY_STATE in catalog.nodes()["animation"].publishes


def test_the_meta_topic_is_not_reported_as_an_input(bus, running):
    """Every node subscribes to it for re-announce requests, so listing
    it tells a reader nothing and buries the real inputs."""
    catalog = BusCatalog(bus).attach()
    catalog.request_announce()
    assert _settle(catalog, 2)
    for meta in catalog.nodes().values():
        assert topics.SYS_NODE_META not in meta.subscribes


# ── the graph view ───────────────────────────────────────────────

def test_topics_maps_producers_to_consumers(bus, running):
    catalog = BusCatalog(bus).attach()
    time.sleep(0.3)
    catalog.request_announce()
    assert _settle(catalog, 2)
    graph = catalog.topics()
    entry = graph[topics.ACT_DISPLAY_STATE]
    assert entry["publishers"] == ["animation"]
    assert entry["subscribers"] == ["window"]


def test_orphan_topics_finds_a_topic_nobody_feeds(bus, running):
    """The cheapest real bug-finder this view enables: a consumer
    waiting for something that never comes."""
    catalog = BusCatalog(bus).attach()
    catalog.request_announce()
    assert _settle(catalog, 2)
    orphans = catalog.orphan_topics()
    assert topics.ACT_DISPLAY_PLAY in orphans["subscribed_but_unfed"]


def test_describe_is_readable(bus, running):
    catalog = BusCatalog(bus).attach()
    time.sleep(0.3)
    catalog.request_announce()
    assert _settle(catalog, 2)
    text = catalog.describe()
    assert "animation" in text and "window" in text
    assert "<-" in text and "->" in text


# ── late attach ──────────────────────────────────────────────────

def test_a_catalog_attached_after_boot_can_still_see_everything(bus, running):
    """The announcements already happened. Rather than persist them
    (stale the moment a node restarts), ask the nodes again — they are
    the source of truth about themselves."""
    catalog = BusCatalog(bus).attach()      # attached AFTER the fixture ran
    assert catalog.nodes() == {}
    catalog.request_announce()
    assert _settle(catalog, 2), "re-announce did not repopulate the catalog"


def test_a_request_is_not_mistaken_for_a_node(bus):
    """The request rides the same topic with an empty node name."""
    catalog = BusCatalog(bus).attach()
    catalog.request_announce()
    time.sleep(0.2)
    assert catalog.nodes() == {}


# ── it must not perturb what it measures ─────────────────────────

def test_the_catalog_is_passive(bus, running):
    """Attaching must not change node behaviour — it only listens."""
    before = [n.state for n in running]
    BusCatalog(bus).attach()
    time.sleep(0.3)
    assert [n.state for n in running] == before


def test_announce_never_raises_through_the_node(bus):
    """Introspection must never be able to take down the thing it
    describes."""
    class _Exploding:
        def publish(self, msg):
            raise RuntimeError("bus is angry")

        def subscribe(self, *a, **k):
            pass

    node = _Face(bus=_Exploding(), name="x", install_signal_handlers=False)
    node.announce()   # must not raise
