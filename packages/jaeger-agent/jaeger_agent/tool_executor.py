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
    """Production executor: ``side_effect="external"`` tools go through
    :meth:`EffectLedger.once`. Validation happens *before* the claim so
    a bad argument list does not leave an indeterminate pending row.

    Keys include the bound ``run_id`` so a new run may legitimately
    repeat the same tool+args (a second user request) while a crash
    resume of the *same* run cannot.
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

    def bind_run(self, run_id: str | None) -> None:
        self._run_id = run_id

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        args = dict(arguments)
        if getattr(tool, "side_effect", "") not in AUTHORITATIVE_SIDE_EFFECTS:
            return self._inner.execute(tool, args)
        self._validate(tool, args)
        key = self._effect_key(tool.name, args)
        result, _executed = self._ledger.once(
            key, tool.name, lambda: self._inner.execute(tool, args),
            run_id=self._run_id,
        )
        return result

    def _effect_key(self, tool_name: str, args: dict[str, Any]) -> str:
        payload = json.dumps(args, sort_keys=True, default=str)
        prefix = self._run_id or "unbound"
        return f"{prefix}:{tool_name}:{payload}"

    @staticmethod
    def _validate(tool: ToolDef, args: dict[str, Any]) -> None:
        from jaeger_os.core.tools.arg_coercion import coerce_args
        coerced = coerce_args(args, tool.args_model.model_json_schema())
        tool.args_model.model_validate(coerced)


__all__ = [
    "AUTHORITATIVE_SIDE_EFFECTS",
    "DirectToolExecutor",
    "LedgerToolExecutor",
    "ToolExecutor",
]
