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

import re as _re
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
    loop_warning,
    semantic_failure_signature,
)
from jaeger_os.agent.schemas.message_types import Message, ToolCall
from jaeger_os.agent.schemas.tool_registry import get_tools
from jaeger_os.agent.schemas.tool_schema import ToolDef, dev_mode_enabled
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
        # Beta gating: tools marked ``beta=True`` (still stabilising —
        # avatar / animation while Mochi is the testbed) are excluded
        # from the catalogue entirely unless dev mode is on, so a
        # half-tested tool can't break a daily-driver session. An
        # explicit ``tools=[...]`` list bypasses the gate — the caller
        # picked those ToolDefs deliberately.
        if tools is not None:
            self._all_tools: list[ToolDef] = list(tools)
            self._tools_filter_locked = True   # explicit list = caller knows best
        elif toolsets is not None:
            from jaeger_os.agent.schemas.toolsets import resolve_toolsets
            wanted = resolve_toolsets(set(toolsets))
            self._all_tools = _exclude_beta(
                [t for t in get_tools() if t.name in wanted]
            )
            self._tools_filter_locked = False
        else:
            self._all_tools = _exclude_beta(get_tools())
            self._tools_filter_locked = False
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
        # Real time-to-first-token of the turn's FIRST model call (the
        # routing decision — the latency the operator feels in voice).
        # None when no adapter reported one.
        self.last_ttft_s: float | None = None

    # ── tool visibility ─────────────────────────────────────────────

    @property
    def tools(self) -> list[ToolDef]:
        """The tools visible to the model THIS turn.

        Recomputed on every access so a mid-session ``load_toolset``
        call (which mutates the shared visibility state in
        :mod:`jaeger_os.agent.skill_registry.toolsets`) takes effect on the
        next turn without rebuilding the agent. The full set the agent
        can dispatch + validate against lives in ``self._all_tools`` —
        ``describe_tool`` reads from there so the model can peek at a
        hidden tool's schema without loading the whole category."""
        if self._tools_filter_locked:
            # Caller passed ``tools=[...]`` explicitly — honour it.
            return list(self._all_tools)
        try:
            from jaeger_os.agent.skill_registry.toolsets import tool_visible
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
        # Fresh per-turn state. Counters from a previous turn would
        # falsely trip the backstop on the second message of a session.
        self._call_signature_counts.clear()
        self._failure_signature_counts.clear()
        self._read_result_hashes.clear()
        self._interrupt_event.clear()
        self._turn_messages = []
        self._post_tool_nudge_used = False
        self._nudge_pending = False
        self._failed_mutations.clear()
        self.last_halt_reason = None
        self.last_iteration_count = 0
        self.last_skip_final = False
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_ttft_s = None

        # Pick up tools registered since construction (a skill
        # activated mid-session) so they're visible AND dispatchable
        # without rebuilding the agent. No-op for explicit ``tools=``
        # agents.
        self._refresh_tool_catalog()

        # Per-turn dedupe trackers in tool modules (file_read's
        # "unchanged since last read" suppression in particular). The
        # legacy pydantic-ai loop reset this implicitly via its own
        # turn lifecycle; Phase-9 has to do it here or a *legitimate*
        # next-turn read of the same file returns an empty-stub result.
        try:
            from jaeger_os.agent.tools.files import reset_read_tracker
            reset_read_tracker()
        except Exception:  # noqa: BLE001 — never break a turn over a reset
            pass

        self._append_message({"role": "user", "content": user_message})
        self._turn_active = True
        try:
            return self._run_turn_inner(user_message)
        except ContextOverflow:
            if len(self._turn_messages) <= 1:
                # Pre-flight refusal — the model never saw this turn.
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

    def _run_turn_inner(self, user_message: str) -> str:
        """The actual loop body — see :meth:`run_turn` for the contract."""
        tool_calls_made = 0
        for iteration in range(1, self.max_iterations + 1):
            self.last_iteration_count = iteration

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
            if not tool_calls and not final_text.strip():
                # Reasoning budget exhausted: the model spent its whole
                # output allowance inside <think> and never surfaced an
                # answer. Deterministic provider/model limit — nudging
                # or retrying produces the same outcome, so surface it
                # plainly instead (Hermes thinking-exhaustion pattern).
                if assistant_msg.get("finish_reason") == "thinking_exhausted":
                    note = (
                        "[the model spent its entire output budget "
                        "thinking and never reached an answer — ask "
                        "more narrowly, or raise model.max_tokens]"
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
                # 5: model produced a final answer.
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
            # 6a: ALL-READ batches (>1 call, every tool explicitly
            # ``side_effect="read"``, none interactive) execute
            # CONCURRENTLY — wall-clock becomes the slowest call
            # instead of the sum (Hermes tool_executor pattern, gated
            # to the provably safe subset). Anything else stays
            # sequential.
            if self._batch_is_parallel_safe(tool_calls):
                tool_calls_made += len(tool_calls)
                self._dispatch_parallel(tool_calls)
                if self._interrupt_event.is_set():
                    self.last_halt_reason = "interrupted"
                    return self._halt_turn()
                halt = loop_halt_reason(
                    tool_calls_made,
                    self._call_signature_counts,
                    self._failure_signature_counts,
                )
                if halt:
                    self.last_halt_reason = halt
                    return self._halt_turn()
                continue

            seen_in_batch: dict[str, str] = {}
            for tc in tool_calls:
                tool_calls_made += 1
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
                )
                if halt:
                    self.last_halt_reason = halt
                    return self._halt_turn()

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

    def _discard_pending_nudge(self) -> None:
        """Remove the synthetic post-tool nudge from history once the
        model has answered it (or the turn is bailing). The nudge is
        plumbing, not user-authored content — it must never persist."""
        if not self._nudge_pending:
            return
        self._nudge_pending = False
        tail = self._turn_messages[-1] if self._turn_messages else None
        if tail is not None and tail.get("content") == self._POST_TOOL_NUDGE:
            self._pop_message()

    def _wind_down_summary(self) -> str:
        """Iteration budget exhausted: ask the model — WITHOUT tools —
        to summarise progress in one short reply. The synthetic prompt
        comes back off the history; the summary stays as the turn's
        final assistant message. Any failure degrades to the plain
        halt path."""
        self._close_dangling_tool_calls(self.last_halt_reason or "budget")
        self._append_message({
            "role": "user", "content": self._WIND_DOWN_PROMPT,
        })
        self.callbacks.on_thinking(
            "[iteration budget exhausted — asking the model to wrap up]"
        )
        prev_locked = self._tools_filter_locked
        prev_tools = self._all_tools
        self._tools_filter_locked = True
        self._all_tools = []
        try:
            msg = self._one_model_step()
        except Exception:  # noqa: BLE001 — grace call is best-effort
            msg = None
        finally:
            self._tools_filter_locked = prev_locked
            self._all_tools = prev_tools
            self._pop_message()  # the synthetic wind-down prompt
        text = ((msg or {}).get("content") or "").strip()
        if text:
            text = self._apply_mutation_footer(text)
            summary = {"role": "assistant", "content": text}
            self._append_message(summary)
            self.callbacks.on_step(self.last_iteration_count + 1, summary)
            return text
        return self._halt_turn()

    def _refresh_tool_catalog(self) -> None:
        """Pick up tools registered AFTER this agent was built (skill
        installed / activated mid-session) so they become visible and
        dispatchable on the next turn. Honours the construction
        contract: an explicit ``tools=[...]`` allowlist never grows;
        a ``toolsets=`` agent re-resolves its categories; a default
        agent tracks the full registry. Beta tools stay excluded
        outside dev mode (re-checked per turn, so flipping
        ``JAEGER_DEV_MODE`` doesn't need an agent rebuild)."""
        if self._tools_filter_locked:
            return
        try:
            if self.toolsets:
                from jaeger_os.agent.schemas.toolsets import resolve_toolsets
                wanted = resolve_toolsets(set(self.toolsets))
                self._all_tools = _exclude_beta(
                    [t for t in get_tools() if t.name in wanted]
                )
            else:
                self._all_tools = _exclude_beta(get_tools())
            self._dispatch_by_name = {t.name: t for t in self._all_tools}
        except Exception:  # noqa: BLE001 — a registry hiccup must not kill the turn
            pass

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
        "You have reached the tool-call budget for this turn. Stop "
        "using tools now. In one short reply: summarise what you "
        "accomplished, what remains undone, and the single next step "
        "you would take."
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
            self._append_message({"role": "assistant", "content": partial})
            self._append_message({
                "role": "user", "content": self._LENGTH_CONTINUE_NUDGE,
            })
            self.callbacks.on_thinking(
                f"[length-truncated response — continuation retry "
                f"{retries + 1}/{self._MAX_LENGTH_CONTINUE_RETRIES}]"
            )
            retries += 1
            try:
                msg = self._one_model_step()
            finally:
                # Trim the synthetic nudge turns back off the history
                # so the visible transcript only carries the final
                # stitched message — the nudges aren't user-authored
                # content. In a ``finally`` so an adapter exception
                # can't leave the synthetic turns stuck in history.
                self._pop_message()  # the nudge user turn
                self._pop_message()  # the partial assistant turn

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

    def _accumulate_usage(self, raw: Any) -> int:
        """Extract token usage from an adapter's raw response and add
        to the per-turn counters. Returns THIS call's prompt-token
        count (0 when unavailable) so the context guard can calibrate
        its estimator from real usage. Best-effort: adapters that
        don't report usage just contribute zero. Known shapes:

          * OpenAI / llama-cpp:
              ``raw["usage"] = {"prompt_tokens": N, "completion_tokens": N}``
          * Anthropic (typed object or dict):
              ``usage = {"input_tokens": N, "output_tokens": N,
                         "cache_read_input_tokens": N,
                         "cache_creation_input_tokens": N}``

        Anthropic reports CACHED prompt tokens separately from
        ``input_tokens`` — ignoring them undercounted the real prompt
        size by whatever the cache served, which skewed both the cost
        telemetry and the guard calibration.

        Never raises — token-counting is observability, not control
        flow, so a malformed response must not break the turn.
        """
        usage: Any = None
        if isinstance(raw, dict):
            usage = raw.get("usage")
        else:
            usage = getattr(raw, "usage", None)
        if usage is None:
            return 0

        def _get(key: str) -> Any:
            if isinstance(usage, dict):
                return usage.get(key)
            return getattr(usage, key, None)

        # OpenAI / llama-cpp style.
        p = _get("prompt_tokens")
        c = _get("completion_tokens")
        # Anthropic style — input_tokens EXCLUDES cache reads/writes;
        # fold them back in so the count reflects the full prompt.
        if p is None:
            p = _get("input_tokens")
            for cache_key in (
                "cache_read_input_tokens", "cache_creation_input_tokens",
            ):
                extra = _get(cache_key)
                try:
                    if p is not None and extra:
                        p = int(p) + int(extra)
                except (TypeError, ValueError):
                    pass
        if c is None:
            c = _get("output_tokens")
        per_call_prompt = 0
        try:
            if p is not None:
                per_call_prompt = int(p)
                self.last_prompt_tokens += per_call_prompt
            if c is not None:
                self.last_completion_tokens += int(c)
        except (TypeError, ValueError):
            return 0
        return per_call_prompt

    # ── stale-call timeout (Phase-8) ───────────────────────────────
    # When a provider's HTTP socket is open but no bytes are flowing,
    # the SDK can sit on the request for the full ``timeout`` (often
    # 600s) before giving up. ``StaleCallTimeout`` lets the agent's
    # adapter-fallback chain react in ~30s instead — set to ``None``
    # to disable and rely on SDK timeouts only.
    stale_call_timeout_s: float | None = 30.0

    # Per-adapter retry caps by error class (Hermes error-classifier
    # pattern, scaled down for a voice agent where long waits are dead
    # air). AUTH / NOT_FOUND never retry the same adapter — the result
    # is deterministic; the fallback chain is the recovery. UNKNOWN is
    # conservative: straight to fallback, as before.
    _RATE_LIMIT_RETRIES = 2
    _TRANSIENT_RETRIES = 1

    def _one_model_step(self) -> Message:
        """Format → call → parse, with classified retry + adapter
        fallback.

        The primary adapter is tried first. A raised exception is
        classified (``cloud_errors.classify_exception``): RATE_LIMIT
        and TRANSIENT retry the SAME adapter with jittered backoff
        (the previous behaviour — any exception → next adapter — turned
        a 2-second 429 blip into a provider switch); AUTH / NOT_FOUND /
        UNKNOWN move straight to the next adapter. Backoff sleeps wait
        on the interrupt event, so a barge-in cuts the wait short.
        ``AgentInterrupted`` short-circuits the chain — that's the
        operator cancelling, not a backend failure. ``StaleCallTimeout``
        moves to the next adapter without retry — the stale window was
        already burned once.
        """
        adapters = [self.primary_adapter, *self.fallback_adapters]

        def _pre_flight_trim() -> None:
            # Pre-flight context guard. Prune/digest/drop history until
            # the prompt fits the ctx window; if even max compaction
            # can't fit, the guard raises ``ContextOverflow`` and we
            # surface that to the caller without hitting the model.
            # Called once up front AND again after a reactive
            # ``tighten()`` so the retry actually sends a smaller
            # prompt.
            if self.context_guard is None:
                return
            trim = self.context_guard.trim_to_fit(
                self.messages,
                system_prompt=self.system_prompt,
                tools=self.tools,
            )
            if trim.dropped_count > 0 or trim.pruned_count > 0:
                self.callbacks.on_thinking(
                    f"[context-guard] pruned {trim.pruned_count} tool "
                    f"result(s), dropped {trim.dropped_count} old "
                    f"message(s) to fit ctx budget"
                )
                self.messages = trim.messages

        _pre_flight_trim()

        # Scrub lone surrogates before the wire sees the transcript —
        # one poisoned paste otherwise crashes json.dumps in the SDK on
        # every later call.
        _scrub_surrogates_in_messages(self.messages)

        last_exc: Exception | None = None
        # One reactive-compaction retry per model step: when a SERVER
        # rejects the prompt as too large (our estimator was too
        # optimistic), tighten the estimator and retry — re-running the
        # pre-flight trim with pessimistic numbers drops more history.
        # Walking the fallback chain with the same oversized prompt is
        # pointless; tightening fixes the actual cause.
        overflow_tightened = False
        for adapter in adapters:
            attempt = 0
            while True:
                try:
                    formatted = adapter.format_messages(
                        self.messages, self.tools, self.system_prompt,
                    )
                    raw = adapter.call(
                        formatted,
                        self._interrupt_event,
                        stale_timeout=self.stale_call_timeout_s,
                        on_heartbeat=self._on_call_heartbeat,
                        # Token-level deltas for live consumers (TTS
                        # sentence-chunking, TUI streaming). None when
                        # nobody is listening so adapters skip the
                        # per-chunk callback cost entirely.
                        on_delta=(
                            self.callbacks.on_stream_delta
                            if self.callbacks.stream_delta is not None
                            else None
                        ),
                    )
                    if self.last_ttft_s is None:
                        adapter_ttft = getattr(adapter, "last_ttft_s", None)
                        if adapter_ttft:
                            self.last_ttft_s = float(adapter_ttft)
                    per_call_prompt = self._accumulate_usage(raw)
                    if self.context_guard is not None and per_call_prompt:
                        try:
                            self.context_guard.observed_call(
                                per_call_prompt,
                                self.messages,
                                system_prompt=self.system_prompt,
                                tools=self.tools,
                            )
                        except Exception:  # noqa: BLE001 — calibration is best-effort
                            pass
                    return adapter.parse_response(raw)
                except AgentInterrupted:
                    # Interrupt propagates — handled by ``run_turn`` via
                    # the event check at the top of the next iteration.
                    # Set the halt reason here so observers (TUI status,
                    # latency log, voice loop's "cancel actually took
                    # effect" check) can distinguish a user cancel from a
                    # clean finish even though run_turn returns whatever
                    # text was assembled.
                    self._interrupt_event.set()
                    self.last_halt_reason = "interrupted"
                    return {"role": "assistant", "content": None}
                except StaleCallTimeout as exc:
                    # Model stalled past the no-progress budget. For
                    # in-process backends the abort flag has already
                    # stopped the decode and reset the context (see
                    # LocalLlamaAdapter.call); an HTTP fallback (if
                    # configured) picks up next. If this was the last
                    # adapter, the caller sees a clean ``stalled`` halt
                    # reason rather than a generic exception.
                    last_exc = exc
                    self.last_halt_reason = "stalled"
                    self.callbacks.on_thinking(
                        f"[adapter {adapter.describe()} stalled after "
                        f"{self.stale_call_timeout_s:.0f}s; "
                        f"try ``jaeger kill`` from another terminal "
                        f"if the TUI feels stuck]"
                    )
                    break  # next adapter — the stale window was burned
                except Exception as exc:  # noqa: BLE001 — adapter chain absorbs
                    last_exc = exc
                    if (
                        not overflow_tightened
                        and self.context_guard is not None
                        and _looks_like_overflow(exc)
                    ):
                        overflow_tightened = True
                        self.context_guard.tighten()
                        self.callbacks.on_thinking(
                            "[server rejected the prompt as too large — "
                            "tightening the context estimator and "
                            "re-trimming]"
                        )
                        _pre_flight_trim()
                        continue  # same adapter, freshly trimmed prompt
                    kind = _classify_adapter_error(exc)
                    cap = {
                        "rate_limit": self._RATE_LIMIT_RETRIES,
                        "transient": self._TRANSIENT_RETRIES,
                    }.get(kind, 0)
                    if attempt < cap and not self._interrupt_event.is_set():
                        attempt += 1
                        delay = _retry_delay(kind, attempt)
                        self.callbacks.on_thinking(
                            f"[adapter {adapter.describe()} "
                            f"{kind.lower().replace('_', ' ')} — retry "
                            f"{attempt}/{cap} in {delay:.1f}s]"
                        )
                        # Wait ON the interrupt event so a barge-in cuts
                        # the backoff short instead of sleeping through.
                        if self._interrupt_event.wait(delay):
                            self.last_halt_reason = "interrupted"
                            return {"role": "assistant", "content": None}
                        continue
                    self.callbacks.on_thinking(
                        f"[adapter {adapter.describe()} failed: "
                        f"{type(exc).__name__} ({kind.lower()})]"
                    )
                    break  # next adapter
        # Every adapter raised — surface the last exception so the
        # caller (REPL, daemon) can decide what to do.
        assert last_exc is not None
        raise last_exc

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

    def _batch_is_parallel_safe(self, tool_calls: list[ToolCall]) -> bool:
        """A batch may run concurrently only when EVERY call resolves to
        a tool explicitly classified ``side_effect="read"`` and not
        interactive. Unclassified tools are treated as write-side —
        conservative by construction."""
        if len(tool_calls) < 2:
            return False
        for tc in tool_calls:
            tool_def = self._dispatch_by_name.get(tc.get("name") or "")
            if tool_def is None:
                return False
            if getattr(tool_def, "side_effect", "") != "read":
                return False
            if getattr(tool_def, "interactive", False):
                return False
        return True

    def _dispatch_parallel(self, tool_calls: list[ToolCall]) -> None:
        """Execute an all-read batch concurrently.

        Prepare and finish stay SERIAL and in batch order (callbacks,
        backstop counters, and the transcript are order-sensitive);
        only the tool functions themselves run on the pool. Duplicate
        signatures execute once — later twins reuse the first result
        via a duplicate marker, same as the sequential path.
        """
        from concurrent.futures import ThreadPoolExecutor

        preps = [self._prepare_dispatch(tc) for tc in tool_calls]
        first_by_sig: dict[str, int] = {}
        unique_idx: list[int] = []
        for i, prep in enumerate(preps):
            if prep["sig"] not in first_by_sig:
                first_by_sig[prep["sig"]] = i
                unique_idx.append(i)

        contents: dict[int, Any] = {}
        with ThreadPoolExecutor(
            max_workers=min(4, len(unique_idx)),
            thread_name_prefix="jaeger-tool",
        ) as pool:
            futures = {
                i: pool.submit(self._execute_prepared, preps[i])
                for i in unique_idx
            }
            for i, fut in futures.items():
                try:
                    contents[i] = fut.result()
                except Exception as exc:  # noqa: BLE001 — belt: execute() shouldn't raise
                    contents[i] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "error_type": "tool_error",
                        "retryable": True,
                    }

        for i, prep in enumerate(preps):
            owner = first_by_sig[prep["sig"]]
            if owner == i:
                self._finish_dispatch(prep, contents[owner])
            else:
                self._append_message({
                    "role": "tool",
                    "tool_call_id": prep["call_id"],
                    "name": prep["name"],
                    "content": _stringify({
                        "ok": True,
                        "duplicate_of": preps[owner]["call_id"] or "(first)",
                        "note": (
                            "identical call deduplicated this "
                            "iteration — see that result"
                        ),
                    }),
                })

    def _prepare_dispatch(self, tc: ToolCall) -> dict[str, Any]:
        """Serial pre-dispatch step: name normalisation, backstop
        pre-count for write-side tools, start callback, pre-dispatch
        guardrail hook."""
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

        # Backstop bookkeeping. Write-side tools are counted *before*
        # dispatch so a tight loop trips the ceiling immediately rather
        # than after one extra wasted call. READ tools defer to the
        # post-dispatch result-hash check in ``_finish_dispatch`` —
        # re-issuing the same read while the answer is CHANGING is
        # legitimate polling, not a loop, so only a same-result repeat
        # counts.
        sig = call_signature(name, args)
        tool_def = dispatch_map.get(name)
        is_read_tool = (
            tool_def is not None
            and getattr(tool_def, "side_effect", "") == "read"
        )
        if not is_read_tool:
            self._call_signature_counts[sig] = (
                self._call_signature_counts.get(sig, 0) + 1
            )

        started = time.perf_counter()
        self.callbacks.on_tool_progress(name, "start", args)
        # Pre-dispatch hook — guardrail returns optional guidance text.
        guidance = self.callbacks.on_before_tool_call(name, args)
        return {
            "name": name,
            "args": args,
            "call_id": call_id,
            "sig": sig,
            "tool_def": tool_def,
            "is_read": is_read_tool,
            "guidance": guidance,
            "started": started,
        }

    def _execute_prepared(self, prep: dict[str, Any]) -> Any:
        """The actual tool call — the only part safe to run off-thread
        for read-only tools. Exceptions become error-result dicts."""
        name = prep["name"]
        args = prep["args"]
        try:
            tool_def = prep["tool_def"]
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
        return content

    def _finish_dispatch(self, prep: dict[str, Any], content: Any) -> None:
        """Serial post-dispatch step: truncation, hooks, observability,
        backstop counting, warning injection, append. Must run in batch
        order — counters and the transcript are order-sensitive."""
        name = prep["name"]
        args = prep["args"]
        call_id = prep["call_id"]
        sig = prep["sig"]
        is_read_tool = prep["is_read"]
        guidance = prep["guidance"]
        started = prep["started"]

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

        # File-mutation verifier bookkeeping: remember failures per
        # (tool, path); a later SUCCESS on the same target supersedes.
        # Un-superseded failures surface in the final-answer footer.
        if name in _MUTATION_TOOLS:
            target = ""
            if isinstance(args, dict):
                target = str(args.get("path") or args.get("file") or "")
            mkey = (name, target)
            if _ok:
                self._failed_mutations.pop(mkey, None)
            else:
                self._failed_mutations[mkey] = (_err or "failed")[:120]

        # Failure-signature tracking — only meaningful when the tool
        # returns an explicit failure dict. Successful calls drop out
        # of this counter via ``semantic_failure_signature``'s None
        # return.
        fail_sig = semantic_failure_signature(name, args, content)
        if fail_sig is not None:
            self._failure_signature_counts[fail_sig] = (
                self._failure_signature_counts.get(fail_sig, 0) + 1
            )

        # Deferred identical-call counting for READ tools: a repeat
        # only counts when the result is byte-identical to the last
        # one (no progress). A changed result resets the streak.
        if is_read_tool:
            result_hash = _hash_result(content)
            if self._read_result_hashes.get(sig) == result_hash:
                self._call_signature_counts[sig] = (
                    self._call_signature_counts.get(sig, 0) + 1
                )
            else:
                self._read_result_hashes[sig] = result_hash
                self._call_signature_counts[sig] = 1

        # Warn-before-halt: when this call is one step from tripping
        # the backstop, ride guidance on the result so the model can
        # change course instead of dying at the halt. Never blocks.
        warning = loop_warning(
            self._call_signature_counts,
            self._failure_signature_counts,
            sig=sig,
            fail_sig=fail_sig,
        )
        if warning:
            content = _merge_guidance(content, warning)

        self._append_message({
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
        self._append_message({"role": "assistant", "content": answer})
        self.callbacks.on_step(self.last_iteration_count + 1, self.messages[-1])
        return answer

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
    "write_file", "patch", "append_file", "delete_file",
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
    """Classify an adapter exception for the retry policy. Delegates to
    :mod:`jaeger_os.core.runtime.cloud_errors` (HTTP status + class-name
    heuristics); degrades to ``UNKNOWN`` if the classifier itself is
    unavailable or chokes — UNKNOWN means "no retry, next adapter",
    which is the pre-classification behaviour."""
    try:
        from jaeger_os.core.runtime.cloud_errors import classify_exception
        return classify_exception(exc)
    except Exception:  # noqa: BLE001 — classification must never mask the error
        return "unknown"


def _retry_delay(kind: str, attempt: int) -> float:
    """Jittered backoff sized for a VOICE agent — long waits are dead
    air, so the caps are far below Hermes' server-side defaults. Rate
    limits get room to clear (~2-8s); transient blips retry almost
    immediately (~1-2s)."""
    from jaeger_os.agent.util.retry_utils import jittered_backoff
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


__all__ = ["JaegerAgent", "SkipFinalFinalizer"]
