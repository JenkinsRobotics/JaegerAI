"""The animation module's inputs and outputs, as contract truth.

An engine module is responsible for declaring every input and output a
host might want to drive or monitor; the framework only provides the
pub/sub. These are the types that let it.
"""

import msgspec
import pytest

from jaeger_os.contract import topics
from jaeger_os.contract.modules import MODULE_KINDS, ModuleSpec
from jaeger_os.core.modules import load_module


# ── FrameBuffer: the one frame truth ─────────────────────────────

def test_frame_buffer_is_in_the_contract():
    fb = topics.FrameBuffer(width=2, height=1, data=b"\x00" * 8)
    assert len(fb.data) == fb.width * fb.height * 4
    assert fb.duration_ms == 0
    assert fb.is_final is False


# ── DisplayFrame: pixels, with pacing ──────────────────────────

def test_animation_frame_roundtrips():
    msg = topics.DisplayFrame(
        data=b"\x01\x02\x03\x04", width=1, height=1,
        duration_ms=40, is_final=True)
    assert msg.topic == "/act/display/frame"
    back = msgspec.msgpack.decode(
        msgspec.msgpack.encode(msg), type=topics.DisplayFrame)
    assert back.duration_ms == 40 and back.is_final is True


def test_a_frame_carries_its_own_pacing():
    """A decoder knows per-frame duration — a GIF's delays vary within
    one file. Without carrying it, a subscriber has to guess a frame
    rate and infer clip ends from a separate topic with no ordering
    guarantee."""
    fields = set(topics.DisplayFrame.__struct_fields__)
    assert {"duration_ms", "is_final"} <= fields


def test_one_frame_topic_serves_every_display():
    """There were once two nearly identical frame topics — an
    "animation" one and a "media" one — so a renderer could subscribe to
    the face without also receiving arbitrary media playback. The
    instance segment does that job now, so the duplication is gone.

    This is the test that the separation is genuinely still available.
    """
    from jaeger_os.contract.paths import for_instance, matches

    face = for_instance(topics.ACT_DISPLAY_FRAME, "face0")
    media = for_instance(topics.ACT_DISPLAY_FRAME, "media0")
    assert face != media

    face_only = "/act/display/face0/"
    assert matches(face_only, face)
    assert not matches(face_only, media), \
        "subscribing to the face would also deliver media playback"


def test_both_frame_kinds_decode_through_one_registration():
    """One class, so one decoder path — the point of merging."""
    for instance in ("face0", "media0", "matrix7"):
        live = f"/act/display/{instance}/frame"
        assert topics.class_for_topic(live) is topics.DisplayFrame


# ── DisplayStats: telemetry, off the pixel path ────────────────

def test_animation_stats_reports_framerate():
    s = topics.DisplayStats(
        adapter="gif", asset_path="idle.gif", width=64, height=64,
        fps_actual=28.5, fps_target=30.0, frames_emitted=100,
        frames_dropped=2, decode_ms=1.4, queue_depth=0)
    assert s.topic == "/act/display/stats"
    back = msgspec.msgpack.decode(
        msgspec.msgpack.encode(s), type=topics.DisplayStats)
    assert back.fps_actual == 28.5
    assert back.frames_dropped == 2


def test_stats_is_not_the_frame_topic():
    """Monitoring a face's health must not require subscribing to its
    full pixel stream."""
    assert "data" not in topics.DisplayStats.__struct_fields__
    assert topics.ACT_DISPLAY_STATS != topics.ACT_DISPLAY_FRAME


# ── registration ─────────────────────────────────────────────────

@pytest.mark.parametrize("topic,cls", [
    ("/act/display/frame", "DisplayFrame"),
    ("/act/display/stats", "DisplayStats"),
])
def test_registered_in_the_codec(topic, cls):
    """An unregistered Struct cannot ride the ZMQ bus."""
    assert topic in topics.ALL_TOPICS
    assert topics.class_for_topic(topic) is getattr(topics, cls)


# ── ModuleSpec.kind ──────────────────────────────────────────────

def test_kind_accepts_the_taxonomy_values():
    for kind in MODULE_KINDS:
        spec = msgspec.convert(
            {"module": "m", "slot": "s", "factory": "p:f", "kind": kind},
            ModuleSpec,
        )
        assert spec.kind == kind


def test_kind_defaults_empty_so_older_manifests_still_validate():
    spec = msgspec.convert(
        {"module": "m", "slot": "s", "factory": "p:f"}, ModuleSpec)
    assert spec.kind == ""


def test_bad_kind_names_the_offending_file(tmp_path):
    (tmp_path / "module.yaml").write_text(
        "module: m\nslot: s\nfactory: p:f\nkind: nonsense\n")
    with pytest.raises(ValueError) as exc:
        load_module(tmp_path)
    assert "module.yaml" in str(exc.value)
    assert "nonsense" in str(exc.value)


def test_valid_kind_loads(tmp_path):
    (tmp_path / "module.yaml").write_text(
        "module: m\nslot: s\nfactory: p:f\nkind: processing\n")
    assert load_module(tmp_path).kind == "processing"
