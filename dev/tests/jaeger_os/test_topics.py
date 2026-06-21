"""Test suite for ``jaeger_os.topics`` — the 0.4 node-topic SSOT.

Track A.1 of the 0.4 roadmap.  Schemas are msgspec.Struct (not
Pydantic) per the operator-resolved transport-schema decision; tests
exercise msgspec's JSON encode/decode + the forbid_unknown_fields
validation.
"""

from __future__ import annotations

import time

import msgspec
import pytest

from jaeger_os import topics


# ── registry shape ────────────────────────────────────────────────

def test_all_topics_matches_registry():
    """ALL_TOPICS must enumerate every key in TOPIC_TO_CLASS, no
    more no less.  Catches "added the constant but forgot to
    register" and "added to registry but forgot to expose"."""
    assert set(topics.ALL_TOPICS) == set(topics.TOPIC_TO_CLASS.keys())


def test_all_topics_are_unique():
    """No two topic constants resolve to the same string."""
    assert len(set(topics.ALL_TOPICS)) == len(topics.ALL_TOPICS)


def test_topic_namespace_shape():
    """Every topic begins with ``/sense/`` or ``/act/``.  The
    ``/health/*`` namespace is reserved for Track D; it shouldn't
    appear here yet."""
    for name in topics.ALL_TOPICS:
        assert name.startswith("/sense/") or name.startswith("/act/"), (
            f"topic {name!r} doesn't follow /sense/* | /act/* convention"
        )
        assert not name.startswith("/health/"), (
            f"{name!r} uses the /health/* namespace reserved for Track D"
        )


def test_class_for_topic_returns_topicmessage_subclass():
    """Every registered class derives from TopicMessage."""
    for name in topics.ALL_TOPICS:
        cls = topics.class_for_topic(name)
        assert issubclass(cls, topics.TopicMessage), (
            f"{cls.__name__} (registered for {name}) "
            f"isn't a TopicMessage subclass"
        )


def test_class_for_topic_raises_on_unknown():
    """Unknown topic strings are a hard error, not a silent miss."""
    with pytest.raises(KeyError):
        topics.class_for_topic("/sense/nonexistent")
    with pytest.raises(KeyError):
        topics.class_for_topic("not_even_namespaced")


def test_raw_camera_frame_topic_is_not_generic_vision():
    """Raw camera bytes should not occupy the future analysis topic."""
    assert topics.SENSE_CAMERA_FRAME == "/sense/camera_frame"
    assert topics.SENSE_VISION == topics.SENSE_CAMERA_FRAME
    assert topics.SENSE_VISION_ANALYSIS == "/sense/vision_analysis"
    assert topics.CameraFrame().topic == topics.SENSE_CAMERA_FRAME
    assert topics.SENSE_VISION_ANALYSIS not in topics.TOPIC_TO_CLASS


# ── envelope ──────────────────────────────────────────────────────

def test_envelope_timestamp_is_recent():
    """t_emit_ns defaults to a recent nanosecond timestamp.  Tight
    bound so a slow CI doesn't false-pass."""
    before = time.time_ns()
    msg = topics.SpokenAck(ok=True)
    after = time.time_ns()
    assert before <= msg.t_emit_ns <= after, (
        f"t_emit_ns={msg.t_emit_ns} not in [{before}, {after}]"
    )


def test_envelope_correlation_id_defaults_to_none():
    """Non-RPC messages don't need a correlation_id."""
    msg = topics.AudioInFrame()
    assert msg.correlation_id is None


def test_envelope_correlation_id_round_trips_via_json():
    """An explicit correlation_id survives JSON serialization."""
    msg = topics.SpeechCommand(text="hello", correlation_id="abc123")
    encoded = msgspec.json.encode(msg)
    decoded = msgspec.json.decode(encoded, type=topics.SpeechCommand)
    assert decoded.correlation_id == "abc123"


def test_envelope_topic_v_defaults_to_one():
    """First-version schema; bumps later only on breaking changes."""
    msg = topics.MotionCommand()
    assert msg.topic_v == 1


# ── per-class invariants ───────────────────────────────────────────

# Each registered topic class is parameterised here.  msgspec
# Structs with kw_only=True don't require constructor args — all
# fields have defaults — so no kwargs dict is needed.
_REGISTERED: tuple[type[topics.TopicMessage], ...] = (
    topics.AudioInFrame,
    topics.Transcript,
    topics.UserSpeechStart,
    topics.CameraFrame,
    topics.TouchReading,
    topics.ProprioReading,
    topics.SpokenAck,
    topics.SpeechCommand,
    topics.AudioOutFrame,
    topics.MotionCommand,
    topics.LightCommand,
    topics.SpeechStop,
)


@pytest.mark.parametrize("cls", _REGISTERED)
def test_topic_class_pins_its_constant(cls):
    """Default-construction of each class must produce ``msg.topic``
    equal to the registered constant.  Catches Literal-vs-constant
    typos at the class definition level."""
    msg = cls()
    name = msg.topic
    assert name in topics.TOPIC_TO_CLASS, (
        f"{cls.__name__}.topic = {name!r}, not a registered topic"
    )
    assert topics.TOPIC_TO_CLASS[name] is cls, (
        f"{name!r} resolves to {topics.TOPIC_TO_CLASS[name].__name__}, "
        f"not the expected {cls.__name__}"
    )


@pytest.mark.parametrize("cls", _REGISTERED)
def test_extra_fields_are_rejected_at_decode(cls):
    """``forbid_unknown_fields=True`` must catch unrecognised payload
    keys arriving over the wire — otherwise a typo silently drops
    the value."""
    canonical = msgspec.json.encode(cls())
    # Inject an unknown key into the encoded JSON.
    bad = canonical.rstrip(b"}") + b',"this_field_does_not_exist":42}'
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(bad, type=cls)


