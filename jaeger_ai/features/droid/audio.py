"""The droid's ears and voice: one AVAudioEngine with Apple voice processing.

Capture and playback share a single engine so macOS's voice-processing unit
(the echo canceller FaceTime uses) hears exactly what the droid says and
removes it from the microphone. That is what lets someone talk over the droid
in a room with open speakers.

Mic audio leaves as 48 kHz mono int16 blocks of 20 ms; speech to play arrives
as float32 mono at 48 kHz. Both run off Python's main loop: the tap and the
player's completion handler run on CoreAudio threads and only touch queues
and counters.
"""
from __future__ import annotations

import math
import threading
from typing import Callable

import numpy as np

RATE = 48000
BLOCK = 960  # 20 ms


class DuplexAudio:
    def __init__(self, on_mic: Callable[[np.ndarray], None], *, listen: bool = True):
        self.on_mic = on_mic
        self.listen = listen
        self.muted = False
        self.engine = self.player = self.fmt = None
        self._carry = np.zeros(0, dtype=np.float32)
        self._queued = 0
        self._lock = threading.Lock()
        self.level = 0.0
        self.voice_processing = False

    # lifecycle -----------------------------------------------------------
    def start(self, output_device: int = 0) -> None:
        import AVFoundation as A

        from . import coreaudio

        engine = A.AVAudioEngine.alloc().init()
        node = None
        if self.listen:
            node = engine.inputNode()
            try:
                result = node.setVoiceProcessingEnabled_error_(True, None)
                self.voice_processing = bool(result[0] if isinstance(result, tuple) else result)
            except Exception:
                self.voice_processing = False
            tap_fmt = node.outputFormatForBus_(0)
            rate = float(tap_fmt.sampleRate())
            if rate <= 0:
                raise RuntimeError("No microphone is available to the droid")

            def tap(buffer, _when):
                try:
                    self._take(buffer, rate)
                except Exception:
                    pass

            node.installTapOnBus_bufferSize_format_block_(0, 2048, tap_fmt, tap)
        player = A.AVAudioPlayerNode.alloc().init()
        fmt = A.AVAudioFormat.alloc().initWithCommonFormat_sampleRate_channels_interleaved_(
            A.AVAudioPCMFormatFloat32, float(RATE), 1, False)
        engine.attachNode_(player)
        engine.connect_to_format_(player, engine.mainMixerNode(), fmt)
        engine.prepare()
        speaker = coreaudio.device_name(output_device) if output_device else coreaudio.device_name(coreaudio.default_device(True))
        if output_device and not coreaudio.set_engine_output(engine, output_device):
            if node is not None:
                try:
                    node.removeTapOnBus_(0)
                except Exception:
                    pass
            raise RuntimeError(f"Could not use speaker '{speaker or output_device}'")
        last = None
        for _ in range(3):
            ok, err = engine.startAndReturnError_(None)
            if ok:
                break
            last = err.localizedDescription() if err else "unknown"
            engine.stop()
            engine.reset()
            if output_device:
                coreaudio.set_engine_output(engine, output_device)
        else:
            if node is not None:
                node.removeTapOnBus_(0)
            where = f" on {speaker}" if speaker else ""
            raise RuntimeError(f"Audio engine would not start{where}: {last}")
        player.play()
        self.engine, self.player, self.fmt = engine, player, fmt

    def stop(self) -> None:
        engine, self.engine = self.engine, None
        if engine is None:
            return
        try:
            self.player.stop()
            if self.listen:
                engine.inputNode().removeTapOnBus_(0)
            engine.stop()
        except Exception:
            pass

    # microphone ----------------------------------------------------------
    def _take(self, buffer, rate: float) -> None:
        n = int(buffer.frameLength())
        data = buffer.floatChannelData()
        if not n or data is None:
            return
        mono = np.array(data[0][0:n], dtype=np.float32)
        if abs(rate - RATE) > 1:
            out_n = int(round(n * RATE / rate))
            mono = np.interp(np.linspace(0, n - 1, out_n), np.arange(n), mono).astype(np.float32)
        if self.muted:
            mono = np.zeros_like(mono)
        self.level = float(min(1.0, np.sqrt(np.mean(mono * mono)) * 8)) if mono.size else 0.0
        combined = np.concatenate([self._carry, mono])
        whole = (combined.size // BLOCK) * BLOCK
        for i in range(0, whole, BLOCK):
            block = np.clip(combined[i:i + BLOCK] * 32767, -32768, 32767).astype(np.int16)
            self.on_mic(block)
        self._carry = combined[whole:]

    # speaker -------------------------------------------------------------
    @property
    def queued_seconds(self) -> float:
        with self._lock:
            return self._queued * BLOCK / RATE

    def play(self, samples: np.ndarray) -> None:
        """Schedule float32 mono 48 kHz samples after whatever is playing."""
        if self.engine is None or samples.size == 0:
            return
        import AVFoundation as A

        for start in range(0, samples.size, BLOCK * 10):
            chunk = samples[start:start + BLOCK * 10]
            buf = A.AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(self.fmt, chunk.size)
            if buf is None:
                return
            buf.setFrameLength_(chunk.size)
            buf.floatChannelData()[0][0:chunk.size] = chunk.tolist()
            blocks = max(1, round(chunk.size / BLOCK))
            with self._lock:
                self._queued += blocks

            def done(_kind, blocks=blocks):
                with self._lock:
                    self._queued = max(0, self._queued - blocks)

            self.player.scheduleBuffer_completionCallbackType_completionHandler_(
                buf, A.AVAudioPlayerNodeCompletionDataPlayedBack, done)

    def flush(self) -> None:
        """Drop queued speech at once (barge-in)."""
        if self.player is not None:
            self.player.stop()
            with self._lock:
                self._queued = 0
            self.player.play()

    def chime(self, kind: str) -> None:
        """Short status tones: rising for awake, falling for sleep, a tick for heard."""
        notes = {"wake": (660, 880, 1320), "sleep": (1320, 880, 660), "tick": (1200,),
                 "error": (440, 330)}.get(kind, (880,))
        parts = []
        for f in notes:
            t = np.arange(int(RATE * 0.09)) / RATE
            env = np.minimum(1, t / 0.008) * np.exp(-t * 22)
            parts.append((0.22 * env * np.sin(2 * math.pi * f * t)).astype(np.float32))
            parts.append(np.zeros(int(RATE * 0.025), dtype=np.float32))
        self.play(np.concatenate(parts))
