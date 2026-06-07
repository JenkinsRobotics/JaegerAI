"""codec.py — wire-format encode/decode for 0.4 topic messages.

The Bus implementations (in-process + ZMQ) call into this module
instead of touching ``msgspec.json`` / ``msgspec.msgpack`` directly,
so the JSON-vs-MessagePack pick lives in ONE place.

Topic → wire format
-------------------
* **Binary topics** (audio frames, camera frames, anything carrying
  raw ``bytes`` payloads) → **MessagePack**.  msgspec encodes bytes
  natively (no base64 hop), and MessagePack is ~30-50 % smaller on
  the wire for binary content.
* **Text topics** (transcripts, motor commands, LED commands, TTS
  acks) → **JSON**.  Debuggable in ``tcpdump`` / Wireshark, lossless
  through curl, no special tooling required.

The split is named per-topic, not per-payload-type, so a future
change to a topic's binary-ness is a single edit here rather than
the caller having to know.

ROADMAP_0.4.md open question #2 (resolved): operator confirmed
JSON-for-text / MessagePack-for-binary as the working default.
"""

from __future__ import annotations

import msgspec

from jaeger_os import topics


# ── topic → wire-format lookup ─────────────────────────────────────
#
# Single source of truth: this set names every topic whose payload
# rides MessagePack.  Anything not in this set rides JSON.  Adding a
# new binary topic is a single line here; flipping a topic between
# formats is also a single line.

BINARY_TOPICS: frozenset[str] = frozenset({
    topics.SENSE_AUDIO_IN,
    topics.ACT_AUDIO_OUT,
    # /sense/camera_frame (CameraFrame) carries JPEG/PNG/raw bytes as the
    # main payload — MessagePack avoids the base64 hop JSON would
    # require, and the smaller wire form matters at 10-30 fps.
    topics.SENSE_CAMERA_FRAME,
})


def is_binary_topic(topic: str) -> bool:
    """True if ``topic`` rides MessagePack on the wire, False if JSON."""
    return topic in BINARY_TOPICS


# ── encode / decode ────────────────────────────────────────────────

def encode(msg: topics.TopicMessage) -> bytes:
    """Serialise ``msg`` to wire bytes, picking JSON or MessagePack
    from the topic name.  Raises ``msgspec.ValidationError`` if the
    payload violates the topic's Struct schema (caught at encode
    time, not on the receiver)."""
    if is_binary_topic(msg.topic):
        return msgspec.msgpack.encode(msg)
    return msgspec.json.encode(msg)


def decode(data: bytes, topic: str) -> topics.TopicMessage:
    """Deserialise ``data`` into the registered class for ``topic``.

    Caller passes the topic explicitly so the bytes can be decoded
    even if some envelope corruption made the in-payload ``topic``
    field unreadable.  Raises ``KeyError`` for an unregistered
    topic (schema drift) and ``msgspec.ValidationError`` for a
    payload that doesn't match the class schema (wire corruption
    or a publisher bug)."""
    cls = topics.class_for_topic(topic)
    if is_binary_topic(topic):
        return msgspec.msgpack.decode(data, type=cls)
    return msgspec.json.decode(data, type=cls)


def decode_with_topic_sniff(data: bytes) -> topics.TopicMessage:
    """Convenience for ZMQ-style frames where the topic is in the
    payload (not a separate frame header).  Slower than :func:`decode`
    because it has to JSON-peek to find the topic; intended only for
    debugging / topic-inspector tools, NOT the hot path."""
    # Peek the topic via a tiny JSON decode on just the envelope.
    # We can't do this for MessagePack-encoded frames without
    # decoding the whole thing, so this helper only handles JSON.
    try:
        envelope = msgspec.json.decode(data, type=dict)
    except msgspec.DecodeError as exc:
        raise ValueError(
            "decode_with_topic_sniff: payload isn't JSON; pass the "
            "topic explicitly via decode(data, topic) instead"
        ) from exc
    topic = envelope.get("topic")
    if not isinstance(topic, str):
        raise ValueError(f"decode_with_topic_sniff: no topic field in {envelope!r}")
    return decode(data, topic)
