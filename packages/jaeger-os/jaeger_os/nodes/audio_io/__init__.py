"""jaeger_os.nodes.audio_io — the microphone and speaker driver.

The one place in the ecosystem that opens an audio device. Everything
else talks to it over topics:

    /sense/mic/pcm      what the room sounds like (echo-cancelled)
    /act/speaker/pcm    what to play

Sibling of :mod:`jaeger_os.nodes.motor`, :mod:`~jaeger_os.nodes.light`
and :mod:`~jaeger_os.nodes.vision` — the framework's other device
nodes. It lives here rather than in a module repo because the audio
stack it wraps (``core/audio/aec.py``, ``core/audio/avaudio_io/``,
``core/audio/reference_buffer.py``) is already framework-owned; a
module would only have re-exported it.

Owning BOTH directions is not an accident of convenience. Echo
cancellation needs the mic frame and the playback frame together, per
frame; splitting them into two drivers would push that reference
across a boundary 100 times a second.
"""

from .node import (
    DEFAULT_FRAME_SAMPLES,
    DEFAULT_PLAYBACK_BLOCK,
    DEFAULT_PLAYBACK_RATE,
    DEFAULT_SAMPLE_RATE,
    AudioIONode,
)


def make_audio_io_node(bus, config=None):
    """Build the audio driver from a config mapping.

    AEC is constructed here rather than by the caller so the node has
    one owner for the whole audio path. It degrades to a passthrough
    when ``speexdsp`` is absent, which is the common case off macOS —
    a missing canceller must cost you barge-in, never your microphone.
    """
    cfg = dict(config or {})
    sample_rate = int(cfg.get("sample_rate", DEFAULT_SAMPLE_RATE))
    frame_samples = int(cfg.get("frame_samples", DEFAULT_FRAME_SAMPLES))

    aec = None
    if cfg.get("aec", True):
        from jaeger_os.core.audio.aec import AECWrapper
        wrapper = AECWrapper(
            sample_rate=sample_rate,
            frame_ms=int(round(frame_samples * 1000 / sample_rate)),
        )
        # A disabled wrapper is a passthrough. Passing None instead
        # keeps the mic callback's fast path free of a pointless call,
        # and lets voice_processing default back to Apple's pipeline.
        aec = wrapper if wrapper.enabled else None

    return AudioIONode(
        bus=bus,
        name=cfg.get("name", "audio_io"),
        sample_rate=sample_rate,
        frame_samples=frame_samples,
        playback_rate=int(cfg.get("playback_rate", DEFAULT_PLAYBACK_RATE)),
        playback_block=int(cfg.get("playback_block", DEFAULT_PLAYBACK_BLOCK)),
        audio_backend=cfg.get("audio_backend", "avaudio"),
        input_device=cfg.get("input_device"),
        aec=aec,
        voice_processing=cfg.get("voice_processing"),
        capture=bool(cfg.get("capture", True)),
        playback=bool(cfg.get("playback", True)),
        keep_output_open=bool(cfg.get("keep_output_open", True)),
    )


__all__ = ["AudioIONode", "make_audio_io_node", "DEFAULT_SAMPLE_RATE",
           "DEFAULT_FRAME_SAMPLES", "DEFAULT_PLAYBACK_RATE",
           "DEFAULT_PLAYBACK_BLOCK"]
