"""Hierarchical topic paths — subscribe at any level, filter in the transport.

    /sense/camera/cam0/image_raw
     └cat──┘ └class┘ └inst┘ └─msg─┘

The point is that a consumer wanting one camera never RECEIVES the other
one. A flat namespace makes it receive everything and discard — free
in-process, but 81 MB/s of wasted link at 720p30 across a network.
"""

from __future__ import annotations

import time

import pytest

from jaeger_os.contract.paths import (
    TopicPathError, canonical, for_instance, instance_of, matches, parse,
)
from jaeger_os.transport import InProcBus, topics


# ── the grammar ──────────────────────────────────────────────────

def test_an_instanced_path_parses():
    p = parse("/sense/camera/cam0/image_raw")
    assert (p.category, p.cls, p.instance, p.message) == (
        "sense", "camera", "cam0", "image_raw")


def test_a_singleton_path_parses():
    p = parse("/act/speech/say")
    assert p.instance == ""


def test_canonical_strips_the_instance():
    """One contract registration serves every instance."""
    assert canonical("/sense/camera/cam0/image_raw") == \
        "/sense/camera/image_raw"
    assert canonical("/act/speech/say") == "/act/speech/say"


def test_for_instance_builds_a_live_path():
    assert for_instance("/sense/camera/image_raw", "cam1") == \
        "/sense/camera/cam1/image_raw"


def test_instance_of_reads_it_back():
    assert instance_of("/sense/camera/cam0/image_raw") == "cam0"
    assert instance_of("/act/speech/say") == ""


@pytest.mark.parametrize("bad,why", [
    ("sensor/camera/image_raw", "leading separator"),
    ("/sense/camera", "too few segments"),
    ("/sense/camera/cam0/deep/image_raw", "too many segments"),
    ("/nonsense/camera/image_raw", "unknown category"),
    ("/sense/cam era/image_raw", "space in class"),
])
def test_a_malformed_path_is_refused(bad, why):
    with pytest.raises(TopicPathError):
        parse(bad)


def test_an_unparseable_path_passes_through_canonical():
    """`canonical` is called on every decode. A path it cannot parse
    must come back unchanged so the caller gets a clean KeyError from
    the registry, not a TopicPathError from three frames down."""
    assert canonical("/sense/camera_frame") == "/sense/camera_frame"
    assert canonical("garbage") == "garbage"


# ── prefix semantics ─────────────────────────────────────────────

def test_a_prefix_matches_everything_beneath_it():
    topic = "/sense/camera/cam0/image_raw"
    assert matches("/sense/", topic)
    assert matches("/sense/camera/", topic)
    assert matches("/sense/camera/cam0/", topic)
    assert not matches("/act/", topic)


def test_the_trailing_separator_prevents_over_matching():
    """Without it, /sense/cam would match /sense/camera/... and a
    subscriber would silently receive a stream it never asked for."""
    p = parse("/sense/camera/cam0/image_raw")
    assert p.prefix.endswith("/")
    assert not matches("/sense/camera/cam0/", "/sense/camera/cam00/x_y")


# ── type resolution ──────────────────────────────────────────────

def test_every_instance_resolves_to_one_registered_class():
    """An instance id is runtime data the contract has never seen."""
    for inst in ("cam0", "cam1", "some-late-added-camera"):
        cls = topics.class_for_topic(f"/sense/camera/{inst}/image_raw")
        assert cls is topics.CameraFrame


def test_a_genuinely_unknown_topic_still_raises():
    with pytest.raises(KeyError):
        topics.class_for_topic("/sense/lidar/scan")


# ── the bus honours it, in-process ───────────────────────────────

def _publish(bus, instance, cam_id):
    msg = topics.CameraFrame(
        topic=f"/sense/camera/{instance}/image_raw", camera_id=cam_id)
    bus.publish(msg)


def test_in_process_prefix_subscription_selects_by_level():
    """The whole point: a subscriber to one camera never sees the other.

    In-process this is cheap either way — but it MUST match ZMQ's
    behaviour, or code that works fused breaks the moment a node moves
    to its own process."""
    bus = InProcBus()
    got = {p: [] for p in ("/sense/", "/sense/camera/",
                           "/sense/camera/cam0/", "/act/")}
    try:
        for prefix in got:
            bus.subscribe(prefix, lambda m, p=prefix: got[p].append(m.camera_id))
        time.sleep(0.15)
        _publish(bus, "cam0", "cam0")
        _publish(bus, "cam1", "cam1")
        deadline = time.monotonic() + 3.0
        while len(got["/sense/"]) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)

        assert sorted(got["/sense/"]) == ["cam0", "cam1"]
        assert sorted(got["/sense/camera/"]) == ["cam0", "cam1"]
        assert got["/sense/camera/cam0/"] == ["cam0"], "leaked cam1"
        assert got["/act/"] == [], "matched an unrelated category"
    finally:
        bus.close()


def test_exact_subscription_still_works_alongside_prefixes():
    """A system that never uses the hierarchy must be unaffected."""
    bus = InProcBus()
    exact, prefixed = [], []
    try:
        bus.subscribe("/sense/camera/cam0/image_raw", exact.append)
        bus.subscribe("/sense/", prefixed.append)
        time.sleep(0.15)
        _publish(bus, "cam0", "cam0")
        deadline = time.monotonic() + 3.0
        while not (exact and prefixed) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(exact) == 1 and len(prefixed) == 1
    finally:
        bus.close()


def test_unsubscribing_a_prefix_stops_it():
    bus = InProcBus()
    got = []
    try:
        bus.subscribe("/sense/", got.append)
        time.sleep(0.15)
        bus.unsubscribe("/sense/", got.append)
        _publish(bus, "cam0", "cam0")
        time.sleep(0.3)
        assert got == []
    finally:
        bus.close()
