"""``InputStream`` — AVAudioEngine input-tap wrapper.

Drop-in for ``sounddevice.InputStream`` so the call sites in
``nodes/whisper_stt/engine/_base.py`` can swap to Apple-native audio I/O
with a one-line constructor change.

Shape matches sounddevice::

    stream = InputStream(
        samplerate=16000,
        channels=1,
        dtype="float32",
        blocksize=320,
        callback=fn,         # (indata, frames, time_info, status) -> None
        device=None,         # ignored — AVAudioEngine uses system input
        voice_processing=False,  # NEW — built-in AEC + NS + AGC
    )
    stream.start()
    ...
    stream.stop()
    stream.close()

Implementation notes
--------------------

* Tap delivers samples in the hardware's native format (typically
  48 kHz stereo Float32 on macOS).  If the caller asked for a
  different rate / channel count, we resample with
  ``scipy.signal.resample_poly`` (good quality, fast) and downmix
  to mono in pure Python — both ops run on the audio render thread.
  For typical voice-loop block sizes (20 ms = 960 frames @ 48 kHz)
  the resample takes < 200 µs on Apple Silicon.
* ``voice_processing=True`` enables the input node's voice-processing
  mode — Apple's pre-canned AEC + NS + AGC pipeline, replaces speexdsp
  for callers that don't need their own AEC reference buffer.
* We deliberately AVOID AVAudioConverter — PyObjC's block-with-pointer-
  argument bridging segfaults on the converter's input block.  The
  pure-Python resample path is simpler and stable.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable, Optional

import numpy as np


def _import_av() -> Any:
    try:
        import AVFoundation  # type: ignore
        return AVFoundation
    except ImportError as exc:
        raise RuntimeError(
            "AVAudioEngine I/O requires pyobjc-framework-AVFoundation. "
            "Install with: pip install pyobjc-framework-AVFoundation"
        ) from exc


CallbackFn = Callable[[np.ndarray, int, Any, Any], None]


class InputStream:
    """AVAudioEngine input-tap wrapper, sounddevice-shaped API."""

    def __init__(
        self,
        *,
        samplerate: int,
        channels: int = 1,
        dtype: str = "float32",
        blocksize: int = 1024,
        callback: Optional[CallbackFn] = None,
        device: Any = None,
        voice_processing: bool = False,
    ) -> None:
        if dtype != "float32":
            raise ValueError("AVAudioEngine InputStream only supports dtype='float32'")
        if device is not None:
            print(f"[avaudio] InputStream: ignoring device={device!r} "
                  "(AVAudioEngine uses system default input)", file=sys.stderr)

        self._samplerate = samplerate
        self._channels = channels
        self._blocksize = blocksize
        self._callback = callback
        self._voice_processing = voice_processing
        self._av = _import_av()

        self._engine: Any = None
        self._hw_samplerate: float = 0.0
        self._hw_channels: int = 0
        self._running = False
        # Carry-over buffer: when resampling produces a non-integer
        # number of frames per hardware block, we buffer the leftover
        # and flush it on the next callback so caller always receives
        # a clean ``blocksize`` of frames.
        self._carry = np.zeros((0, channels), dtype=np.float32)
        self._carry_lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return

        av = self._av
        engine = av.AVAudioEngine.alloc().init()
        input_node = engine.inputNode()

        if self._voice_processing:
            try:
                # PyObjC returns the BOOL directly; some versions
                # wrap it as a tuple.  Be defensive.
                result = input_node.setVoiceProcessingEnabled_error_(True, None)
                if isinstance(result, tuple):
                    success, err = result
                    if not success:
                        print(f"[avaudio] voice processing failed: {err}",
                              file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"[avaudio] voice processing not available: {exc}",
                      file=sys.stderr)

        hw_format = input_node.inputFormatForBus_(0)
        if hw_format.sampleRate() == 0:
            raise RuntimeError("AVAudioEngine reports no input device available")

        self._engine = engine
        self._hw_samplerate = float(hw_format.sampleRate())
        self._hw_channels = int(hw_format.channelCount())

        def _tap_block(buffer: Any, when: Any) -> None:
            try:
                self._handle_buffer(buffer)
            except Exception as exc:  # noqa: BLE001
                # Never let a Python exception kill the render thread.
                print(f"[avaudio] InputStream tap exception: {exc}",
                      file=sys.stderr)

        # bufferSize is just a hint — AVAudioEngine often delivers
        # different sizes (typically larger).  We adapt in the callback.
        input_node.installTapOnBus_bufferSize_format_block_(
            0,
            self._blocksize,
            hw_format,
            _tap_block,
        )

        # CoreAudio can be in a transient stuck state from a prior
        # engine teardown or from another process holding the audio
        # device.  Retry up to 3 times with a reset between attempts
        # — covers the common cases without papering over real
        # failures (a hard wedge errors after 3 tries the same as
        # before, just with a clearer message).
        last_err = None
        for attempt in range(3):
            success, err = engine.startAndReturnError_(None)
            if success:
                self._running = True
                return
            last_err = err
            err_desc = err.localizedDescription() if err else "unknown"
            print(f"[avaudio] input start attempt {attempt + 1}/3 failed: "
                  f"{err_desc}; resetting + retrying",
                  file=sys.stderr, flush=True)
            try:
                engine.stop()
                engine.reset()
                input_node.removeTapOnBus_(0)
                input_node.installTapOnBus_bufferSize_format_block_(
                    0, self._blocksize, hw_format, _tap_block,
                )
            except Exception:  # noqa: BLE001
                pass
            import time as _time
            _time.sleep(0.5)

        # All retries exhausted.
        try:
            input_node.removeTapOnBus_(0)
        except Exception:  # noqa: BLE001
            pass
        err_desc = last_err.localizedDescription() if last_err else "unknown"
        raise RuntimeError(
            f"AVAudioEngine input start failed after 3 attempts: {err_desc}. "
            "This is usually CoreAudio in a stuck state — try "
            "`sudo killall coreaudiod` and retry, or fall back with "
            "`--audio-backend portaudio` if the wedge persists."
        )

    def stop(self) -> None:
        if not self._running:
            return
        try:
            if self._engine is not None:
                self._engine.inputNode().removeTapOnBus_(0)
                self._engine.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"[avaudio] InputStream stop error: {exc}", file=sys.stderr)
        finally:
            self._running = False

    def close(self) -> None:
        self.stop()
        self._engine = None

    # ── compatibility shims ───────────────────────────────────────

    @property
    def samplerate(self) -> int:
        return self._samplerate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def blocksize(self) -> int:
        return self._blocksize

    @property
    def active(self) -> bool:
        return self._running

    # ── internals ─────────────────────────────────────────────────

    def _handle_buffer(self, buffer: Any) -> None:
        """Pull samples out of the AVAudioPCMBuffer, downmix +
        resample if needed, hand the caller fixed-size ``blocksize``
        blocks."""
        n_frames = int(buffer.frameLength())
        if n_frames == 0:
            return

        # Pull native samples — (n_frames, hw_channels) Float32.
        native = self._pcm_buffer_to_numpy(buffer, n_frames)
        if native is None:
            return

        # Downmix if hardware delivers more channels than caller wants.
        if native.shape[1] != self._channels:
            if self._channels == 1 and native.shape[1] > 1:
                downmixed = native.mean(axis=1, keepdims=True).astype(np.float32)
            elif self._channels < native.shape[1]:
                downmixed = native[:, : self._channels]
            else:
                # Caller wants more channels than hardware delivers —
                # duplicate channel 0 across the rest.
                downmixed = np.tile(native[:, :1], (1, self._channels))
        else:
            downmixed = native

        # Resample if needed.  Hardware ÷ caller ratio — use scipy
        # polyphase resampling for clean results.  We only resample
        # when rates actually differ.
        if abs(self._hw_samplerate - self._samplerate) > 1e-3:
            try:
                from scipy.signal import resample_poly
                # Find a clean integer ratio.  48000 → 16000 is 1:3
                # exactly; 44100 → 16000 needs higher-order ratios.
                gcd = np.gcd(int(self._hw_samplerate), int(self._samplerate))
                up = self._samplerate // gcd
                down = int(self._hw_samplerate) // gcd
                # ``axis=0`` resamples along time.
                resampled = resample_poly(downmixed, up, down, axis=0)
                resampled = resampled.astype(np.float32)
            except Exception as exc:  # noqa: BLE001
                print(f"[avaudio] resample failed: {exc}", file=sys.stderr)
                return
        else:
            resampled = downmixed

        # Coalesce with carry-over, then deliver in blocksize chunks.
        with self._carry_lock:
            combined = np.concatenate([self._carry, resampled], axis=0)
            total = combined.shape[0]
            bs = self._blocksize
            offset = 0
            while total - offset >= bs:
                block = combined[offset:offset + bs]
                if self._callback is not None:
                    try:
                        self._callback(block.copy(), bs, None, None)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[avaudio] callback exception: {exc}",
                              file=sys.stderr)
                offset += bs
            self._carry = combined[offset:].copy()

    def _pcm_buffer_to_numpy(self, buffer: Any, n_frames: int) -> Optional[np.ndarray]:
        """Copy the PCMBuffer's float channel data into a NumPy
        ``(n_frames, hw_channels)`` array.  Returns None on failure.

        AVAudioPCMBuffer.floatChannelData() returns a tuple of
        ``objc.varlist`` objects (one per channel — each is a
        variable-length C array wrapper).  PyObjC supports slicing
        a varlist with ``v[0:n]`` which yields a tuple of floats —
        we feed that straight into ``np.array``.  Trying to grab the
        underlying C pointer via ``int(v)`` doesn't work (varlist
        isn't ``int()``-able)."""
        floats = buffer.floatChannelData()
        if floats is None:
            return None
        try:
            arr = np.empty((n_frames, self._hw_channels), dtype=np.float32)
            for ch in range(self._hw_channels):
                channel_data = floats[ch]
                arr[:, ch] = np.array(
                    channel_data[0:n_frames],
                    dtype=np.float32,
                )
            return arr
        except Exception as exc:  # noqa: BLE001
            print(f"[avaudio] PCM buffer read failed: {exc}", file=sys.stderr)
            return None
