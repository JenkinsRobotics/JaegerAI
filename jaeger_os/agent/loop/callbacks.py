"""Agent-loop observability hooks.

Five callback surfaces, all optional. The TUI feeds the `┊` tool-activity
lines and the spinner off these; the latency log writes off ``step``; the
voice loop's interrupt UI listens on ``interrupt``. Keeping them as plain
callable fields (rather than an ABC) makes them composable — production
code can install several callbacks side-by-side without inheritance.

For hardware deployments this is the seam: the operator's safety UI on a
humanoid would wire ``tool_progress`` to surface dangerous-tool dispatch
in real time; a UAV's flight-deck display would wire ``step`` to its
telemetry channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from jaeger_os.agent.schemas.message_types import Message


@dataclass
class AgentCallbacks:
    """Optional hooks fired by ``JaegerAgent`` at well-defined points
    in the loop. Every field defaults to ``None``; the agent checks
    ``is not None`` before invoking."""

    # Tool dispatch — phase ∈ {"start", "complete", "error"}, ``data``
    # is the args (start), the result (complete), or the exception (error).
    tool_progress: Callable[[str, str, Any], None] | None = None

    # Reasoning / thinking signal from models that emit it (Anthropic
    # extended thinking, Hermes-style ``<think>`` blocks). ``state`` is
    # an opaque string the adapter decides — typically the text so far.
    thinking: Callable[[str], None] | None = None

    # Per-token streaming. Off by default in v1; adapters that support
    # streaming fire this if the callback is installed.
    stream_delta: Callable[[str], None] | None = None

    # Per-turn step. ``index`` is the agent-loop iteration count,
    # ``message`` is the assistant's response that just landed.
    step: Callable[[int, Message], None] | None = None

    # Fired exactly once when the agent observes its interrupt event
    # and bails out of the loop. The voice loop / TUI use this to know
    # the cancel actually took effect (vs. the model finishing before
    # the cancel was checked).
    interrupt: Callable[[], None] | None = None

    # Pre-dispatch hook. Fired immediately before each tool call; the
    # return value (a ``str | None``) is appended to the dispatched
    # result so the model sees guidance on the next turn — that's the
    # surface ``core/tool_guardrails.ToolGuardrail`` hooks into to warn
    # one step before the loop backstop trips. Return ``None`` for no
    # injection.
    before_tool_call: Callable[[str, dict[str, Any]], str | None] | None = None

    # Post-dispatch hook. Fired immediately after each tool call lands
    # but before the result is appended to ``messages``. The handler
    # may return a modified ``content`` (any JSON-serialisable value)
    # to replace the original — used by
    # ``core/tool_result_budget.TurnResultBudget`` to persist oversized
    # payloads to disk and substitute a pointer. Return ``None`` to
    # leave the result untouched.
    after_tool_call: Callable[[str, dict[str, Any], Any], Any] | None = None

    # Observer hook — fired once per tool call after dispatch + any
    # after_tool_call rewrites have settled, with the data needed to
    # persist a tool-call audit row. Distinct from ``tool_progress``
    # (which carries only the elapsed_s preview) and ``after_tool_call``
    # (which can mutate the result): this one is a passive observer
    # used by the memory layer to write the ``tool_calls`` table.
    # ``ok`` reflects the final content (False if the result is a
    # ``{"ok": False, ...}`` dict OR the dispatch raised).
    tool_done: (
        Callable[[str, dict[str, Any], Any, bool, str | None, float], None] | None
    ) = None

    # Phase-8 liveness: fired on every ``interruptible_call`` poll tick
    # (~10 Hz by default) while a model call is in flight. ``elapsed_s``
    # is wall-clock seconds since the call started. TUI status bars
    # read this to surface "still waiting (12.4 s)…" instead of
    # appearing frozen; gateway watchdogs use it to keep their
    # inactivity timers paused during long generations.
    heartbeat: Callable[[float], None] | None = None

    # ── safe-invocation helpers ──────────────────────────────────────
    # Always call these from the agent loop rather than reaching for the
    # field directly: they no-op on missing callbacks and swallow handler
    # exceptions so a buggy observer never breaks the turn.

    def on_tool_progress(self, name: str, phase: str, data: Any) -> None:
        if self.tool_progress is None:
            return
        try:
            self.tool_progress(name, phase, data)
        except Exception:  # noqa: BLE001 — callback must never break the turn
            pass

    def on_thinking(self, state: str) -> None:
        if self.thinking is None:
            return
        try:
            self.thinking(state)
        except Exception:  # noqa: BLE001
            pass

    def on_stream_delta(self, token: str) -> None:
        if self.stream_delta is None:
            return
        try:
            self.stream_delta(token)
        except Exception:  # noqa: BLE001
            pass

    def on_step(self, index: int, message: Message) -> None:
        if self.step is None:
            return
        try:
            self.step(index, message)
        except Exception:  # noqa: BLE001
            pass

    def on_interrupt(self) -> None:
        if self.interrupt is None:
            return
        try:
            self.interrupt()
        except Exception:  # noqa: BLE001
            pass

    def on_before_tool_call(
        self, name: str, args: dict[str, Any],
    ) -> str | None:
        """Return guidance text to inject into the tool result, or
        ``None``. Exceptions are swallowed — a buggy guardrail must
        never crash a turn."""
        if self.before_tool_call is None:
            return None
        try:
            return self.before_tool_call(name, args)
        except Exception:  # noqa: BLE001
            return None

    def on_after_tool_call(
        self, name: str, args: dict[str, Any], result: Any,
    ) -> Any:
        """Return a modified result or ``None`` to keep the original.
        Returning ``None`` is the no-op path — callers should return
        the original value explicitly when they want to override with
        a literal ``None``."""
        if self.after_tool_call is None:
            return None
        try:
            return self.after_tool_call(name, args, result)
        except Exception:  # noqa: BLE001
            return None

    def on_heartbeat(self, elapsed_s: float) -> None:
        """Liveness tick — fires while a model call is in flight."""
        if self.heartbeat is None:
            return
        try:
            self.heartbeat(elapsed_s)
        except Exception:  # noqa: BLE001
            pass

    def on_tool_done(
        self,
        name: str,
        args: dict[str, Any],
        result: Any,
        ok: bool,
        error: str | None,
        elapsed_s: float,
    ) -> None:
        """Passive observer — fires after dispatch settles. The memory
        layer uses this to persist a ``tool_calls`` row."""
        if self.tool_done is None:
            return
        try:
            self.tool_done(name, args, result, ok, error, elapsed_s)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["AgentCallbacks"]
