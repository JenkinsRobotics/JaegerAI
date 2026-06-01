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

import threading
import time
from typing import Any

from typing import Callable

from jaeger_os.agent.adapters.base import ProviderAdapter
from jaeger_os.agent.loop.callbacks import AgentCallbacks
from jaeger_os.agent.loop.interrupt import AgentInterrupted, StaleCallTimeout
from jaeger_os.agent.loop.loop_backstop import (
    call_signature,
    loop_halt_reason,
    semantic_failure_signature,
)
from jaeger_os.agent.schemas.message_types import Message, ToolCall
from jaeger_os.agent.schemas.tool_registry import get_tool, get_tools, has_tool
from jaeger_os.agent.schemas.tool_schema import ToolDef
from jaeger_os.agent.util.context_guard import ContextGuard, ContextOverflow


# Type alias for the skip-final finalizer. Takes the tool name, the
# tool result, and the user message that triggered the turn; returns
# the final assistant text. The default formatter does a one-line JSON
# dump — callers (eventually ``main.py``) install a bounded model call
# here so the answer reads as a natural sentence.
SkipFinalFinalizer = Callable[[str, "object", str], str]


class JaegerAgent:
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
    ) -> None:
        self.primary_adapter = adapter
        self.fallback_adapters: list[ProviderAdapter] = list(fallback_adapters or [])
        self.system_prompt = system_prompt
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
        # mid-session ``load_toolset`` call expands what the model sees
        # on the very next turn — without rebuilding the agent.
        if tools is not None:
            self._all_tools: list[ToolDef] = list(tools)
            self._tools_filter_locked = True   # explicit list = caller knows best
        elif toolsets is not None:
            from jaeger_os.agent.schemas.toolsets import resolve_toolsets
            wanted = resolve_toolsets(set(toolsets))
            self._all_tools = [t for t in get_tools() if t.name in wanted]
            self._tools_filter_locked = False
        else:
            self._all_tools = get_tools()
            self._tools_filter_locked = False
        # Per-agent dispatch map. ``_dispatch_one_tool`` previously
        # resolved by name against the *global* registry — so an agent
        # built with ``tools=[a, b, c]`` (an explicit allowlist) would
        # still happily dispatch any other globally registered tool
        # the model named. Building the map from ``_all_tools`` here
        # binds dispatch to the agent's *intended* set.
        # The map is recomputed on demand whenever the visible set
        # shifts (see ``_refresh_dispatch_map``).
        self._dispatch_by_name: dict[str, ToolDef] = {
            t.name: t for t in self._all_tools
        }
        # Record the originally-requested toolset names for diagnostics
        # (the ``/runtime`` panel surfaces this); not used by the loop.
        self.toolsets: frozenset[str] = frozenset(toolsets or ())
        self.max_iterations = int(max_iterations)
        self.callbacks = callbacks or AgentCallbacks()

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

        # Running state — fresh per agent, never reused across instances.
        self.messages: list[Message] = []
        self._interrupt_event = threading.Event()

        # Loop-backstop counters. Reset at the start of every turn so a
        # spinning previous turn can't carry over and trip the new one.
        self._call_signature_counts: dict[str, int] = {}
        self._failure_signature_counts: dict[str, int] = {}

        # Diagnostic surface — populated by the most recent ``run_turn``.
        # ``last_halt_reason`` is None on a clean finish; a string when
        # the backstop or interrupt cut the loop short.
        self.last_halt_reason: str | None = None
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

    # ── tool visibility ─────────────────────────────────────────────

    @property
    def tools(self) -> list[ToolDef]:
        """The tools visible to the model THIS turn.

        Recomputed on every access so a mid-session ``load_toolset``
        call (which mutates the shared visibility state in
        :mod:`jaeger_os.core.skills.toolsets`) takes effect on the
        next turn without rebuilding the agent. The full set the agent
        can dispatch + validate against lives in ``self._all_tools`` —
        ``describe_tool`` reads from there so the model can peek at a
        hidden tool's schema without loading the whole category."""
        if self._tools_filter_locked:
            # Caller passed ``tools=[...]`` explicitly — honour it.
            return list(self._all_tools)
        try:
            from jaeger_os.core.skills.toolsets import tool_visible
        except Exception:  # noqa: BLE001
            return list(self._all_tools)
        return [t for t in self._all_tools if tool_visible(t.name)]

    @property
    def all_tools(self) -> list[ToolDef]:
        """Every tool the agent can dispatch — including ones currently
        hidden from the model. Used by ``describe_tool`` + by the
        loop-backstop's "did you mean…?" suggestions."""
        return list(self._all_tools)

    # ── public surface ──────────────────────────────────────────────

    def run_turn(self, user_message: str) -> str:
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
        """
        # Fresh per-turn state. Counters from a previous turn would
        # falsely trip the backstop on the second message of a session.
        self._call_signature_counts.clear()
        self._failure_signature_counts.clear()
        self._interrupt_event.clear()
        self.last_halt_reason = None
        self.last_iteration_count = 0
        self.last_skip_final = False
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0

        # Per-turn dedupe trackers in tool modules (file_read's
        # "unchanged since last read" suppression in particular). The
        # legacy pydantic-ai loop reset this implicitly via its own
        # turn lifecycle; Phase-9 has to do it here or a *legitimate*
        # next-turn read of the same file returns an empty-stub result.
        try:
            from jaeger_os.core.tools.files import reset_read_tracker
            reset_read_tracker()
        except Exception:  # noqa: BLE001 — never break a turn over a reset
            pass

        self.messages.append({"role": "user", "content": user_message})

        tool_calls_made = 0
        for iteration in range(1, self.max_iterations + 1):
            self.last_iteration_count = iteration

            if self._interrupt_event.is_set():
                self.last_halt_reason = "interrupted"
                break

            # 1-3: format → call → parse, with Phase-8 retry on length
            # truncation (max-tokens hit). Truncated tool calls get one
            # silent retry; truncated text gets up to 3 continuation
            # nudges. ``_one_model_step_with_length_retry`` returns the
            # final assistant message after the retry chain settles.
            assistant_msg = self._one_model_step_with_length_retry()

            if self._interrupt_event.is_set():
                self.last_halt_reason = "interrupted"
                return self._final_text_or_halt()

            # 4: append. The model can hold both text and tool_calls in
            # the same message (e.g. "I'll check that — call X"), so we
            # always append before deciding next steps.
            self.messages.append(assistant_msg)
            self.callbacks.on_step(iteration, assistant_msg)

            tool_calls = assistant_msg.get("tool_calls") or []
            if not tool_calls:
                # 5: model produced a final answer.
                return assistant_msg.get("content") or ""

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
                self._dispatch_one_tool(tc)
                # The result lives on the just-appended tool message.
                tool_msg = self.messages[-1]
                return self._finalize_skip_final(
                    tc.get("name") or "",
                    tool_msg.get("content"),
                    user_message,
                )

            # 6: dispatch every tool call, append each result.
            for tc in tool_calls:
                tool_calls_made += 1
                if self._interrupt_event.is_set():
                    self.last_halt_reason = "interrupted"
                    return self._final_text_or_halt()

                self._dispatch_one_tool(tc)

                # Backstop check after each call — catches the model
                # that hammers the same (tool, args) before its next
                # response. The reason string is human-readable so the
                # TUI / log row can surface it unchanged.
                halt = loop_halt_reason(
                    tool_calls_made,
                    self._call_signature_counts,
                    self._failure_signature_counts,
                )
                if halt:
                    self.last_halt_reason = halt
                    return self._final_text_or_halt()

        # Fell out of the for-loop: max_iterations exhausted with the
        # model still trying to use tools.
        if self.last_halt_reason is None:
            self.last_halt_reason = (
                f"hit max_iterations={self.max_iterations} without a final answer"
            )
        return self._final_text_or_halt()

    def interrupt(self) -> None:
        """Signal the loop to bail at the next safe point. Idempotent —
        re-firing after the loop has already exited is a no-op. The next
        :meth:`run_turn` clears the event at the top so a stale signal
        can't kill the next turn."""
        self._interrupt_event.set()
        self.callbacks.on_interrupt()

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

    def _one_model_step_with_length_retry(self) -> Message:
        """Wrap :meth:`_one_model_step` with Phase-8 length-retry logic.

        Two distinct cases:

          1. ``finish_reason == "length"`` AND the response has
             ``tool_calls`` → the call's JSON args were truncated.
             Retry the model call ONCE without appending the broken
             response. Two truncations in a row → return the partial
             so the loop can surface it as an error.

          2. ``finish_reason == "length"`` AND the response is plain
             text → the answer got cut off. Append the partial,
             inject a continuation nudge, retry. Concatenate text on
             each subsequent successful step. Up to 3 nudges; on
             exhaustion return the accumulated partial.

        Non-length finish reasons return the assistant message
        unchanged.
        """
        # Case 1: truncated tool call.
        for _ in range(self._MAX_TRUNCATED_TOOL_CALL_RETRIES + 1):
            msg = self._one_model_step()
            if (
                msg.get("finish_reason") == "length"
                and msg.get("tool_calls")
            ):
                # Don't append the broken call to history — retry the
                # same model step with the same input. One retry only.
                self.callbacks.on_thinking(
                    "[truncated tool call detected — retrying once]"
                )
                continue
            break
        # If we exited the loop with a truncated tool call still on
        # the table, fall through to case 2's append-and-nudge — at
        # least the partial reaches the loop where the dispatcher
        # will surface a clean validation error.

        # Case 2: truncated text (no tool calls, or tool-call retry
        # exhausted). Append and nudge up to N times.
        retries = 0
        accumulated_text: list[str] = []
        while (
            msg.get("finish_reason") == "length"
            and not msg.get("tool_calls")
            and retries < self._MAX_LENGTH_CONTINUE_RETRIES
        ):
            partial = msg.get("content") or ""
            accumulated_text.append(partial)
            # Stash the partial as a real assistant message so the
            # next call sees it, then nudge as a user turn.
            self.messages.append({"role": "assistant", "content": partial})
            self.messages.append({
                "role": "user", "content": self._LENGTH_CONTINUE_NUDGE,
            })
            self.callbacks.on_thinking(
                f"[length-truncated response — continuation retry "
                f"{retries + 1}/{self._MAX_LENGTH_CONTINUE_RETRIES}]"
            )
            retries += 1
            msg = self._one_model_step()
            # Trim the synthetic nudge turns back off the history so
            # the visible transcript only carries the final stitched
            # message — the nudges aren't user-authored content.
            self.messages.pop()  # the nudge user turn
            self.messages.pop()  # the partial assistant turn

        if accumulated_text:
            stitched = "".join(accumulated_text) + (msg.get("content") or "")
            msg = {**msg, "content": stitched}
        return msg

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

    def _accumulate_usage(self, raw: Any) -> None:
        """Extract token usage from an adapter's raw response and add
        to the per-turn counters. Best-effort: adapters that don't
        report usage just contribute zero. Three known shapes:

          * OpenAI / llama-cpp:
              ``raw["usage"] = {"prompt_tokens": N, "completion_tokens": N}``
          * Anthropic:
              ``raw["usage"] = {"input_tokens": N, "output_tokens": N}``
          * Local-llama umbrella + others: no usage field → no-op

        Never raises — token-counting is observability, not control
        flow, so a malformed response must not break the turn.
        """
        if not isinstance(raw, dict):
            return
        usage = raw.get("usage")
        if not isinstance(usage, dict):
            return
        # OpenAI / llama-cpp style.
        p = usage.get("prompt_tokens")
        c = usage.get("completion_tokens")
        # Anthropic style.
        if p is None:
            p = usage.get("input_tokens")
        if c is None:
            c = usage.get("output_tokens")
        try:
            if p is not None:
                self.last_prompt_tokens += int(p)
            if c is not None:
                self.last_completion_tokens += int(c)
        except (TypeError, ValueError):
            return

    # ── stale-call timeout (Phase-8) ───────────────────────────────
    # When a provider's HTTP socket is open but no bytes are flowing,
    # the SDK can sit on the request for the full ``timeout`` (often
    # 600s) before giving up. ``StaleCallTimeout`` lets the agent's
    # adapter-fallback chain react in ~30s instead — set to ``None``
    # to disable and rely on SDK timeouts only.
    stale_call_timeout_s: float | None = 30.0

    def _one_model_step(self) -> Message:
        """Format → call → parse, with adapter fallback on hard errors.

        The primary adapter is tried first; on a raised exception we walk
        the fallback list in order. ``AgentInterrupted`` short-circuits
        the chain — that's the operator cancelling, not a backend
        failure. ``StaleCallTimeout`` is treated like any other
        adapter exception — the fallback chain gets a chance.
        """
        adapters = [self.primary_adapter, *self.fallback_adapters]
        # Pre-flight context guard. Trim oldest history until the
        # prompt fits the server's ctx window; if even max trimming
        # can't fit, the guard raises ``ContextOverflow`` and we
        # surface that to the caller without hitting the model.
        if self.context_guard is not None:
            try:
                trim = self.context_guard.trim_to_fit(
                    self.messages,
                    system_prompt=self.system_prompt,
                    tools=self.tools,
                )
            except ContextOverflow:
                raise
            if trim.dropped_count > 0:
                self.callbacks.on_thinking(
                    f"[context-guard] trimmed {trim.dropped_count} old "
                    f"message(s) to fit ctx budget"
                )
                self.messages = trim.messages

        last_exc: Exception | None = None
        for adapter in adapters:
            try:
                formatted = adapter.format_messages(
                    self.messages, self.tools, self.system_prompt,
                )
                raw = adapter.call(
                    formatted,
                    self._interrupt_event,
                    stale_timeout=self.stale_call_timeout_s,
                    on_heartbeat=self._on_call_heartbeat,
                )
                self._accumulate_usage(raw)
                return adapter.parse_response(raw)
            except AgentInterrupted:
                # Interrupt propagates — handled by ``run_turn`` via the
                # event check at the top of the next iteration. Set the
                # halt reason here so observers (TUI status, latency log,
                # voice loop's "cancel actually took effect" check) can
                # distinguish a user cancel from a clean finish even
                # though run_turn returns whatever text was assembled.
                self._interrupt_event.set()
                self.last_halt_reason = "interrupted"
                return {"role": "assistant", "content": None}
            except StaleCallTimeout as exc:
                # Model stalled past the wall-clock budget. For
                # in-process backends the worker thread is still
                # running (we cannot safely cancel llama.cpp mid-decode
                # — see LocalLlamaAdapter.call), so the next adapter in
                # the fallback chain will inherit a degraded Llama
                # instance. We still propagate via the fallback chain
                # so an HTTP fallback (if configured) can pick up; if
                # this was the last adapter the message reaches the
                # caller with a clean ``stalled`` halt reason rather
                # than a generic exception.
                last_exc = exc
                self.last_halt_reason = "stalled"
                self.callbacks.on_thinking(
                    f"[adapter {adapter.describe()} stalled after "
                    f"{self.stale_call_timeout_s:.0f}s; "
                    f"try ``jaeger kill`` from another terminal "
                    f"if the TUI feels stuck]"
                )
                continue
            except Exception as exc:  # noqa: BLE001 — adapter chain absorbs
                last_exc = exc
                self.callbacks.on_thinking(
                    f"[adapter {adapter.describe()} failed: {type(exc).__name__}]"
                )
                continue
        # Every adapter raised — surface the last exception so the
        # caller (REPL, daemon) can decide what to do.
        assert last_exc is not None
        raise last_exc

    def _dispatch_one_tool(self, tc: ToolCall) -> None:
        """Validate, dispatch, append result. Captures both validation
        failures (Pydantic) and tool-raised exceptions as tool-result
        messages so the model can self-correct on the next turn rather
        than crashing the whole loop.

        Fires the ``before_tool_call`` / ``after_tool_call`` hooks
        around the dispatch — the integration seams for
        :mod:`jaeger_os.core.tool_guardrails` (warn one step before the
        backstop trips) and :mod:`jaeger_os.core.tool_result_budget`
        (persist oversized payloads out of the context window). Both
        currently live in the legacy loop and migrate here in Phase 6.
        """
        name = tc.get("name") or ""
        args = tc.get("arguments") or {}
        call_id = tc.get("id") or ""

        # Resolve the tool against THIS agent's dispatch map (built
        # from ``_all_tools`` at construction). The previous code
        # asked the global registry, which silently bypassed an
        # explicit ``tools=[...]`` allowlist — a model that named any
        # globally registered tool could get it dispatched even when
        # the agent was supposed to expose only ``[a, b, c]``.
        dispatch_map = self._dispatch_by_name

        # Normalise drifted tool names ONCE at the loop boundary — case
        # variants, separator swaps, ``_tool`` suffixes, ``CamelCase``.
        # No fuzzy matching: an unrecognised name returns unchanged and
        # surfaces a clean "unknown tool" error so the model can
        # self-correct, rather than silently dispatching a guess.
        if name and name not in dispatch_map:
            try:
                from jaeger_os.agent.dialects import normalize_tool_name
                valid = frozenset(dispatch_map.keys())
                normalised = normalize_tool_name(name, valid)
                if normalised != name and normalised in dispatch_map:
                    name = normalised
                    # Patch the tool_call in place so the loop's bookkeeping
                    # (backstop signatures, post-dispatch hook) sees the
                    # corrected name too.
                    tc["name"] = name  # type: ignore[typeddict-item]
            except Exception:  # noqa: BLE001
                pass

        # Backstop bookkeeping — counted *before* dispatch so a tight
        # loop trips the ceiling immediately rather than after one
        # extra wasted call.
        sig = call_signature(name, args)
        self._call_signature_counts[sig] = self._call_signature_counts.get(sig, 0) + 1

        started = time.perf_counter()
        self.callbacks.on_tool_progress(name, "start", args)
        # Pre-dispatch hook — guardrail returns optional guidance text.
        guidance = self.callbacks.on_before_tool_call(name, args)

        try:
            tool_def = dispatch_map.get(name)
            if tool_def is None:
                content: Any = {
                    "ok": False,
                    "error": f"unknown tool {name!r}",
                    "error_type": "unknown_tool",
                    "retryable": False,
                }
            else:
                content = tool_def.dispatch(args)
        except Exception as exc:  # noqa: BLE001 — surfaced to the model
            # Tag safety/permission failures distinctly so the model
            # (and the latency log) can tell "retry with different
            # args" from "user said no, don't try again". The legacy
            # generic-catch lumped them together and the model would
            # cheerfully retry a denied PRIVILEGED call.
            err_type = "tool_error"
            retryable = True
            required_tier: str | None = None
            try:
                from jaeger_os.core.safety.permissions import (
                    PermissionDenied,
                    ConfirmationRequired,
                    HumanOverrideRequired,
                )
                if isinstance(exc, (PermissionDenied,
                                    ConfirmationRequired,
                                    HumanOverrideRequired)):
                    err_type = "permission_denied"
                    retryable = False
                    required_tier = getattr(exc, "tier", None) or getattr(
                        exc, "required_tier", None,
                    )
            except Exception:  # noqa: BLE001 — never break the loop over typing
                pass
            # Hardline guard refusals (run_shell catastrophic-command
            # blocklist) come back as a typed dict, not an exception;
            # they don't land here. But if a future refusal layer
            # raises, treat it the same as permission_denied.
            content = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "error_type": err_type,
                "retryable": retryable,
            }
            if required_tier:
                content["required_tier"] = str(required_tier)

        # Per-tool-result oversize guard. A single ``run_shell`` dump
        # or screenshot can dominate the next turn's context; cap it
        # here so the history-trim pass downstream isn't fighting a
        # losing battle. Runs before the user-provided after_tool_call
        # hook so an external budget (if any) sees the trimmed shape.
        if self.context_guard is not None:
            content, truncated = self.context_guard.truncate_oversized_result(content)
            if truncated:
                self.callbacks.on_thinking(
                    f"[context-guard] truncated oversized {name!r} result"
                )

        # Post-dispatch hook — budget can substitute a pointer if the
        # payload is oversized. ``None`` means "leave content alone".
        replacement = self.callbacks.on_after_tool_call(name, args, content)
        if replacement is not None:
            content = replacement
        if guidance:
            content = _merge_guidance(content, guidance)

        elapsed = time.perf_counter() - started
        self.callbacks.on_tool_progress(
            name, "done", {"elapsed_s": round(elapsed, 3)},
        )

        # Passive observer for the tool_calls audit table. Determine
        # ok/error from the final content shape: dispatch-raised paths
        # built a ``{"ok": False, "error": ...}`` dict above; a tool
        # returning a successful payload won't carry ``"ok": False``.
        _ok = True
        _err: str | None = None
        if isinstance(content, dict) and content.get("ok") is False:
            _ok = False
            _err = str(content.get("error") or "") or None
        self.callbacks.on_tool_done(
            name, dict(args) if isinstance(args, dict) else {},
            content, _ok, _err, round(elapsed, 6),
        )

        # Failure-signature tracking — only meaningful when the tool
        # returns an explicit failure dict. Successful calls drop out
        # of this counter via ``semantic_failure_signature``'s None
        # return.
        fail_sig = semantic_failure_signature(name, args, content)
        if fail_sig is not None:
            self._failure_signature_counts[fail_sig] = (
                self._failure_signature_counts.get(fail_sig, 0) + 1
            )

        self.messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": content if isinstance(content, str) else _stringify(content),
        })

    def _finalize_skip_final(
        self,
        tool_name: str,
        tool_result: Any,
        user_message: str,
    ) -> str:
        """Call the skip-final finalizer to phrase the tool result and
        append a synthetic assistant message for history continuity.

        Doing the append here (rather than letting the finalizer mutate
        the message list) means the next turn sees a clean
        user → assistant(tool_call) → tool → assistant transcript, even
        though the second assistant text was produced by the finalizer
        path instead of the main model loop.
        """
        self.last_skip_final = True
        try:
            answer = self.skip_final_finalizer(
                tool_name, tool_result, user_message,
            )
        except Exception as exc:  # noqa: BLE001 — finaliser bugs degrade gracefully
            answer = (
                f"[skip-final finalizer failed: {type(exc).__name__}; "
                f"raw result: {tool_result}]"
            )
        self.messages.append({"role": "assistant", "content": answer})
        self.callbacks.on_step(self.last_iteration_count + 1, self.messages[-1])
        return answer

    def _final_text_or_halt(self) -> str:
        """Return the most recent assistant text, falling back to the
        halt reason when no text exists. Used when the loop bails
        without a clean final answer (interrupt, backstop, budget)."""
        for msg in reversed(self.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]  # type: ignore[return-value]
        return f"[halted: {self.last_halt_reason or 'no response'}]"


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


def _merge_guidance(content: Any, guidance: str) -> Any:
    """Attach guardrail guidance to a tool result without losing the
    original payload. Dict gains a ``loop_guard`` key; string appends
    the guidance; anything else is wrapped. Mirrors
    :func:`jaeger_os.core.tool_guardrails.merge_guidance` so the two
    paths stay byte-compatible during migration."""
    if isinstance(content, dict):
        return {**content, "loop_guard": guidance}
    if isinstance(content, str):
        return f"{content}\n\n{guidance}"
    return {"result": content, "loop_guard": guidance}


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


__all__ = ["JaegerAgent", "SkipFinalFinalizer"]
