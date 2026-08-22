"""STT method bench — run a clip through each method and print latency,
so you can flip a pipeline variant and immediately see the cost.

    python -m jaeger_whisper_stt.nodes.whisper_stt.engine --audio clip.wav
    python -m jaeger_whisper_stt.nodes.whisper_stt.engine --method two_pass --audio clip.wav --ref "hello there"
    python -m jaeger_whisper_stt.nodes.whisper_stt.engine --record 5 --method all

Reports per method: model-load · transcribe · real-time-factor · WER (if
--ref) · the transcript.  two_pass also splits fast vs accurate.
"""

from __future__ import annotations

import argparse
import sys

from ._bench import load_wav_16k
from .registry import METHODS


def _record(seconds: float, sr: int = 16000):
    import sounddevice as sd  # optional — only needed for --record

    print(f"recording {seconds:.0f}s @ {sr} Hz — speak now...", flush=True)
    a = sd.rec(int(seconds * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    return a.reshape(-1), sr


def _fmt(r) -> str:
    if r.error:
        return f"  {r.method:<16}  {r.error}"
    line = (f"  {r.method:<16}  load {r.model_load_s:6.2f}s   "
            f"transcribe {r.transcribe_s:6.2f}s   RTF {r.rtf:5.2f}")
    if r.wer is not None:
        line += f"   WER {r.wer:5.2f}"
    if "fast_s" in r.extra:
        line += f"   (fast {r.extra['fast_s']:.2f}s + accurate {r.extra['accurate_s']:.2f}s)"
    return line + f'\n      -> "{(r.text or "")[:90]}"'


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="whisper_stt.bench",
                                description="Bench the STT pipeline methods.")
    p.add_argument("--method", default="all",
                   help="two_pass | continuous | local_agreement | all")
    p.add_argument("--audio", help="path to a .wav clip")
    p.add_argument("--record", type=float, default=0.0,
                   help="record N seconds from the mic instead of --audio")
    p.add_argument("--ref", default=None, help="reference transcript, for WER")
    p.add_argument("--list", action="store_true", help="list methods + exit")
    args = p.parse_args(argv)

    if args.list:
        for name, m in METHODS.items():
            flag = "" if m.available else "  (stub)"
            print(f"  {name:<16} {m.desc}{flag}")
        return 0

    if args.audio:
        audio, sr = load_wav_16k(args.audio)
    elif args.record > 0:
        audio, sr = _record(args.record)
    else:
        print("need --audio <path.wav> or --record <seconds> (or --list)",
              file=sys.stderr)
        return 2

    print(f"audio: {len(audio) / sr:.1f}s @ {sr} Hz"
          + (f'   ref: "{args.ref}"' if args.ref else ""))
    names = list(METHODS) if args.method == "all" else [args.method]
    for name in names:
        m = METHODS.get(name)
        if m is None:
            print(f"  {name:<16}  unknown method")
            continue
        if not m.available:
            print(f"  {name:<16}  (stub — not implemented)")
            continue
        try:
            print(_fmt(m.bench(audio, sr, ref=args.ref)))
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:<16}  ERROR: {type(exc).__name__}: {exc}")
    return 0
