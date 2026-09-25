"""``jaeger-whisper-stt`` — run the STT engine standalone, no app required.

This exists so the module can be developed and demoed WITHOUT JaegerOS
app scaffolding: pick a method, talk, see text.

    jaeger-whisper-stt list
    jaeger-whisper-stt models --prepare
    jaeger-whisper-stt run local_agreement
    jaeger-whisper-stt run two_pass --wake --model base.en
    jaeger-whisper-stt bench --record 5
    jaeger-whisper-stt transcribe clip.wav
    jaeger-whisper-stt doctor --seconds 10

``run`` stands up a real ``InProcBus`` + ``jaeger_os.nodes.audio_io``
node and then builds the engine exactly as an app would.  It does NOT
open the microphone itself.  That is deliberate and it is the whole
point: if this CLI had its own sounddevice path, "works in the CLI"
would stop being evidence that it works in an app.  One mic path, one
set of bugs.

File-driven ``bench`` and ``transcribe`` calls need no bus or audio device.
``bench --record`` deliberately uses the same JaegerOS audio node as ``run``.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import threading
import time

from . import __version__
from .engine.registry import METHODS

#: What the log lines are tagged with. The module name from
#: ``module.yaml``, NOT the distribution name — so a line printed by
#: this CLI and a line printed by the node under a supervisor carry the
#: same source, and grepping a mixed log for one subsystem works.
LOG_SOURCE = "whisper_stt"


# ── shared bits ───────────────────────────────────────────────────────
class _CliConfig:
    """The handful of attributes the registry factories read off
    ``AudioSessionConfig``.  A tiny stand-in beats importing the real
    settings stack just to run a mic for 30 seconds."""

    def __init__(self, args) -> None:
        self.stt_mode = args.method
        self.fast_model_name = args.model
        self.accurate_model_name = args.accurate_model
        self.language = args.language
        self.require_wake_word = args.wake
        self.followup_window_s = args.followup


def _wake_phrases(args) -> tuple[str, ...]:
    from .engine._base import DEFAULT_WAKE_PHRASES
    if args.wake_phrase:
        return tuple(p.strip().lower() for p in args.wake_phrase)
    return DEFAULT_WAKE_PHRASES


def _device(value: str | None):
    """Accept either PortAudio's numeric index or a device-name fragment."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


# ── list ──────────────────────────────────────────────────────────────
def _cmd_list(args) -> int:
    print("STT methods (jaeger_whisper_stt.engine.registry):\n")
    for name, m in METHODS.items():
        tags = []
        if m.partials:
            tags.append("partials")
        if not m.available:
            tags.append("unavailable")
        if not m.wake_word:
            tags.append("app wake only")
        suffix = f"   [{', '.join(tags)}]" if tags else ""
        print(f"  {name:<16} {m.desc}{suffix}")
    print("\n  partials = emits live is_final=False text while you are "
          "still speaking.\n  Run one:  jaeger-whisper-stt run <method>")
    return 0


def _cmd_models(args) -> int:
    """Report or prepare every model a production configuration needs."""
    from .models import model_status, prepare_model

    names = args.model or ["base.en", "medium.en"]
    statuses = []
    failed = False
    for name in names:
        try:
            status = prepare_model(name) if args.prepare else model_status(name)
        except Exception as exc:  # corrupt download/load should be actionable
            failed = True
            if args.json:
                statuses.append({
                    "name": name, "cached": False, "path": None, "bytes": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                })
            else:
                print(f"  {name:<20} ERROR  {type(exc).__name__}: {exc}")
            continue
        statuses.append(status.as_json())
        if not status.cached:
            failed = True
        if not args.json:
            state = "READY" if status.cached else "MISSING"
            size = f"{status.bytes / 1_000_000:.1f} MB" if status.bytes else ""
            print(f"  {name:<20} {state:<8} {size:<10} {status.path or ''}")
    if args.json:
        print(json.dumps(statuses, indent=2))
    if failed and not args.prepare and not args.json:
        print("\nPrepare before deployment: jaeger-whisper-stt models --prepare")
    return 1 if failed else 0


