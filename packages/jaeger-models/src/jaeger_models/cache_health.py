"""Prompt-cache collapse detection across multi-turn agent conversations.

Adapted from Pydantic AI (MIT License) ``_cache_health.py`` (Claude Code thresholds).
Tracks established cached prefix size per ``(conversation_id, provider, model)`` and
classifies sudden drops as ``unexpected``, ``ttl_expired``, or ``compacted``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

MIN_CACHEABLE_TOKENS = 4096
MIN_MISSED_TOKENS = 2000
MIN_MISSED_RATIO = 0.05
DEFAULT_CACHE_TTL_S = 300.0


@dataclass(frozen=True)
class CacheCollapseEvent:
    conversation_id: str
    provider: str
    model: str
    previous_cached_tokens: int
    current_cached_tokens: int
    missed_tokens: int
    reason: str  # "unexpected" | "ttl_expired" | "compacted"


@dataclass
class _CacheMark:
    cached_tokens: int
    timestamp: float


class ConversationCacheMarkStore:
    """Thread-safe in-memory store detecting silent prompt-cache collapse."""

    def __init__(self, *, ttl_s: float = DEFAULT_CACHE_TTL_S, max_entries: int = 512) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._marks: dict[tuple[str, str, str], _CacheMark] = {}
        self._lock = threading.Lock()

    def record(
        self,
        *,
        conversation_id: str,
        provider: str,
        model: str,
        cache_read_tokens: int,
        compacted: bool = False,
        now: float | None = None,
    ) -> CacheCollapseEvent | None:
        ts = time.monotonic() if now is None else now
        key = (conversation_id, provider, model)
        with self._lock:
            prev = self._marks.get(key)
            event: CacheCollapseEvent | None = None
            if prev is not None and prev.cached_tokens >= MIN_CACHEABLE_TOKENS:
                missed = prev.cached_tokens - cache_read_tokens
                if missed >= MIN_MISSED_TOKENS and (missed / prev.cached_tokens) >= MIN_MISSED_RATIO:
                    if compacted:
                        reason = "compacted"
                    elif (ts - prev.timestamp) > self._ttl_s:
                        reason = "ttl_expired"
                    else:
                        reason = "unexpected"
                    event = CacheCollapseEvent(
                        conversation_id=conversation_id,
                        provider=provider,
                        model=model,
                        previous_cached_tokens=prev.cached_tokens,
                        current_cached_tokens=cache_read_tokens,
                        missed_tokens=missed,
                        reason=reason,
                    )
            if len(self._marks) >= self._max_entries and key not in self._marks:
                oldest = min(self._marks.items(), key=lambda kv: kv[1].timestamp)[0]
                del self._marks[oldest]
            self._marks[key] = _CacheMark(cached_tokens=cache_read_tokens, timestamp=ts)
            return event


__all__ = [
    "CacheCollapseEvent",
    "ConversationCacheMarkStore",
    "DEFAULT_CACHE_TTL_S",
    "MIN_CACHEABLE_TOKENS",
    "MIN_MISSED_RATIO",
    "MIN_MISSED_TOKENS",
]
