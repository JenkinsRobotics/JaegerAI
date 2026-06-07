"""Clean model reply text before voice rendering/TTS."""

from __future__ import annotations

import re


_CONTROL_TOKEN_RE = re.compile(
    r"<\|?/?(?:start|end|channel|message|call|return|assistant|user|"
    r"analysis|commentary|final|thought)[^>\|]*\|?>",
    re.IGNORECASE,
)
_LEADING_CHANNEL_LABEL_RE = re.compile(
    r"^\s*(?:analysis|commentary|final|thought)\b\s*[:\-]?\s*",
    re.IGNORECASE,
)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def clean_voice_reply(text: str | None) -> str:
    """Return user-facing voice text with control-channel markup removed.

    This is intentionally defensive. The normal adapter path strips exact
    gpt-oss harmony output, but local models sometimes leak malformed
    variants such as ``<|channel>thought <channel|>answer``. Voice should
    never speak those control tokens.
    """
    if not text:
        return ""
    cleaned = str(text).strip()
    if not cleaned:
        return ""

    if "<|channel|>" in cleaned:
        try:
            from jaeger_os.agent.dialects import parse_harmony

            _calls, answer = parse_harmony(cleaned)
            if answer:
                cleaned = answer
        except Exception:  # noqa: BLE001
            pass

    cleaned = _THINK_BLOCK_RE.sub("", cleaned)
    cleaned = _CONTROL_TOKEN_RE.sub("", cleaned)
    cleaned = _LEADING_CHANNEL_LABEL_RE.sub("", cleaned)
    return cleaned.strip()


__all__ = ["clean_voice_reply"]
