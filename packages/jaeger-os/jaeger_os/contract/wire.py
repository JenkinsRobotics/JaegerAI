"""wire.py — named packet-format + audio constants (the 0.9 contract package).

Two things live here:

* **Length-prefix framing** — the ``[4-byte big-endian length][payload]``
  shape used by both the animation bridge's WebSocket frames
  (``jaeger_os/nodes/animation/bridge.py``, mirrored in
  ``animation_dev``) and the vision node's raw TCP camera frames
  (``jaeger_os/nodes/vision/adapters.py``). Same wire idea, two
  call sites — named here so a future third implementation doesn't
  reinvent (or subtly mis-invent, e.g. swapping byte order) the format.
* **Audio PCM sample rates** — the canonical rates carried by
  :class:`jaeger_os.contract.topics.AudioInFrame` /
  :class:`~jaeger_os.contract.topics.AudioOutFrame` (mic input, TTS
  output). Engine-internal literals that happen to match these values
  (kokoro's 24 kHz output buffer, whisper's 16 kHz input requirement,
  the AEC reference buffer, etc.) are NOT repointed to import from here —
  those are properties of the engines themselves, not wire-format
  duplication; only the topic schema defaults and the two length-prefixed
  framing call sites were centralized in this pass.
* **JP01 video fragmentation header + MTU** — the UDP H.264 wire-format v2
  fragment header shared byte-for-byte by VCC01's ``core/vision_tx.py``
  (sender) and CC01's ``core/videorx.py`` (receiver), added 4.0 P1.
* **JP01 raw audio packet header + PCM format** — the UDP mic/speaker
  packet header and PCM shape shared byte-for-byte by VCC01's
  ``core/audio_manager.py`` and CC01's ``core/audio.py``, added 4.0 P1.
  Distinct from the ``AUDIO_IN/OUT_SAMPLE_RATE_HZ`` pair above — those are
  the voice-pipeline (whisper/kokoro) rates, this is JP01's own raw
  mic/speaker wire, which runs at 48 kHz regardless of what the voice
  pipeline does with it after resampling.
* **JP01 ZMQ command envelope** — the ``{target, cmd, params}`` JSON shape
  every command on ``JP01_VCC01_CMD_PORT`` / ``JP01_VCC01_VISION_REP_PORT``
  (``contract.ports``) carries, added 4.0 P1. Documented as a stdlib
  :func:`dataclasses.dataclass` for readers/validators; real senders build
  the raw dict directly (CC01's ``nodes/jetson_link.py::command_payload``
  has a byte-identity/key-order guarantee to preserve, so it is not
  repointed to construct-then-encode this class).

This module is STDLIB-ONLY by contract: VCC01 (Jetson, JetPack-lean)
vendors it verbatim (``JP01_Firmware/controllers/JP01-VCC01/core/
contract/``), so a third-party import here becomes a forced dependency in
that repo's requirements. Other contract modules (``topics.py``,
``capability.py``, ``modules.py``) may use msgspec — they are not vendored.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# ── length-prefix framing ────────────────────────────────────────────────
# struct.Struct format for a 4-byte unsigned length prefix, network
# (big-endian) byte order. Used verbatim by struct.pack/struct.unpack at
# both call sites above.
LENGTH_PREFIX_FORMAT = "!I"
LENGTH_PREFIX_SIZE = 4

# ── audio PCM ─────────────────────────────────────────────────────────────
# Mirrors AudioInFrame.sample_rate / AudioOutFrame.sample_rate defaults in
# contract/topics.py — the topic schema IS the wire truth; these are named
# aliases for code that wants the number without importing a topic class.
AUDIO_IN_SAMPLE_RATE_HZ = 16000
AUDIO_OUT_SAMPLE_RATE_HZ = 24000

# ── JP01 video fragmentation (UDP H.264, wire-format v2) ─────────────────
# struct.Struct format for the fragment header: frame_id (u32),
# total_chunks (u16), chunk_idx (u16), seq (u32, global per-packet
# sequence, monotonically increasing across the whole connection), network
# (big-endian) byte order. Real measured value — confirmed byte-identical
# against VCC01 core/vision_tx.py::HEADER and CC01 core/videorx.py::HEADER
# (JP01_Firmware branch 4.0).
JP01_VIDEO_FRAG_HEADER = "!IHHI"
JP01_VIDEO_FRAG_HEADER_SIZE = struct.calcsize(JP01_VIDEO_FRAG_HEADER)

# Max UDP datagram size (header + H.264 payload bytes) the sender
# fragments a frame into. Confirmed against VCC01 core/vision_manager.py
# (``self.mtu``).
JP01_VIDEO_UDP_MTU_BYTES = 1200

# ── JP01 raw audio (mic/speaker UDP PCM, not ZMQ) ─────────────────────────
# struct.Struct format for the audio packet header: channel_id (u8),
# sample_rate_hz (u32), timestamp_us (u64), little-endian. Confirmed
# byte-identical against VCC01 core/audio_manager.py::HEADER_FMT and CC01
# core/audio.py::HEADER.
JP01_AUDIO_PACKET_HEADER = "<BIQ"
JP01_AUDIO_PACKET_HEADER_SIZE = struct.calcsize(JP01_AUDIO_PACKET_HEADER)

# PCM payload carried by JP01_AUDIO_PACKET_HEADER packets: mono int16 LE
# at 48 kHz, 1024 samples per packet (2061 B/datagram incl. header, ~21.33
# ms, ~47 pkt/s). Confirmed against VCC01 core/audio_manager.py
# (AudioStreamNode defaults) and CC01 core/audio.py (MIC_SR/CHUNK).
JP01_AUDIO_SAMPLE_RATE_HZ = 48_000
JP01_AUDIO_CHANNELS = 1
JP01_AUDIO_SAMPLE_WIDTH_BYTES = 2   # int16
JP01_AUDIO_CHUNK_SAMPLES = 1024


# ── JP01 ZMQ command envelope ─────────────────────────────────────────────
@dataclass
class JP01CommandEnvelope:
    """The ``{target, cmd, params}`` JSON shape carried by every command on
    ``contract.ports.JP01_VCC01_CMD_PORT`` /
    ``contract.ports.JP01_VCC01_VISION_REP_PORT``.

    ``target`` routes the command on the Jetson side (``motion`` / ``av`` /
    ``vision`` / ``system`` / ``audio``); ``cmd`` is the raw command string
    (a bracket command like ``MJ[90,90,10]`` or a bare verb like ``PING``);
    ``params`` carries payloads that don't fit the bracket string (e.g.
    ``SET_DESTINATION``'s ``{host, port}``, ``SET_VOLUME``'s ``{level}``).

    Documentation type, not a required encoder — see module docstring.
    Stdlib dataclass, NOT msgspec: this module gets vendored (see above).
    """
    target: str
    cmd: str
    params: dict = field(default_factory=dict)


__all__ = [
    "LENGTH_PREFIX_FORMAT",
    "LENGTH_PREFIX_SIZE",
    "AUDIO_IN_SAMPLE_RATE_HZ",
    "AUDIO_OUT_SAMPLE_RATE_HZ",
    "JP01_VIDEO_FRAG_HEADER",
    "JP01_VIDEO_FRAG_HEADER_SIZE",
    "JP01_VIDEO_UDP_MTU_BYTES",
    "JP01_AUDIO_PACKET_HEADER",
    "JP01_AUDIO_PACKET_HEADER_SIZE",
    "JP01_AUDIO_SAMPLE_RATE_HZ",
    "JP01_AUDIO_CHANNELS",
    "JP01_AUDIO_SAMPLE_WIDTH_BYTES",
    "JP01_AUDIO_CHUNK_SAMPLES",
    "JP01CommandEnvelope",
]
