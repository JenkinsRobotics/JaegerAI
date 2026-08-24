"""Replaceable execution boundary for validated agent tools.

The cognitive loop decides *which* declared tool to call.  The executor
decides *how* that call is performed.  Keeping those decisions separate
allows a host to substitute a sandbox, remote worker, audit wrapper, or
test double without changing the loop.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol, runtime_checkable

from jaeger_agent.cognition.effects import EffectLedger
from jaeger_os.core.tools.tool_schema import ToolDef

# Tools whose bodies are authoritative external actions. A retry after a
# crash must not re-send; LedgerToolExecutor routes them through once().
AUTHORITATIVE_SIDE_EFFECTS = frozenset({"external"})


@runtime_checkable
class ToolExecutor(Protocol):
    """Execute one declared tool with untrusted model-supplied arguments."""

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any: ...


class DirectToolExecutor:
    """Compatibility adapter using ``ToolDef`` validation and dispatch."""

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        return tool.dispatch(dict(arguments))


class LedgerToolExecutor:
    """Wraps another executor so ``side_effect="external"`` tools go
    through :meth:`EffectLedger.once`. Default behaviour of the loop is
    unchanged (it still uses DirectToolExecutor); hosts that want
    at-most-once sends inject this.
    """

    def __init__(
        self,
        ledger: EffectLedger,
        inner: ToolExecutor | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        self._ledger = ledger
        self._inner = inner or DirectToolExecutor()
        self._run_id = run_id

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        args = dict(arguments)
        if getattr(tool, "side_effect", "") not in AUTHORITATIVE_SIDE_EFFECTS:
            return self._inner.execute(tool, args)
        key = f"{tool.name}:{json.dumps(args, sort_keys=True, default=str)}"
        result, _executed = self._ledger.once(
            key, tool.name, lambda: self._inner.execute(tool, args),
            run_id=self._run_id,
        )
        return result


__all__ = [
    "AUTHORITATIVE_SIDE_EFFECTS",
    "DirectToolExecutor",
    "LedgerToolExecutor",
    "ToolExecutor",
]
