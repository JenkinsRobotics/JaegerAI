"""STT method bench — run a clip through each method and print latency,
so you can flip a pipeline variant and immediately see the cost.

    python -m jaeger_whisper_stt.engine --audio clip.wav
    python -m jaeger_whisper_stt.engine --method two_pass --audio clip.wav --ref "hello there"
    python -m jaeger_whisper_stt.engine --record 5 --method all

Reports per method: model-load · transcribe · real-time-factor · WER (if
--ref) · the transcript.  two_pass also splits fast vs accurate.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from ._bench import load_wav_16k
from .registry import METHODS


def _device(value: str | None):
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _record(
    seconds: float,
    sr: int = 16000,
    *,
    audio_backend: str = "avaudio",
    input_device=None,
    voice_processing: bool | None = None,
):
    """Record through JaegerOS's one hardware owner.

    Benchmark recording used to open ``sounddevice`` directly, creating a
    second microphone path with different device selection, recovery, and
    Apple voice-processing behavior. A production benchmark must exercise the
    same AudioIONode that a robot app uses.
    """
    import numpy as np

    from jaeger_os.nodes.audio_io import AudioIONode
    from jaeger_os.transport import InProcBus, topics

    bus = InProcBus()
    chunks: list[np.ndarray] = []

    def on_frame(msg) -> None:
        if int(getattr(msg, "sample_rate", sr)) != sr:
            return
        chunks.append(np.frombuffer(msg.samples, dtype=np.float32).copy())

    bus.subscribe(topics.SENSE_MIC_PCM, on_frame)
    audio = AudioIONode(
        bus=bus, capture=True, playback=False, sample_rate=sr,
        audio_backend=audio_backend, input_device=_device(input_device),
        voice_processing=voice_processing, install_signal_handlers=False,
    )
    thread = threading.Thread(
        target=audio.run, name="bench-audio-io", daemon=True,
    )
    thread.start()
    try:
        ready_deadline = time.monotonic() + 15.0
        while time.monotonic() < ready_deadline:
            if audio.state.value in ("running", "failed"):
                break
            time.sleep(0.05)
        if audio.state.value != "running":
            raise RuntimeError(
                f"audio driver did not start: {audio.health().get('error') or audio.state.value}"
            )
        print(f"recording {seconds:.0f}s @ {sr} Hz — speak now...", flush=True)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and audio.state.value == "running":
            time.sleep(0.02)
        health = audio.health()
        if audio.state.value != "running" or health.get("link_ok") is not True:
            raise RuntimeError(
                f"audio link failed while recording: "
                f"{health.get('last_input_error') or audio.state.value}"
            )
        if not chunks:
            raise RuntimeError("audio driver produced no microphone frames")
        return np.concatenate(chunks)[:int(seconds * sr)], sr
    finally:
        audio.stop()
        thread.join(timeout=5.0)
        bus.close()


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
    p.add_argument("--audio-backend", default="avaudio",
                   choices=("avaudio", "portaudio"))
    p.add_argument("--input-device", default=None)
    p.add_argument(
        "--voice-processing", action=argparse.BooleanOptionalAction,
        default=None,
    )
    p.add_argument("--ref", default=None, help="reference transcript, for WER")
    p.add_argument("--list", action="store_true", help="list methods + exit")
    args = p.parse_args(argv)

    if args.list:
        for name, m in METHODS.items():
            flag = "" if m.available else "  (unavailable)"
            print(f"  {name:<16} {m.desc}{flag}")
        return 0

    if args.audio:
        audio, sr = load_wav_16k(args.audio)
    elif args.record > 0:
        audio, sr = _record(
            args.record, audio_backend=args.audio_backend,
            input_device=args.input_device,
            voice_processing=args.voice_processing,
        )
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
            print(f"  {name:<16}  unavailable")
            continue
        try:
            print(_fmt(m.bench(audio, sr, ref=args.ref)))
        except Exception as exc:  # noqa: BLE001
            print(f"  {name:<16}  ERROR: {type(exc).__name__}: {exc}")
    return 0
