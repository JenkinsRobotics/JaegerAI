"""Trajectory Compressor — Middle-Out Context Window Compression.

Adapted from Hermes Agent for JaegerAI.
Instead of raising hard ContextOverflow exceptions or dropping messages blindly,
this module compresses intermediate tool execution trajectories into a single
summary node while protecting the initial system/user setup and recent turn context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CompressionConfig:
    """Configuration for trajectory compression."""
    target_max_tokens: int = 14000
    summary_target_tokens: int = 500
    protect_first_n_turns: int = 3
    protect_last_n_turns: int = 4
    avg_chars_per_token: float = 3.8


@dataclass
class CompressionMetrics:
    original_tokens: int = 0
    compressed_tokens: int = 0
    tokens_saved: int = 0
    was_compressed: bool = False
    turns_removed: int = 0


def estimate_tokens(text: str, chars_per_token: float = 3.8) -> int:
    """Fast heuristics for token estimation."""
    if not text:
        return 0
    return max(1, int(len(text) / chars_per_token))


def estimate_messages_tokens(messages: List[Dict[str, Any]], chars_per_token: float = 3.8) -> int:
    """Estimate total tokens in a list of message dicts or objects."""
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = str(msg.get("content", ""))
            tool_calls = str(msg.get("tool_calls", ""))
        else:
            content = getattr(msg, "content", "") or ""
            tool_calls = str(getattr(msg, "tool_calls", "")) or ""
        total += estimate_tokens(content + tool_calls, chars_per_token)
    return total


class TrajectoryCompressor:
    """Compresses conversation history to fit within context window limits.

    Strategy:
    1. Keep initial setup turns (System prompt, initial user request, first assistant turn).
    2. Keep recent turns (Last N turns representing current active work).
    3. Compress intermediate middle turns (long tool outputs, shell execution logs).
    4. Replace compressed middle region with a structured summary node.
    """

    def __init__(self, config: Optional[CompressionConfig] = None):
        self.config = config or CompressionConfig()

    def compress(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        summarize_fn: Optional[Callable[[List[Dict[str, Any]]], str]] = None,
    ) -> tuple[List[Dict[str, Any]], CompressionMetrics]:
        target = max_tokens or self.config.target_max_tokens
        metrics = CompressionMetrics()

        orig_tokens = estimate_messages_tokens(messages, self.config.avg_chars_per_token)
        metrics.original_tokens = orig_tokens
        metrics.compressed_tokens = orig_tokens

        if orig_tokens <= target or len(messages) <= (self.config.protect_first_n_turns + self.config.protect_last_n_turns):
            return messages, metrics

        head_idx = self.config.protect_first_n_turns
        tail_idx = len(messages) - self.config.protect_last_n_turns

        if head_idx >= tail_idx:
            return messages, metrics

        head_messages = messages[:head_idx]
        middle_messages = messages[head_idx:tail_idx]
        tail_messages = messages[tail_idx:]

        # Build summary for middle messages
        if summarize_fn:
            try:
                summary_text = summarize_fn(middle_messages)
            except Exception as e:
                logger.warning(f"Summarize function failed, using default text summary: {e}")
                summary_text = self._default_summary(middle_messages)
        else:
            summary_text = self._default_summary(middle_messages)

        summary_message = {
            "role": "user",
            "content": f"[SYSTEM CONTEXT COMPRESSION]: The following intermediate tool executions were summarized to save context tokens:\n{summary_text}",
        }

        compressed = head_messages + [summary_message] + tail_messages
        comp_tokens = estimate_messages_tokens(compressed, self.config.avg_chars_per_token)

        metrics.compressed_tokens = comp_tokens
        metrics.tokens_saved = max(0, orig_tokens - comp_tokens)
        metrics.turns_removed = len(middle_messages)
        metrics.was_compressed = True

        return compressed, metrics

    def _default_summary(self, middle_messages: List[Dict[str, Any]]) -> str:
        summary_lines = []
        for idx, msg in enumerate(middle_messages, 1):
            if isinstance(msg, dict):
                role = msg.get("role", "unknown")
                content = str(msg.get("content", ""))
            else:
                role = getattr(msg, "role", "unknown")
                content = str(getattr(msg, "content", ""))
            snippet = content[:120].replace("\n", " ")
            summary_lines.append(f"- Step {idx} [{role}]: {snippet}...")
        return "\n".join(summary_lines[:15])  # Cap at 15 bullet points


def compress_trajectory_if_needed(
    messages: List[Dict[str, Any]],
    max_tokens: int = 14000,
) -> List[Dict[str, Any]]:
    """Convenience helper for quick turn context compression."""
    compressor = TrajectoryCompressor(CompressionConfig(target_max_tokens=max_tokens))
    compressed_msgs, metrics = compressor.compress(messages, max_tokens=max_tokens)
    if metrics.was_compressed:
        logger.info(
            f"Context compressed: {metrics.turns_removed} turns removed, "
            f"saved {metrics.tokens_saved} tokens ({metrics.original_tokens} -> {metrics.compressed_tokens})."
        )
    return compressed_msgs
