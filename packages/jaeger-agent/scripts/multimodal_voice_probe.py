#!/usr/bin/env python3
"""Real-model wake → fact → follow-up recall probe with Kokoro am_adam."""

from __future__ import annotations

import argparse
import math
import os

os.environ.setdefault("JAEGER_TOOLSET_SCOPING", "1")

import numpy as np  # noqa: E402
from scipy.signal import resample_poly  # noqa: E402

from jaeger_agent.core.config import MultimodalConfig  # noqa: E402
from jaeger_agent import MultimodalAgent  # noqa: E402
from jaeger_agent.core.policy import (  # noqa: E402
    FRAME_MS,
    SILENCE_HANGOVER_MS,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = MultimodalConfig()
    parser.add_argument("--model-path", default=defaults.fallback_llm_model_path)
    parser.add_argument("--silero-model-path", default=defaults.silero_model_path)
    parser.add_argument("--stt-model", default=defaults.stt_model)
    parser.add_argument("--name", default="Orion")
    args = parser.parse_args()

    from kokoro import KPipeline

    events = []
    config = MultimodalConfig(
        audio_mode="structured",
        stt_model=args.stt_model,
        silero_model_path=args.silero_model_path,
        fallback_llm_model_path=args.model_path,
    )
    engine = MultimodalAgent(
        play=False,
        config=config,
        runtime_config={"provider": "llama_cpp", "model_path": args.model_path},
        on_event=events.append,
    )
    engine.load()
    synthetic_user = KPipeline(lang_code="a")

    def feed_utterance(text: str) -> None:
        chunks = [
            np.asarray(result.audio, dtype=np.float32)
            for result in synthetic_user(text, voice="am_adam")
            if result.audio is not None
        ]
        audio24 = np.concatenate(chunks)
        audio16 = resample_poly(audio24, up=2, down=3).astype(np.float32)
        pad_frames = math.ceil(SILENCE_HANGOVER_MS / FRAME_MS)
        audio16 = np.concatenate(
            [audio16, np.zeros(pad_frames * engine.FRAME, dtype=np.float32)]
        )
        for start in range(0, len(audio16), engine.FRAME):
            frame = audio16[start : start + engine.FRAME]
            if len(frame) < engine.FRAME:
                frame = np.pad(frame, (0, engine.FRAME - len(frame)))
            engine.push_audio(frame)

    try:
        feed_utterance(f"Hey Jaeger, my name is {args.name}. Remember it.")
        feed_utterance("What is my name?")
    finally:
        engine.close()

    transcripts = [event.text for event in events if event.kind == "user"]
    replies = [event.text for event in events if event.kind == "assistant"]
    recalled = replies[-1] if replies else ""
    print(f"endpoint_ms: {SILENCE_HANGOVER_MS}")
    print(f"user_turns: {transcripts}")
    print(f"final_reply: {recalled}")
    passed = len(transcripts) >= 2 and args.name.lower() in recalled.lower()
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
