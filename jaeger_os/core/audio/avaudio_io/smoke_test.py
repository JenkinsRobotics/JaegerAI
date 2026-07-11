"""Standalone smoke test for the AVAudioEngine I/O wrappers.

Runs INDEPENDENT of voice_loop / Kokoro / Whisper so the operator can
verify the bridge works on their hardware before flipping any
production call sites.

Usage::

    python -m jaeger_os.core.audio.avaudio_io.smoke_test --input
    python -m jaeger_os.core.audio.avaudio_io.smoke_test --output
    python -m jaeger_os.core.audio.avaudio_io.smoke_test --loopback
    python -m jaeger_os.core.audio.avaudio_io.smoke_test --aec

``--input``    capture from mic for 3 seconds, print sample stats
``--output``   play a 1-second 440 Hz sine through speakers
``--loopback`` capture for 5 seconds, play the captured audio back
``--aec``      same as --input but with voice processing enabled
               (built-in AEC + NS + AGC) so the operator can hear
               the difference vs the raw capture
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

import numpy as np

from .input_stream import InputStream
from .output_stream import OutputStream


def smoke_input(voice_processing: bool = False) -> int:
    print(f"[smoke] InputStream — capturing 3s "
          f"(voice_processing={voice_processing})")
    samples_collected: list[np.ndarray] = []
    callback_count = 0

    def cb(indata, frames, _t, _s):
        nonlocal callback_count
        callback_count += 1
        samples_collected.append(indata.copy())

    stream = InputStream(
        samplerate=16000,
        channels=1,
        blocksize=320,           # 20ms @ 16kHz
        callback=cb,
        voice_processing=voice_processing,
    )
    try:
        stream.start()
        time.sleep(3.0)
    finally:
        stream.close()

    if not samples_collected:
        print("[smoke] FAIL — no callbacks fired", file=sys.stderr)
        return 1

    all_samples = np.concatenate(samples_collected, axis=0)
    peak = float(np.abs(all_samples).max())
    rms = float(np.sqrt(np.mean(all_samples ** 2)))
    duration_actual = len(all_samples) / 16000
    print(f"[smoke] OK — {callback_count} callbacks, "
          f"{len(all_samples)} samples ({duration_actual:.2f}s), "
          f"peak={peak:.3f}, rms={rms:.4f}")
    return 0


def smoke_output() -> int:
    print("[smoke] OutputStream — playing 1s of 440 Hz")
    samplerate = 24000
    blocksize = 480  # 20ms @ 24kHz
    total_samples = samplerate
    sent = [0]

    def cb(outdata, frames, _t, _s):
        i = sent[0]
        t = np.arange(i, i + frames) / samplerate
        outdata[:, 0] = 0.3 * np.sin(2 * np.pi * 440.0 * t)
        sent[0] += frames
        if sent[0] >= total_samples:
            from .output_stream import CallbackStop
            raise CallbackStop()

    finished = threading.Event()
    stream = OutputStream(
        samplerate=samplerate,
        channels=1,
        blocksize=blocksize,
        callback=cb,
        finished_callback=finished.set,
    )
    try:
        stream.start()
        if not finished.wait(timeout=5.0):
            print("[smoke] FAIL — playback didn't finish within 5s",
                  file=sys.stderr)
            return 1
    finally:
        stream.close()
    print(f"[smoke] OK — sent {sent[0]} samples")
    return 0


def smoke_loopback() -> int:
    print("[smoke] Loopback — capturing 5s, then playing back")
    samples_collected: list[np.ndarray] = []

    def in_cb(indata, frames, _t, _s):
        samples_collected.append(indata.copy())

    in_stream = InputStream(
        samplerate=24000,
        channels=1,
        blocksize=480,
        callback=in_cb,
    )
    try:
        in_stream.start()
        time.sleep(5.0)
    finally:
        in_stream.close()

    if not samples_collected:
        print("[smoke] FAIL — no input received", file=sys.stderr)
        return 1
    captured = np.concatenate(samples_collected, axis=0)
    print(f"[smoke] captured {len(captured)} samples")

    cursor = [0]
    finished = threading.Event()

    def out_cb(outdata, frames, _t, _s):
        i = cursor[0]
        end = i + frames
        if end >= len(captured):
            n = len(captured) - i
            outdata[:n, 0] = captured[i:i + n, 0]
            outdata[n:, 0] = 0.0
            cursor[0] = len(captured)
            from .output_stream import CallbackStop
            raise CallbackStop()
        outdata[:, 0] = captured[i:end, 0]
        cursor[0] = end

    out_stream = OutputStream(
        samplerate=24000,
        channels=1,
        blocksize=480,
        callback=out_cb,
        finished_callback=finished.set,
    )
    try:
        out_stream.start()
        if not finished.wait(timeout=10.0):
            print("[smoke] FAIL — playback didn't finish",
                  file=sys.stderr)
            return 1
    finally:
        out_stream.close()
    print("[smoke] OK — loopback round-trip complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="avaudio-smoke",
                                     description=__doc__)
    parser.add_argument("--input", action="store_true",
                        help="capture from mic for 3s")
    parser.add_argument("--output", action="store_true",
                        help="play 1s of 440 Hz")
    parser.add_argument("--loopback", action="store_true",
                        help="record 5s + play back")
    parser.add_argument("--aec", action="store_true",
                        help="capture with voice processing enabled")
    args = parser.parse_args()

    if args.input:
        return smoke_input(voice_processing=False)
    if args.output:
        return smoke_output()
    if args.loopback:
        return smoke_loopback()
    if args.aec:
        return smoke_input(voice_processing=True)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
