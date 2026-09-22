"""``jaeger voice`` — talk to the resident Entity.

    jaeger voice status               what voice can use here (JSON)
    jaeger voice                      microphone → Entity → speaker
    jaeger voice --text               typed turns, spoken replies
    jaeger voice --wav a.wav b.wav    prepared audio in place of the mic
    jaeger voice --no-speech          print replies instead of speaking

The Entity must already be running (``jaeger gateway daemon``). Voice does
not start one: if it did, it would be a second Jaeger.
"""
from __future__ import annotations

import argparse
import json
import sys

from jaeger_ai.core.gateway.client import GatewayUnavailable

from .engines import make_kokoro_speaker, make_microphone_listener, stt_status, tts_status, voice_status
from .listeners import TypedListener, WavFileListener
from .session import PrintSpeaker, VoiceSession, VoiceTurn


def _report(turn: VoiceTurn) -> None:
    result = turn.result
    record = {
        "heard": turn.transcript,
        "status": result.status if result else "unreachable",
        "request_id": result.request_id if result else None,
        "model": result.model if result else None,
        "spoken": turn.spoken,
        "latency_ms": turn.latencies_ms(),
    }
    if turn.error:
        record["error"] = turn.error
    print(json.dumps(record), file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jaeger voice", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", nargs="?", choices=["status"], help="print voice capability truth")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", action="store_true", help="type instead of speaking")
    source.add_argument("--wav", nargs="+", metavar="FILE", help="16 kHz mono WAV files to hear")
    parser.add_argument("--no-speech", action="store_true", help="print replies instead of speaking")
    parser.add_argument("--session", help="voice session id (default: a new one)")
    parser.add_argument("--stt-model", default="base.en")
    parser.add_argument("--max-turns", type=int, default=0, help="stop after N turns (0: until EOF/Ctrl-C)")
    args = parser.parse_args(argv)

    if args.action == "status":
        print(json.dumps(voice_status(), indent=2))
        return 0

    if args.wav:
        listener = WavFileListener(args.wav, model_name=args.stt_model)
    elif args.text or not (stt_status(args.stt_model).available and voice_status()["microphone"]["available"]):
        if not args.text:
            print("[voice] no usable speech input here; typing instead", file=sys.stderr)
        listener = TypedListener()
    else:
        listener = make_microphone_listener(args.stt_model)

    speaker = PrintSpeaker()
    if not args.no_speech:
        if tts_status().available:
            try:
                speaker = make_kokoro_speaker()
            except Exception as exc:  # noqa: BLE001 — degrade to text, keep the conversation
                print(f"[voice] speech output unavailable ({exc}); printing replies", file=sys.stderr)
        else:
            print(f"[voice] speech output unavailable ({tts_status().detail}); printing replies", file=sys.stderr)

    session = VoiceSession(listener, speaker, session_id=args.session, on_turn=_report)
    try:
        entity_id = session.open()
    except GatewayUnavailable as exc:
        print(f"[voice] Jaeger is not running ({exc}). Start it with `jaeger gateway daemon`.", file=sys.stderr)
        return 2
    print(f"[voice] attached to {entity_id} on session {session.session_id}", file=sys.stderr, flush=True)

    turns = 0
    try:
        while not args.max_turns or turns < args.max_turns:
            turn = session.step()
            if turn is None:
                if getattr(listener, "exhausted", False) or args.text:
                    break
                continue
            turns += 1
    except KeyboardInterrupt:
        pass
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
