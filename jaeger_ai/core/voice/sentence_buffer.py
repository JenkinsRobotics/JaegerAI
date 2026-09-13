"""Streaming sentence aggregator for pipelined voice synthesis.

Inspired by Pipecat and LiveKit streaming sentence boundary splitters:
buffers streaming LLM tokens/deltas, detects natural sentence and clause
boundaries, and yields speakable phrases as early as possible so TTS
synthesis can start while the rest of the turn is still generating.
"""

from __future__ import annotations

import re
from typing import Generator

from jaeger_os.core.voice import clean_voice_reply

# Common abbreviations that end in a dot but should NOT terminate a sentence.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "eg", "ie",
    "st", "ave", "rd", "blvd", "dept", "est", "approx", "min", "sec",
}

# Regex to find potential sentence terminators (. ! ? \n)
_PUNCT_SPLIT_RE = re.compile(r"([.!?\n]+(?:\s+|$))")

# Secondary clause terminators (; :) when buffer is sufficiently long
_CLAUSE_SPLIT_RE = re.compile(r"([;:]\s+)")


class StreamingSentenceAggregator:
    """Buffers streaming token deltas and yields clean, complete sentences."""

    def __init__(
        self,
        *,
        min_sentence_length: int = 15,
        max_clause_length: int = 80,
    ) -> None:
        self.min_sentence_length = min_sentence_length
        self.max_clause_length = max_clause_length
        self._buffer = ""
        self._in_think_block = False

    def _is_abbreviation(self, text_before_dot: str) -> bool:
        """Check if the word immediately preceding a period is an abbreviation."""
        tokens = text_before_dot.split()
        if not tokens:
            return False
        last_word = re.sub(r"[^\w]", "", tokens[-1]).lower()
        if len(last_word) == 1:
            # Single letter initial, e.g. "J." or "U."
            return True
        return last_word in _ABBREVIATIONS

    def feed(self, delta: str) -> list[str]:
        """Ingest a text delta and return any complete sentences."""
        if not delta:
            return []

        self._buffer += delta

        # Handle <think> blocks if present in raw token stream
        if "<think>" in self._buffer and not self._in_think_block:
            self._in_think_block = True

        if self._in_think_block:
            if "</think>" in self._buffer:
                # Discard the think block
                _, remainder = self._buffer.split("</think>", 1)
                self._buffer = remainder
                self._in_think_block = False
            else:
                return []

        sentences: list[str] = []
        search_start = 0

        while True:
            # Check for sentence terminators (. ! ? \n)
            match = _PUNCT_SPLIT_RE.search(self._buffer, search_start)
            if match:
                end_pos = match.end()
                candidate = self._buffer[:end_pos]
                before_punct = candidate[:match.start()].strip()

                # Check if this period is just an abbreviation or number (e.g. 3.14)
                matched_punct = match.group(1).strip()
                if "." in matched_punct and not any(p in matched_punct for p in "!?\n"):
                    # Check for decimal numbers
                    if re.search(r"\d\.\d*$", before_punct) or self._is_abbreviation(before_punct):
                        # Skip past this dot and continue searching further in the buffer
                        search_start = end_pos
                        continue

                cleaned = clean_voice_reply(candidate)
                self._buffer = self._buffer[end_pos:]
                search_start = 0
                if cleaned:
                    sentences.append(cleaned)
                continue

            # If buffer is getting very long and has clause breaks (; or :), flush early
            if len(self._buffer) >= self.max_clause_length:
                clause_match = _CLAUSE_SPLIT_RE.search(self._buffer)
                if clause_match:
                    end_pos = clause_match.end()
                    candidate = self._buffer[:end_pos]
                    cleaned = clean_voice_reply(candidate)
                    self._buffer = self._buffer[end_pos:]
                    search_start = 0
                    if cleaned:
                        sentences.append(cleaned)
                    continue

            break

        return sentences

    def flush(self) -> list[str]:
        """Flush any remaining text in the buffer as the final sentence."""
        sentences: list[str] = []
        if self._buffer:
            cleaned = clean_voice_reply(self._buffer)
            self._buffer = ""
            if cleaned:
                sentences.append(cleaned)
        self._in_think_block = False
        return sentences


__all__ = ["StreamingSentenceAggregator"]