# ── run ───────────────────────────────────────────────────────────────
def _cmd_run(args) -> int:
    method = METHODS.get(args.method)
    if method is None:
        print(f"unknown method {args.method!r} — try `jaeger-whisper-stt list`",
              file=sys.stderr)
        return 2
    if not method.available:
        print(f"method {args.method!r} is not available", file=sys.stderr)
        return 2
    if args.wake and not method.wake_word:
        print(
            f"method {args.method!r} commits rolling chunks and cannot apply "
            "a leading wake phrase reliably; use two_pass/phrase_word or "
            "perform directed-command detection in the app",
            file=sys.stderr,
        )
        return 2

    try:
        # The framework's log-line shape, not a private one: a CLI run
        # and the same engine under a supervisor print identically, so
        # a log pasted into a bug report reads the same either way.
        from jaeger_os import topics
        from jaeger_os.app.logging import kv, log
        from jaeger_os.core.audio import AudioSession
        from jaeger_os.nodes.audio_io import AudioIONode
        from jaeger_os.transport import InProcBus
        from .node import AudioSessionNode
    except ImportError as exc:
        print(f"`run` needs jaeger-os for the mic driver ({exc}).\n"
              f"  pip install -e '.[bootstrap]'\n"
              f"`bench` and `transcribe` work without it.", file=sys.stderr)
        return 3

    log(LOG_SOURCE, "booting jaeger node — whisper stt", level="boot")
    kv(LOG_SOURCE, "node", LOG_SOURCE)
    kv(LOG_SOURCE, "host", socket.gethostname())
    kv(LOG_SOURCE, "version", __version__)
    kv(LOG_SOURCE, "method", f"{args.method} ({method.desc})")
    kv(LOG_SOURCE, "model", args.model)
    kv(LOG_SOURCE, "language", args.language)
    if args.method == "two_pass":
        kv(LOG_SOURCE, "2nd pass", args.accurate_model)
    kv(LOG_SOURCE, "partials", "yes" if method.partials else "no")
    kv(LOG_SOURCE, "wake", ", ".join(_wake_phrases(args)[:4])
       if args.wake else "not required")

    bus = InProcBus()
    # No device selection: AudioIONode takes the system default input,
    # and its default sample rate is already 16 kHz (Whisper's rate).
    # `playback=False` because nothing in this process publishes speaker
    # frames, so an output stream would just hold the device open.
    # No OK line for the driver here, deliberately: `run()` opens the
    # device on its own thread and reports `running` itself, a second or
    # two later. An "audio driver up" printed the instant the thread is
    # spawned would be a green light for something that has not happened
    # — and on a machine with no input device it would be a green light
    # for something that never will.
    audio = AudioIONode(
        bus=bus,
        playback=False,
        audio_backend=args.audio_backend,
        input_device=_device(args.input_device),
        voice_processing=args.voice_processing,
        install_signal_handlers=False,
    )
    audio_thread = threading.Thread(target=audio.run, daemon=True,
                                    name="audio_io")

    # This is where the seconds go: the pipeline constructors load and
    # warm every model they need, so `make()` blocks for as long as the
    # weights take. `start()` afterwards is milliseconds. Timing them
    # separately is the difference between a number you can act on and
    # one that just says "boot was slow".
    log(LOG_SOURCE, f"initializing {args.method} pipeline...")
    t0 = time.perf_counter()
    try:
        engine = method.make(_CliConfig(args), bus, _wake_phrases(args))
    except Exception as exc:  # model/cache/config errors must release the bus
        log(LOG_SOURCE, f"pipeline initialization failed: "
                        f"{type(exc).__name__}: {exc}", level="error")
        bus.close()
        return 1
    log(LOG_SOURCE, f"models loaded and warmed — "
                    f"{time.perf_counter() - t0:.1f}s", level="ok")

    # Exercise the production semantic path, not only the adapter. The
    # session applies JaegerOS's deterministic filters; AudioSessionNode
    # turns adapter results into typed Transcript messages on the bus.
    session = AudioSession(adapter=engine, self_speech_filter=False)
    stt = AudioSessionNode(
        bus=bus, session=session, name=LOG_SOURCE,
        install_signal_handlers=False,
    )

    def on_transcript(msg) -> None:
        if msg.is_final:
            sys.stdout.write("\r\033[K")
            print(f"> {msg.text}", flush=True)
        elif not args.no_partials:
            sys.stdout.write(
                "\r\033[K" + (f"  … {msg.text}" if msg.text else ""),
            )
            sys.stdout.flush()

    bus.subscribe(topics.SENSE_STT_TRANSCRIPT, on_transcript)
    stt_thread = threading.Thread(
        target=stt.run, daemon=True, name=LOG_SOURCE,
    )
    log(LOG_SOURCE, "starting audio driver...")
    audio_thread.start()
    stt_thread.start()

    ready_deadline = time.monotonic() + 10.0
    while time.monotonic() < ready_deadline:
        states = (audio.state.value, stt.state.value)
        if states == ("running", "running"):
            break
        if "failed" in states:
            break
        time.sleep(0.05)
    if audio.state.value != "running" or stt.state.value != "running":
        log(LOG_SOURCE, f"startup failed — audio={audio.state.value}, "
                        f"stt={stt.state.value}", level="error")
        stt.stop()
        audio.stop()
        stt_thread.join(timeout=5.0)
        audio_thread.join(timeout=5.0)
        bus.close()
        return 1

    # The green light, and the only line that means "use it now".
    log(LOG_SOURCE, f"ready — {args.method} listening on "
                    f"{topics.SENSE_MIC_PCM}", level="ok")

    # Transcripts stay on STDOUT while the logs go to stderr: the text is
    # this command's product — `... | tee transcript.txt` has to work —
    # and the partial line's \r rewriting only behaves if one stream owns
    # the terminal for the duration.
    print("\nsay something. Ctrl-C to stop.\n", flush=True)
    deadline = time.monotonic() + args.seconds if args.seconds else None
    runtime_failed = False
    try:
        while deadline is None or time.monotonic() < deadline:
            time.sleep(0.1)
            if audio.state.value == "failed" or stt.state.value == "failed":
                runtime_failed = True
                log(LOG_SOURCE, f"runtime failure — audio={audio.state.value}, "
                                f"stt={stt.state.value}", level="error")
                break
            if stt.health_level() == topics.HEALTH_ERROR:
                runtime_failed = True
                log(LOG_SOURCE, f"runtime health error: {stt.health()}",
                    level="error")
                break
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\r\033[K")
        stt.stop()
        audio.stop()
        stt_thread.join(timeout=5.0)
        audio_thread.join(timeout=5.0)
        bus.close()
    log(LOG_SOURCE, "stopped", level="ok")
    return 1 if runtime_failed else 0


# ── transcribe ────────────────────────────────────────────────────────
def _cmd_transcribe(args) -> int:
    """Batch media transcription; one model load for every input file."""
    from pathlib import Path

    from .offline import OfflineTranscriber, write_transcripts

    transcriber = OfflineTranscriber(args.model, language=args.language,
                                     n_threads=args.threads,
                                     translate=args.translate)
    formats = tuple(args.format or ())
    for source in args.audio:
        result = transcriber.transcribe(source)
        print(f"{result.source}  ({result.audio_s:.1f}s audio, "
              f"{result.decode_s:.2f}s decode, RTF {result.rtf:.2f})\n")
        print(result.text)
        if formats:
            output_dir = Path(args.output_dir) if args.output_dir else result.source.parent
            for path in write_transcripts(
                    result, output_dir / result.source.stem, formats):
                print(f"wrote {path}")
    return 0


def _cmd_devices(args) -> int:
    """List PortAudio devices in a killable child process.

    CoreAudio device enumeration can wedge inside native code. A Python thread
    cannot interrupt that call; isolating it in a child gives this diagnostic a
    real timeout and keeps an unhealthy audio service from hanging the CLI.
    """
    probe = r'''
import json
import sounddevice as sd
defaults = sd.default.device
rows = []
for index, device in enumerate(sd.query_devices()):
    rows.append({
        "id": index,
        "name": str(device["name"]),
        "inputs": int(device["max_input_channels"]),
        "outputs": int(device["max_output_channels"]),
        "default_rate": float(device["default_samplerate"]),
        "default_input": index == int(defaults[0]),
        "default_output": index == int(defaults[1]),
    })
print(json.dumps(rows))
'''
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe], text=True, capture_output=True,
            timeout=max(1.0, args.timeout), check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"audio device query timed out after {args.timeout:.1f}s; "
            "the OS audio service may be wedged",
            file=sys.stderr,
        )
        return 1
    if result.returncode:
        detail = result.stderr.strip() or f"child exited {result.returncode}"
        print(f"audio device query failed: {detail}",
              file=sys.stderr)
        return 1
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"audio device query returned invalid data: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print("PortAudio devices (pass an id or name to --input-device):\n")
    for row in rows:
        markers = []
        if row["default_input"]:
            markers.append("default input")
        if row["default_output"]:
            markers.append("default output")
        marker = f"  [{', '.join(markers)}]" if markers else ""
        print(f"  {row['id']:>3}  in={row['inputs']:<2} out={row['outputs']:<2} "
              f"{row['default_rate']:>7.0f} Hz  {row['name']}{marker}")
    print("\nJaegerOS AVAudio uses the macOS system default. Supplying "
          "--input-device selects PortAudio so the choice is honored.")
    return 0


