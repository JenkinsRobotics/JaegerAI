"""Queue invariants for the macOS output bridge, without audio hardware."""

from __future__ import annotations

import threading

import numpy as np

from jaeger_os.core.audio.avaudio_io.output_stream import OutputStream


def test_worker_replaces_only_buffers_the_device_reports_rendered():
    """No completion means no new buffer and therefore no growing queue."""
    stream = object.__new__(OutputStream)
    stream._queue_depth_blocks = 2
    stream._stop_event = threading.Event()
    stream._rendered = threading.Semaphore(0)
    filled = threading.Event()
    fill_count = 0

    def fill_one() -> bool:
        nonlocal fill_count
        fill_count += 1
        filled.set()
        return True

    stream._fill_one_block = fill_one
    stream._signal_finish = lambda: None
    worker = threading.Thread(target=stream._worker_loop, daemon=True)
    worker.start()
    assert filled.wait(1.0)
    while fill_count < 2:
        filled.clear()
        assert filled.wait(1.0)
    assert fill_count == 2

    # A rendered-buffer callback permits exactly one replacement.
    stream._rendered.release()
    while fill_count < 3:
        filled.clear()
        assert filled.wait(1.0)
    assert fill_count == 3

    stream._stop_event.set()
    stream._rendered.release()
    worker.join(timeout=1.0)
    assert not worker.is_alive()


def test_scheduled_buffers_use_rendered_not_played_back_completion():
    """Device latency belongs at the output, not in the queue refill clock."""
    rendered = object()

    class FakePCMBuffer:
        @classmethod
        def alloc(cls):
            return cls()

        def initWithPCMFormat_frameCapacity_(self, _format, capacity):
            self.data = [np.zeros(capacity, dtype=np.float32)]
            return self

        def setFrameLength_(self, _length):
            pass

        def floatChannelData(self):
            return self.data

    class FakeAV:
        AVAudioPCMBuffer = FakePCMBuffer
        AVAudioPlayerNodeCompletionDataRendered = rendered

    class FakePlayer:
        def scheduleBuffer_completionCallbackType_completionHandler_(
                self, _buffer, callback_type, callback):
            self.callback_type = callback_type
            self.callback = callback

    stream = object.__new__(OutputStream)
    stream._callback = lambda out, *_args: out.fill(0.25)
    stream._player = FakePlayer()
    stream._fill_np = np.zeros((4, 1), dtype=np.float32)
    stream._blocksize = 4
    stream._channels = 1
    stream._av = FakeAV()
    stream._format = object()
    stream._queued_lock = threading.Lock()
    stream._queued_blocks = 0
    stream._all_rendered = threading.Event()

    assert stream._fill_one_block() is True
    assert stream._player.callback_type is rendered
    assert stream._player.callback.__self__ is stream
