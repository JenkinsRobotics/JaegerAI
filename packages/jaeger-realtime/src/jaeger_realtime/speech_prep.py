"""Live voice speech preprocessor, first-comma streaming chunker & turn-end judge.

Adapted from MIT-licensed patterns in Open-LLM-VTuber (first-comma low-latency
TTS chunking, ``[expression]`` cue extraction, inner-thought stripping) and
Project AIRI (``toSpeechText`` natural pronunciation of URLs, file paths, math,
currency, and pause-aware end-of-turn judgement). Pure stdlib.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Callable
import urllib.parse

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_EXPRESSION_TAG_RE = re.compile(r"\[([a-zA-Z][a-zA-Z0-9_-]{1,24})\]")
_STAGE_ACTION_RE = re.compile(r"(?<!\*)\*([^*\n]{1,80})\*(?!\*)")
_PAREN_THOUGHT_RE = re.compile(r"\(([^()\n]{2,100})\)")
_FENCED_CODE_RE = re.compile(r"```[a-zA-Z0-9_-]*\n.*?```", re.DOTALL)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_URL_RE = re.compile(r"https?://[^\s)>]+")
_FILEPATH_RE = re.compile(r"(?<![A-Za-z0-9:/])(?:\.{1,2}/|[a-zA-Z0-9_-]+/)[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,8}\b")
_CURRENCY_RE = re.compile(r"\$(\d+)(?:\.(\d{1,2}))?\b")
_BOLD_ITALIC_RE = re.compile(r"(\*\*|__|~~|`+)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u27BF"
    "]+",
    flags=re.UNICODE,
)

_MATH_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (">=", " greater than or equal to "),
    ("<=", " less than or equal to "),
    ("!=", " not equal to "),
    ("~=", " approximately "),
    ("->", " to "),
    ("=>", " implies "),
)

_INCOMPLETE_TAILS: frozenset[str] = frozenset({
    "and",
    "or",
    "but",
    "so",
    "because",
    "if",
    "then",
    "that",
    "which",
    "with",
    "for",
    "to",
    "from",
    "about",
    "into",
    "like",
    "um",
    "uh",
    "hmm",
    "well",
})


@dataclass(frozen=True)
class PreparedSpeech:
    spoken: str
    display_text: str
    expressions: tuple[str, ...]
    thoughts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "spoken": self.spoken,
            "display_text": self.display_text,
            "expressions": list(self.expressions),
            "thoughts": list(self.thoughts),
        }


def _speak_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    parsed = urllib.parse.urlsplit(raw)
    host = (parsed.hostname or "").removeprefix("www.")
    if not host:
        return "link"
    return host.replace(".", " dot ")


def _speak_filepath(match: re.Match[str]) -> str:
    path = match.group(0)
    cleaned = path.lstrip("./")
    return cleaned.replace("/", " slash ").replace(".", " dot ")


def _speak_currency(match: re.Match[str]) -> str:
    dollars = match.group(1)
    cents = match.group(2)
    unit = "dollar" if dollars == "1" else "dollars"
    if cents and int(cents) > 0:
        return f"{dollars} {unit} and {int(cents)} cents"
    return f"{dollars} {unit}"


def to_speech_text(
    text: str,
    *,
    strip_emojis: bool = True,
    strip_stage_actions: bool = True,
    strip_parenthetical_thoughts: bool = False,
) -> str:
    """Convert Markdown/technical text into clean, natural text for TTS synthesis."""
    out = text or ""
    out = _THINK_BLOCK_RE.sub(" ", out)
    out = _FENCED_CODE_RE.sub(" code block omitted. ", out)
    out = _EXPRESSION_TAG_RE.sub(" ", out)
    if strip_stage_actions:
        out = _STAGE_ACTION_RE.sub(" ", out)
    if strip_parenthetical_thoughts:
        out = _PAREN_THOUGHT_RE.sub(" ", out)
    out = _MD_LINK_RE.sub(r"\1", out)
    out = _URL_RE.sub(_speak_url, out)
    out = _FILEPATH_RE.sub(_speak_filepath, out)
    out = _CURRENCY_RE.sub(_speak_currency, out)
    for sym, word in _MATH_REPLACEMENTS:
        out = out.replace(sym, word)
    out = _HEADING_RE.sub("", out)
    out = _BULLET_RE.sub("", out)
    out = _BOLD_ITALIC_RE.sub("", out)
    if strip_emojis:
        out = _EMOJI_RE.sub("", out)
    return " ".join(out.split()).strip()


def extract_visual_and_speech(
    text: str,
    *,
    strip_parenthetical_thoughts: bool = True,
) -> PreparedSpeech:
    """Split a reply into spoken TTS text, avatar expression cues, and visual inner thoughts."""
    raw = text or ""
    thoughts: list[str] = []
    for m in _THINK_BLOCK_RE.finditer(raw):
        inner = m.group(0)[7:-8].strip()
        if inner:
            thoughts.append(inner)
    no_think = _THINK_BLOCK_RE.sub("", raw)
    expressions = [m.group(1).lower() for m in _EXPRESSION_TAG_RE.finditer(no_think)]
    for m in _STAGE_ACTION_RE.finditer(no_think):
        act = m.group(1).strip()
        if act:
            thoughts.append(act)
    if strip_parenthetical_thoughts:
        for m in _PAREN_THOUGHT_RE.finditer(no_think):
            p = m.group(1).strip()
            if p:
                thoughts.append(p)

    display_text = _EXPRESSION_TAG_RE.sub("", no_think).strip()
    spoken = to_speech_text(
        no_think,
        strip_emojis=True,
        strip_stage_actions=True,
        strip_parenthetical_thoughts=strip_parenthetical_thoughts,
    )
    return PreparedSpeech(
        spoken=spoken,
        display_text=display_text,
        expressions=tuple(expressions),
        thoughts=tuple(thoughts),
    )


class FirstCommaChunker:
    """Streaming TTS sentence chunker with first-comma fast-path for low voice TTFT.

    Emits the very first speakable chunk on the first comma/colon/semicolon once
    ``min_first_chars`` characters have accumulated, then switches to natural
    sentence-boundary splitting while respecting open code fences and decimals.
    """

    def __init__(self, *, min_first_chars: int = 16, max_chunk_chars: int = 240) -> None:
        self._min_first = max(4, int(min_first_chars))
        self._max_chars = max(40, int(max_chunk_chars))
        self._buf = ""
        self._emitted_first = False
        self._in_code_fence = False

    def feed(self, delta: str) -> list[str]:
        if not delta:
            return []
        self._buf += delta
        # Track fenced code blocks so we never split mid-code
        if self._buf.count("```") % 2 == 1:
            self._in_code_fence = True
            return []
        self._in_code_fence = False

        chunks: list[str] = []
        while True:
            split_at = self._find_split_index()
            if split_at is None:
                break
            head = self._buf[:split_at]
            self._buf = self._buf[split_at:].lstrip()
            spoken = to_speech_text(head)
            if spoken:
                chunks.append(spoken)
                self._emitted_first = True
        return chunks

    def flush(self) -> list[str]:
        if not self._buf.strip():
            self._buf = ""
            return []
        spoken = to_speech_text(self._buf)
        self._buf = ""
        if spoken:
            self._emitted_first = True
            return [spoken]
        return []

    def _find_split_index(self) -> int | None:
        s = self._buf
        if not s:
            return None
        # Fast first-chunk split on comma/colon/semicolon once enough text exists
        if not self._emitted_first:
            for idx, ch in enumerate(s):
                if ch in ",;:" and idx + 1 >= self._min_first:
                    if idx + 1 < len(s) and s[idx + 1].isspace():
                        return idx + 1
        # Standard sentence end (skipping decimals like 3.14)
        for idx, ch in enumerate(s):
            if ch in "!?\n":
                return idx + 1
            if ch == ".":
                prev_digit = idx > 0 and s[idx - 1].isdigit()
                next_digit = idx + 1 < len(s) and s[idx + 1].isdigit()
                if prev_digit and next_digit:
                    continue
                if idx + 1 == len(s) or s[idx + 1].isspace():
                    return idx + 1
        if len(s) >= self._max_chars:
            ws = s.rfind(" ", 0, self._max_chars)
            return ws if ws > 0 else self._max_chars
        return None


@dataclass(frozen=True)
class TurnEndDecision:
    complete: bool
    recommended_wait_ms: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TurnEndJudge:
    """Pause-aware turn-end detector (heuristic fast-path + optional LLM judge)."""

    def __init__(
        self,
        *,
        base_pause_ms: int = 1200,
        extended_pause_ms: int = 3000,
        llm_judge: Callable[[str], bool] | None = None,
    ) -> None:
        self._base_pause_ms = max(200, int(base_pause_ms))
        self._extended_pause_ms = max(self._base_pause_ms, int(extended_pause_ms))
        self._llm_judge = llm_judge

    def judge(self, transcript: str, *, pause_ms: int = 1200) -> TurnEndDecision:
        cleaned = (transcript or "").strip()
        if not cleaned:
            return TurnEndDecision(False, self._extended_pause_ms, "empty_transcript")
        if pause_ms >= self._extended_pause_ms:
            return TurnEndDecision(True, 0, "extended_silence_elapsed")
        if cleaned[-1] in ".?!":
            return TurnEndDecision(True, 0, "terminal_punctuation")

        words = re.findall(r"[a-zA-Z0-9']+", cleaned.lower())
        if not words:
            return TurnEndDecision(False, self._extended_pause_ms, "no_words")
        last_word = words[-1]
        if last_word in _INCOMPLETE_TAILS or cleaned.endswith((",", ":", "-", "—")):
            return TurnEndDecision(
                False,
                max(0, self._extended_pause_ms - pause_ms),
                f"trailing_continuation:{last_word}",
            )
        if self._llm_judge is not None:
            try:
                if bool(self._llm_judge(cleaned)):
                    return TurnEndDecision(True, 0, "llm_judge_complete")
                return TurnEndDecision(
                    False,
                    max(0, self._extended_pause_ms - pause_ms),
                    "llm_judge_incomplete",
                )
            except Exception:  # noqa: BLE001
                pass
        if pause_ms >= self._base_pause_ms and len(words) >= 2:
            return TurnEndDecision(True, 0, "base_pause_complete")
        return TurnEndDecision(
            False,
            max(0, self._base_pause_ms - pause_ms),
            "waiting_for_pause",
        )


__all__ = [
    "FirstCommaChunker",
    "PreparedSpeech",
    "TurnEndDecision",
    "TurnEndJudge",
    "extract_visual_and_speech",
    "to_speech_text",
]
