"""``OutputStream`` — AVAudioEngine player-node wrapper.

Drop-in for ``sounddevice.OutputStream``: caller's ``callback(outdata,
frames, time_info, status)`` is invoked on a worker thread, the
resulting samples are wrapped into ``AVAudioPCMBuffer`` and
scheduled on an ``AVAudioPlayerNode``.

Why a worker thread instead of the player's built-in completion
handler:

PyObjC's bridging of ``scheduleBuffer:atTime:options:completionHandler:``
trips signature-inference issues — passing a Python callable as the
``completionHandler`` block crashes the audio thread on macOS 26.
The simpler ``scheduleBuffer:completionHandler:`` variant with
``None`` for the handler works fine, so we use that and drive the
pacing ourselves: a worker thread pre-schedules ``queue_depth_blocks``
of audio to prime the player, then schedules one block per loop
iteration with a sleep of half the block duration in between.
There is no explicit queue-full check — the constant playback rate
plus the half-block sleep keep the player roughly N blocks ahead
of the playback cursor without polling AVAudioEngine's internal
queue depth.
"""

from __future__ import annotations

import sys
import threading
import time
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
        """Background driver: keep the player's queue fed.

        Loop pacing: each iteration schedules one block (~20 ms of
        audio at typical rates).  ``time.sleep`` for half the block
        duration so we stay roughly ``queue_depth_blocks`` ahead of
        the playback cursor.  Actual queue depth is implicit — we
        don't poll it; the playback rate is constant and the
        callback rate is bounded by our sleep."""
        # Pre-warm the queue by scheduling N blocks back to back.
        for _ in range(self._queue_depth_blocks):
            if self._stop_event.is_set() or not self._fill_one_block():
                self._signal_finish()
                return

        # Then pace.
        sleep_dt = self._block_duration * 0.5
        while not self._stop_event.is_set():
            if not self._fill_one_block():
                self._signal_finish()
                return
            time.sleep(sleep_dt)

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

        # 2-arg scheduleBuffer:completionHandler: with None.  The
        # 4-arg variant with a block trips PyObjC signature inference
        # and crashes the audio thread on macOS 26.
        try:
            self._player.scheduleBuffer_completionHandler_(pcm_buf, None)
        except Exception as exc:  # noqa: BLE001
            print(f"[avaudio] scheduleBuffer failed: {exc}", file=sys.stderr)
            return False

        return True

    def _signal_finish(self) -> None:
        """End-of-stream tidy-up — wait briefly for the player's
        already-queued buffers to drain, then tear down.  Runs on
        the worker thread; we call ``_teardown`` directly to avoid
        the self-join in ``stop()``."""
        drain_wait = self._block_duration * self._queue_depth_blocks
        time.sleep(min(drain_wait, 2.0))
        self._teardown()
