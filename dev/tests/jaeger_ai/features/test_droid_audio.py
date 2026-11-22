import numpy as np

from jaeger_ai.features.droid.audio import BLOCK, DuplexAudio


class _FakeAec:
    def __init__(self):
        self.calls = []
        self.resets = 0

    def process(self, near, far):
        self.calls.append((near.copy(), far.copy()))
        return near - far

    def reset(self):
        self.resets += 1


def test_software_aec_uses_scheduled_audio_as_far_end_reference():
    heard = []
    audio = DuplexAudio(heard.append)
    audio._aec = _FakeAec()
    far = np.full(BLOCK, 0.1, dtype=np.float32)
    audio._queue_far(far)

    class Buffer:
        def frameLength(self):
            return BLOCK

        def floatChannelData(self):
            return [np.full(BLOCK, 0.25, dtype=np.float32)]

    audio._take(Buffer(), 48000)

    assert len(heard) == 1
    assert len(audio._aec.calls) == 1
    np.testing.assert_allclose(audio._aec.calls[0][1], far)
    np.testing.assert_allclose(heard[0], np.full(BLOCK, int(0.15 * 32767), dtype=np.int16))


def test_far_reference_preserves_order_and_pads_silence():
    audio = DuplexAudio(lambda _: None)
    audio._aec = _FakeAec()
    audio._queue_far(np.arange(5, dtype=np.float32))
    audio._queue_far(np.arange(5, 9, dtype=np.float32))

    np.testing.assert_array_equal(audio._far_block(7), np.arange(7, dtype=np.float32))
    np.testing.assert_array_equal(audio._far_block(4), np.array([7, 8, 0, 0], dtype=np.float32))


def test_flush_resets_reference_and_canceller_without_player():
    audio = DuplexAudio(lambda _: None)
    audio._aec = _FakeAec()
    audio._queue_far(np.ones(BLOCK, dtype=np.float32))

    audio.flush()

    assert audio._aec.resets == 1
    assert not audio._far
