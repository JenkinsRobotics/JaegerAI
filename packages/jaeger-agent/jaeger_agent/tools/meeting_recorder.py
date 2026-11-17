"""Child process for meeting_record: stream the Mac's default input to a
16 kHz mono WAV until SIGTERM. Run as a plain script (no tool registry)."""

from __future__ import annotations

import signal
import sys
import time

_MAX_RECORD_S = 3 * 3600


def main(out: str) -> int:
    """Child process: stream the default input to a 16 kHz mono WAV until SIGTERM."""
    import wave

    import numpy as np
    import sounddevice as sd

    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
    started = time.time()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)

        def _cb(indata, _frames, _t, _status):
            pcm = np.clip(indata[:, 0], -1.0, 1.0)
            wav.writeframes((pcm * 32767).astype("<i2").tobytes())

        with sd.InputStream(samplerate=16000, channels=1, dtype="float32", callback=_cb):
            while not stop["flag"] and time.time() - started < _MAX_RECORD_S:
                time.sleep(0.2)
    return 0



if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
