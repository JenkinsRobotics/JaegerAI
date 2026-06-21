"""Voice helper tests for always-on mic filtering and reply cleanup."""

from __future__ import annotations

import pytest

from jaeger_os.core.voice import clean_voice_reply, is_non_speech_marker


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[BLANK_AUDIO]",
        "[SOUND]",
        "(wind blowing)",
        "(engine roaring)",
        "(engine revving)",
        "(sighs)",
        "(tapping)",
        "(clicking)",
        "[typing sounds]",
        "(clapping)",
        "(water splashing)",
        "(air whooshing)",
        "(keyboard clacking)",
        "(paper rustling)",
        "(upbeat music)",
        "(scissors snipping)",
        "(beeping) (clicking)",
        "computer click",
    ],
)
def test_non_speech_markers_drop_open_mic_noise(text: str) -> None:
    assert is_non_speech_marker(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "(yes)",
        "[no]",
        "can you hear me?",
        "(clicking) hey jaeger what time is it",
    ],
)
def test_non_speech_filter_keeps_real_short_answers(text: str) -> None:
    assert is_non_speech_marker(text) is False


def test_clean_voice_reply_extracts_harmony_final() -> None:
    raw = (
        "<|channel|>analysis<|message|>thinking<|end|>"
        "<|channel|>final<|message|>It is 2:12 AM."
    )
    assert clean_voice_reply(raw) == "It is 2:12 AM."


def test_clean_voice_reply_strips_malformed_channel_tokens() -> None:
    raw = "<|channel>thought <channel|>It is 2:12 AM."
    assert clean_voice_reply(raw) == "It is 2:12 AM."


def test_clean_voice_reply_strips_think_blocks() -> None:
    assert clean_voice_reply("<think>private</think>Hello.") == "Hello."
