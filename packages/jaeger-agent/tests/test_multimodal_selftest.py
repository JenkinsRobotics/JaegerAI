"""Twenty-three model-free checks ported from the VoiceLLM playground."""

from __future__ import annotations

import threading
import time
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jaeger_agent.core import context as context_module  # noqa: E402
from jaeger_agent.core.context import context_line, is_echo_garble  # noqa: E402
from jaeger_agent.core.engine import DriftAnchor, GemmaMultimodal  # noqa: E402
from jaeger_agent.core.policy import (  # noqa: E402
    FRAME_MS,
    SAMPLE_RATE,
    _match_wake,
    closes_conversation,
    followup_window,
    is_non_speech,
)


class _ProbeRuntime:
    def __init__(self) -> None:
        self.turns: list[tuple[Any, str, str]] = []

    def run_turn(self, text: str, *, session_key: str) -> str:
        self.turns.append((text, text, session_key))
        return "done"

    def run_multimodal_turn(
        self,
        content: Any,
        *,
        text: str,
        system_prompt: str,
        session_key: str,
    ) -> str:
        self.turns.append((content, system_prompt, session_key))
        return "done"

    def clear_session(self, _session_key: str) -> None:
        return None

    def close(self) -> None:
        return None


def selftest() -> list[tuple[bool, str]]:
    """Return the same 23 policy/wiring decisions without models or audio."""
    eng = GemmaMultimodal.__new__(GemmaMultimodal)
    eng.speaking = threading.Event()
    eng._last_spoken = "The capital of France is Paris."
    eng._last_spoken_at = time.time()
    eng.SELF_ECHO_GRACE_S = 1.5
    eng.speaking.set()

    checks: list[tuple[bool, str]] = []

    def ok(condition: bool, what: str) -> None:
        checks.append((bool(condition), what))

    ok(
        eng._is_self_echo("the capital of france is paris"),
        "our own sentence read back is recognised as ours",
    )
    ok(
        eng._is_self_echo("the capital of france is perris"),
        "a misheard version of our own sentence is still ours",
    )
    ok(
        not eng._is_self_echo("what about germany"),
        "a genuine follow-up is not mistaken for echo",
    )
    eng.speaking.clear()
    eng._last_spoken_at = time.time() - 5.0
    ok(
        not eng._is_self_echo("the capital of france is paris"),
        "the same words minutes later are a real question",
    )

    ok(_match_wake("hey jaeger what time is it") is not None, "wake phrase is recognised")
    ok(
        _match_wake("the computer crashed again") is None,
        "a bare name in ordinary speech does not wake it",
    )
    ok(is_non_speech("(clapping)"), "applause is environment, not speech")
    ok(closes_conversation("bye"), "'bye' closes the conversation")
    ok(not closes_conversation("by the way, what time is it"), "'by the way' does not")
    ok(
        followup_window(turns=1) < followup_window(turns=1, agent_asked=True),
        "the window extends when the agent asked a question",
    )

    ok(
        GemmaMultimodal.FRAME == SAMPLE_RATE * FRAME_MS // 1000,
        "frame size matches the verified audio pipeline",
    )
    for name in ("send_text", "attach_image", "push_audio"):
        ok(callable(getattr(GemmaMultimodal, name, None)), f"input '{name}' exists")

    for mode, has_annotator in (
        ("plain", False),
        ("structured", True),
        ("quasi", True),
        ("full", True),
    ):
        candidate = GemmaMultimodal(
            play=False,
            audio_mode=mode,
            runtime=_ProbeRuntime(),
        )
        ok(
            (candidate.annotator is not None) == has_annotator
            and candidate.audio_mode == mode,
            f"audio pipeline '{mode}' wires its layers",
        )
    ok(
        GemmaMultimodal(play=False, audio_mode="full", runtime=_ProbeRuntime())._agg
        is not None,
        "full audio pipeline carries the utterance aggregator",
    )
    ok(
        is_echo_garble("one two three four five six seven", 900)
        and not is_echo_garble("yes please", 700),
        "family echo-garble guard is live in the engine",
    )

    runtime = _ProbeRuntime()
    structured = GemmaMultimodal(
        play=False,
        audio_mode="structured",
        runtime=runtime,
    )
    structured._speak = lambda _text: None
    prior = context_module.STRUCTURED_CONTEXT
    context_module.STRUCTURED_CONTEXT = True
    try:
        turns = [{"speaker": 1, "speaker_conf": 0.9}]
        structured._respond_locked("hello", time.perf_counter(), turns)
        submitted = runtime.turns[-1][0]
        ok(
            isinstance(submitted, str)
            and submitted.startswith(
                "[input: speech]\n" + context_line(turns, "turn") + "\n"
            ),
            "the [context:] line reaches the injected runtime",
        )
    finally:
        context_module.STRUCTURED_CONTEXT = prior

    anchor = DriftAnchor()
    ok(callable(anchor.should_flush), "DriftAnchor ships enabled for full audio_mode")

    for index in range(12):
        structured._remember(f"q{index}", f"a{index}")
    ok(
        structured._history == [] and len(runtime.turns) == 1,
        "AgentRuntime owns memory; the framework rolling log is disabled",
    )
    assert len(checks) == 23
    return checks


def main() -> int:
    checks = selftest()
    for passed, description in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {description}")
    failed = sum(1 for passed, _ in checks if not passed)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


def test_full_model_free_contract() -> None:
    checks = selftest()
    assert len(checks) == 23
    assert [description for passed, description in checks if not passed] == []


if __name__ == "__main__":
    raise SystemExit(main())
