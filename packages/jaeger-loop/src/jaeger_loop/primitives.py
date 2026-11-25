"""Core Slice 6 execution primitives distilled from Goose, Pydantic-AI, Codex & Gemini CLI.

- Goose: Persisted state-machine operations & effects (``LoopState``, ``LoopOperation``,
  ``LoopEffect``, ``LoopStateMachine``).
- Pydantic-AI: ``CapabilityOrdering`` middleware sorting + ``for_run()`` per-run
  state isolation so middleware never leaks across concurrent sessions.
- Codex: ``TurnMailbox`` priority input queue (``ABORT`` > ``STEER`` > ``NORMAL``).
- Gemini CLI: ``TwoTierLoopDetector`` (Tier 1 exact/semantic + Tier 2 oscillation cycle).
"""

from __future__ import annotations

import heapq
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Mapping, Sequence

from .backstop import (
    MAX_IDENTICAL_CALLS,
    MAX_SEMANTIC_FAILURES,
    call_signature,
    semantic_failure_signature,
)


# ---------------------------------------------------------------------------
# Goose: Pure state-machine operations & effects
# ---------------------------------------------------------------------------

class LoopState(str, Enum):
    IDLE = "idle"
    CALLING_MODEL = "calling_model"
    EXECUTING_TOOLS = "executing_tools"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    HALTED = "halted"
    FAILED = "failed"


class LoopOperation(str, Enum):
    START_TURN = "start_turn"
    MODEL_TEXT_ONLY = "model_text_only"
    MODEL_TOOL_CALLS = "model_tool_calls"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    TOOLS_FINISHED = "tools_finished"
    STEER_RECEIVED = "steer_received"
    LOOP_DETECTED = "loop_detected"
    ERROR = "error"


@dataclass(frozen=True)
class LoopEffect:
    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)


class LoopStateMachine:
    """Deterministic Goose-style state machine emitting explicit side-effect descriptors."""

    def __init__(self, initial: LoopState = LoopState.IDLE) -> None:
        self.state: LoopState = initial
        self.history: list[tuple[LoopState, LoopOperation, LoopState]] = []

    def apply(
        self,
        op: LoopOperation,
        payload: Mapping[str, Any] | None = None,
    ) -> list[LoopEffect]:
        data = dict(payload or {})
        prev = self.state
        effects: list[LoopEffect] = []

        if op == LoopOperation.START_TURN:
            self.state = LoopState.CALLING_MODEL
            effects.append(LoopEffect("invoke_model", data))
        elif op == LoopOperation.MODEL_TEXT_ONLY:
            self.state = LoopState.COMPLETED
            effects.append(LoopEffect("checkpoint", data))
            effects.append(LoopEffect("emit_complete", data))
        elif op == LoopOperation.MODEL_TOOL_CALLS:
            self.state = LoopState.EXECUTING_TOOLS
            effects.append(LoopEffect("dispatch_tools", data))
        elif op == LoopOperation.APPROVAL_REQUIRED:
            self.state = LoopState.AWAITING_APPROVAL
            effects.append(LoopEffect("checkpoint", data))
            effects.append(LoopEffect("request_approval", data))
        elif op == LoopOperation.APPROVAL_GRANTED:
            self.state = LoopState.EXECUTING_TOOLS
            effects.append(LoopEffect("dispatch_tools", data))
        elif op == LoopOperation.APPROVAL_DENIED:
            self.state = LoopState.CALLING_MODEL
            effects.append(LoopEffect("inject_denial", data))
            effects.append(LoopEffect("invoke_model", data))
        elif op == LoopOperation.TOOLS_FINISHED:
            self.state = LoopState.CALLING_MODEL
            effects.append(LoopEffect("invoke_model", data))
        elif op == LoopOperation.STEER_RECEIVED:
            self.state = LoopState.CALLING_MODEL
            effects.append(LoopEffect("inject_steer", data))
            effects.append(LoopEffect("invoke_model", data))
        elif op == LoopOperation.LOOP_DETECTED:
            self.state = LoopState.HALTED
            effects.append(LoopEffect("checkpoint", data))
            effects.append(LoopEffect("emit_halt", data))
        elif op == LoopOperation.ERROR:
            self.state = LoopState.FAILED
            effects.append(LoopEffect("emit_error", data))

        self.history.append((prev, op, self.state))
        return effects


# ---------------------------------------------------------------------------
# Pydantic-AI: CapabilityOrdering middleware & per-run isolation (for_run)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityOrdering:
    """Declarative middleware ordering (lower priority runs earlier on entry / outer onion)."""

    name: str
    priority: int = 100
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


def sort_middlewares_by_capability(middlewares: Sequence[Any]) -> list[Any]:
    """Topologically sort middlewares honoring ``capability_ordering`` constraints + priority."""
    items = list(middlewares)
    if len(items) <= 1:
        return items

    def _meta(mw: Any, idx: int) -> CapabilityOrdering:
        meta = getattr(mw, "capability_ordering", None)
        if isinstance(meta, CapabilityOrdering):
            return meta
        return CapabilityOrdering(name=getattr(mw, "name", f"mw_{idx}"), priority=100)

    metas = [_meta(mw, i) for i, mw in enumerate(items)]
    by_name = {m.name: i for i, m in enumerate(metas)}
    indeg = [0] * len(items)
    adj: list[list[int]] = [[] for _ in items]

    for i, m in enumerate(metas):
        for target in m.before:
            if target in by_name and by_name[target] != i:
                adj[i].append(by_name[target])
                indeg[by_name[target]] += 1
        for dep in m.after:
            if dep in by_name and by_name[dep] != i:
                adj[by_name[dep]].append(i)
                indeg[i] += 1

    heap: list[tuple[int, int]] = [
        (metas[i].priority, i) for i in range(len(items)) if indeg[i] == 0
    ]
    heapq.heapify(heap)
    ordered_idx: list[int] = []
    while heap:
        _, u = heapq.heappop(heap)
        ordered_idx.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                heapq.heappush(heap, (metas[v].priority, v))

    if len(ordered_idx) != len(items):
        # Cycle fallback: deterministic priority sort
        return [items[i] for i in sorted(range(len(items)), key=lambda i: (metas[i].priority, i))]
    return [items[i] for i in ordered_idx]


