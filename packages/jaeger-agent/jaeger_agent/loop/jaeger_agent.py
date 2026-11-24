"""``JaegerAgent`` — the agent loop, framework-free.

Phase-2 shape: the real ``format → call → parse → dispatch`` loop runs
here. ``run_turn`` drives one user message to a final assistant text,
dispatching tool calls along the way through the registered ``ToolDef``
contracts. The adapter owns wire-format translation and the actual model
call; the agent owns the loop, the budget, the cancel flag, the halt
backstop, and the observability hooks.

The agent is *stateful per turn*: ``self.messages`` is the running
conversation, ``self._interrupt_event`` is the cancel signal, and the
two signature-count dicts are the loop backstops. Multi-instance use
(deep think, voice loop, scheduled tasks each holding their own
conversation) is the design assumption — every running context
constructs its own ``JaegerAgent``.
"""

from __future__ import annotations

import json
import logging
import re as _re
import threading
import time
from typing import Any

from typing import Callable

logger = logging.getLogger(__name__)

from jaeger_agent.adapters.base import ProviderAdapter
from jaeger_agent.core.cancellation import bind_turn_cancellation, current_cancellation
from jaeger_agent.loop.callbacks import AgentCallbacks
from jaeger_agent.loop.interrupt import AgentInterrupted, StaleCallTimeout
from jaeger_agent.loop.loop_backstop import (
    MAX_TOOL_CALLS,
    call_signature,
    collapse_generated_repetition,
    loop_halt_reason,
    loop_warning,
    semantic_failure_signature,
    tool_budget_warning,
)
from jaeger_agent.loop.tool_result_safety import protect_tool_result
from jaeger_agent.loop.turn_budget import TurnBudget, TurnBudgetLimits
from jaeger_agent.loop.tool_dispatch_safety import (
    cancelled_tool_result, paths_overlap, unique_tool_call_ids,
)
from jaeger_agent.schemas.message_types import Message, ToolCall
from jaeger_agent.tool_executor import ToolExecutor
from jaeger_agent.skill_registry.tool_selection import ToolSelection, in_agent_selection, tool_permitted
from jaeger_os.core.tools.tool_registry import get_tools
from jaeger_os.core.tools.tool_schema import ToolDef, dev_mode_enabled, tool_result_failed
from jaeger_agent.util.context_guard import ContextGuard, ContextOverflow


# Type alias for the skip-final finalizer. Takes the tool name, the
# tool result, and the user message that triggered the turn; returns
# the final assistant text. The default formatter does a one-line JSON
# dump — callers (eventually ``main.py``) install a bounded model call
# here so the answer reads as a natural sentence.
SkipFinalFinalizer = Callable[[str, "object", str], str]
ToolsetResolver = Callable[[set[str]], set[str]]


def _default_tool_executor() -> ToolExecutor:
    """Ledger-backed executor is the production composition.

    SQLite when the instance store is bound; an in-memory ledger
    otherwise so tests and embedders still get at-most-once within
    the process without requiring a database.
    """
    from jaeger_agent.cognition.effects import InMemoryEffectLedger
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.tool_executor import (
        CheckpointingToolExecutor, DirectToolExecutor, HookedToolExecutor,
        LedgerToolExecutor,
    )

    if sqlite_store.is_bound():
        from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
        ledger: Any = SqliteEffectLedger()
    else:
        ledger = InMemoryEffectLedger()
    # Hooks wrap the ledger, never the reverse: a pre_tool_call veto has to
    # stop the call BEFORE ``EffectLedger.once`` claims its key, or the block
    # would burn that key and the retry after the operator fixes their hook
    # would come back as a duplicate instead of running.
    #
    # Zero cost when unconfigured — ``shell_hooks.fire`` returns immediately
    # unless the instance config enables hooks.
    # hooks → checkpoints → ledger → direct.
    #   hooks outermost   : a vetoed call costs neither a snapshot nor a key
    #   checkpoints next  : the snapshot must precede the effect
    #   ledger innermost  : at-most-once wraps only the real execution
    # Both new layers are inert unless enabled in the instance config.
    return HookedToolExecutor(
        CheckpointingToolExecutor(
            LedgerToolExecutor(ledger, DirectToolExecutor())))


def _open_or_create_run(agent: "JaegerAgent") -> str:
    """Ephemeral run id for this agent instance.

    Persistence is ``TurnExecutive``'s job: the loop must not import
    SQLite. A host that binds a run before ``run_turn`` keeps that id
    across turns, retries and provider swaps.
    """
    from jaeger_agent.cognition.runs import new_id
    return new_id()
ToolVisibility = Callable[[str], bool]
TurnStartHook = Callable[[], None]


# ── module-owned defaults ────────────────────────────────────────────
#
# Resolved lazily, not imported at module scope: tool_bundles imports
# toolset_scoping, tools.files imports the workspace, and the loop is
# imported by all of them. Doing it at call time keeps that graph
# acyclic without anyone having to remember the order.
#
# Each returns None if its piece is unavailable, so a partial install
# degrades to "no scoping" rather than failing to construct an agent.


def _default_toolset_resolver() -> ToolsetResolver | None:
    try:
        from jaeger_agent.schemas.tool_bundles import resolve_toolsets
    except Exception:  # noqa: BLE001 — scoping is optional, an agent is not
        return None
    return resolve_toolsets


def _default_tool_visibility() -> ToolVisibility | None:
    try:
        from jaeger_agent.skill_registry.toolset_scoping import tool_visible
    except Exception:  # noqa: BLE001
        return None
    return tool_visible


def _default_turn_start_hook() -> TurnStartHook | None:
    """The per-turn file-read tracker — ONLY if the file tools are loaded.

    Deliberately reads ``sys.modules`` instead of importing. Importing
    ``jaeger_agent.tools.files`` runs the ``jaeger_agent.tools`` package
    ``__init__``, which registers all ~96 built-in tools as a side
    effect — so an earlier version of this function turned every
    ``JaegerAgent(...)`` into a fully armed agent whether the caller
    wanted tools or not. A chat demo with no tools blew its 4096-token
    window on a tool catalogue it never asked for.

    An app that wants the built-ins imports ``jaeger_agent.tools``; then
    this finds it and wires up. An app that doesn't gets a bare loop,
    which is what it asked for.
    """
    import sys

    module = sys.modules.get("jaeger_agent.tools.files")
    return getattr(module, "reset_read_tracker", None) if module else None




def _policy_blocks_model(exc: BaseException) -> bool:
    return type(exc).__name__ == "ModelPolicyError" or "ModelPolicyError" in f"{type(exc).__name__}: {exc}"


def _local_adapter_url(adapter: Any) -> str:
    return str(getattr(adapter, "base_url", "") or "")


def _fallback_reachable(adapter: Any) -> bool:
    """Skip a fallback that is obviously down (local Ollama with nothing listening)."""
    url = _local_adapter_url(adapter).lower()
    local = any(token in url for token in ("127.0.0.1", "localhost", "0.0.0.0", "::1"))
    if not local:
        return True
    health = getattr(adapter, "health_check", None)
    if not callable(health):
        return True
    try:
        result = health()
    except Exception:
        return False
    return bool(isinstance(result, dict) and result.get("ok", True))


def _emit_fallback(adapters: list[Any], failed: Any, reason: str) -> None:
    """Report walking the adapter chain (or running out of it)."""
    from jaeger_agent import live as _live
    try:
        nxt = adapters[adapters.index(failed) + 1]
    except (ValueError, IndexError):
        nxt = None
    _live.emit("reliability.fallback" if nxt is not None else "reliability.exhausted", {
        "from": failed.describe() if hasattr(failed, "describe") else type(failed).__name__,
        "to": (nxt.describe() if hasattr(nxt, "describe") else type(nxt).__name__) if nxt is not None else None,
        "reason": reason,
    })

def _model_identity(adapter: Any, raw: Any) -> dict[str, str]:
    """Configured model/provider of ``adapter`` and, when the response says,
    the model that actually answered. Strings only; never prompt content."""
    out: dict[str, str] = {}
    route = getattr(adapter, "route", None)
    receipt = route.receipt() if callable(getattr(route, "receipt", None)) else None
    if isinstance(receipt, dict):  # governed call: the routing decision itself
        for key, name in (("model", "model"), ("provider", "provider"), ("location", "location"),
                          ("reason", "route_reason")):
            if receipt.get(key):
                out[name] = str(receipt[key])[:120]
    model = out.get("model") or next((v for a in ("model", "model_name", "model_id", "backend_id")
                  if isinstance(v := getattr(adapter, a, None), str) and v), None)
    if model:
        out["model"] = str(model)[:120]
    provider = next((v for a in ("provider", "provider_name", "provider_id")
                     if isinstance(v := getattr(adapter, a, None), str) and v), None)
    provider = out.get("provider") or provider
    if not provider:
        kind = type(adapter).__name__.replace("BackendAdapter", "").replace("Adapter", "")
        provider = kind.lower() or "model"
    out["provider"] = str(provider)[:80]
    actual = raw.get("model") if isinstance(raw, dict) else getattr(raw, "model", None)
    if isinstance(actual, str) and actual:
        out["actual_model"] = actual[:120]
    return out

from .provider_step import AgentProviderStepMixin
from .tool_dispatch import AgentToolDispatchMixin


