"""``jaeger-kokoro-tts`` — run the Kokoro engine standalone, no app required.

    jaeger-kokoro-tts speak "hello there"
    jaeger-kokoro-tts speak "hello" --voice bm_george
    jaeger-kokoro-tts save "hello there" out.wav
    jaeger-kokoro-tts voices
    jaeger-kokoro-tts bench

Deliberately smaller than the STT module's CLI, and for a real reason:
speech-to-text has six competing segmentation strategies to pick
between, so its CLI needs a registry and a ``run <method>``.  Kokoro has
ONE synthesis path.  What varies here is the voice, and where the audio
goes — a device, a file, or the bus — which is three verbs, not a
registry.

``speak`` opens the output device directly (no bus), because a CLI with
no other nodes in the process has nothing to share the speaker WITH.
Inside an app the engine takes the bus instead and publishes to
``/act/speaker/pcm`` so the audio driver owns the device — that is the
path the demo apps exercise, and it is chosen by whether a bus was
passed, not by a setting.

``save``, ``voices`` and ``bench --no-play`` touch no audio hardware at
all, so they work on a build box or over SSH.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid

from .engine import KOKORO_LANG, KOKORO_SAMPLE_RATE, KOKORO_VOICE, KokoroTTS

#: Voice ids by region, carried over from MockingAgent's
#: ``00_REFERENCES/03_TTS/kokorotts_demo.py`` header. Kokoro ships no
#: introspection API, so this is a curated list rather than a query —
#: `--voice` accepts ANY id and lets Kokoro complain, so an id missing
#: here is still usable.
VOICES = {
    "American":      [("af_heart", "female, calm neutral"),
                      ("af_nicole", "female, warm upbeat"),
                      ("am_adam", "male, strong neutral")],
    "British":       [("bf_emma", "female, friendly smooth"),
                      ("bf_sophie", "female, elegant clear"),
                      ("bm_george", "male, calm dignified"),
                      ("bm_oliver", "male, younger sharper")],
    "Chinese":       [("cf_li", "female, gentle"),
                      ("cm_jun", "male, neutral Mandarin")],
    "Japanese":      [("jf_hana", "female, soft polite"),
                      ("jm_ryo", "male, energetic")],
    "Korean":        [("kf_jiwoo", "female, soft neutral"),
                      ("km_dongha", "male, natural")],
    "French":        [("ff_claire", "female, soft elegant"),
                      ("fm_lucas", "male, smooth deep")],
    "German":        [("gf_lena", "female, clear diction"),
                      ("gm_fritz", "male, firm")],
    "Italian":       [("if_giulia", "female, expressive"),
                      ("im_luca", "male, warm")],
}

#: The `lang` KPipeline needs for a voice id. Kokoro keys it off the
#: first letter of the voice, so this is derivable rather than a second
#: thing to keep in sync — but 'a' is right for the American voices and
#: is the only default that would otherwise be silently wrong.
def _lang_for(voice: str, explicit: str | None) -> str:
    return explicit or (voice[:1] if voice else KOKORO_LANG) or KOKORO_LANG


def _engine(args) -> KokoroTTS:
    """A device-owning engine (no bus). See the module docstring."""
    return KokoroTTS(voice=args.voice, lang=_lang_for(args.voice, args.lang))


# ── speak ─────────────────────────────────────────────────────────────
def _cmd_speak(args) -> int:
    tts = _engine(args)
    t0 = time.perf_counter()
    result = tts.speak(args.text)
    elapsed = time.perf_counter() - t0
    tts.shutdown()
    if not result.get("spoken", False):
        print(f"not spoken: {result.get('reason', 'unknown')}", file=sys.stderr)
        return 1
    print(f"[{args.voice}] spoke in {elapsed:.2f}s", file=sys.stderr)
    return 0


# ── save ──────────────────────────────────────────────────────────────
def _cmd_save(args) -> int:
    """Render to a wav without opening a device.

    Written with the stdlib ``wave`` module rather than soundfile: the
    only conversion needed is float32 -> int16, and adding a dependency
    for one multiply would be the tail wagging the dog.
    """
    import wave

    import numpy as np

    tts = _engine(args)
    t0 = time.perf_counter()
    audio = tts.render(args.text)
    elapsed = time.perf_counter() - t0
    if audio is None:
        print("nothing to render (empty text after cleanup)", file=sys.stderr)
        return 1

    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(KOKORO_SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    secs = len(audio) / KOKORO_SAMPLE_RATE
    print(f"{args.out}  {secs:.2f}s audio, {elapsed:.2f}s synth "
          f"(RTF {elapsed / max(1e-9, secs):.2f}), voice={args.voice}")
    return 0


# ── voices ────────────────────────────────────────────────────────────
def _cmd_voices(args) -> int:
    for region, entries in VOICES.items():
        print(f"\n{region}")
        for vid, desc in entries:
            mark = " ←default" if vid == KOKORO_VOICE else ""
            print(f"  {vid:<14} {desc}{mark}")
    print("\nAny Kokoro voice id works — this list is a curated shortcut, "
          "not a whitelist.\n  jaeger-kokoro-tts speak \"hi\" --voice bm_george")
    return 0


# ── bench ─────────────────────────────────────────────────────────────
def _cmd_bench(args) -> int:
    """Model load vs synthesis, separately.

    They are the two numbers that matter and they behave nothing alike:
    load is a one-time ~8 s that ``warm()`` exists to move off the
    critical path, while synthesis is per-utterance and should beat
    real time. Reporting one total would hide both.

    Timed with two ``render`` calls rather than ``warm()`` + one
    render, because ``warm()`` also opens the output device — which
    would make ``--no-play`` a lie on a machine with no speaker.
    ``render`` loads the pipeline lazily and touches no hardware, so
    the first call is load+synth and the second is synth alone.
    """
    tts = _engine(args)
    t0 = time.perf_counter()
    audio = tts.render(args.text)
    cold_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    audio = tts.render(args.text)
    synth_s = time.perf_counter() - t1
    load_s = max(0.0, cold_s - synth_s)
    if audio is None:
        print("nothing rendered", file=sys.stderr)
        return 1
    secs = len(audio) / KOKORO_SAMPLE_RATE
    print(f"  voice        {args.voice}")
    print(f"  model load   {load_s:6.2f}s   (once — warm() moves this off boot)")
    print(f"  synthesis    {synth_s:6.2f}s   for {secs:.2f}s of audio")
    print(f"  RTF          {synth_s / max(1e-9, secs):6.2f}    (<1 = faster than real time)")

    if not args.no_play:
        tts.speak(args.text)
    tts.shutdown()
    return 0


# ── production hardware soak ─────────────────────────────────────────
def _cmd_soak(args) -> int:
    """Exercise the complete JaegerOS production playback path.

    Unlike ``speak`` and ``bench``, this command deliberately constructs the
    audio driver and communicates with Kokoro over the bus. It is intended
    for release qualification on the actual robot or development machine.
    """
    from jaeger_os.nodes.audio_io import AudioIONode
    from jaeger_os.transport import InProcBus, topics

    from . import make_tts_node

    phrases = (
        "Jaeger audio endurance check. The speech path is operating normally.",
        "Testing clear consonants, smooth vowels, and stable real time playback.",
        "Robotics speech should remain responsive, intelligible, and interruption safe.",
        "The quick brown fox jumps over the lazy dog. One, two, three, four, five.",
        "Persistent audio prevents device churn between consecutive robot responses.",
    )
    rates = (0.9, 1.0, 1.1, 1.0)
    duration_s = max(1.0, float(args.minutes) * 60.0)
    deadline = time.monotonic() + duration_s
    bus = InProcBus()
    audio = AudioIONode(
        bus=bus,
        capture=False,
        keep_output_open=True,
        install_signal_handlers=False,
    )
    tts = make_tts_node(bus, {
        "voice": args.voice,
        "lang": _lang_for(args.voice, args.lang),
        "warm": True,
        "queue_maxsize": 4,
    })
    threads = [
        threading.Thread(target=audio.run, name="soak-audio", daemon=True),
        threading.Thread(target=tts.run, name="soak-tts", daemon=True),
    ]
    for thread in threads:
        thread.start()

    started = time.monotonic()
    records: list[dict] = []
    failures: list[str] = []
    iteration = 0
    baseline_drops: dict[str, int] = {}

    try:
        ready_deadline = time.monotonic() + 10.0
        while time.monotonic() < ready_deadline:
            if audio.state.value == "running" and tts.state.value == "running":
                break
            time.sleep(0.05)
        if audio.state.value != "running" or tts.state.value != "running":
            print("soak failed: nodes did not reach running", file=sys.stderr)
            return 1

        baseline_drops = {
            topic: int(stats.get("dropped", 0))
            for topic, stats in bus.stats().items()
        }
        print(json.dumps({
            "event": "soak_started",
            "minutes": args.minutes,
            "voice": args.voice,
            "playback_rate": audio.health()["playback_rate"],
            "output_open": audio.health()["output_open"],
        }), flush=True)

        while time.monotonic() < deadline:
            text = phrases[iteration % len(phrases)]
            rate = rates[iteration % len(rates)]
            cid = uuid.uuid4().hex
            request_started = time.monotonic()
            ack = bus.request(
                topics.SpeechCommand(
                    text=text,
                    voice=args.voice,
                    rate=rate,
                    correlation_id=cid,
                    node_id="kokoro_soak",
                ),
                ack_topic=topics.ACT_SPEECH_SPOKEN,
                timeout_s=120.0,
            )
            wall_s = time.monotonic() - request_started
            audio_health = audio.health()
            tts_health = tts.health()
            record = {
                "iteration": iteration + 1,
                "elapsed_min": round((time.monotonic() - started) / 60.0, 2),
                "ok": bool(ack and ack.ok),
                "reason": None if ack is None else ack.reason,
                "wall_s": round(wall_s, 3),
                "rate": rate,
                "output_open": audio_health["output_open"],
                "callback_age_s": audio_health["playback_callback_age_s"],
                "underruns": audio_health["underruns"],
                "restarts": audio_health["output_restarts"],
                "flushes": audio_health["output_flushes"],
                "queued_ms": audio_health["queued_ms"],
                "tts_failed": tts_health["failed"],
            }
            records.append(record)
            print(json.dumps(record), flush=True)
            if ack is None:
                failures.append(f"iteration {iteration + 1}: ack timeout")
            elif not ack.ok:
                failures.append(
                    f"iteration {iteration + 1}: {ack.reason or 'speech failed'}"
                )
            iteration += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(float(args.pause), remaining))

        final_audio = audio.health()
        bus_drops = {
            topic: int(stats.get("dropped", 0)) - baseline_drops.get(topic, 0)
            for topic, stats in bus.stats().items()
            if int(stats.get("dropped", 0)) - baseline_drops.get(topic, 0) > 0
        }
        summary = {
            "event": "soak_complete",
            "elapsed_min": round((time.monotonic() - started) / 60.0, 2),
            "utterances": iteration,
            "successful": sum(1 for record in records if record["ok"]),
            "failures": failures,
            "underruns": final_audio["underruns"],
            "output_restarts": final_audio["output_restarts"],
            "output_flushes": final_audio["output_flushes"],
            "last_output_error": final_audio["last_output_error"],
            "bus_drops": bus_drops,
        }
        print(json.dumps(summary), flush=True)
        return 0 if not failures and not bus_drops else 1
    finally:
        tts.stop()
        audio.stop()
        for thread in reversed(threads):
            thread.join(timeout=5.0)
        bus.close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="jaeger-kokoro-tts",
        description="Run the JaegerKokoroTTS engine standalone.")
    p.add_argument("--voice", default=KOKORO_VOICE,
                   help=f"Kokoro voice id (default: {KOKORO_VOICE}) — "
                        f"see `voices`")
    p.add_argument("--lang", default=None,
                   help="KPipeline language code (default: inferred from "
                        "the voice id's first letter)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("speak", help="synthesize and play through the speaker")
    s.add_argument("text")
    s.set_defaults(func=_cmd_speak)

    v = sub.add_parser("save", help="render to a wav file — no audio device")
    v.add_argument("text")
    v.add_argument("out", help="output .wav path")
    v.set_defaults(func=_cmd_save)

    sub.add_parser("voices", help="list voice ids").set_defaults(
        func=_cmd_voices)

    b = sub.add_parser("bench", help="time model load vs synthesis")
    b.add_argument("text", nargs="?",
                   default="The quick brown fox jumps over the lazy dog.")
    b.add_argument("--no-play", action="store_true",
                   help="skip playback — for machines with no speaker")
    b.set_defaults(func=_cmd_bench)

    soak = sub.add_parser(
        "soak", help="run a timed JaegerOS production-path hardware soak",
    )
    soak.add_argument("--minutes", type=float, default=30.0)
    soak.add_argument(
        "--pause", type=float, default=0.5,
        help="seconds of silence between utterances (default: 0.5)",
    )
    soak.set_defaults(func=_cmd_soak)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
