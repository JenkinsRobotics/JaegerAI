"""Replaceable execution boundary for validated agent tools.

The cognitive loop decides *which* declared tool to call.  The executor
decides *how* that call is performed.  Keeping those decisions separate
allows a host to substitute a sandbox, remote worker, audit wrapper, or
test double without changing the loop.

Enhanced with Hermes Agent pattern:
1. Resilient argument coercion & validation error recovery (prevents loop crashes on bad LLM args).
2. ContextVar suppression override for delegated worker/sub-agent execution.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Mapping, Protocol, runtime_checkable

from jaeger_agent.cognition.effects import EffectLedger
from jaeger_os.core.tools.tool_schema import ToolDef

logger = logging.getLogger(__name__)

# Tools whose bodies are authoritative external actions. A retry after a
# crash must not re-send; LedgerToolExecutor routes them through once().
AUTHORITATIVE_SIDE_EFFECTS = frozenset({"external"})

# ContextVar for worker thread and sub-agent post-tool hook suppression (from Hermes model_tools.py)
_post_tool_call_hook_suppressed: ContextVar[bool] = ContextVar(
    "post_tool_call_hook_suppressed", default=False
)


@contextmanager
def suppress_post_tool_call_hook():
    """Let an outer executor or sub-agent own the terminal post-tool event (Hermes pattern)."""
    token = _post_tool_call_hook_suppressed.set(True)
    try:
        yield
    finally:
        _post_tool_call_hook_suppressed.reset(token)


@runtime_checkable
class ToolExecutor(Protocol):
    """Execute one declared tool with untrusted model-supplied arguments."""

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any: ...


class DirectToolExecutor:
    """Compatibility adapter using ``ToolDef`` validation and dispatch."""

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        # ToolDef.dispatch owns coercion + validation. Exceptions deliberately
        # cross this replaceable boundary: JaegerAgent._execute_prepared turns
        # them into structured model feedback and can still distinguish a bad
        # argument from a permission denial or an indeterminate side effect.
        return tool.dispatch(dict(arguments))


class HookedToolExecutor:
    """Fire operator shell hooks around a tool call, with a real veto.

    Ported behaviour from hermes-agent's ``pre_tool_call`` / ``post_tool_call``
    events (MIT — Copyright (c) 2025 Nous Research), but implemented as a
    *wrapping executor* rather than as callbacks threaded through the loop.
    The donor has to dispatch from ~199 ``invoke_hook`` call sites because it
    has no execution seam; Jaeger has :class:`ToolExecutor`, so composing one
    more executor is both smaller and impossible to bypass — every tool call
    goes through an executor by construction.

    Compose it OUTSIDE the ledger::

        HookedToolExecutor(LedgerToolExecutor(ledger))

    That ordering is the point: a blocked call must never reach
    :meth:`EffectLedger.once`, or a veto would still burn the effect key and
    the retry after the operator fixes their hook would be refused as a
    duplicate.
    """

    def __init__(self, inner: ToolExecutor | None = None) -> None:
        self._inner = inner or DirectToolExecutor()

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        args = dict(arguments)
        from jaeger_agent import shell_hooks

        decision = shell_hooks.fire(
            "pre_tool_call", tool_name=tool.name, tool_input=args)
        if decision.blocked:
            logger.info("tool %r blocked by pre_tool_call hook: %s",
                        tool.name, decision.reason)
            # Shaped like every other tool failure so the model reads it as
            # feedback and can adapt. NOT retryable: the hook will refuse the
            # identical call again, and a retry loop against a deliberate
            # policy veto is just noise in the operator's logs.
            return {
                "ok": False,
                "success": False,
                "error": decision.reason or "blocked by policy hook",
                "error_type": "blocked_by_hook",
                "retryable": False,
            }

        result = self._inner.execute(tool, args)

        # post_tool_call is advisory: the effect already happened, so its
        # decision is discarded (shell_hooks logs if one tries to block).
        # Suppressed for delegated children so a sub-agent's inner calls do
        # not double-fire the operator's audit hook — same reasoning as the
        # ContextVar suppression above.
        if not _post_tool_call_hook_suppressed.get():
            shell_hooks.fire(
                "post_tool_call", tool_name=tool.name, tool_input=args,
                extra={"result_type": type(result).__name__},
            )
        return result


#: Tools whose bodies can change files on disk. A snapshot is taken before
#: the first of these in a turn. Mirrors the donor's trigger set
#: (``write_file``, ``patch``, ``terminal`` with destructive flags); Jaeger
#: names a few more because its file surface is wider.
MUTATING_TOOLS = frozenset({
    "write_file", "append_file", "patch", "delete_file", "move_file",
    "copy_file", "terminal", "remote_terminal", "execute_code",
    "run_in_venv", "install_package",
})


class CheckpointingToolExecutor:
    """Snapshot the working tree before the first file-mutating tool of a turn.

    Ported behaviour from hermes-agent ``tools/checkpoint_manager.py`` (MIT —
    Copyright (c) 2025 Nous Research). The donor triggers from inside its
    tool implementations; Jaeger has an execution seam, so the trigger lives
    here and cannot be forgotten when a new mutating tool is added — only the
    :data:`MUTATING_TOOLS` set needs updating.

    Composed INSIDE hooks and OUTSIDE the ledger::

        HookedToolExecutor(CheckpointingToolExecutor(LedgerToolExecutor(…)))

    Inside hooks because a call a policy hook is about to veto should not
    cost a snapshot. Outside the ledger for the same reason hooks are: the
    snapshot must happen before the effect is claimed.

    A snapshot failure never blocks the call — the checkpoint layer is a
    safety net, and a net that can stop work is worse than no net.
    """

    def __init__(self, inner: ToolExecutor | None = None) -> None:
        self._inner = inner or DirectToolExecutor()

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        if tool.name in MUTATING_TOOLS:
            try:
                from jaeger_agent import checkpoints
                from jaeger_agent.workspace import get_project_root

                root = get_project_root()
                if root is not None:
                    checkpoints.manager().ensure_checkpoint(
                        root, f"before {tool.name}")
            except Exception:  # noqa: BLE001 — never block the call
                logger.debug("checkpoint before %r skipped", tool.name,
                             exc_info=True)
        return self._inner.execute(tool, dict(arguments))


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

        # Resilient validation check (Hermes pattern)
        validation_error = self._validate(tool, args)
        if validation_error is not None:
            raise validation_error

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
    def _validate(tool: ToolDef, args: dict[str, Any]) -> Exception | None:
        """Coerce and validate before claiming an external side effect."""
        try:
            from jaeger_os.core.tools.arg_coercion import coerce_args
            coerced = coerce_args(args, tool.args_model.model_json_schema())
            tool.args_model.model_validate(coerced)
            return None
        except Exception as err:
            return err


__all__ = [
    "AUTHORITATIVE_SIDE_EFFECTS",
    "MUTATING_TOOLS",
    "CheckpointingToolExecutor",
    "DirectToolExecutor",
    "HookedToolExecutor",
    "LedgerToolExecutor",
    "ToolExecutor",
    "suppress_post_tool_call_hook",
]