class JaegerAgent(AgentProviderStepMixin, AgentToolDispatchMixin):
    """One agent — one adapter (with optional fallbacks), one
    conversation, one cancel flag. Build a fresh instance per logical
    context."""

    def __init__(
        self,
        adapter: ProviderAdapter,
        *,
        fallback_adapters: list[ProviderAdapter] | None = None,
        system_prompt: str = "",
        tools: list[ToolDef] | None = None,
        toolsets: set[str] | frozenset[str] | list[str] | None = None,
        max_iterations: int = 50,
        callbacks: AgentCallbacks | None = None,
        skip_final_tools: set[str] | frozenset[str] | None = None,
        skip_final_finalizer: SkipFinalFinalizer | None = None,
        context_guard: "ContextGuard | None" = None,
        toolset_resolver: ToolsetResolver | None = None,
        tool_visibility: ToolVisibility | None = None,
        turn_start_hook: TurnStartHook | None = None,
        tool_executor: ToolExecutor | None = None,
        turn_budget_limits: TurnBudgetLimits | None = None,
        scope_tools: bool | None = None,
    ) -> None:
        self.primary_adapter = adapter
        self.fallback_adapters: list[ProviderAdapter] = list(fallback_adapters or [])
        self.system_prompt = system_prompt
        from jaeger_agent.tool_executor import active_tool_allowlist
        self.allowed_tools = active_tool_allowlist()
        if self.allowed_tools is not None:
            tools = [tool for tool in (tools if tools is not None else get_tools())
                     if tool.name in self.allowed_tools]
        # Tool selection precedence:
        #   1. explicit ``tools=`` list  — caller picks exact ToolDefs
        #   2. ``toolsets={...}`` set    — pick by category; resolve to names
        #   3. neither → every tool in the registry (legacy default)
        # Toolsets are the Hermes-style pattern that keeps per-turn
        # context tight: only the relevant ~10 tools land in the
        # model's schema, not all 80.
        # ``_all_tools`` holds the FULL registered set the agent can
        # dispatch + validate against. ``tools`` (the property below)
        # filters this per access through :func:`tool_visible` so a
        # mid-session ``load_tools`` call expands what the model sees
        # on the very next turn — without rebuilding the agent.
        # Beta gating: tools marked ``beta=True`` (still stabilising —
        # avatar / animation while Mochi is the testbed) are excluded
        # from the catalogue entirely unless dev mode is on, so a
        # half-tested tool can't break a daily-driver session. An
        # explicit ``tools=[...]`` list bypasses the gate — the caller
        # picked those ToolDefs deliberately.
        # These three used to be injected by a JaegerAI subclass, back
        # when the toolset bundles, the visibility gate and the per-turn
        # file tracker were all application code. 0.11 moved them into
        # this package, so the subclass was injecting the module into
        # itself — an embedder that skipped it silently lost toolset
        # scoping. They default to the module's own now; pass an
        # explicit value to override, or ``False`` to opt out entirely.
        self._toolset_resolver = (
            _default_toolset_resolver() if toolset_resolver is None else toolset_resolver
        )
        self._tool_visibility = (
            _default_tool_visibility() if tool_visibility is None else tool_visibility
        )
        self._turn_start_hook = (
            _default_turn_start_hook() if turn_start_hook is None else turn_start_hook
        )
        for attr in ("_toolset_resolver", "_tool_visibility", "_turn_start_hook"):
            if getattr(self, attr) is False:
                setattr(self, attr, None)
        if tools is not None:
            self._all_tools: list[ToolDef] = list(tools)
            self._tools_filter_locked = True   # explicit list = caller knows best
            self._tools_filter_locked_reason = "allowlist"
        elif toolsets is not None:
            if self._toolset_resolver is None:
                raise ValueError(
                    "toolsets require a toolset_resolver supplied by the host application"
                )
            wanted = self._toolset_resolver(set(toolsets))
            self._all_tools = _filter_available_tools(
                [t for t in get_tools() if t.name in wanted]
            )
            self._tools_filter_locked = False
            self._tools_filter_locked_reason = None
        else:
            self._all_tools = _filter_available_tools(get_tools())
            self._tools_filter_locked = False
            self._tools_filter_locked_reason = None
        # Per-agent dispatch map. ``_dispatch_one_tool`` previously
        # resolved by name against the *global* registry — so an agent
        # built with ``tools=[a, b, c]`` (an explicit allowlist) would
        # still happily dispatch any other globally registered tool
        # the model named. Building the map from ``_all_tools`` here
        # binds dispatch to the agent's *intended* set.
        # The map is rebuilt at the top of every turn (see
        # ``_refresh_tool_catalog``) so tools registered mid-session
        # become dispatchable without rebuilding the agent.
        self._dispatch_by_name: dict[str, ToolDef] = {
            t.name: t for t in self._all_tools
        }
        # Per-agent, monotonically growing intent-selected surface. Unlike
        # the legacy module-level active set, this cannot leak one session's
        # privileged tool choices into another concurrent agent.
        self._tool_selection = ToolSelection(scoped=scope_tools,
            grant=self.allowed_tools,
            restricted=frozenset(t.name for t in self._all_tools) if self._tools_filter_locked or toolsets is not None else None)
        # Record the originally-requested toolset names for diagnostics
        # (the ``/runtime`` panel surfaces this); not used by the loop.
        self.toolsets: frozenset[str] = frozenset(toolsets or ())
        self.max_iterations = int(max_iterations)
        self.turn_budget = TurnBudget(turn_budget_limits or TurnBudgetLimits(
            max_tool_calls=MAX_TOOL_CALLS,
            max_iterations=self.max_iterations,
        ))
        self.callbacks = callbacks or AgentCallbacks()
        self._run_id: str | None = None
        #: Set when an adapter streams reasoning for the current step, so the
        #: post-step fallback does not repeat what was already sent.
        self._streamed_reasoning = False
        self._effect_checkpoint: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None
        self._tool_executor: ToolExecutor = tool_executor or _default_tool_executor()
        if self.allowed_tools is not None:
            from jaeger_agent.tool_executor import AllowlistToolExecutor
            self._tool_executor = AllowlistToolExecutor(self._tool_executor, self.allowed_tools)

        # Skip-final: tools whose dict result IS the answer (``get_time``,
        # ``recall``, ``calculate``, …). When the turn's first model
        # response is a single tool call to one of these, the loop
        # dispatches the tool, calls the finalizer to phrase the result,
        # and returns — bypassing the second model call entirely. Saves
        # 1-3 seconds per qualifying turn.
        self.skip_final_tools: frozenset[str] = frozenset(skip_final_tools or ())
        self.skip_final_finalizer: SkipFinalFinalizer = (
            skip_final_finalizer or _default_skip_final_finalizer
        )

        # Pre-flight context guardrail. The loop hands every prompt to
        # ``guard.trim_to_fit`` before formatting, so an overflow is
        # caught here rather than as a hard error from the server. A
        # None default disables the guard (legacy callers / tests).
        self.context_guard: ContextGuard | None = context_guard

        # Mid-turn steering (Hermes ``/steer`` pattern): user text that
        # arrives WHILE a turn is running queues here and is injected as
        # a real user message before the next model step — guidance
        # lands without killing the in-flight work. Survives across
        # turns: a steer that misses the last model step of one turn
        # delivers at the top of the next.
        self._steer_queue: list[str] = []
        self._steer_lock = threading.Lock()
        self._turn_active = False

        # Running state — fresh per agent, never reused across instances.
        self.messages: list[Message] = []
        # The Message objects appended during the CURRENT turn, in
        # order. Tracked by object (not index) because the context
        # guard can rebind ``self.messages`` to a head-trimmed copy
        # mid-turn — an index recorded at turn start goes stale the
        # moment that happens. ``runtime_bridge.drive_one_turn`` reads
        # ``last_turn_messages`` for the per-turn slice.
        self._turn_messages: list[Message] = []
        self._interrupt_event = threading.Event()
        # Externally owned cancel signal (e.g. a host's per-request scope).
        # Never cleared by this loop — see bind_cancel_signal.
        self._cancel_signal: threading.Event | None = None

        # Loop-backstop counters. Reset at the start of every turn so a
        # spinning previous turn can't carry over and trip the new one.
        self._call_signature_counts: dict[str, int] = {}
        self._failure_signature_counts: dict[str, int] = {}
        # (tool, path) → first error line, for file mutations that
        # failed and were never superseded by a later success on the
        # same target. Drives the verifier footer on the final answer.
        self._failed_mutations: dict[tuple[str, str], str] = {}
        # Last result hash per call signature, for READ tools only.
        # Identical read calls whose results CHANGE are legitimate
        # polling (``check_background`` every few seconds) — only a
        # repeat with the SAME result counts toward the identical-call
        # halt. Write-side tools keep the strict pre-dispatch count.
        self._read_result_hashes: dict[str, str] = {}
        # Conservative cross-iteration cache for immutable-looking metadata
        # reads. Any write/external call invalidates it. Polling/status tools
        # are deliberately absent so changing state is still observed.
        self._read_result_cache: dict[str, Any] = {}
        self._turn_skill_names: set[str] = set()
        self._turn_tool_names: list[str] = []
        self.last_skill_route: dict[str, Any] | None = None
        self._tool_budget_warning_used = False
        self._pending_nudge_text: str | None = None

        # Diagnostic surface — populated by the most recent ``run_turn``.
        # ``last_halt_reason`` is None on a clean finish; a string when
        # the backstop or interrupt cut the loop short.
        self.last_halt_reason: str | None = None
        #: Set when an input/output guardrail tripped this turn (jaeger_agent.guardrails).
        self.last_guardrail: dict[str, str] | None = None
        self.last_iteration_count: int = 0
        # Phase-8 liveness: wall-clock timestamp of the most recent
        # observed progress — set on every heartbeat tick during a
        # model call, and on every tool dispatch. The TUI / gateway
        # uses this for "still working?" checks.
        self.last_activity_ts: float = 0.0
        self.last_activity_desc: str = "idle"
        # ``True`` when the most recent turn short-circuited via
        # skip-final. The TUI / latency log uses this to colour the
        # status bar and distinguish fast-finalised turns from full
        # multi-iteration turns.
        self.last_skip_final: bool = False

        # Token usage accumulator — refreshed on every successful
        # adapter call within a turn. The bench reads
        # ``last_prompt_tokens`` + ``last_completion_tokens`` to
        # compute real tokens/sec (vs the whitespace-split estimate
        # in summarise()). Each adapter that exposes ``usage`` on
        # its raw response (OpenAI-shape, llama-cpp, Anthropic)
        # contributes; adapters without usage info just don't add to
        # the totals. Reset to 0 at the start of every ``run_turn``.
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0
        # Real time-to-first-token of the turn's FIRST model call (the
        # routing decision — the latency the operator feels in voice).
        # None when no adapter reported one.
        self.last_ttft_s: float | None = None

    # ── tool visibility ─────────────────────────────────────────────

    @property
    @in_agent_selection
    def tools(self) -> list[ToolDef]:
        """The tools visible to the model THIS turn.

        Recomputed on every access so a mid-session ``load_tools``
        call (which mutates the shared visibility state in
        :mod:`jaeger_agent.skill_registry.toolset_scoping`) takes effect on the
        next turn without rebuilding the agent. The full set the agent
        can dispatch + validate against lives in ``self._all_tools`` —
        ``describe_tool`` reads from there so the model can peek at a
        hidden tool's schema without loading the whole category."""
        if self._tools_filter_locked:
            # Caller passed ``tools=[...]`` explicitly — honour it.
            visible = list(self._all_tools)
            if self._tools_filter_locked_reason == "overflow":
                existing = {tool.name for tool in visible}
                visible.extend(tool for tool in _filter_available_tools(get_tools())
                               if tool.name in self._tool_selection.names and tool.name not in existing)
        elif self._tool_visibility is None:
            visible = list(self._all_tools)
        else:
            visible = [t for t in self._all_tools
                       if t.name in self._tool_selection.inferred or self._tool_visibility(t.name)]

        visible = [t for t in visible if tool_permitted(t.name)]

        # Final-output speech in a multimodal face is a typed response channel,
        # not an agent tool. Exclude both current and legacy spellings even from
        # an explicit tool list so no adapter can send those schemas to the
        # model while the self-contained engine owns output.
        try:
            from jaeger_agent.core.outputs import multimodal_output_active

            if multimodal_output_active():
                visible = [
                    tool
                    for tool in visible
                    if tool.name not in {"text_to_speech", "speak"}
                ]
        except Exception:  # noqa: BLE001 — tool presentation must stay safe
            pass
        if self._tool_selection.scoped and not self._tools_filter_locked and self.context_guard:
            from jaeger_agent.skill_registry.tool_selection import budget_visible_tools
            visible = budget_visible_tools(
                visible, self._tool_selection, self.context_guard, self.system_prompt,
                getattr(self, '_tool_route_query', ''),
            )
        return visible

    @property
    def all_tools(self) -> list[ToolDef]:
        """Every tool the agent can dispatch — including ones currently
        hidden from the model. Used by ``describe_tool`` + by the
        loop-backstop's "did you mean…?" suggestions."""
        return list(self._all_tools)

    # ── public surface ──────────────────────────────────────────────

    @property
    def run_id(self) -> str | None:
        """Durable id of the run this agent is currently discharging."""
        return self._run_id

    def bind_run(self, run_id: str | None) -> None:
        """Attach this agent to an existing run (resume / host-owned)."""
        self._run_id = run_id
        binder = getattr(self._tool_executor, "bind_run", None)
        if callable(binder):
            binder(run_id)

    def set_effect_checkpoint(
        self, fn: Callable[[str, dict[str, Any], dict[str, Any]], None] | None
    ) -> None:
        """Called after each non-read tool result is appended.

        The callback receives the finalized, JSON-safe transcript message so
        a crash mid-turn does not lose evidence of a completed mutation. The
        executive owns the durable write.
        """
        self._effect_checkpoint = fn

    def _emit_streamed_reasoning(self, chunk: str) -> None:
        """Forward one reasoning delta and remember that we did.

        The flag is what keeps the post-step fallback from emitting the same
        deliberation a second time once the adapter has already streamed it.
        """
        self._streamed_reasoning = True
        self.callbacks.on_reasoning(chunk)

    def _bind_turn_run(self) -> None:
        if self._run_id is None:
            self._ephemeral_run = True
            self.bind_run(_open_or_create_run(self))
        else:
            self._ephemeral_run = False

    @bind_turn_cancellation
    @in_agent_selection
    def run_turn(self, user_message: str, *, content: Any = None) -> str:
        """Run one conversational turn end-to-end.

        Appends the user message, then loops:

          1. Format the conversation through the adapter.
          2. Call the model (interruptibly).
          3. Parse the response into an internal ``Message``.
          4. Append the assistant message.
          5. If no tool calls, return its text — turn done.
          6. Otherwise dispatch each tool call, append a tool result,
             then loop.

        Stops cleanly on cancel (``AgentInterrupted``), on the loop
        backstop (identical-call / semantic-failure / runaway-total),
        on ``max_iterations``, or when the model returns a turn with no
        tool calls.

        **Exception contract.** ``self.messages`` is left well-formed
        on EVERY exit path — including raises. A transcript with a
        dangling assistant ``tool_calls`` (no matching tool results)
        or an orphaned user message makes cloud providers 400 on every
        subsequent call, turning one bad turn into a permanently mute
        session. So:

          * pre-flight :class:`ContextOverflow` (nothing reached the
            model yet) rolls the user message back off the history and
            re-raises — the caller surfaces it, the next turn starts
            from the pre-turn transcript;
          * mid-turn ``ContextOverflow`` degrades to a clean halt —
            un-dispatched tool calls get synthetic "not executed"
            results, an explanatory assistant message is appended, and
            its text is returned (no raise);
          * any other exception repairs the transcript the same way,
            appends a ``[turn failed: …]`` assistant note, then
            re-raises for the caller to surface.
        """
        # Route against the admitted request, never recalled instructions
        # inside the host's background envelope.
        from jaeger_agent.task_port import current_task_context
        task_context = current_task_context() or {}
        route_query = str(task_context.get('user_text', user_message))
        self._tool_route_query = route_query
        self.__dict__.setdefault('_skill_route_query', route_query)
        # Tool discovery is explicit.  The model starts with the stable core
        # surface and may inspect/load named groups through the meta-tools.
        # User wording must never silently widen authority or mutate the
        # model-visible schema before its first decision.
        self._select_named_tools(route_query)

        # Fresh per-turn state. Counters from a previous turn would
        # falsely trip the backstop on the second message of a session.
        self._call_signature_counts.clear()
        self._failure_signature_counts.clear()
        self._read_result_hashes.clear()
        self._read_result_cache.clear()
        if current_cancellation() is None:
            self._interrupt_event.clear()
            if self._cancel_signal is not None and self._cancel_signal.is_set():
                # Cancelled before this turn started: the per-turn reset above
                # must not swallow a signal the host owns.
                self._interrupt_event.set()
        self._turn_messages = []
        self._post_tool_nudge_used = False
        self._nudge_pending = False
        self._pending_nudge_text = None
        self._turn_skill_names.clear()
        self._turn_tool_names.clear()
        self.last_skill_route = None
        self._tool_budget_warning_used = False
        self._failed_mutations.clear()
        self.last_halt_reason = None
        self.last_iteration_count = 0
        self.last_skip_final = False
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_ttft_s = None
        self.turn_budget.reset()

        # Pick up tools registered since construction (a skill
        # activated mid-session) so they're visible AND dispatchable
        # without rebuilding the agent. No-op for explicit ``tools=``
        # agents.
        # Overflow slim-to-CORE is emergency for one turn only; allowlist
        # locks stay. Otherwise non-CORE tools stay unknown forever.
        if getattr(self, "_tools_filter_locked_reason", None) == "overflow":
            self._tools_filter_locked = False
            self._tools_filter_locked_reason = None
            self._overflow_tools_slimmed = False
        self._refresh_tool_catalog()
        self._bind_turn_run()

        # Per-turn dedupe trackers in tool modules (file_read's
        # "unchanged since last read" suppression in particular). The
        # legacy pydantic-ai loop reset this implicitly via its own
        # turn lifecycle; Phase-9 has to do it here or a *legitimate*
        # next-turn read of the same file returns an empty-stub result.
        if self._turn_start_hook is not None:
            try:
                self._turn_start_hook()
            except Exception:  # noqa: BLE001 — a host hook must not break a turn
                pass

        from jaeger_agent import guardrails as _guardrails
        self.last_guardrail = None
        tripped = _guardrails.run("input", route_query)
        if tripped is not None:
            # Input guardrail tripwire (OpenAI Agents SDK semantics): the
            # agent does no work on this input; the turn ends with a notice.
            self.last_guardrail = {"stage": "input", "guardrail": tripped.guardrail, "reason": tripped.reason}
            note = _guardrails.refusal("input", tripped)
            self._append_message({"role": "user", "content": user_message})
            self._append_message({"role": "assistant", "content": note})
            return note
        model_user_message = user_message if content is None else content
        self._append_message({"role": "user", "content": model_user_message})
        self._turn_active = True
        self._thinking_boost_count = 0
        from jaeger_loop import TaskConvergenceController
        self._convergence = TaskConvergenceController(user_message)
        try:
            return self._guard_output(self._run_turn_inner(user_message))
        except ContextOverflow:
            # Try middle-out trajectory compression before giving up or re-raising
            try:
                from jaeger_agent.util.trajectory_compressor import compress_trajectory_if_needed
                compressed = compress_trajectory_if_needed(self.messages)
                if len(compressed) < len(self.messages):
                    self.messages = compressed
                    # Retry inner turn once with compressed context; the
                    # output guardrail applies to the retried answer too.
                    return self._guard_output(self._run_turn_inner(user_message))
            except Exception:
                pass

            if len(self._turn_messages) <= 1:
                # Pre-flight refusal — often the FULL tool-schema JSON alone
                # exceeds a small local model's usable prompt room (~34k
                # tokens with every toolset active). Slim to CORE once and
                # retry before rolling the user message back.
                if self._slim_tools_to_core_for_overflow():
                    try:
                        self.callbacks.on_thinking(
                            "[context-guard] slimmed tool schemas to CORE to fit ctx budget"
                        )
                    except Exception:
                        pass
                    return self._guard_output(self._run_turn_inner(user_message))
                # Roll the user message back so a too-big prompt isn't
                # sticky: with it left in place, every later turn
                # re-fails on the same un-trimmable history.
                self._pop_message()
                raise
            # Mid-turn: tool results already landed, the in-flight turn
            # itself outgrew the window. Halt cleanly instead of
            # raising — side effects happened, the operator deserves an
            # answer that says so rather than a backtrace.
            self._discard_pending_nudge()
            self._close_dangling_tool_calls("context overflow mid-turn")
            self.last_halt_reason = "context_overflow"
            note = (
                "[I had to stop mid-task: the conversation plus tool "
                "results no longer fit the model's context window. "
                "The work done so far is recorded above.]"
            )
            self._append_message({"role": "assistant", "content": note})
            return note
        except AgentInterrupted:
            # Belt-and-braces: ``_one_model_step`` converts interrupts
            # to a halt internally, but a stray raise (custom adapter)
            # must not leave the transcript broken.
            self.last_halt_reason = "interrupted"
            return self._halt_turn()
        except Exception as exc:
            # Adapter chain exhausted, dispatch-layer crash, anything
            # unexpected: repair the transcript so the NEXT turn can
            # format cleanly, leave a visible failure note, then let
            # the caller surface the error.
            self._discard_pending_nudge()
            self._close_dangling_tool_calls(
                f"turn failed ({type(exc).__name__})"
            )
            if self.last_halt_reason is None:
                self.last_halt_reason = f"error: {type(exc).__name__}"
            note = f"[turn failed: {type(exc).__name__}: {exc}]"
            self._append_message({"role": "assistant", "content": note[:500]})
            raise
        finally:
            self._turn_active = False
            self._thinking_budget_boosted = False
            self._thinking_boost_count = 0
            self._thinking_effort_override = None
            if getattr(self, "_convergence", None) is not None:
                self._convergence.reset()
            self._record_skill_outcomes()
            if getattr(self, "_ephemeral_run", False):
                self.bind_run(None)

    def _select_named_tools(self, route_query: str) -> None:
        """A tool the owner names exactly (``mcp__rea__inspect_plist``) is
        selected for the session, even from a gated MCP server: naming it is
        the explicit opt-in (Claude Code: an MCP tool named in the prompt is
        loaded by tool search). Never for untrusted content, never past an
        explicit ``tools=[...]`` allowlist or the permission filter."""
        if self._tools_filter_locked or not route_query or "_" not in route_query:
            return
        try:
            from jaeger_agent.skill_registry.toolset_scoping import is_untrusted_content
            if is_untrusted_content():
                return
        except Exception:  # noqa: BLE001
            return
        import re as _re
        words = set(_re.findall(r"[A-Za-z][A-Za-z0-9_]*_[A-Za-z0-9_]+", route_query))
        if not words:
            return
        named = {t.name for t in self._all_tools if t.name in words}
        self._tool_selection.inferred.update(named)

    def _guard_output(self, text: str) -> str:
        """Output guardrail tripwire on the final answer: a tripped wire
        replaces the answer (in the transcript too) with a notice."""
        from jaeger_agent import guardrails as _guardrails
        tripped = _guardrails.run("output", text or "") if text else None
        if tripped is None:
            return text
        self.last_guardrail = {"stage": "output", "guardrail": tripped.guardrail, "reason": tripped.reason}
        note = _guardrails.refusal("output", tripped)
        for message in reversed(self.messages):
            if message.get("role") == "assistant" and not message.get("tool_calls"):
                message["content"] = note
                break
        return note

    def _run_turn_inner(self, user_message: str) -> str:
        """The actual loop body — see :meth:`run_turn` for the contract."""
        tool_calls_made = 0
        max_tool_calls = self.turn_budget.limits.max_tool_calls
        for iteration in range(1, self.max_iterations + 1):
            self.last_iteration_count = iteration
            self.turn_budget.observe_iteration(iteration)
            boundary_halt = self.turn_budget.halt_reason()
            if boundary_halt and "max_iterations" not in boundary_halt:
                self.last_halt_reason = boundary_halt
                return self._budget_halt_or_stop(boundary_halt)

            if self._interrupt_event.is_set():
                self.last_halt_reason = "interrupted"
                break

            # Deliver any mid-turn steering before the model step so
            # the very next call sees the user's course correction.
            self._drain_steers()

            # 1-3: format → call → parse, with Phase-8 retry on length
            # truncation (max-tokens hit). Truncated tool calls get one
            # silent retry; truncated text gets up to 3 continuation
            # nudges. ``_one_model_step_with_length_retry`` returns the
            # final assistant message after the retry chain settles.
            assistant_msg = self._one_model_step_with_length_retry()

            # MODEL deliberation, if the adapter separated any out of the
            # visible answer. Fired here rather than inside the adapter so
            # every adapter that records ``reasoning`` on its message gets the
            # behaviour for free, and so a surface sees it in turn order —
            # before the tool calls the deliberation led to.
            # Fallback ONLY. Adapters that stream reasoning have already sent
            # it token by token, so re-emitting the finished block here would
            # show the same thinking twice. Adapters that cannot stream it
            # (no reasoning channel on the wire) still surface it this way,
            # which is why the branch stays.
            if isinstance(assistant_msg, dict) and not self._streamed_reasoning:
                deliberation = assistant_msg.get("reasoning")
                if deliberation:
                    self.callbacks.on_reasoning(str(deliberation))
            self._streamed_reasoning = False

            # The post-tool nudge (below) is synthetic — once the model
            # has seen it, take it back off the history so the visible
            # transcript carries only real turns.
            self._discard_pending_nudge()

            if self._interrupt_event.is_set():
                self.last_halt_reason = "interrupted"
                return self._halt_turn()

            # 4: append. The model can hold both text and tool_calls in
            # the same message (e.g. "I'll check that — call X"), so we
            # always append before deciding next steps.
            tool_calls = assistant_msg.get("tool_calls") or []
            final_text = assistant_msg.get("content") or ""
            if not tool_calls and final_text:
                # Plain-text tool-call recovery:
                # Local or open models (Ollama, DeepSeek, Qwen) often emit tool
                # calls as plain text (<tool_call>, <function=...>, [call: ...],
                # or markdown JSON). If no structured tool_calls were emitted,
                # attempt repair before assuming the model finished speaking.
                try:
                    from jaeger_agent.parsing.tool_call_repair import repair_plain_text_tool_calls

                    allowed_names = (
                        {getattr(t, "name", "") for t in (self.tools or []) if getattr(t, "name", "")}
                        or None
                    )
                    repaired_calls, scrubbed_text = repair_plain_text_tool_calls(
                        final_text,
                        allowed_tool_names=allowed_names,
                    )
                    if repaired_calls:
                        # The recovery parser returns OpenAI wire calls, while
                        # dispatch consumes internal ToolCall dictionaries.
                        tool_calls = [
                            {"id": call["id"], "name": call["function"]["name"],
                             "arguments": json.loads(call["function"]["arguments"])}
                            for call in repaired_calls
                        ]
                        final_text = scrubbed_text
                        assistant_msg = {
                            **assistant_msg,
                            "tool_calls": tool_calls,
                            "content": scrubbed_text,
                        }
                        self.callbacks.on_thinking(
                            f"[promoted {len(tool_calls)} plain-text tool call(s) to execution]"
                        )
                except Exception as exc:
                    logger.debug("tool_call_repair error: %s", exc)

            # Live step status — after plain-text tool-call recovery, so a CLI or
            # local model that writes its calls as text still reads "continue".
            from jaeger_agent import live as _live
            _live.emit("loop.iteration", {
                "index": iteration, "max": self.max_iterations,
                "decision": "continue" if tool_calls else "answer",
                "reason": (f"{len(tool_calls)} tool call(s) requested" if tool_calls
                           else "model returned text without tool calls"),
                "tool_calls": len(tool_calls),
            })

            if tool_calls:
                tool_calls = unique_tool_call_ids(tool_calls, self.messages)
                assistant_msg = {**assistant_msg, "tool_calls": tool_calls}

            if not tool_calls and final_text:
                guarded_text, repetitions = collapse_generated_repetition(final_text)
                if repetitions > 1:
                    final_text = guarded_text
                    assistant_msg = {**assistant_msg, "content": guarded_text}
                    self.last_halt_reason = "repetitive_generated_response"
                    self.callbacks.on_thinking(
                        f"[repetition guard — collapsed {repetitions} identical response blocks]"
                    )
            if not tool_calls and not final_text.strip():
                # Reasoning budget exhausted: the model spent its whole
                # output allowance inside <think> and never surfaced an
                # answer. Deterministic provider/model limit — nudging
                # or retrying produces the same outcome, so surface it
                # plainly instead (Hermes thinking-exhaustion pattern).
                if assistant_msg.get("finish_reason") == "thinking_exhausted":
                    # Auto-expand output token budget and nudge up to twice per turn
                    # when a reasoning model exhausts max_tokens mid-thought
                    # before emitting code or tool calls.
                    boost_count = int(getattr(self, "_thinking_boost_count", 0) or 0)
                    if boost_count < 2:
                        self._thinking_boost_count = boost_count + 1
                        self._thinking_budget_boosted = True
                        cur_max = int(getattr(self.primary_adapter, "max_tokens", 0) or 0)
                        cap = 16384 if boost_count == 0 else 32768
                        if 0 < cur_max < cap:
                            boosted = min(cap, max(8192 if boost_count == 0 else 16384, cur_max * 2))
                            setattr(self.primary_adapter, "max_tokens", boosted)
                        if boost_count >= 1:
                            # On the second boost, also dial down reasoning effort so
                            # the model breaks out of an internal thought loop.
                            self._thinking_effort_override = "low"
                        self._nudge_pending = True
                        self._pending_nudge_text = (
                            "Your reasoning hit the token limit before producing output. "
                            "Keep reasoning concise and immediately emit the tool call (e.g. write_file or patch) or final answer."
                            if boost_count == 0
                            else "Output limit hit again inside reasoning. Do NOT spend more tokens thinking — "
                            "emit the concrete tool call (write_file / patch / terminal) IMMEDIATELY now."
                        )
                        self._append_message({"role": "user", "content": self._pending_nudge_text})
                        self.callbacks.on_thinking(
                            f"[thinking budget exhausted — boost #{self._thinking_boost_count} with expanded output budget]"
                        )
                        continue
                    note = (
                        "[the model spent its entire output budget "
                        "thinking and never reached an answer — the task "
                        "is incomplete. Adjust the active model's output "
                        "budget (external_model.max_tokens for cloud/API "
                        "models; model.max_tokens for in-process models).]"
                    )
                    exhausted = {**assistant_msg, "content": note}
                    self._append_message(exhausted)
                    self.callbacks.on_step(iteration, exhausted)
                    self.last_halt_reason = "thinking_exhausted"
                    return note
                # A genuinely empty response (whitespace text, no
                # calls). Right after a tool batch this is the classic
                # weak-local-model stall — one synthetic nudge usually
                # unsticks it (Hermes pattern). Only once per turn.
                prev = self._turn_messages[-1] if self._turn_messages else None
                if (
                    not self._post_tool_nudge_used
                    and prev is not None
                    and prev.get("role") == "tool"
                ):
                    self._post_tool_nudge_used = True
                    self._nudge_pending = True
                    self._pending_nudge_text = self._POST_TOOL_NUDGE
                    self._append_message({
                        "role": "user", "content": self._POST_TOOL_NUDGE,
                    })
                    self.callbacks.on_thinking(
                        "[empty response after tool results — nudging once]"
                    )
                    continue
                # No nudge available: an empty assistant message poisons
                # the transcript — Anthropic rejects empty text blocks
                # on every later call — so store a placeholder while
                # returning "" to the caller (nothing speakable
                # happened).
                assistant_msg = {**assistant_msg, "content": "[empty response]"}
                self._append_message(assistant_msg)
                self.callbacks.on_step(iteration, assistant_msg)
                self.last_halt_reason = "empty_response"
                return ""
            self._append_message(assistant_msg)
            self.callbacks.on_step(iteration, assistant_msg)

            if not tool_calls:
                # Sprint Phase 3: TaskConvergenceController (standalone jaeger-loop).
                # Verifies explicitly requested output artifacts exist AND any
                # mutated code files were tested before accepting a final answer.
                import os as _os
                if _os.environ.get("JAEGER_POST_EDIT_VERIFY", "1").strip() != "0":
                    ctrl = getattr(self, "_convergence", None)
                    tool_names = set(self._dispatch_by_name.keys())
                    has_verify_tool = bool(
                        {"terminal", "execute_code", "run_shell", "run_python", "bash"} & tool_names
                    )
                    has_edit_tool = bool(
                        {"write_file", "patch", "edit_file", "apply_patch"} & tool_names
                    )
                    ws_root = None
                    try:
                        from jaeger_agent.core.workspace import get_layout
                        _lay = get_layout()
                        if _lay is not None:
                            ws_root = getattr(_lay, "project_root", None) or getattr(_lay, "workspace_dir", None) or getattr(_lay, "root", None)
                    except Exception:
                        ws_root = None
                    nudge = (
                        ctrl.maybe_finish_nudge(
                            workspace=ws_root,
                            has_verify_tool=has_verify_tool,
                            has_edit_tool=has_edit_tool,
                        )
                        if ctrl is not None
                        else None
                    )
                    if nudge and iteration < self.max_iterations:
                        self._nudge_pending = True
                        self._pending_nudge_text = nudge
                        self._append_message({"role": "user", "content": nudge})
                        self.callbacks.on_thinking(
                            "[convergence guard — nudging to verify code/artifacts before concluding]"
                        )
                        continue
                # A response with no provider-native or strictly repaired tool
                # calls is final. Ordinary prose is never treated as a call;
                # the allow-listed repair grammar above exists for providers
                # that serialize real calls into their text channel.
                return self._apply_mutation_footer(final_text)

            # 5a: skip-final short-circuit. When the FIRST iteration
            # returns exactly one tool call to a deterministic tool, the
            # finalizer phrases the result and we return without a
            # second model call. Subsequent iterations don't qualify —
            # by then the model is mid-conversation and needs the full
            # loop.
            #
            # Additionally suppress skip-final when the user message
            # has multi-step intent ("and then", "first … then",
            # numbered lists, etc.) — those tasks legitimately need
            # the full loop even if the model's *first* call happens
            # to be a deterministic skip-final tool. Without this
            # check, "what's the time, then look up the weather" was
            # finalising on ``get_time`` and silently dropping the
            # weather step.
            if (
                iteration == 1
                and len(tool_calls) == 1
                and tool_calls[0].get("name", "") in self.skip_final_tools
                and not _looks_multistep(user_message)
            ):
                tc = tool_calls[0]
                tool_calls_made += 1
                self.turn_budget.consume_tool(cost=self._normalized_tool_cost(tc))
                self._dispatch_one_tool(tc)
                # The result lives on the just-appended tool message.
                tool_msg = self.messages[-1]
                return self._finalize_skip_final(
                    tc.get("name") or "",
                    tool_msg.get("content"),
                    user_message,
                )

            # 6: dispatch every tool call, append each result. Identical
            # READ calls within the same batch dedupe to one dispatch —
            # models occasionally emit the same read twice in one
            # message; recomputing wastes a call and re-bloats context.
            # Write-side duplicates dispatch as asked (a double ``speak``
            # may be intentional).
            #
            # 6a: RW-lock-partitioned parallel dispatch via standalone Module 03
            # (jaeger-loop partition_read_write_batches): consecutive read-only
            # runs execute concurrently even in mixed read+write batches, while
            # mutating calls serialize strictly.
            def _is_parallel_read(tc_item: ToolCall) -> bool:
                name = tc_item.get("name") or ""
                td = self._dispatch_by_name.get(name)
                return (
                    td is not None
                    and not getattr(td, "interactive", False)
                    and name not in self._SERIAL_READ_TOOLS
                    and getattr(td, "side_effect", "") == "read"
                )

            _rw_batches: list[tuple[bool, list[ToolCall]]]
            try:
                from jaeger_loop import partition_read_write_batches

                _rw_batches = partition_read_write_batches(tool_calls, _is_parallel_read)
            except ImportError:
                _rw_batches = [(True, list(tool_calls))] if self._batch_is_parallel_safe(tool_calls) else [(False, [tc]) for tc in tool_calls]

            if self._batch_is_parallel_safe(tool_calls):
                remaining = max(0, max_tool_calls - tool_calls_made)
                allowed, refused = tool_calls[:remaining], tool_calls[remaining:]
                if allowed:
                    tool_calls_made += len(allowed)
                    self.turn_budget.consume_tool(count=len(allowed), cost=float(len(allowed)))
                    self._dispatch_parallel(allowed)
                for tc in refused:
                    self._append_budget_refusal(tc)
                self._attach_tool_budget_warning(tool_calls_made)
                if self._interrupt_event.is_set():
                    self.last_halt_reason = "interrupted"
                    return self._halt_turn()
                halt = loop_halt_reason(
                    tool_calls_made,
                    self._call_signature_counts,
                    self._failure_signature_counts,
                    max_tool_calls=max_tool_calls,
                )
                if halt:
                    self.last_halt_reason = halt
                    return self._budget_halt_or_stop(halt)
                handed = self._close_after_handoff()
                if handed is not None:
                    return handed
                early = self._finalize_after_first_tools_if_set()
                if early is not None:
                    return early
                continue

            seen_in_batch: dict[str, str] = {}
            for _is_read_run, _run_calls in _rw_batches:
                if _is_read_run and len(_run_calls) >= 2 and self._batch_is_parallel_safe(_run_calls):
                    remaining = max(0, max_tool_calls - tool_calls_made)
                    allowed, refused = _run_calls[:remaining], _run_calls[remaining:]
                    if allowed:
                        tool_calls_made += len(allowed)
                        self.turn_budget.consume_tool(count=len(allowed), cost=float(len(allowed)))
                        self._dispatch_parallel(allowed)
                    for tc in refused:
                        self._append_budget_refusal(tc)
                    if self._interrupt_event.is_set():
                        self.last_halt_reason = "interrupted"
                        return self._halt_turn()
                    continue
                for tc in _run_calls:
                    if tool_calls_made >= max_tool_calls:
                        self._append_budget_refusal(tc)
                        self.last_halt_reason = (
                            f"made {tool_calls_made} tool calls in a single turn"
                        )
                        continue
                    tool_calls_made += 1
                    self.turn_budget.consume_tool(cost=self._normalized_tool_cost(tc))
                    if self._interrupt_event.is_set():
                        self.last_halt_reason = "interrupted"
                        return self._halt_turn()

                    dup_sig = call_signature(
                        tc.get("name") or "", tc.get("arguments") or {},
                    )
                    tdef = self._dispatch_by_name.get(tc.get("name") or "")
                    if (
                        tdef is not None
                        and getattr(tdef, "side_effect", "") == "read"
                        and dup_sig in seen_in_batch
                    ):
                        self._append_message({
                            "role": "tool",
                            "tool_call_id": tc.get("id") or "",
                            "name": tc.get("name") or "",
                            "content": _stringify({
                                "ok": True,
                                "duplicate_of": seen_in_batch[dup_sig],
                                "note": (
                                    "identical call deduplicated this "
                                    "iteration — see that result"
                                ),
                            }),
                        })
                        continue
                    seen_in_batch[dup_sig] = tc.get("id") or "(first)"

                    self._dispatch_one_tool(tc)

                    # Backstop check after each call — catches the model
                    # that hammers the same (tool, args) before its next
                    # response. The reason string is human-readable so the
                    # TUI / log row can surface it unchanged.
                    halt = loop_halt_reason(
                        tool_calls_made,
                        self._call_signature_counts,
                        self._failure_signature_counts,
                        max_tool_calls=max_tool_calls,
                    )
                    if halt:
                        self.last_halt_reason = halt
                        return self._budget_halt_or_stop(halt)

                    self._attach_tool_budget_warning(tool_calls_made)

            if self.last_halt_reason:
                return self._budget_halt_or_stop(self.last_halt_reason)
            handed = self._close_after_handoff()
            if handed is not None:
                return handed
            early = self._finalize_after_first_tools_if_set()
            if early is not None:
                return early

        # Fell out of the for-loop: max_iterations exhausted with the
        # model still trying to use tools. Spend ONE toolless grace
        # call asking the model to wrap up — a spoken summary of what
        # happened beats "[halted: hit max_iterations]" every time.
        if self.last_halt_reason is None:
            self.last_halt_reason = (
                f"hit max_iterations={self.max_iterations} without a final answer"
            )
            return self._wind_down_summary()
        return self._halt_turn()

    def interrupt(self) -> None:
        """Signal the loop to bail at the next safe point. Idempotent —
        re-firing after the loop has already exited is a no-op. The next
        :meth:`run_turn` clears the event at the top so a stale signal
        can't kill the next turn."""
        self._interrupt_event.set()
        self.callbacks.on_interrupt()

    def steer(self, text: str) -> bool:
        """Inject user guidance into the RUNNING turn without killing
        it. The text lands as a real user message before the next model
        step — "actually use metric units", "skip the third file" —
        steering the in-flight work instead of restarting it.

        Returns ``True`` when a turn is active and the steer was
        queued; ``False`` when no turn is running (the caller should
        deliver the text as an ordinary message instead). Thread-safe —
        this is called from the voice/TUI thread while ``run_turn``
        owns the worker thread."""
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        if not self._turn_active:
            return False
        with self._steer_lock:
            self._steer_queue.append(cleaned)
        self.touch_activity("steer queued")
        return True

    def _drain_steers(self) -> None:
        """Move queued steer texts into the conversation as user
        messages. Called at the top of every loop iteration, so a steer
        is seen by the very next model step."""
        with self._steer_lock:
            if not self._steer_queue:
                return
            items = list(self._steer_queue)
            self._steer_queue.clear()
        for text in items:
            self._append_message({"role": "user", "content": text})
            self.callbacks.on_thinking(
                f"[mid-turn steer injected: {text[:80]}]"
            )

    def bind_cancel_signal(self, signal: threading.Event | None) -> None:
        """Honour a host-owned cancellation signal for this agent's turns.

        Unlike the agent's own interrupt event, which ``run_turn`` resets at
        the top of every turn so a stale barge-in cannot kill the next one,
        this signal is never cleared here: a host that cancels a request
        before (or while) its turn starts still gets an interrupted turn.
        The host should also call :meth:`interrupt` when it cancels, so an
        in-flight provider call is woken immediately.
        """
        self._cancel_signal = signal

    def reset_interrupt(self) -> None:
        """Clear the interrupt event manually. ``run_turn`` does this on
        entry too, so calling here is only needed by code that wants to
        unstick the event between turns without starting one."""
        self._interrupt_event.clear()

    @property
    def interrupted(self) -> bool:
        """True when an interrupt has been signalled and not yet cleared."""
        return self._interrupt_event.is_set()

    @property
    def interrupt_event(self) -> threading.Event:
        """Direct access to the underlying ``threading.Event`` — exposed
        so adapters can pass it into :func:`interruptible_call`."""
        return self._interrupt_event

    # ── introspection ───────────────────────────────────────────────

    def describe(self) -> str:
        """One-line label for logs / status. Mirrors the existing
        ``_brain_line`` shape so the TUI status bar can use it unchanged
        when the migration lands."""
        return self.primary_adapter.describe()

    def tool_names(self) -> list[str]:
        """The tool surface this agent can see, in registration order.
        Useful for the ``/tools`` slash command and for skill-aware
        diagnostics."""
        return [t.name for t in self.tools]

    # ── internals ───────────────────────────────────────────────────

    def _record_skill_outcomes(self) -> None:
        if not self._turn_skill_names:
            return
        halt = self.last_halt_reason or ""
        if halt and ("failure" in halt or "identical" in halt or halt.startswith("error")):
            outcome = "failed"
        elif halt or self._failure_signature_counts or self._failed_mutations:
            outcome = "issues"
        else:
            outcome = "smooth"
        for name in self._turn_skill_names:
            self.callbacks.on_record_skill_outcome(name, outcome=outcome, halt_reason=halt)
        if outcome == "smooth":
            return
        try:
            from jaeger_agent.skill_improvement import skill_notes
            from jaeger_agent.core.workspace import get_layout
            layout = get_layout()
            for name in self._turn_skill_names:
                note = skill_notes.add_note(
                    layout,
                    skill=name,
                    outcome=outcome,
                    note=(halt or "tool failures occurred during the routed turn")[:240],
                    calls=self.turn_budget.tool_calls,
                    procedure=",".join(self._turn_tool_names[:40]),
                    errors=",".join(sorted(self._failure_signature_counts)[:8]),
                    flag=outcome == "failed",
                )
                try:
                    from jaeger_agent.background import skill_review
                    skill_review.maybe_propose_on_note(layout, note)
                except Exception:  # noqa: BLE001 — review is asynchronous advice
                    pass
        except Exception:  # noqa: BLE001 — no bound instance in embedders/tests
            pass

    # ── turn bookkeeping ────────────────────────────────────────────

    @property
    def last_turn_messages(self) -> list[Message]:
        """The ``Message`` objects produced by the most recent turn, in
        order (user message included). Stable across mid-turn context
        trims — callers must NOT slice ``self.messages`` by a length
        recorded at turn start, because the context guard rebinds the
        list to a head-trimmed copy when the prompt outgrows the
        window."""
        return list(self._turn_messages)

    def _append_message(self, msg: Message) -> None:
        """Append to the conversation AND the per-turn record. Every
        in-turn append goes through here so the two stay in lockstep."""
        self.messages.append(msg)
        self._turn_messages.append(msg)

    def _pop_message(self) -> None:
        """Remove the most recent in-turn message from both records.
        Used by the length-retry path (synthetic nudge turns) and the
        pre-flight overflow rollback."""
        if self._turn_messages:
            tail = self._turn_messages.pop()
            # The same object is the conversation tail unless something
            # exotic mutated history mid-turn; guard rather than assume.
            if self.messages and self.messages[-1] is tail:
                self.messages.pop()
            elif tail in self.messages:
                self.messages.remove(tail)

    def _close_dangling_tool_calls(self, reason: str) -> None:
        """Append synthetic tool results for any tool calls in this
        turn that never got one.

        An assistant message whose ``tool_calls`` lack matching tool
        results is a transcript poison pill: OpenAI and Anthropic both
        400 on the NEXT call, and since the broken pair sits at the
        recent end of history (the trim drops oldest-first), every
        subsequent turn fails identically until restart. This runs on
        every early exit — interrupt, backstop halt, exception — so
        the next turn always formats cleanly.

        Only the LAST assistant message can be partially serviced
        (dispatch is sequential within an iteration), and its results
        land in call order, so the un-serviced calls are exactly the
        tail beyond the appended result count.
        """
        last_assistant: Message | None = None
        results_after = 0
        for msg in self._turn_messages:
            role = msg.get("role")
            if role == "assistant" and (msg.get("tool_calls") or []):
                last_assistant = msg
                results_after = 0
            elif role == "tool" and last_assistant is not None:
                results_after += 1
        if last_assistant is None:
            return
        pending = (last_assistant.get("tool_calls") or [])[results_after:]
        for tc in pending:
            self._append_message({
                "role": "tool",
                "tool_call_id": tc.get("id") or "",
                "name": tc.get("name") or "",
                "content": _stringify({
                    "ok": False,
                    "error": f"not executed — {reason}",
                    "error_type": "cancelled",
                    "retryable": False,
                }),
            })

    def _apply_mutation_footer(self, text: str) -> str:
        """Append a verifier footer when file mutations failed this
        turn and were never superseded — the model may still CLAIM the
        edits landed, and the operator deserves the contradiction in
        the same breath (Hermes file-mutation-verifier pattern)."""
        if not self._failed_mutations or not text:
            return text
        notes = "; ".join(
            f"{tool}({path or '?'}): {err}"
            for (tool, path), err in list(self._failed_mutations.items())[:4]
        )
        return (
            f"{text}\n\n[file-ops warning: "
            f"{len(self._failed_mutations)} file operation(s) did NOT "
            f"land — {notes}. Verify before trusting any claim of "
            f"success above.]"
        )

    def _halt_turn(self) -> str:
        """Common early-exit path: repair the transcript (synthetic
        results for un-dispatched tool calls), then hand back the best
        available text for this turn."""
        self._discard_pending_nudge()
        self._close_dangling_tool_calls(
            self.last_halt_reason or "turn halted"
        )
        return self._final_text_or_halt()

    def _budget_halt_or_stop(self, reason: str) -> str:
        """Summarize gathered evidence after a budget or repeated tool failure.

        Execution remains halted; a tool-free summary never clears the failure
        receipt. Interrupts and repeated identical actions still stop cold.
        """
        if "tool calls in a single turn" in reason or (
            reason.startswith("hit the same ") and " failure " in reason
        ):
            return self._wind_down_summary()
        return self._halt_turn()

    def _attach_tool_budget_warning(self, tool_calls_made: int) -> None:
        """Merge the one-shot remaining-budget notice into the latest result."""
        if self._tool_budget_warning_used:
            return
        warnings = [item for item in (
            tool_budget_warning(
                tool_calls_made,
                max_tool_calls=self.turn_budget.limits.max_tool_calls,
                warning_fraction=self.turn_budget.limits.warning_fraction,
            ),
            self.turn_budget.warning(),
        ) if item]
        warning = "\n".join(dict.fromkeys(warnings))
        if not warning:
            return
        for message in reversed(self._turn_messages):
            if message.get("role") == "tool":
                message["content"] = _merge_guidance(
                    message.get("content") or "", warning,
                )
                self._tool_budget_warning_used = True
                self.callbacks.on_thinking(
                    "[tool budget warning — "
                    f"{self.turn_budget.limits.max_tool_calls - tool_calls_made} "
                    "calls remain]"
                )
                return

    def _normalized_tool_cost(self, tc: ToolCall) -> float:
        """Return deterministic cost units when a tool has no price metadata.

        Read-only work costs 1, local writes 2, and externally visible or
        hardware actions 3. This is not a currency claim; hosts may supply a
        tighter ``max_tool_cost`` policy while every run gets comparable
        telemetry today.
        """
        tdef = self._dispatch_by_name.get(tc.get("name") or "")
        side_effect = getattr(tdef, "side_effect", "") if tdef else ""
        return {"read": 1.0, "write": 2.0, "external": 3.0, "hardware": 3.0}.get(side_effect, 2.0)

    def _append_budget_refusal(self, tc: ToolCall) -> None:
        """Close a model-emitted call without executing past the hard cap."""
        self._append_message({
            "role": "tool",
            "tool_call_id": tc.get("id") or "",
            "name": tc.get("name") or "",
            "content": _stringify({
                "ok": False,
                "success": False,
                "executed": False,
                "error_code": "tool_budget_exhausted",
                "error": (
                    "hard limit of "
                    f"{self.turn_budget.limits.max_tool_calls} tool calls reached"
                ),
                "retryable": False,
            }),
        })

    def _discard_pending_nudge(self) -> None:
        """Remove the synthetic post-tool nudge from history once the model
        has answered it (or the turn is bailing).
        A nudge is plumbing, not user-authored content — it must never
        persist."""
        if not self._nudge_pending:
            return
        self._nudge_pending = False
        expected = self._pending_nudge_text
        self._pending_nudge_text = None
        tail = self._turn_messages[-1] if self._turn_messages else None
        if (tail is not None and expected is not None
                and tail.get("content") == expected):
            self._pop_message()

    _HANDOFF_REPLY = "It's running in the background; I'll post the result here when it finishes."

    def _close_after_handoff(self) -> str | None:
        """The turn queued its job with ``queue_background_task``: the worker owns
        it now, so end here with one line instead of more model steps that
        re-check or redo the work (parity P2, Grok Bot-style hand-off)."""
        try:
            from jaeger_agent.tools.deepthink_tools import handed_off_this_request
            if not handed_off_this_request():
                return None
        except Exception:  # noqa: BLE001
            return None
        self._close_dangling_tool_calls("handed off to a background worker")
        text = self._HANDOFF_REPLY
        summary = {"role": "assistant", "content": text}
        self._append_message(summary)
        self.callbacks.on_step(self.last_iteration_count + 1, summary)
        self.last_halt_reason = None
        return text

    def _finalize_after_first_tools_if_set(self) -> str | None:
        """Heartbeat / cron check-ins: close after the first read, no second pass."""
        if not getattr(self, "finalize_after_first_tools", False):
            return None
        if getattr(self, "_finalized_after_first_tools", False):
            return None
        self._finalized_after_first_tools = True
        prompt = str(getattr(self, "finalize_after_first_tools_prompt", "") or "").strip()
        if not prompt:
            try:
                from jaeger_ai.core.runtime.cron_turns import HEARTBEAT_FINALIZE_PROMPT
                prompt = HEARTBEAT_FINALIZE_PROMPT
            except Exception:  # noqa: BLE001
                prompt = (
                    "You have finished the check-in reads. Reply now with "
                    "exactly HEARTBEAT_OK if nothing needs attention, or a "
                    "short 3-line summary. Do not call tools."
                )
        return self._finalize_without_tools(prompt)




    def _selection_receipt(self) -> dict[str, Any]:
        from jaeger_agent.skill_registry import tool_discovery as discovery
        from jaeger_agent.skill_registry.toolset_scoping import _scoping_enabled
        selected = {tool.name for tool in self.tools}
        rows = []
        for tool in discovery.catalog():
            row = discovery.row(tool)
            row['selected'] = tool.name in selected
            if row['selected'] and tool.name in self._tool_selection.inferred:
                row['selection_reason'] = 'Matched this task'
            rows.append({key: row[key] for key in ('tool', 'source', 'available', 'selected',
                                                'selection_reason', 'unavailable_reason')})
        # Selected tools first; bound the user receipt without truncating model schemas.
        rows.sort(key=lambda row: (not row['selected'], row['available'], row['tool']))
        return {'mode': 'progressive' if _scoping_enabled() else 'full',
                'selected_count': len(selected), 'catalog_count': len(rows),
                'truncated': len(rows) > 250, 'tools': rows[:250]}


    # ── retry policy constants ──────────────────────────────────────
    #
    # Max number of "continue from where you stopped" nudges allowed
    # for a length-truncated text response. The legacy Hermes path
    # uses 3 — same here so a multi-paragraph answer can survive two
    # cut-offs before we hand the user the partial.
    _MAX_LENGTH_CONTINUE_RETRIES = 3
    # Max number of silent retries on a length-truncated *tool call*
    # (the JSON args got cut mid-string). Hermes uses exactly one —
    # two truncations in a row mean the model can't fit the call
    # under the token limit.
    _MAX_TRUNCATED_TOOL_CALL_RETRIES = 1
    _LENGTH_CONTINUE_NUDGE = (
        "Your previous response was cut off because it hit the output "
        "token limit. Continue from exactly where you stopped — no "
        "preamble, no restatement, just the next characters."
    )
    # One-shot recovery for the "silent after tool results" failure mode
    # (weak local models — Qwen, GLM — routinely return empty content
    # right after a tool batch). The nudge is synthetic and removed from
    # history once the model answers; it never persists.
    _POST_TOOL_NUDGE = (
        "Your last response was empty. Read the tool results above and "
        "continue the task — produce your answer now, or make the next "
        "tool call if more work is needed."
    )
    # Wind-down grace call at iteration exhaustion (Hermes pattern):
    # instead of handing the user a bare \"[halted: hit max_iterations]\",
    # spend ONE extra toolless call asking the model to wrap up. The
    # synthetic prompt is removed from history; the summary stays.
    _WIND_DOWN_PROMPT = (
        "Tool execution has stopped for this turn. Stop "
        "using tools now. In one short reply: summarise what you "
        "accomplished, what remains undone, and the single next step "
        "you would take. Preserve citations from gathered evidence and state "
        "uncertainty. Do not claim missing tools, archives, or outputs succeeded."
    )


    def _on_call_heartbeat(self, elapsed_s: float) -> None:
        """Adapter call heartbeat — updates the activity timestamp and
        forwards to the user-supplied callback. Fires every ~100 ms
        while a model call is in flight."""
        self.last_activity_ts = time.time()
        self.last_activity_desc = f"waiting on model ({elapsed_s:.1f}s)"
        self.callbacks.on_heartbeat(elapsed_s)

    def touch_activity(self, desc: str) -> None:
        """Mark progress with a human-readable description. Use from
        tool implementations or callbacks to flag "still working" to
        the watchdog. Mirrors Hermes' ``_touch_activity``."""
        self.last_activity_ts = time.time()
        self.last_activity_desc = desc


    # ── stale-call timeout (Phase-8) ───────────────────────────────
    # When a provider's HTTP socket is open but no bytes are flowing,
    # the SDK can sit on the request for the full ``timeout`` (often
    # 600s) before giving up. ``StaleCallTimeout`` lets the agent's
    # adapter-fallback chain react in ~30s instead — set to ``None``
    # to disable and rely on SDK timeouts only.
    stale_call_timeout_s: float | None = 30.0
    first_progress_timeout_s: float | None = None

    # Per-adapter retry caps by error class (Hermes error-classifier
    # pattern, scaled down for a voice agent where long waits are dead
    # air). AUTH / NOT_FOUND never retry the same adapter — the result
    # is deterministic; the fallback chain is the recovery. UNKNOWN is
    # conservative: straight to fallback, as before.
    _RATE_LIMIT_RETRIES = 2
    _TRANSIENT_RETRIES = 1
    _STALE_RETRIES = 1


    def _dispatch_one_tool(self, tc: ToolCall) -> None:
        """Validate, dispatch, append result. Captures both validation
        failures (Pydantic) and tool-raised exceptions as tool-result
        messages so the model can self-correct on the next turn rather
        than crashing the whole loop.

        Split into prepare → execute → finish so the parallel path
        (:meth:`_dispatch_parallel`) can run EXECUTE concurrently for
        all-read batches while prepare and finish stay serial and
        ordered (callbacks, backstop counters, and appends are not
        thread-safe and must observe batch order).
        """
        prep = self._prepare_dispatch(tc)
        content = self._execute_prepared(prep)
        self._finish_dispatch(prep, content)

    # File tools whose only side effect is a file at ``args["path"]``. These
    # may run concurrently with each other when their paths don't overlap —
    # so a multi-file edit fans out — while read-only tools (web_search etc.)
    # are always parallel-safe.
    _PATH_SCOPED_READ = frozenset({"read_file"})
    _PATH_SCOPED_WRITE = frozenset({
        "write_file", "append_file", "edit_file", "patch", "delete_file"})
    _CACHEABLE_READ_TOOLS = frozenset({
        "read_file", "list_skill_dir", "search_files",
        "describe_tool", "list_tools", "list_skills",
    })

    # These are logically read-only but share the process-wide SQLite
    # connection. ``check_same_thread=False`` permits a connection to move
    # between threads; it does not make simultaneous cursor use on that one
    # connection safe. Gemma commonly emits two ``recall`` calls together,
    # so keep memory reads serial while other independent reads still fan out.
    _SERIAL_READ_TOOLS = frozenset({
        "recall", "list_facts", "search_memory", "session_search",
    })

    @staticmethod
    def _call_path(tc: ToolCall) -> str | None:
        args = tc.get("arguments") or {}
        p = args.get("path") or args.get("file_path")
        return str(p) if p else None

    @staticmethod
    def _paths_overlap(a: str, b: str) -> bool:
        """True if two paths are the same file or one contains the other."""
        return paths_overlap(a, b)








    def _final_text_or_halt(self) -> str:
        """Return the most recent assistant text FROM THIS TURN, falling
        back to the halt reason when no text exists. Scanning all of
        ``self.messages`` here re-surfaced the PREVIOUS turn's answer
        when a turn was interrupted before its first model response —
        the voice loop would then speak the old answer again."""
        for msg in reversed(self._turn_messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]  # type: ignore[return-value]
        return f"[halted: {self.last_halt_reason or 'no response'}]"