# ── audio hardware preflight ─────────────────────────────────────────
def _cmd_doctor(args) -> int:
    """Verify continuous JaegerOS mic capture without loading Whisper.

    This isolates the hardware/driver half of the stack. If ``doctor``
    fails, the problem is below the model; if it passes but ``run`` cannot
    transcribe known speech, investigate the engine or its settings.
    """
    import numpy as np

    from jaeger_os.nodes.audio_io import AudioIONode
    from jaeger_os.transport import InProcBus, topics

    bus = InProcBus()
    audio = AudioIONode(
        bus=bus, capture=True, playback=False,
        audio_backend=args.audio_backend,
        input_device=_device(args.input_device),
        voice_processing=args.voice_processing,
        install_signal_handlers=False,
    )
    frames = 0
    samples = 0
    peak = 0.0
    sum_squares = 0.0
    sequence_gaps = 0
    last_seq: int | None = None

    def on_frame(msg) -> None:
        nonlocal frames, samples, peak, sum_squares, sequence_gaps, last_seq
        data = np.frombuffer(msg.samples, dtype=np.float32)
        frames += 1
        samples += int(data.size)
        if data.size:
            peak = max(peak, float(np.max(np.abs(data))))
            sum_squares += float(np.sum(np.square(data, dtype=np.float64)))
        seq = int(getattr(msg, "seq", 0) or 0)
        if last_seq is not None and seq and seq != last_seq + 1:
            sequence_gaps += max(0, seq - last_seq - 1)
        if seq:
            last_seq = seq

    bus.subscribe(topics.SENSE_MIC_PCM, on_frame)
    thread = threading.Thread(target=audio.run, name="audio-doctor", daemon=True)
    thread.start()
    try:
        ready_deadline = time.monotonic() + 15.0
        while time.monotonic() < ready_deadline:
            if audio.state.value in ("running", "failed"):
                break
            time.sleep(0.05)
        if audio.state.value != "running":
            print(json.dumps({
                "event": "microphone_doctor",
                "state": audio.state.value,
                "error": audio.health().get("error") or "startup timeout",
            }, indent=2))
            return 1

        started = time.monotonic()
        deadline = started + max(1.0, float(args.seconds))
        while time.monotonic() < deadline and audio.state.value != "failed":
            time.sleep(0.05)
        health = audio.health()
        drops = {
            topic: int(values.get("dropped", 0))
            for topic, values in bus.stats().items()
            if int(values.get("dropped", 0))
        }
        report = {
            "event": "microphone_doctor",
            "elapsed_s": round(time.monotonic() - started, 2),
            "state": audio.state.value,
            "link_ok": health.get("link_ok"),
            "sample_rate": health.get("capture_rate"),
            "input_backend": health.get("input_backend"),
            "input_restarts": health.get("input_restarts"),
            "input_recovery_active": health.get("input_recovery_active"),
            "last_input_error": health.get("last_input_error"),
            "frames": frames,
            "samples": samples,
            "audio_s": round(samples / max(1, health.get("capture_rate", 16000)), 2),
            "rms": round((sum_squares / max(1, samples)) ** 0.5, 6),
            "peak": round(peak, 6),
            "sequence_gaps": sequence_gaps,
            "bus_drops": drops,
        }
        print(json.dumps(report, indent=2))
        return 0 if (
            audio.state.value == "running"
            and health.get("link_ok") is True
            and frames > 0
            and not sequence_gaps
            and not drops
        ) else 1
    finally:
        audio.stop()
        thread.join(timeout=5.0)
        bus.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="jaeger-whisper-stt",
        description="Run the JaegerWhisperSTT engine standalone.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list the STT methods").set_defaults(
        func=_cmd_list)

    models = sub.add_parser(
        "models", help="check or prepare cached Whisper model weights",
    )
    models.add_argument("model", nargs="*")
    models.add_argument("--prepare", action="store_true",
                        help="download missing weights and load-validate them")
    models.add_argument("--json", action="store_true")
    models.set_defaults(func=_cmd_models)

    r = sub.add_parser("run", help="run a method live on the microphone")
    r.add_argument("method", nargs="?", default="two_pass",
                   help=f"one of: {', '.join(METHODS)}")
    r.add_argument("--model", default="base.en",
                   help="whisper model (the only model for single-model methods)")
    r.add_argument("--accurate-model", default="medium.en",
                   help="second-pass model — two_pass only")
    r.add_argument("--language", default="en",
                   help="Whisper language code (default: en)")
    r.add_argument("--audio-backend", default="avaudio",
                   choices=("avaudio", "portaudio"))
    r.add_argument("--input-device", default=None,
                   help="input device id/name; explicit selection uses PortAudio")
    r.add_argument(
        "--voice-processing", action=argparse.BooleanOptionalAction,
        default=None,
        help="enable/disable Apple voice processing (default: automatic)",
    )
    r.add_argument("--wake", action="store_true",
                   help="require a wake phrase before a phrase counts")
    r.add_argument("--wake-phrase", action="append",
                   help="override the wake phrases (repeatable)")
    r.add_argument("--followup", type=float, default=10.0,
                   help="seconds after a turn where no wake word is needed")
    r.add_argument("--seconds", type=float, default=0.0,
                   help="stop after N seconds (default: until Ctrl-C)")
    r.add_argument("--no-partials", action="store_true",
                   help="suppress the live partial line")
    r.set_defaults(func=_cmd_run)

    t = sub.add_parser("transcribe", help="transcribe one or more media files")
    t.add_argument("audio", nargs="+")
    t.add_argument("--model", default="base.en")
    t.add_argument("--language", default="en")
    t.add_argument("--threads", type=int, default=None)
    t.add_argument("--translate", action="store_true",
                   help="translate speech to English")
    t.add_argument("--format", action="append",
                   choices=("txt", "srt", "vtt", "csv", "json"),
                   help="write an output format (repeatable)")
    t.add_argument("--output-dir", default=None)
    t.set_defaults(func=_cmd_transcribe)

    devices = sub.add_parser("devices", help="list audio input/output devices")
    devices.add_argument("--json", action="store_true")
    devices.add_argument("--timeout", type=float, default=10.0)
    devices.set_defaults(func=_cmd_devices)

    d = sub.add_parser(
        "doctor", help="verify JaegerOS microphone capture (no model load)",
    )
    d.add_argument("--seconds", type=float, default=10.0)
    d.add_argument("--audio-backend", default="avaudio",
                   choices=("avaudio", "portaudio"))
    d.add_argument("--input-device", default=None)
    d.add_argument(
        "--voice-processing", action=argparse.BooleanOptionalAction,
        default=None,
    )
    d.set_defaults(func=_cmd_doctor)

    b = sub.add_parser("bench", help="bench methods on a clip (no mic needed "
                                     "unless --record)")
    b.add_argument("--method", default="all")
    b.add_argument("--audio")
    b.add_argument("--record", type=float, default=0.0)
    b.add_argument("--audio-backend", default="avaudio",
                   choices=("avaudio", "portaudio"))
    b.add_argument("--input-device", default=None)
    b.add_argument(
        "--voice-processing", action=argparse.BooleanOptionalAction,
        default=None,
    )
    b.add_argument("--ref", default=None)
    b.add_argument("--list", action="store_true")
    b.set_defaults(func=lambda a: _cmd_bench(a))

    args = p.parse_args(argv)
    return args.func(args)


def _cmd_bench(args) -> int:
    """Delegate to the existing bench CLI so there is exactly one
    implementation of the timing table."""
    from .engine.bench import main as bench_main
    argv = ["--method", args.method]
    if args.audio:
        argv += ["--audio", args.audio]
    if args.record:
        argv += ["--record", str(args.record)]
    argv += ["--audio-backend", args.audio_backend]
    if args.input_device is not None:
        argv += ["--input-device", str(args.input_device)]
    if args.voice_processing is not None:
        argv.append("--voice-processing" if args.voice_processing
                    else "--no-voice-processing")
    if args.ref:
        argv += ["--ref", args.ref]
    if args.list:
        argv = ["--list"]
    return bench_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
