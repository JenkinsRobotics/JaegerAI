"""Apple-native audio I/O for the Python voice loop.

PyObjC ``AVAudioEngine`` wrappers exposed with the **same call surface
as sounddevice's** ``InputStream`` / ``OutputStream``.  ``InputStream``
is used by the live mic path; ``OutputStream`` remains a generic
compatibility wrapper for smoke tests and future call sites.  Kokoro
TTS does not use the output wrapper in 0.3.0 — it schedules directly
on ``AVAudioPlayerNode`` inside ``PersistentKokoroPlayer``.

Why
---

The 0.2.x audio path is::

    Kokoro / pywhispercpp  →  sounddevice  →  PortAudio  →  CoreAudio

PortAudio's CoreAudio backend is the source of the wedging bugs the
operator has hit repeatedly — the BenQ-AUHAL stall, the
``kAudioHardwareUnspecifiedError`` ('what') that breaks YouTube
playback after a failed mic-engine start, etc.  Apple's own
``AVAudioEngine`` doesn't suffer from these: it's the canonical
high-level Mac audio API, used by FaceTime, Voice Memos, GarageBand.

Replacing **only the I/O layer** keeps everything else the same:

* Same Kokoro voice quality (the synthesizer is unchanged)
* Same pywhispercpp accuracy (the recognizer is unchanged)
* Same Python codebase (no Swift required for headless / CLI users)
* Built-in voice processing mode supplies AEC + NS + AGC — retires
  the optional ``speexdsp`` dependency for AEC barge-in

API
---

::

    from jaeger_os.core.audio.avaudio_io import InputStream, OutputStream

    # Same signature as ``sd.InputStream``:
    stream = InputStream(
        samplerate=16000,
        channels=1,
        dtype="float32",
        blocksize=320,           # 20ms @ 16kHz
        callback=my_cb,          # (indata, frames, time_info, status) -> None
        voice_processing=True,   # built-in AEC + NS + AGC (the only new kwarg)
    )
    stream.start()
    ...
    stream.stop()
    stream.close()

The ``voice_processing`` kwarg is the headline win — when ``True``
AVAudioEngine's voice-processing audio unit handles echo cancellation
internally, so callers don't need to wire a separate speexdsp AEC.

Status (2026-06-04)
-------------------

* ``InputStream`` (mic capture): shipped + default backend on macOS
  via ``whisper_stt/_base.py``.  Voice-processing AEC auto-on when
  no speexdsp is wired.
* ``OutputStream`` (speaker): shipped as the generic sounddevice-shaped
  wrapper, but not used by Kokoro TTS in 0.3.0.  TTS uses direct
  ``AVAudioPlayerNode.scheduleBuffer:completionHandler:`` scheduling
  inside ``PersistentKokoroPlayer`` to avoid worker-thread pacing.
* Smoke test (``smoke_test.py``): standalone, verifies capture +
  playback + loopback + AEC paths without touching the voice loop.
* Fallback: when the bridge can't load (non-macOS, missing
  ``pyobjc-framework-AVFoundation``, or ``--audio-backend portaudio``),
  the consumers transparently drop back to ``sounddevice``.
"""

from .input_stream import InputStream
from .output_stream import CallbackStop, OutputStream

__all__ = ["InputStream", "OutputStream", "CallbackStop"]