def _exclude_beta(tools: list[ToolDef]) -> list[ToolDef]:
    """Drop ``beta=True`` tools unless dev mode is on. The single
    chokepoint for the beta gate — both the constructor and the
    per-turn catalogue refresh route through here, so a beta tool is
    neither visible to the model nor dispatchable outside dev mode."""
    if dev_mode_enabled():
        return tools
    return [t for t in tools if not t.beta]


def _filter_available_tools(tools: list[ToolDef]) -> list[ToolDef]:
    """Apply beta and runtime-readiness gates to the model and dispatch surface.

    Availability is evaluated per catalog refresh, not cached process-wide, so
    credentials and session-installed scopes can change between turns.
    """
    return [tool for tool in _exclude_beta(tools) if tool.is_available()]


_MULTISTEP_PATTERNS = (
    " and then ", " then ", " after that", " next, ",
    " followed by ", " ; ",
    "step 1", "step 2", "step 3",
    "first,", "first ,", "second,", "third,",
    "finally,",
)
_MULTISTEP_RE = None  # built lazily


def _looks_multistep(user_message: str) -> bool:
    """Heuristic: does the user's message ask for more than one
    deliberate action?

    Used to suppress :attr:`JaegerAgent.skip_final_tools` short-circuit
    on prompts like *"what's the time, then look up the weather"*. The
    skip-final path can drop subsequent steps because it ends the turn
    after the first deterministic tool call — fine for one-shot
    questions, wrong for chained tasks.

    Conservative on purpose: a false POSITIVE (declaring single-step
    work multi-step) just falls back to the full loop — one extra
    model call. A false NEGATIVE silently drops user work. So we err
    toward calling it multi-step when in doubt.
    """
    if not user_message:
        return False
    text = " " + user_message.strip().lower() + " "
    if any(p in text for p in _MULTISTEP_PATTERNS):
        return True
    # Numbered list — "1. … 2. …" — also signals multi-step.
    import re
    if re.search(r"\b1[.)]\s.+\b2[.)]\s", text):
        return True
    return False


