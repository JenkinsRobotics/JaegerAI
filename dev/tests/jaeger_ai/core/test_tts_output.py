"""text_to_speech output behavior.

A spoken turn must still render a visible answer in the CLI — not a
bare tool line — and the echoed line must be the spoken text verbatim,
never an LLM paraphrase of what the user just heard.
"""

from __future__ import annotations

from jaeger_ai.main import _fast_finalize_sync, _format_tool_result_as_answer


# ── formatter ───────────────────────────────────────────────────────


def test_spoken_result_echoes_the_text() -> None:
    """A successful speak echoes what was said so the turn isn't blank."""
    out = _format_tool_result_as_answer(
        "text_to_speech", {"spoken": True, "text": "Hello there"}
    )
    assert out == "🔊 Hello there"


def test_spoken_result_with_no_text_is_not_empty() -> None:
    """Even with no text in the result, the turn shows something."""
    out = _format_tool_result_as_answer(
        "text_to_speech", {"spoken": True, "text": ""}
    )
    assert out.strip()  # never a bare/empty answer


def test_failed_speak_surfaces_the_reason() -> None:
    out = _format_tool_result_as_answer(
        "text_to_speech", {"spoken": False, "reason": "no audio device"}
    )
    assert "Couldn't speak" in out
    assert "no audio device" in out


# ── fast-finalize passthrough ───────────────────────────────────────


class _SpyClient:
    """A client that records whether the finalize LLM pass was invoked."""

    def __init__(self) -> None:
        self.called = False

    def chat(self, *args: object, **kwargs: object) -> object:
        self.called = True
        raise RuntimeError("should not be reached")


def test_fast_finalize_does_not_rephrase_spoken_text() -> None:
    """text_to_speech is verbatim — the finalize pass must be skipped so
    the echoed line matches exactly what was spoken aloud."""
    spy = _SpyClient()
    joke = "Why don't scientists trust atoms? They make up everything."
    out = _fast_finalize_sync(
        spy, "tell me a joke", "text_to_speech",
        {"spoken": True, "text": joke},
    )
    assert out == f"🔊 {joke}"
    assert spy.called is False  # no LLM rephrase pass


def test_fast_finalize_skips_llm_for_deterministic_tools() -> None:
    spy = _SpyClient()
    out = _fast_finalize_sync(
        spy, "calculate 2+2", "calculate",
        {"result": 4, "expression": "2+2"},
    )
    assert out == "4"
    assert spy.called is False