def instantiate_middlewares_for_run(middlewares: Sequence[Any], run_id: str) -> list[Any]:
    """Pydantic-AI ``for_run`` isolation: clone per-run middleware state if supported."""
    ordered = sort_middlewares_by_capability(middlewares)
    out: list[Any] = []
    for mw in ordered:
        for_run = getattr(mw, "for_run", None)
        out.append(for_run(run_id) if callable(for_run) else mw)
    return out


# ---------------------------------------------------------------------------
# Codex: Steer / Mailbox priority input queue
# ---------------------------------------------------------------------------

class MailPriority(IntEnum):
    ABORT = 0
    STEER = 10
    NORMAL = 20


@dataclass(frozen=True)
class MailboxMessage:
    priority: MailPriority
    content: str
    sender: str = "user"
    timestamp: float = field(default_factory=time.time)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class TurnMailbox:
    """Thread-safe priority input queue polled at safe loop boundaries (Codex Steer/Mailbox)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._heap: list[tuple[int, int, MailboxMessage]] = []

    def post(
        self,
        content: str,
        *,
        priority: MailPriority = MailPriority.NORMAL,
        sender: str = "user",
        metadata: Mapping[str, Any] | None = None,
    ) -> MailboxMessage:
        msg = MailboxMessage(
            priority=priority,
            content=content,
            sender=sender,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._seq += 1
            heapq.heappush(self._heap, (int(priority), self._seq, msg))
        return msg

    def steer(self, content: str, *, sender: str = "user") -> MailboxMessage:
        return self.post(content, priority=MailPriority.STEER, sender=sender)

    def abort(self, reason: str = "user aborted") -> MailboxMessage:
        return self.post(reason, priority=MailPriority.ABORT, sender="system")

    def drain(self) -> list[MailboxMessage]:
        with self._lock:
            out: list[MailboxMessage] = []
            while self._heap:
                out.append(heapq.heappop(self._heap)[2])
            return out

    def has_abort(self) -> bool:
        with self._lock:
            return any(item[0] == int(MailPriority.ABORT) for item in self._heap)

    def __len__(self) -> int:
        with self._lock:
            return len(self._heap)


# ---------------------------------------------------------------------------
# Gemini CLI: 2-tier loop detector (exact/semantic + ping-pong oscillation)
# ---------------------------------------------------------------------------

class TwoTierLoopDetector:
    """2-tier loop detector combining exact/semantic counters with A-B-A-B oscillation detection."""

    def __init__(
        self,
        *,
        max_identical: int = MAX_IDENTICAL_CALLS,
        max_semantic_failures: int = MAX_SEMANTIC_FAILURES,
        oscillation_repeats: int = 3,
    ) -> None:
        self._max_identical = max(2, int(max_identical))
        self._max_semantic = max(2, int(max_semantic_failures))
        self._osc_repeats = max(2, int(oscillation_repeats))
        self._call_counts: dict[str, int] = {}
        self._fail_counts: dict[str, int] = {}
        self._recent: deque[str] = deque(maxlen=24)

    def record(self, tool_name: str, args: Any, result: Any) -> str | None:
        """Record a completed tool call and return a halt reason if a loop tripped."""
        sig = call_signature(tool_name, args)
        self._call_counts[sig] = self._call_counts.get(sig, 0) + 1
        self._recent.append(sig)

        fail_sig = semantic_failure_signature(tool_name, args, result)
        if fail_sig:
            self._fail_counts[fail_sig] = self._fail_counts.get(fail_sig, 0) + 1
            if self._fail_counts[fail_sig] >= self._max_semantic:
                return f"tier1 semantic failure loop on {tool_name} ({self._fail_counts[fail_sig]}x)"

        if self._call_counts[sig] >= self._max_identical:
            return f"tier1 identical call loop on {tool_name} ({self._call_counts[sig]}x)"

        # Tier 2: detect period-2 or period-3 oscillation cycles (A, B, A, B, A, B)
        seq = list(self._recent)
        for period in (2, 3):
            need = period * self._osc_repeats
            if len(seq) >= need:
                tail = seq[-need:]
                unit = tail[:period]
                if len(set(unit)) > 1 and all(
                    tail[i : i + period] == unit for i in range(0, need, period)
                ):
                    tools = " -> ".join(u.split("|", 1)[0] for u in unit)
                    return f"tier2 oscillation loop detected ({tools}) x{self._osc_repeats}"
        return None


__all__ = [
    "CapabilityOrdering",
    "LoopEffect",
    "LoopOperation",
    "LoopState",
    "LoopStateMachine",
    "MailPriority",
    "MailboxMessage",
    "TurnMailbox",
    "TwoTierLoopDetector",
    "instantiate_middlewares_for_run",
    "sort_middlewares_by_capability",
]