@pytest.mark.parametrize("cls", _REGISTERED)
def test_topic_field_rejected_when_mismatched(cls):
    """A wire payload claiming the wrong topic for the class must
    fail decode — msgspec validates Literal types."""
    canonical = msgspec.json.encode(cls())
    # Replace the topic value with a known-different one.
    other_topic = next(t for t in topics.ALL_TOPICS if t != cls().topic)
    bad = canonical.replace(
        f'"topic":"{cls().topic}"'.encode(),
        f'"topic":"{other_topic}"'.encode(),
    )
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(bad, type=cls)


# ── per-class field semantics ─────────────────────────────────────

def test_audio_in_frame_carries_binary_samples():
    """Binary samples survive msgpack round-trip natively — no
    base64 hop needed (the whole point of using MessagePack for
    binary topics per ROADMAP_0.4.md open question #2)."""
    raw = b"\x00\x01\x02\xff\xfe\xfd"
    msg = topics.AudioInFrame(samples=raw, sample_rate=16000)
    encoded = msgspec.msgpack.encode(msg)
    decoded = msgspec.msgpack.decode(encoded, type=topics.AudioInFrame)
    assert decoded.samples == raw
    assert decoded.sample_rate == 16000


def test_audio_in_frame_json_uses_base64_for_bytes():
    """JSON encoding of bytes goes through base64 in msgspec (same
    as Pydantic), so JSON round-trip ALSO works — text-topic-only
    is a guideline for performance, not a hard constraint."""
    raw = b"\x00\x01\x02\xff\xfe\xfd"
    msg = topics.AudioInFrame(samples=raw, sample_rate=16000)
    encoded = msgspec.json.encode(msg)
    decoded = msgspec.json.decode(encoded, type=topics.AudioInFrame)
    assert decoded.samples == raw


def test_text_topic_json_round_trips():
    """Text topics MUST survive JSON round-trip — they ride JSON on
    the wire by design."""
    original = topics.Transcript(
        text="hello world",
        confidence=0.92,
        language="en",
        is_final=True,
        duration_s=1.3,
        node_id="stt",
        correlation_id="utt-42",
    )
    encoded = msgspec.json.encode(original)
    parsed = msgspec.json.decode(encoded, type=topics.Transcript)
    assert parsed.text == "hello world"
    assert parsed.confidence == 0.92
    assert parsed.is_final is True
    assert parsed.duration_s == 1.3
    assert parsed.node_id == "stt"
    assert parsed.correlation_id == "utt-42"


def test_transcript_sensible_defaults():
    msg = topics.Transcript(text="hello")
    assert msg.confidence == 0.0
    assert msg.language == "en"
    assert msg.is_final is True
    assert msg.duration_s == 0.0


def test_camera_frame_carries_image_bytes():
    """CameraFrame holds the encoded image as ``frame_bytes`` with
    a dimensions + encoding header.  Default encoding is JPEG —
    the universal-debug choice; raw_bgr8 / raw_rgb8 / png available
    when a producer wants minimal CPU overhead."""
    payload = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # fake JPEG header
    msg = topics.CameraFrame(
        image_w=640, image_h=480, encoding="jpeg",
        frame_bytes=payload, camera_id="usb-0",
    )
    assert msg.image_w == 640
    assert msg.image_h == 480
    assert msg.encoding == "jpeg"
    assert msg.frame_bytes == payload
    assert msg.camera_id == "usb-0"
    assert msg.frame_seq == 0


def test_camera_frame_sensible_defaults():
    msg = topics.CameraFrame()
    assert msg.image_w == 0
    assert msg.image_h == 0
    assert msg.encoding == "jpeg"
    assert msg.frame_bytes == b""
    assert msg.camera_id == "default"
    assert msg.frame_seq == 0


def test_motion_command_velocity_mode_default():
    """Velocity mode (use_waypoint=False) is the default."""
    msg = topics.MotionCommand(linear_x_mps=0.5, duration_s=1.0)
    assert msg.use_waypoint is False
    assert msg.target_xy == []


def test_motion_command_waypoint_mode_distinguishable():
    """When the caller flips use_waypoint, target_xy carries the goal."""
    msg = topics.MotionCommand(
        use_waypoint=True, target_xy=[1.0, 2.0],
    )
    assert msg.use_waypoint is True
    assert msg.target_xy == [1.0, 2.0]


def test_light_command_off_is_three_zeros():
    msg = topics.LightCommand()
    assert msg.rgb == [0, 0, 0]
    assert msg.pattern == "solid"
    assert msg.duration_ms == 0


def test_spoken_ack_carries_failure_reason():
    """Failure replies must propagate a human-readable reason."""
    msg = topics.SpokenAck(ok=False, reason="audio device locked")
    assert msg.ok is False
    assert msg.reason == "audio device locked"


# ── msgspec-specific performance hints (smoke, not assertion) ─────

def test_messagepack_smaller_than_json_for_audio():
    """Sanity: MessagePack should produce a smaller wire form than
    JSON for binary topics — that's why we use it for audio frames.
    Not a hard contract, just a guard against accidental regression
    if msgspec's encoder ever changes shape."""
    raw = b"\x00" * 320  # 20 ms of 16 kHz mono float32
    msg = topics.AudioInFrame(samples=raw)
    json_bytes = msgspec.json.encode(msg)
    msgpack_bytes = msgspec.msgpack.encode(msg)
    assert len(msgpack_bytes) < len(json_bytes), (
        f"msgpack={len(msgpack_bytes)}B, json={len(json_bytes)}B — "
        "expected msgpack to be smaller for binary payload"
    )