def _stringify(content: Any) -> str:
    """Tool results are arbitrary JSON-friendly Python. The internal
    message log stores them as strings so adapters don't have to
    re-encode on every format pass. ``json.dumps`` with ``default=str``
    handles non-serialisable objects without raising."""
    if content is None:
        return ""
    try:
        import json
        return json.dumps(content, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001 — last-resort fallback
        return str(content)


_PATH_ERROR = _re.compile(
    r"(?i)(no such file|not found|does not exist|outside (the )?(allowed|writable)|"
    r"not a directory|is a directory|permission denied|escapes|not allowed)")


def _recovery_hint(name: str, args: Any, error: str | None) -> str:
    """What to do after a failed call: reflect, change something, retry.

    Small local models tend to repeat the identical failing call or quietly
    give up. One structured line on every failed result asks for the cause,
    a concrete change, and an honest report if it cannot work.
    """
    hint = ("This call failed. Read the error, state the cause in one line, then change "
            "something before retrying (arguments, path, or a different tool). Do not repeat "
            "the identical call. If it cannot work, say so plainly instead of guessing.")
    has_path = isinstance(args, dict) and any(k in args for k in ("path", "file", "src", "dst", "cwd", "workdir"))
    if has_path and _PATH_ERROR.search(str(error or "")):
        try:
            from jaeger_agent.core import workspace as _ws
            roots = ", ".join(str(r) for r in _ws.writable_roots())
            base = _ws.get_project_root() or _ws._require_layout().root
            hint += (f" Relative paths resolve from {base}; absolute paths must be inside "
                     f"{roots}. Check what exists (search_files, or ls in terminal) first.")
        except Exception:  # noqa: BLE001 — the generic hint still stands
            hint += " Check what exists (search_files, or ls in terminal) before retrying."
    elif name == "execute_code" and _PATH_ERROR.search(str(error or "")):
        try:
            from jaeger_agent.core import workspace as _ws
            sandbox = _ws.get_project_root() or _ws._require_layout().skills_dir
            base = _ws.get_project_root() or _ws._require_layout().root
            where = f" It runs sandboxed in {sandbox} and can only open files there."
            shell = f" or the terminal tool (starts in {base}, so `workspace/...` resolves)"
        except Exception:  # noqa: BLE001 — the generic hint still stands
            where, shell = " It runs sandboxed and can only open files in its own directory.", " or the terminal tool"
        hint += (f" execute_code cannot see workspace files.{where} Read inputs with read_file and "
                 f"write outputs with write_file (paths like `workspace/...`){shell}.")
    return hint


def _stderr_tail(content: dict) -> str:
    """Last non-empty stderr line of a failed code/shell result, so the
    recorded error and recovery hint name the real cause."""
    lines = [ln.strip() for ln in str(content.get("stderr") or "").splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""


def _merge_guidance(content: Any, guidance: str) -> Any:
    """Attach guardrail guidance to a tool result without losing the
    original payload. Dict gains a ``loop_guard`` key; string appends
    the guidance; anything else is wrapped. A second merge on the same
    dict concatenates rather than overwriting, so the pre-dispatch
    hook's guidance and the backstop warning can coexist."""
    if isinstance(content, dict):
        existing = content.get("loop_guard")
        merged = f"{existing}\n\n{guidance}" if existing else guidance
        return {**content, "loop_guard": merged}
    if isinstance(content, str):
        return f"{content}\n\n{guidance}"
    return {"result": content, "loop_guard": guidance}


# File-mutating tools whose failures must not be paper-overable: a
# model that ran ``write_file`` (failed) then says "I've updated the
# file!" is the worst kind of wrong — confidently so. The loop tracks
# un-superseded failures and appends a verifier footer to the final
# answer (Hermes file-mutation-verifier pattern).
_MUTATION_TOOLS = frozenset({
    "write_file", "file_write", "edit_file", "patch", "apply_patch", "patch_file", "append_file", "delete_file",
})

# Server-side context-overflow signatures (LM Studio / Ollama /
# llama.cpp-server / cloud wordings). When one of these comes back the
# estimator was too optimistic — tighten it and retry, instead of
# walking the fallback chain with the same oversized prompt.
_OVERFLOW_HINTS = (
    "context window", "context length", "maximum context",
    "tokens to keep", "input is too long", "too many tokens",
    "exceeds the maximum",
)


def _looks_like_overflow(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(h in text for h in _OVERFLOW_HINTS)


# Lone UTF-16 surrogates (U+D800–U+DFFF) are invalid in UTF-8 and crash
# ``json.dumps`` inside provider SDKs. They arrive from clipboard pastes
# (Word, Google Docs) and from byte-level local reasoning models, then
# sit in history detonating EVERY subsequent call — a permanent-mute
# class. Scrubbed to U+FFFD before each model call; fast no-op when the
# transcript is clean.
_SURROGATE_RE = _re.compile(r"[\ud800-\udfff]")


def _scrub_surrogates_in_messages(messages: list[Message]) -> None:
    """Replace lone surrogates across every string the wire can carry —
    content, tool names, stringified args. In-place: once scrubbed, the
    history stays clean."""
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and _SURROGATE_RE.search(content):
            msg["content"] = _SURROGATE_RE.sub("�", content)
        for tc in (msg.get("tool_calls") or []):
            name = tc.get("name")
            if isinstance(name, str) and _SURROGATE_RE.search(name):
                tc["name"] = _SURROGATE_RE.sub("�", name)
            args = tc.get("arguments")
            if isinstance(args, dict):
                for k, v in list(args.items()):
                    if isinstance(v, str) and _SURROGATE_RE.search(v):
                        args[k] = _SURROGATE_RE.sub("�", v)
            elif isinstance(args, str) and _SURROGATE_RE.search(args):
                tc["arguments"] = _SURROGATE_RE.sub("�", args)


def _classify_adapter_error(exc: BaseException) -> str:
    """Classify an adapter exception via standalone Module 07 (jaeger-reliability)."""
    from jaeger_reliability import FailoverReason, classify_error

    if isinstance(exc, Exception):
        reason = classify_error(exc)
        if reason == FailoverReason.RATE_LIMIT.value:
            return "rate_limit"
        if reason in {FailoverReason.TRANSIENT.value, FailoverReason.EMPTY_RESPONSE.value}:
            return "transient"
        if reason == FailoverReason.AUTH.value:
            return "auth"
    try:
        from jaeger_agent.core.errors import classify_exception
        return classify_exception(exc)
    except Exception:  # noqa: BLE001 — classification must never mask the error
        return "unknown"


def _retry_delay(kind: str, attempt: int) -> float:
    """Jittered backoff sized for a VOICE agent — long waits are dead
    air, so the caps are far below Hermes' server-side defaults. Rate
    limits get room to clear (~2-8s); transient blips retry almost
    immediately (~1-2s)."""
    from jaeger_agent.util.retry_utils import jittered_backoff
    if kind == "rate_limit":
        return jittered_backoff(attempt, base_delay=2.0, max_delay=8.0)
    return jittered_backoff(attempt, base_delay=1.0, max_delay=3.0)


def _hash_result(content: Any) -> str:
    """Stable hash of a tool result for the read-tool no-progress
    check. JSON-canonicalised when possible so dict key order doesn't
    fake progress."""
    import hashlib
    try:
        import json
        canonical = json.dumps(
            content, sort_keys=True, default=str, ensure_ascii=False,
        )
    except Exception:  # noqa: BLE001
        canonical = str(content)
    return hashlib.sha256(canonical.encode("utf-8", "replace")).hexdigest()


def _default_skip_final_finalizer(
    tool_name: str, tool_result: Any, user_message: str,
) -> str:
    """Default phrasing for skip-final: the result rendered as-is.

    The real-world caller (``main.py``) installs a finalizer that does
    a bounded model call (``max_tokens=120, temp=0.2``) to phrase the
    result conversationally. Unit tests use this default so the loop
    is testable without a model.
    """
    if isinstance(tool_result, str):
        return tool_result
    return _stringify(tool_result)


__all__ = [
    "JaegerAgent",
    "SkipFinalFinalizer",
    "ToolsetResolver",
    "ToolVisibility",
    "TurnStartHook",
]
