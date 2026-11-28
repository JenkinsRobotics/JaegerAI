"""Codex ToolRouter (Direct/Deferred/Hidden), RwLock parallel-read/serial-write dispatcher,
and Pydantic-AI cache-preserving progressive tool discovery.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence


class ToolVisibility(str, Enum):
    DIRECT = "direct"
    DEFERRED = "deferred"
    HIDDEN = "hidden"


@dataclass(frozen=True)
class RoutedTool:
    name: str
    visibility: ToolVisibility
    read_only: bool = False
    interactive: bool = False
    tool: Any = None


class ToolRouter:
    """Partitions registered tools into Direct, Deferred, and Hidden tiers (Codex pattern)."""

    def __init__(self) -> None:
        self._entries: dict[str, RoutedTool] = {}

    def register(
        self,
        name: str,
        *,
        visibility: ToolVisibility = ToolVisibility.DIRECT,
        read_only: bool = False,
        interactive: bool = False,
        tool: Any = None,
    ) -> None:
        self._entries[name] = RoutedTool(
            name=name,
            visibility=visibility,
            read_only=read_only,
            interactive=interactive,
            tool=tool,
        )

    def promote(self, name: str) -> bool:
        """Promote a deferred tool to DIRECT visibility (HIDDEN tools cannot be promoted)."""
        entry = self._entries.get(name)
        if entry is None or entry.visibility == ToolVisibility.HIDDEN:
            return False
        if entry.visibility == ToolVisibility.DEFERRED:
            self._entries[name] = RoutedTool(
                name=entry.name,
                visibility=ToolVisibility.DIRECT,
                read_only=entry.read_only,
                interactive=entry.interactive,
                tool=entry.tool,
            )
        return True

    def direct_tools(self) -> list[RoutedTool]:
        return [e for e in self._entries.values() if e.visibility == ToolVisibility.DIRECT]

    def deferred_tools(self) -> list[RoutedTool]:
        return [e for e in self._entries.values() if e.visibility == ToolVisibility.DEFERRED]

    def hidden_tools(self) -> list[RoutedTool]:
        return [e for e in self._entries.values() if e.visibility == ToolVisibility.HIDDEN]

    def can_dispatch(self, name: str) -> bool:
        entry = self._entries.get(name)
        return entry is not None and entry.visibility != ToolVisibility.HIDDEN

    def get(self, name: str) -> RoutedTool | None:
        return self._entries.get(name)


class ToolDiscoverySession:
    """Cache-preserving progressive tool discovery (Pydantic-AI append-only prefix rule).

    The base tool list stays in a fixed deterministic prefix order. Newly
    discovered/loaded tools are appended strictly at the tail and never
    re-sorted into the prefix, preserving LLM prompt KV-cache hits across turns.
    """

    def __init__(self, base_tools: Sequence[str] = ()) -> None:
        self._order: list[str] = []
        self._seen: set[str] = set()
        for name in base_tools:
            if name not in self._seen:
                self._order.append(name)
                self._seen.add(name)

    def activate(self, tool_names: Sequence[str]) -> list[str]:
        """Append newly activated tools to the tail; return the newly added names."""
        added: list[str] = []
        for name in tool_names:
            if name and name not in self._seen:
                self._order.append(name)
                self._seen.add(name)
                added.append(name)
        return added

    def active_names(self) -> tuple[str, ...]:
        return tuple(self._order)

    def ordered_tools(self, catalog: Mapping[str, Any]) -> list[Any]:
        return [catalog[name] for name in self._order if name in catalog]


class ReadWriteToolDispatcher:
    """RwLock-style tool batch dispatcher (Codex parallel-read / serial-write pattern).

    Partitions an ordered batch of tool calls into contiguous runs:
      - Contiguous ``read_only`` (and non-interactive) calls execute in parallel
        via a bounded thread pool while preserving original result ordering.
      - Any mutating or interactive call acts as a write barrier and executes
        serially in exact sequence.
    """

    def __init__(self, *, max_workers: int = 4) -> None:
        self._max_workers = max(1, int(max_workers))

    def dispatch_batch(
        self,
        calls: Sequence[Mapping[str, Any]],
        *,
        is_read_only: Callable[[str], bool],
        executor: Callable[[Mapping[str, Any]], Any],
    ) -> list[Any]:
        if not calls:
            return []
        if len(calls) == 1:
            return [executor(calls[0])]

        results: list[Any] = [None] * len(calls)
        i = 0
        n = len(calls)
        while i < n:
            name = str(calls[i].get("name") or "")
            if not is_read_only(name):
                results[i] = executor(calls[i])
                i += 1
                continue
            # Gather maximal contiguous read-only run
            j = i + 1
            while j < n and is_read_only(str(calls[j].get("name") or "")):
                j += 1
            if j - i == 1:
                results[i] = executor(calls[i])
            else:
                workers = min(self._max_workers, j - i)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [(idx, pool.submit(executor, calls[idx])) for idx in range(i, j)]
                    for idx, fut in futures:
                        results[idx] = fut.result()
            i = j
        return results


__all__ = [
    "ReadWriteToolDispatcher",
    "RoutedTool",
    "ToolDiscoverySession",
    "ToolRouter",
    "ToolVisibility",
]
