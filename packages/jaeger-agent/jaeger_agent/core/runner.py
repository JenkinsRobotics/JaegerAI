"""Core implementation of the packaged multimodal CLI."""

from __future__ import annotations

import argparse
import queue
from pathlib import Path

import numpy as np

from jaeger_agent.core.config import MultimodalConfig
from jaeger_agent.core import context
from jaeger_agent.core import engine as engine_module
from jaeger_agent.core.engine import GemmaMultimodal
from jaeger_agent.core.events import Event
from jaeger_agent.core.policy import SAMPLE_RATE, WAKE_PHRASES


def _show(event: Event) -> None:
    if event.kind == "user":
        print(f"you       {event.text}")
    elif event.kind == "assistant":
        print(f"assistant {event.text}")
    elif event.kind in ("environment", "overheard", "self"):
        print(f"[{event.kind}] {event.text[:70]}")


def run_mic(engine: GemmaMultimodal) -> int:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is required for microphone capture; "
            "install jaeger-agent"
        ) from exc

    frames: queue.Queue[np.ndarray] = queue.Queue()

    def drain() -> None:
        with frames.mutex:
            frames.queue.clear()

    engine.on_event = _show
    engine.drain_input = drain
    engine.load()
    print(f"\nlistening — say '{WAKE_PHRASES[0]}'. Ctrl-C to quit.\n")
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=engine.FRAME,
            callback=lambda audio, _n, _t, _s: frames.put(audio[:, 0].copy()),
        ):
            while True:
                engine.push_audio(frames.get())
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        engine.close()
    return 0


def run_wav(engine: GemmaMultimodal, path: Path) -> int:
    try:
        import soundfile as sf
        from scipy.signal import resample_poly
    except ImportError as exc:
        raise RuntimeError(
            "soundfile and scipy are required for WAV replay; "
            "install jaeger-agent"
        ) from exc

    pcm, sample_rate = sf.read(path, dtype="float32")
    if pcm.ndim > 1:
        pcm = pcm[:, 0]
    if sample_rate != SAMPLE_RATE:
        pcm = resample_poly(pcm, up=SAMPLE_RATE, down=sample_rate).astype(np.float32)
    seen: list[Event] = []

    def record(event: Event) -> None:
        seen.append(event)
        _show(event)

    engine.on_event = record
    engine.load()
    try:
        pcm = np.concatenate([pcm, np.zeros(SAMPLE_RATE * 3, dtype=np.float32)])
        for start in range(0, len(pcm) - engine.FRAME, engine.FRAME):
            engine.push_audio(pcm[start : start + engine.FRAME])
    finally:
        engine.close()
    replies = sum(event.kind == "assistant" for event in seen)
    print(f"\n{path.name}: {replies} reply/replies")
    return 0 if replies else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--prompt", default="")
    parser.add_argument(
        "--audio",
        choices=("plain", "structured", "quasi", "full"),
        default="structured",
        help="verified audio_mode (default: structured)",
    )
    parser.add_argument("--barge", choices=("stop", "continue"), default="stop")
    parser.add_argument("--plain-context", action="store_true")
    parser.add_argument("--model-path", default="", help="AgentRuntime GGUF path")
    parser.add_argument("--stt-model", default="large-v3-turbo")
    parser.add_argument("--silero-model-path", default="")
    parser.add_argument("--mmproj-path", default="")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument(
        "--agentic-tools",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "enable AgentRuntime tools (default); --no-agentic-tools keeps "
            "runtime-owned chat history but sends Gemma no tool schemas"
        ),
    )
    parser.add_argument(
        "--output-mode",
        choices=("dynamic", "speech", "text", "mirror"),
        default=None,
        help=(
            "output policy: dynamic lets the agent select speech; speech "
            "reproduces the original always-TTS Gemma pipeline; text disables "
            "post-turn TTS; mirror speaks only spoken-input turns"
        ),
    )
    parser.add_argument(
        "--offline-fallback",
        action="store_true",
        help="use the non-agentic Gemma baseline instead of AgentRuntime",
    )
    args = parser.parse_args(argv)
    defaults = MultimodalConfig()
    output_mode = args.output_mode or (
        "dynamic" if args.agentic_tools and not args.offline_fallback else "speech"
    )
    multimodal = MultimodalConfig(
        audio_mode=args.audio,
        stt_model=args.stt_model,
        silero_model_path=args.silero_model_path or defaults.silero_model_path,
        vision_mmproj_path=args.mmproj_path or defaults.vision_mmproj_path,
        fallback_llm_model_path=args.model_path or defaults.fallback_llm_model_path,
        kokoro_voice=args.voice,
        output_mode=output_mode,
    )
    engine_module.dxr.BARGE_MODE = args.barge
    context.STRUCTURED_CONTEXT = not args.plain_context
    runtime_config = {"tools_enabled": args.agentic_tools}
    if args.model_path:
        runtime_config["model_path"] = args.model_path
    engine = GemmaMultimodal(
        want_vision=args.vision,
        extra_prompt=args.prompt,
        config=multimodal,
        runtime_config=runtime_config,
        use_offline_fallback=args.offline_fallback,
    )
    if args.wav:
        return run_wav(engine, args.wav)
    return run_mic(engine)


if __name__ == "__main__":
    raise SystemExit(main())
