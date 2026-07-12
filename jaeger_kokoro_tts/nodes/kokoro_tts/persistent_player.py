"""Persistent output player for the Kokoro TTS plugin.

Direct port of the working pattern from
``dev/tools/audio_smoke/voice_assistant_persistent.py::PersistentPlayer``
(and ``voice_assistant_avaudio.py::SessionPlayer``), adapted to live
inside the plugin with backend selection.

Design notes
------------
* ONE output stream opens at plugin warm / first speak() and stays
  alive for the whole session.  Closed at process shutdown.
* Audio chunks come in via :meth:`enqueue`; the sounddevice backend
  feeds them through a callback queue, while the avaudio backend
  schedules them directly on an ``AVAudioPlayerNode``.  No
  per-utterance stream churn → no audible device power-cycle clicks
  between replies.
* Two backends, chosen at construction time:
    - ``backend="sounddevice"`` — PortAudio via the sounddevice
      wrapper.  Output device resolved live at start() via a direct
      CoreAudio query (PortAudio's cached "default" can lag behind
      the operator's Settings → Sound choice on macOS).
    - ``backend="avaudio"`` — PyObjC AVAudioEngine direct scheduling
      on ``AVAudioPlayerNode``.  Apple-native, no PortAudio in the
      loop, no worker-thread pacing.
* Caller picks the backend via the ``audio_backend`` field on the
  instance's ``voice`` config block (default: ``"sounddevice"`` since
  step 1 proved it works end-to-end in the 0.2.6 TUI).
"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
from ctypes import POINTER, byref, c_int, c_uint32, c_void_p, sizeof
from typing import Any, Optional

import numpy as np


# ── live macOS default output lookup ──────────────────────────────────
#
# PortAudio caches "default" at process start; the OS user can change
# their output device anytime via Settings → Sound.  We ask CoreAudio
# directly for the *current* default so the persistent stream lands on
# the same device AVAudioEngine would resolve to (i.e. what the
# operator actually hears today, not what was default an hour ago).
#
# ``JAEGER_AUDIO_OUTPUT`` env override:
#   - integer  → use that sounddevice index verbatim
#   - string   → fuzzy match against device names (case-insensitive
#                substring)

def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


class _AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", c_uint32),
        ("mScope", c_uint32),
        ("mElement", c_uint32),
    ]


def _query_macos_default_output_name() -> Optional[str]:
    """Return the live macOS default output device name, or None if
    we're not on macOS / the CoreAudio call fails."""
    if sys.platform != "darwin":
        return None
    try:
        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return None

    ca.AudioObjectGetPropertyData.argtypes = [
        c_uint32, POINTER(_AudioObjectPropertyAddress),
        c_uint32, c_void_p,
        POINTER(c_uint32), c_void_p,
    ]
    ca.AudioObjectGetPropertyData.restype = c_int
    cf.CFStringGetCString.argtypes = [c_void_p, c_void_p, c_int, c_uint32]
    cf.CFStringGetCString.restype = c_int
    cf.CFRelease.argtypes = [c_void_p]

    # Step 1: ask the system object for the default output device ID.
    addr_dev = _AudioObjectPropertyAddress(
        _fourcc("dOut"), _fourcc("glob"), 0,
    )
    dev_id = c_uint32(0)
    size = c_uint32(4)
    err = ca.AudioObjectGetPropertyData(
        1,  # kAudioObjectSystemObject
        byref(addr_dev), 0, None,
        byref(size), byref(dev_id),
    )
    if err != 0 or dev_id.value == 0:
        return None

    # Step 2: ask that device for its CFString name.
    addr_name = _AudioObjectPropertyAddress(
        _fourcc("lnam"), _fourcc("glob"), 0,
    )
    cfstr = c_void_p(0)
    size = c_uint32(sizeof(c_void_p))
    err = ca.AudioObjectGetPropertyData(
        dev_id.value,
        byref(addr_name), 0, None,
        byref(size), byref(cfstr),
    )
    if err != 0 or not cfstr.value:
        return None

    buf = ctypes.create_string_buffer(256)
    ok = cf.CFStringGetCString(cfstr, buf, 256, 0x08000100)  # UTF-8
    name = buf.value.decode("utf-8", errors="replace") if ok else None
    cf.CFRelease(cfstr)
    return name


