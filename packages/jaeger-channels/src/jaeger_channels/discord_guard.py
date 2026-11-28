"""Discord community room guard: AmbientRoomBuffer + BotLoopGuard.

Adapted from OpenClaw (MIT) channel safety patterns so Jaeger can participate
naturally in community Discord servers without spamming unmentioned rooms or
getting trapped in bot-to-bot reply loops. Pure stdlib.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import threading
import time
from typing import Any, Iterable


@dataclass(frozen=True)
class AmbientMessage:
    channel_id: str
    sender: str
    text: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AmbientRoomBuffer:
    """Stores bounded recent unmentioned Discord messages as quiet room context."""

    def __init__(self, *, max_per_channel: int = 30, max_chars: int = 4000) -> None:
        self._max_per_channel = max(5, int(max_per_channel))
        self._max_chars = max(500, int(max_chars))
        self._rooms: dict[str, deque[AmbientMessage]] = {}
        self._lock = threading.RLock()

    def record(self, channel_id: str, sender: str, text: str, *, timestamp: float | None = None) -> None:
        cid = (channel_id or "").strip()
        cleaned = (text or "").strip()
        if not cid or not cleaned:
            return
        with self._lock:
            buf = self._rooms.setdefault(cid, deque(maxlen=self._max_per_channel))
            buf.append(
                AmbientMessage(
                    channel_id=cid,
                    sender=(sender or "member").strip()[:64],
                    text=cleaned[:400],
                    timestamp=float(timestamp if timestamp is not None else time.time()),
                )
            )

    def recent(self, channel_id: str, *, limit: int = 12) -> list[AmbientMessage]:
        with self._lock:
            buf = self._rooms.get((channel_id or "").strip())
            if not buf:
                return []
            return list(buf)[-max(1, int(limit)) :]

    def format_context(self, channel_id: str, *, limit: int = 12) -> str:
        """Render recent ambient room chatter wrapped as untrusted context."""
        msgs = self.recent(channel_id, limit=limit)
        if not msgs:
            return ""
        lines = ["[Ambient room context — untrusted external chatter]"]
        total = len(lines[0])
        for m in msgs:
            row = f"- {m.sender}: {m.text}"
            if total + len(row) + 1 > self._max_chars:
                break
            lines.append(row)
            total += len(row) + 1
        return "\n".join(lines)


class BotLoopGuard:
    """Prevents infinite bot-to-bot ping-pong loops and rapid reply bursts per channel."""

    def __init__(
        self,
        *,
        max_replies_per_window: int = 5,
        window_s: float = 60.0,
        max_consecutive_bot_turns: int = 2,
    ) -> None:
        self._max_replies = max(1, int(max_replies_per_window))
        self._window_s = max(5.0, float(window_s))
        self._max_bot_turns = max(1, int(max_consecutive_bot_turns))
        self._reply_times: dict[str, deque[float]] = {}
        self._bot_streak: dict[str, int] = {}
        self._lock = threading.RLock()

    def allow_inbound(
        self,
        channel_id: str,
        *,
        is_bot_author: bool,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Check whether an inbound message should trigger a response."""
        cid = (channel_id or "").strip()
        ts = float(now if now is not None else time.time())
        with self._lock:
            if is_bot_author:
                streak = self._bot_streak.get(cid, 0) + 1
                self._bot_streak[cid] = streak
                if streak > self._max_bot_turns:
                    return False, "bot_loop_limit_exceeded"
            else:
                self._bot_streak[cid] = 0

            times = self._reply_times.setdefault(cid, deque())
            cutoff = ts - self._window_s
            while times and times[0] < cutoff:
                times.popleft()
            if len(times) >= self._max_replies:
                return False, "channel_rate_limited"
            return True, "ok"

    def record_reply(self, channel_id: str, *, now: float | None = None) -> None:
        cid = (channel_id or "").strip()
        ts = float(now if now is not None else time.time())
        with self._lock:
            times = self._reply_times.setdefault(cid, deque())
            times.append(ts)


def is_mentioned(text: str, mention_tokens: Iterable[str]) -> bool:
    """Return True if any configured mention token (e.g. '@jaeger', '<@123>') appears in text."""
    low = (text or "").lower()
    for tok in mention_tokens:
        t = (tok or "").strip().lower()
        if t and t in low:
            return True
    return False


__all__ = [
    "AmbientMessage",
    "AmbientRoomBuffer",
    "BotLoopGuard",
    "is_mentioned",
]
