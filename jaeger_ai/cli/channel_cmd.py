"""``jaeger channel`` — first slice of the YouTube pipeline.

    jaeger channel script  BRIEF.md --episode "Ep 1: ..." [--log LOG.md ...] -o ep1.script.md
    jaeger channel voice   ep1.script.md -o ep1.narration.wav
    jaeger channel roughcut footage.mp4 -o out_dir/

Local files in, local files out. Nothing is uploaded or published.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "channel", help="YouTube pipeline: episode script, AI-host voice, rough cut",
        description="Draft an episode script, voice it with Kokoro, and rough-cut "
                    "build footage. Local only; never uploads.")
    sub = parser.add_subparsers(dest="channel_cmd", metavar="<step>")

    s = sub.add_parser("script", help="brief (+ build logs) -> outline/script/shot list")
    s.add_argument("brief", type=Path)
    s.add_argument("--episode", required=True, help="what this episode is about")
    s.add_argument("--log", dest="logs", type=Path, action="append", default=[],
                   help="build log file (repeatable)")
    s.add_argument("-o", "--out", type=Path, required=True)
    s.add_argument("--model", help="override the instance's external_model")
    s.add_argument("--base-url", help="override the instance's external_model base_url")
    s.add_argument("--max-tokens", type=int, default=8000)
    s.set_defaults(_handler=_script)

    v = sub.add_parser("voice", help="script markdown -> narration WAV (Kokoro)")
    v.add_argument("script", type=Path)
    v.add_argument("-o", "--out", type=Path, required=True)
    v.add_argument("--host-voice", default=None)
    v.add_argument("--robot-voice", default=None)
    v.set_defaults(_handler=_voice)

    r = sub.add_parser("roughcut", help="video -> silences trimmed + captions (Whisper)")
    r.add_argument("video", type=Path)
    r.add_argument("-o", "--out-dir", type=Path, required=True)
    r.add_argument("--whisper-model", default="base.en")
    r.add_argument("--noise-db", type=float, default=-35.0)
    r.add_argument("--min-silence", type=float, default=0.8)
    r.add_argument("--pad", type=float, default=0.2)
    r.add_argument("--threads", type=int, default=4)
    r.set_defaults(_handler=_roughcut)

    parser.set_defaults(_handler=lambda args: (parser.print_help(), 0)[1])


def _script(args: Any) -> int:
    from jaeger_ai.features.youtube_studio import script as mod

    settings = mod.load_model_settings()
    settings = mod.ModelSettings(base_url=args.base_url or settings.base_url,
                                 model=args.model or settings.model)
    print(c.dim(f"  writing script with {settings.model} …"))
    out = mod.generate_script(args.brief, args.out, episode=args.episode,
                              log_paths=args.logs, settings=settings,
                              max_tokens=args.max_tokens)
    gaps = mod.missing_sections(out.read_text(encoding="utf-8"))
    print(c.green(f"  wrote {out}") + (c.yellow(f"  (missing: {', '.join(gaps)})") if gaps else ""))
    return 0


def _voice(args: Any) -> int:
    from jaeger_ai.features.youtube_studio import voice as mod

    lines = mod.narration_lines(args.script.read_text(encoding="utf-8"))
    if not lines:
        print(c.red("  no HOST:/ROBOT: lines under ## Narration"))
        return 1
    cues = mod.render_narration(lines, args.out,
                                host_voice=args.host_voice or mod.DEFAULT_HOST_VOICE,
                                robot_voice=args.robot_voice or mod.DEFAULT_ROBOT_VOICE)
    print(c.green(f"  wrote {args.out}  ({len(cues)} lines, {cues[-1].end_s:.1f}s)"))
    return 0


def _roughcut(args: Any) -> int:
    from jaeger_ai.features.youtube_studio import roughcut as mod

    result = mod.make_roughcut(args.video, args.out_dir, whisper_model=args.whisper_model,
                               noise_db=args.noise_db, min_silence_s=args.min_silence,
                               pad_s=args.pad, threads=args.threads)
    print(c.green(f"  wrote {result.captioned}"))
    print(c.dim(f"  {result.source_s:.1f}s -> {result.cut_s:.1f}s, "
                f"{len(result.kept)} kept segments; captions: "
                + ", ".join(p.name for p in result.captions)))
    return 0
