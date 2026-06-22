"""Tests for ``jaeger_os.transport.codec`` — Track A.2.

Pins the JSON-vs-MessagePack pick + the encode/decode contract that
both Bus implementations depend on.
"""

from __future__ import annotations

import msgspec
import pytest

from jaeger_os.transport import topics
from jaeger_os.transport import codec


# ── topic classification ──────────────────────────────────────────

def test_payload_heavy_topics_are_binary():
    """Audio frames AND camera frames ride MessagePack — both carry
    raw payload bytes that benefit from MessagePack's native bytes
    encoding (no base64 hop)."""
    assert codec.is_binary_topic(topics.SENSE_AUDIO_IN) is True
    assert codec.is_binary_topic(topics.ACT_AUDIO_OUT) is True
    assert codec.is_binary_topic(topics.SENSE_CAMERA_FRAME) is True


def test_text_topics_are_not_binary():
    """Every non-payload-heavy topic rides JSON for debug-ability."""
    binary = {
        topics.SENSE_AUDIO_IN,
        topics.ACT_AUDIO_OUT,
        topics.SENSE_CAMERA_FRAME,
    }
    for name in topics.ALL_TOPICS:
        if name in binary:
            continue
        assert codec.is_binary_topic(name) is False, (
            f"{name} unexpectedly classified as binary"
        )


def test_unknown_topic_treated_as_text():
    """An unknown topic name returns False (not raises) — the codec
    is the wrong layer to enforce topic existence; class_for_topic
    in decode() does that.  This lets the inspector tooling probe
    unknown topics without crashing."""
    assert codec.is_binary_topic("/sense/unregistered") is False


# ── encode round-trips ────────────────────────────────────────────

def test_text_topic_round_trips_via_json():
    """Transcript (text topic) encodes to JSON, decodes back."""
    msg = topics.Transcript(
        text="hello world",
        confidence=0.92,
        language="en",
        node_id="stt",
        correlation_id="utt-1",
    )
    wire = codec.encode(msg)
    # JSON is human-debuggable — the wire form should be ASCII
    # and start with '{' so curl/wireshark show it readable.
    assert wire.startswith(b"{")
    parsed = codec.decode(wire, topics.SENSE_TRANSCRIPT)
    assert isinstance(parsed, topics.Transcript)
    assert parsed.text == "hello world"
    assert parsed.confidence == 0.92
    assert parsed.correlation_id == "utt-1"


def test_binary_topic_round_trips_via_msgpack():
    """AudioInFrame (binary topic) encodes to MessagePack with bytes
    natively preserved — no base64 hop."""
    raw = b"\x00\x01\x02\xff\xfe\xfd" * 32  # 192 bytes of "audio"
    msg = topics.AudioInFrame(samples=raw, sample_rate=16000)
    wire = codec.encode(msg)
    # MessagePack is binary — the wire form should NOT be ASCII
    # printable.  Tightest detector: it must NOT start with '{'.
    assert not wire.startswith(b"{")
    parsed = codec.decode(wire, topics.SENSE_AUDIO_IN)
    assert isinstance(parsed, topics.AudioInFrame)
    assert parsed.samples == raw
    assert parsed.sample_rate == 16000


def test_binary_topic_smaller_than_json():
    """Confirms the size win that motivated MessagePack-for-binary.
    Without this guarantee the whole format split has no reason."""
    raw = b"\x00" * 640  # 20 ms of 16 kHz mono float32
    msg = topics.AudioInFrame(samples=raw)
    msgpack_wire = codec.encode(msg)
    # Same payload via JSON should be at least 20 % larger
    json_wire = msgspec.json.encode(msg)
    assert len(msgpack_wire) < len(json_wire) * 0.95, (
        f"msgpack={len(msgpack_wire)}B is NOT meaningfully smaller "
        f"than json={len(json_wire)}B"
    )


# ── decode failure modes ──────────────────────────────────────────

def test_decode_unknown_topic_raises_keyerror():
    """An unknown topic in the registry is schema drift — hard error."""
    with pytest.raises(KeyError):
        codec.decode(b"{}", "/sense/nonexistent")


def test_decode_corrupt_payload_raises_validation_error():
    """A payload that doesn't match the topic's class fails decode."""
    bad = b'{"topic": "/sense/transcript", "text": 123}'  # text=int
    with pytest.raises(msgspec.ValidationError):
        codec.decode(bad, topics.SENSE_TRANSCRIPT)


def test_decode_wrong_topic_literal_raises():
    """The Literal pin catches a payload claiming a different topic
    than the requested class."""
    # Encode as SpeechCommand but pass SENSE_TRANSCRIPT to decode.
    msg = topics.SpeechCommand(text="hi")
    wire = codec.encode(msg)
    with pytest.raises(msgspec.ValidationError):
        codec.decode(wire, topics.SENSE_TRANSCRIPT)


# ── decode_with_topic_sniff (debug helper) ────────────────────────

def test_sniff_decode_works_on_text_topics():
    """The debug helper sniffs the topic from the JSON envelope."""
    msg = topics.SpeechCommand(text="hello", voice="af_heart")
    wire = codec.encode(msg)
    parsed = codec.decode_with_topic_sniff(wire)
    assert isinstance(parsed, topics.SpeechCommand)
    assert parsed.text == "hello"


def test_sniff_decode_rejects_msgpack_payload():
    """MessagePack payloads can't be peeked as JSON — caller has to
    pass the topic explicitly via :func:`decode`."""
    msg = topics.AudioInFrame(samples=b"\xff\xfe\xfd")
    wire = codec.encode(msg)  # msgpack
    with pytest.raises(ValueError):
        codec.decode_with_topic_sniff(wire)


def test_sniff_decode_rejects_no_topic_field():
    """A JSON payload missing the topic field is unusable."""
    bad = b'{"text": "no envelope"}'
    with pytest.raises(ValueError):
        codec.decode_with_topic_sniff(bad)
