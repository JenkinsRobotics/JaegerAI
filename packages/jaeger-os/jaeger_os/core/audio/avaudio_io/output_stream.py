"""``OutputStream`` — AVAudioEngine player-node wrapper.

Drop-in for ``sounddevice.OutputStream``: caller's ``callback(outdata,
frames, time_info, status)`` is invoked on a worker thread, the
resulting samples are wrapped into ``AVAudioPCMBuffer`` and
scheduled on an ``AVAudioPlayerNode``.

Why a worker thread plus the player's completion handler:

PyObjC's bridging of ``scheduleBuffer:atTime:options:completionHandler:``
trips signature-inference issues — passing a Python callable as the
``completionHandler`` block crashes the audio thread on macOS 26. The
shorter ``scheduleBuffer:completionCallbackType:completionHandler:`` selector
is correctly annotated by PyObjC, however, and lets AVAudioEngine report when
each buffer has been rendered. A worker pre-schedules
``queue_depth_blocks`` and then schedules exactly one replacement for each
``DataRendered`` completion. The hardware clock therefore owns pacing: no
Python sleep jitter, no underruns under GUI load, and no unbounded silence
queue. ``DataPlayedBack`` must not be used as the refill signal because it
includes downstream processing and device latency; feeding that latency back
into every small block makes playback slower than real time.
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


class CallbackStop(Exception):
    """Mirror of ``sounddevice.CallbackStop`` so callers raising the
    same idiom signal end-of-stream cleanly."""


CallbackFn = Callable[[np.ndarray, int, Any, Any], None]
FinishedFn = Callable[[], None]


class OutputStream:
    """AVAudioEngine playback wrapper, sounddevice-shaped API."""

    def __init__(
        self,
        *,
        samplerate: int,
        channels: int = 1,
        dtype: str = "float32",
        blocksize: int = 480,
        callback: Optional[CallbackFn] = None,
        finished_callback: Optional[FinishedFn] = None,
        device: Any = None,
        queue_depth_blocks: int = 5,
    ) -> None:
        if dtype != "float32":
            raise ValueError("AVAudioEngine OutputStream only supports dtype='float32'")
        if device is not None:
            print(f"[avaudio] OutputStream: ignoring device={device!r} "
                  "(AVAudioEngine uses system default output)", file=sys.stderr)

        self._samplerate = samplerate
        self._channels = channels
        self._blocksize = blocksize
        self._callback = callback
        self._finished_callback = finished_callback
        self._queue_depth_blocks = max(2, int(queue_depth_blocks))
        self._av = _import_av()

        self._engine: Any = None
        self._player: Any = None
        self._format: Any = None
        self._running = False
        self._stop_event = threading.Event()
        self._rendered = threading.Semaphore(0)
        self._queued_lock = threading.Lock()
        self._queued_blocks = 0
        self._all_rendered = threading.Event()
        self._all_rendered.set()
        self._worker: Optional[threading.Thread] = None
        self._block_duration = float(blocksize) / float(samplerate)
        # Reused fill buffer — callback writes into this in place.
        self._fill_np = np.zeros((blocksize, channels), dtype=np.float32)

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        av = self._av

        engine = av.AVAudioEngine.alloc().init()
        player = av.AVAudioPlayerNode.alloc().init()

        fmt = av.AVAudioFormat.alloc(
        ).initWithCommonFormat_sampleRate_channels_interleaved_(
            av.AVAudioPCMFormatFloat32,
            float(self._samplerate),
            self._channels,
            False,  # deinterleaved
        )

        engine.attachNode_(player)
        engine.connect_to_format_(player, engine.mainMixerNode(), fmt)

        success, err = engine.startAndReturnError_(None)
        if not success:
            raise RuntimeError(
                f"AVAudioEngine output start failed: "
                f"{err.localizedDescription() if err else 'unknown'}"
            )

        self._engine = engine
        self._player = player
        self._format = fmt
        self._stop_event.clear()
        self._rendered = threading.Semaphore(0)
        with self._queued_lock:
            self._queued_blocks = 0
        self._all_rendered.set()
        self._running = True

        player.play()

        # Worker drives buffer refills + scheduling.
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="avaudio-output",
            daemon=True,
        )
        self._worker.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        # Only join the worker if we're being called FROM a different
        # thread.  When the worker calls stop() on itself at end-of-
        # stream, joining is a self-deadlock (RuntimeError).
        if (self._worker is not None
                and self._worker.is_alive()
                and threading.current_thread() is not self._worker):
            self._worker.join(timeout=1.0)
        self._teardown()

    def _teardown(self) -> None:
        """Idempotent teardown — safe to call from any thread,
        including the worker itself."""
        if not self._running:
            return
        try:
            if self._player is not None:
                self._player.stop()
            if self._engine is not None:
                self._engine.stop()
        except Exception as exc:  # noqa: BLE001
            print(f"[avaudio] OutputStream stop error: {exc}", file=sys.stderr)
        finally:
            self._running = False
            if self._finished_callback is not None:
                try:
                    self._finished_callback()
                except Exception:  # noqa: BLE001
                    pass

    def close(self) -> None:
        self.stop()
        self._engine = None
        self._player = None
        self._format = None

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

    def _worker_loop(self) -> None:
        """Keep a fixed number of buffers ahead of the playback cursor.

        AVAudioEngine's ``DataRendered`` callback is the pacing clock. Once
        the pre-roll is scheduled, every completion permits exactly one new
        buffer. This stays bounded without guessing at the device rate from a
        Python thread."""
        # Pre-warm the queue by scheduling N blocks back to back.
        for _ in range(self._queue_depth_blocks):
            if self._stop_event.is_set() or not self._fill_one_block():
                self._signal_finish()
                return

        # Thereafter the render thread releases one permit per buffer.
        while not self._stop_event.is_set():
            if not self._rendered.acquire(timeout=0.1):
                continue
            if self._stop_event.is_set():
                return
            if not self._fill_one_block():
                self._signal_finish()
                return

    def _fill_one_block(self) -> bool:
        """Call the user callback, build a PCMBuffer, schedule it.
        Returns False if the callback raised ``CallbackStop`` (or
        any other exception) — caller treats that as end-of-stream."""
        if self._callback is None or self._player is None:
            return False

        self._fill_np.fill(0.0)
        try:
            self._callback(self._fill_np, self._blocksize, None, None)
        except CallbackStop:
            return False
        except Exception as exc:  # noqa: BLE001
            print(f"[avaudio] OutputStream callback exception: {exc}",
                  file=sys.stderr)
            return False

        av = self._av
        pcm_buf = av.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(
            self._format, self._blocksize,
        )
        if pcm_buf is None:
            print("[avaudio] failed to allocate PCM buffer", file=sys.stderr)
            return False
        pcm_buf.setFrameLength_(self._blocksize)

        try:
            floats = pcm_buf.floatChannelData()
            for ch in range(self._channels):
                channel_data = floats[ch]
                channel_data[0:self._blocksize] = self._fill_np[:, ch].tolist()
        except Exception as exc:  # noqa: BLE001
            print(f"[avaudio] PCM buffer write failed: {exc}",
                  file=sys.stderr)
            return False

        # Increment before scheduling: a very short buffer may complete on the
        # render thread immediately after the selector returns.
        with self._queued_lock:
            self._queued_blocks += 1
            self._all_rendered.clear()
        try:
            self._player.scheduleBuffer_completionCallbackType_completionHandler_(
                pcm_buf,
                self._av.AVAudioPlayerNodeCompletionDataRendered,
                self._on_buffer_rendered,
            )
        except Exception as exc:  # noqa: BLE001
            with self._queued_lock:
                self._queued_blocks = max(0, self._queued_blocks - 1)
                if self._queued_blocks == 0:
                    self._all_rendered.set()
            print(f"[avaudio] scheduleBuffer failed: {exc}", file=sys.stderr)
            return False

        return True

    def _on_buffer_rendered(self, _callback_type: Any) -> None:
        """AVAudio render-thread callback. Counters and a semaphore only."""
        with self._queued_lock:
            self._queued_blocks = max(0, self._queued_blocks - 1)
            if self._queued_blocks == 0:
                self._all_rendered.set()
        self._rendered.release()

    def _signal_finish(self) -> None:
        """End-of-stream tidy-up — wait briefly for the player's
        already-queued buffers to drain, then tear down.  Runs on
        the worker thread; we call ``_teardown`` directly to avoid
        the self-join in ``stop()``."""
        with self._queued_lock:
            queued = self._queued_blocks
        self._all_rendered.wait(timeout=min(
            max(0.1, queued * self._block_duration + 0.5), 5.0))
        self._teardown()
