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
"""

from __future__ import annotations

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

__all__ = [
    "LENGTH_PREFIX_FORMAT",
    "LENGTH_PREFIX_SIZE",
    "AUDIO_IN_SAMPLE_RATE_HZ",
    "AUDIO_OUT_SAMPLE_RATE_HZ",
]
