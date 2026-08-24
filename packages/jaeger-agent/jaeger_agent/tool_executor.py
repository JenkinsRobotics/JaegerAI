"""Replaceable execution boundary for validated agent tools.

The cognitive loop decides *which* declared tool to call.  The executor
decides *how* that call is performed.  Keeping those decisions separate
allows a host to substitute a sandbox, remote worker, audit wrapper, or
test double without changing the loop.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from jaeger_os.core.tools.tool_schema import ToolDef


@runtime_checkable
class ToolExecutor(Protocol):
    """Execute one declared tool with untrusted model-supplied arguments."""

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any: ...


class DirectToolExecutor:
    """Compatibility adapter using ``ToolDef`` validation and dispatch."""

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        return tool.dispatch(dict(arguments))


__all__ = ["DirectToolExecutor", "ToolExecutor"]