def resolve_output_device(sd: Any) -> Optional[int]:
    """Pick the sounddevice output device index that matches the live
    macOS default.  Returns None to let PortAudio pick its own default
    when CoreAudio can't tell us anything (non-macOS, query failed)."""
    # Env override wins.
    override = os.environ.get("JAEGER_AUDIO_OUTPUT")
    if override:
        try:
            return int(override)
        except ValueError:
            sub = override.lower().strip()
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] > 0 and sub in d["name"].lower():
                    return i

    target = _query_macos_default_output_name()
    if not target:
        return None
    nlc = target.lower()
    # Exact match first, then substring fallback.
    exact = None
    fuzzy = None
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] <= 0:
            continue
        nm = d["name"].lower()
        if nm == nlc:
            exact = i
        elif nlc in nm or nm in nlc:
            if fuzzy is None:
                fuzzy = i
    return exact if exact is not None else fuzzy


# ── persistent player ────────────────────────────────────────────────
#
# Same shape as ``voice_assistant_persistent.py::PersistentPlayer``,
# with one addition: ``start()`` resolves the live macOS default device
# so PortAudio's stale "default" can't route TTS to a silent monitor.

class PersistentKokoroPlayer:
    """Long-lived output stream + feed queue with pluggable backend.

    Stream opens once and stays running for the whole process
    lifetime, closed at exit by :meth:`close`.  All TTS chunks go
    through :meth:`enqueue` (non-blocking); callers
    :meth:`mark_end` + :meth:`wait_until_drained` to wait until
    everything queued has actually played.

    Backends
    --------
    ``backend="sounddevice"``  (default)
        PortAudio via the sounddevice wrapper.  Output device
        resolved live via :func:`resolve_output_device`.
    ``backend="avaudio"``
        PyObjC AVAudioEngine via direct ``AVAudioPlayerNode`` buffer
        scheduling.  Apple-native, bypasses PortAudio and the
        avaudio_io worker wrapper entirely.

    A misspelled / unavailable backend raises at :meth:`start`; the
    caller (``KokoroTTS._ensure_player``) catches that and logs
    "persistent player warm failed — will retry on first speak()".
    """

    SUPPORTED_BACKENDS = ("sounddevice", "avaudio")

    def __init__(
        self,
        *,
        backend: str = "sounddevice",
        samplerate: int = 24000,
        channels: int = 1,
    ) -> None:
        if backend not in self.SUPPORTED_BACKENDS:
            raise ValueError(
                f"unknown audio backend {backend!r}; "
                f"expected one of {self.SUPPORTED_BACKENDS}"
            )
        self.backend = backend
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        # Queue items: np.ndarray (audio) or None (end-of-message marker).
        self._q: "queue.Queue[Any]" = queue.Queue()
        # Buffer the callback is currently writing out of.
        self._current: np.ndarray = np.zeros(0, dtype=np.float32)
        self._drained = threading.Event()
        self._drained.set()           # idle = drained
        self._stream: Any = None
        self._av: Any = None
        self._engine: Any = None
        self._player: Any = None
        self._format: Any = None
        self._running = False
        # AVAudio drain tracking via per-buffer completion handlers.
        self._scheduled_count = 0
        self._drained_count = 0
        self._drain_lock = threading.Lock()
        # Keep PyObjC block wrappers alive until AVAudio fires them.
        self._pending_callbacks: list[Any] = []
        # Resolved at start() so callers can log them.
        self.device_index: Optional[int] = None
        self.device_name: Optional[str] = None

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the persistent output stream.  Idempotent.

        The sounddevice path opens a callback-driven ``OutputStream``.
        The avaudio path opens one AVAudioEngine + player node and
        later schedules each enqueued buffer directly on that node."""
        if self.is_open():
            return
        blocksize = int(self.samplerate * 0.02)  # 20 ms

        if self.backend == "avaudio":
            self._start_avaudio()
            return
        else:  # sounddevice
            import sounddevice as sd  # deferred import
            device = resolve_output_device(sd)
            try:
                info = sd.query_devices(device if device is not None
                                        else sd.default.device[1])
                self.device_index = device
                self.device_name = info["name"]
            except Exception:  # noqa: BLE001 — informational only
                self.device_name = "(unknown)"
            self._stream = sd.OutputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                dtype="float32",
                blocksize=blocksize,
                callback=self._cb,
                device=device,
            )
            self._stream.start()

    def _start_avaudio(self) -> None:
        try:
            import AVFoundation  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "AVAudioEngine output requires pyobjc-framework-AVFoundation. "
                "Install with: pip install pyobjc-framework-AVFoundation"
            ) from exc

        av = AVFoundation
        engine = av.AVAudioEngine.alloc().init()
        player = av.AVAudioPlayerNode.alloc().init()
        fmt = av.AVAudioFormat.alloc(
        ).initWithCommonFormat_sampleRate_channels_interleaved_(
            av.AVAudioPCMFormatFloat32,
            float(self.samplerate),
            self.channels,
            False,
        )

        engine.attachNode_(player)
        engine.connect_to_format_(player, engine.mainMixerNode(), fmt)
        success, err = engine.startAndReturnError_(None)
        if not success:
            raise RuntimeError(
                f"AVAudioEngine output start failed: "
                f"{err.localizedDescription() if err else 'unknown'}"
            )

        player.play()
        self._av = av
        self._engine = engine
        self._player = player
        self._format = fmt
        self._running = True
        self.device_index = None
        self.device_name = "(macOS system default via AVAudioEngine)"

    def _close_avaudio(self) -> None:
        if not self._running and self._engine is None and self._player is None:
            return
        try:
            if self._player is not None:
                self._player.stop()
            if self._engine is not None:
                self._engine.stop()
        except Exception:  # noqa: BLE001
            pass
        finally:
            with self._drain_lock:
                self._pending_callbacks.clear()
                self._drained_count = self._scheduled_count
                self._drained.set()
            self._running = False
            self._engine = None
            self._player = None
            self._format = None
            self._av = None
            self.device_name = "(macOS system default via AVAudioEngine)"

    def close(self) -> None:
        """Stop + close the stream.  Idempotent.  Safe to call at any
        point on the main thread; the audio callback won't fire after
        ``stop()`` returns."""
        if self.backend == "avaudio":
            self._close_avaudio()
            return
        if self._stream is None:
            return
        try:
            self._stream.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass
        self._stream = None
        # Clear residual queue state.
        self._current = np.zeros(0, dtype=np.float32)
        with self._q.mutex:
            self._q.queue.clear()
        self._drained.set()

    def reset(self) -> None:
        """Flush queued audio and repair drain accounting.

        Used after a drain timeout.  The sounddevice stream stays open
        and resumes outputting silence from its callback.  The AVAudio
        player node is stopped to flush scheduled buffers, then re-armed
        with ``play()`` so the next enqueue can schedule cleanly without
        cycling the engine.
        """
        if self.backend == "avaudio":
            if self._player is not None:
                try:
                    self._player.stop()
                except Exception:  # noqa: BLE001
                    pass
            with self._drain_lock:
                self._pending_callbacks.clear()
                self._drained_count = self._scheduled_count
                self._drained.set()
            if self._player is not None:
                try:
                    self._player.play()
                except Exception:  # noqa: BLE001
                    pass
            return

        self._current = np.zeros(0, dtype=np.float32)
        with self._q.mutex:
            self._q.queue.clear()
        self._drained.set()

    def cancel(self) -> None:
        """Stop current playback without closing the persistent stream."""
        self.reset()

    def is_open(self) -> bool:
        if self.backend == "avaudio":
            return bool(self._running and self._engine is not None
                        and self._player is not None)
        return self._stream is not None

    # ── callback ──────────────────────────────────────────────────────

    def _cb(self, outdata, frames: int, _t, _s) -> None:
        """Audio thread: pull samples from the queue, write to
        ``outdata``.  Fills remainder with silence on underrun so the
        stream stays alive and ready for the next ``enqueue``."""
        i = 0
        while i < frames:
            if len(self._current) == 0:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    outdata[i:, 0] = 0.0
                    return
                if item is None:
                    # End-of-message marker — unblock waiter, silence rest.
                    self._drained.set()
                    outdata[i:, 0] = 0.0
                    return
                self._current = item
            take = min(frames - i, len(self._current))
            outdata[i:i + take, 0] = self._current[:take]
            self._current = self._current[take:]
            i += take

    # ── producer side ────────────────────────────────────────────────

    def enqueue(self, audio: np.ndarray) -> None:
        """Append a chunk to the play queue.  Non-blocking — caller
        keeps going (Kokoro keeps synthesizing chunk N+1 while chunk N
        is playing).  ``audio`` must be float32 mono at
        ``self.samplerate``; empty / None chunks are silently dropped."""
        if audio is None:
            return
        if not isinstance(audio, np.ndarray):
            audio = np.asarray(audio, dtype=np.float32)
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.size == 0:
            return
        if self.backend == "avaudio":
            self._enqueue_avaudio(audio)
            return
        self._drained.clear()
        self._q.put(audio)

    def _enqueue_avaudio(self, audio: np.ndarray) -> None:
        if not self.is_open():
            self.start()
        if self._av is None or self._player is None or self._format is None:
            raise RuntimeError("AVAudioEngine output is not open")

        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.reshape(-1, audio.shape[-1])
            n = int(audio.shape[0])
        else:
            audio = audio.reshape(-1)
            n = int(audio.size)
        if n == 0:
            return

        pcm = self._av.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(
            self._format, n,
        )
        if pcm is None:
            raise RuntimeError("failed to allocate AVAudioPCMBuffer")
        pcm.setFrameLength_(n)

        floats = pcm.floatChannelData()
        if audio.ndim == 1:
            samples = audio.tolist()
            floats[0][0:n] = samples
            for ch in range(1, self.channels):
                floats[ch][0:n] = samples
        else:
            for ch in range(self.channels):
                src_ch = min(ch, audio.shape[1] - 1)
                floats[ch][0:n] = audio[:, src_ch].tolist()

        with self._drain_lock:
            self._scheduled_count += 1
            self._drained.clear()

        def _on_done() -> None:
            _ = pcm  # capture the PCM buffer for the callback lifetime
            with self._drain_lock:
                self._drained_count += 1
                try:
                    self._pending_callbacks.remove(_on_done)
                except ValueError:
                    pass
                if self._drained_count >= self._scheduled_count:
                    self._drained.set()

        self._pending_callbacks.append(_on_done)
        try:
            # 2-arg scheduleBuffer:completionHandler:.  The 4-arg
            # atTime/options form crashes PyObjC signature inference
            # on macOS 26.
            self._player.scheduleBuffer_completionHandler_(pcm, _on_done)
        except Exception:
            with self._drain_lock:
                self._scheduled_count -= 1
                try:
                    self._pending_callbacks.remove(_on_done)
                except ValueError:
                    pass
                if self._drained_count >= self._scheduled_count:
                    self._drained.set()
            raise

    def mark_end(self) -> None:
        """Put an end-of-message sentinel on the queue.  The callback
        fires :attr:`_drained` when it pulls this marker — i.e. once
        every chunk enqueued *before* the marker has played."""
        if self.backend == "avaudio":
            return
        self._q.put(None)

    def wait_until_drained(self, timeout: float = 60.0) -> bool:
        """Block until the backend has consumed all queued audio.
        Returns ``False`` on timeout."""
        return self._drained.wait(timeout=timeout)
