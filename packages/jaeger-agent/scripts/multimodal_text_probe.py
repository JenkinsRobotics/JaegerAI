#!/usr/bin/env python3
"""Real-model AgentRuntime memory probe through the multimodal engine."""

from __future__ import annotations

import argparse
import os

os.environ.setdefault("JAEGER_TOOLSET_SCOPING", "1")

from jaeger_agent.core.config import MultimodalConfig  # noqa: E402
from jaeger_agent import MultimodalAgent  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", default=MultimodalConfig().fallback_llm_model_path)
    parser.add_argument("--name", default="Orion")
    args = parser.parse_args()

    replies: list[str] = []
    engine = MultimodalAgent(
        play=False,
        audio_mode="plain",
        runtime_config={"provider": "llama_cpp", "model_path": args.model_path},
        on_event=lambda event: replies.append(event.text)
        if event.kind == "assistant"
        else None,
    )
    # This probe isolates the brain path; the companion voice probe exercises
    # Kokoro/Whisper. Do not load or synthesize audio here.
    engine._speak = lambda _text: None
    try:
        engine.send_text(f"My name is {args.name}. Please remember it.")
        engine.send_text("What is my name?")
    finally:
        engine.close()

    recalled = replies[-1] if replies else ""
    print(f"reply: {recalled}")
    print(f"framework_history_messages: {len(engine._history)}")
    passed = args.name.lower() in recalled.lower() and engine._history == []
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
