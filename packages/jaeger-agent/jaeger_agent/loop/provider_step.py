"""Extracted provider call, sticky failover & overflow recovery mixin for JaegerAgent (Wave 4B)."""
from __future__ import annotations

import time
from typing import Any

from jaeger_contracts import Message
from jaeger_loop.interrupt import AgentInterrupted, StaleCallTimeout


def _ja(name: str) -> Any:
    from . import jaeger_agent as _mod
    return getattr(_mod, name)


def _classify_adapter_error(*a: Any, **kw: Any) -> Any: return _ja("_classify_adapter_error")(*a, **kw)
def _emit_fallback(*a: Any, **kw: Any) -> Any: return _ja("_emit_fallback")(*a, **kw)
def _fallback_reachable(*a: Any, **kw: Any) -> Any: return _ja("_fallback_reachable")(*a, **kw)
def _looks_like_overflow(*a: Any, **kw: Any) -> Any: return _ja("_looks_like_overflow")(*a, **kw)
def _model_identity(*a: Any, **kw: Any) -> Any: return _ja("_model_identity")(*a, **kw)
def _policy_blocks_model(*a: Any, **kw: Any) -> Any: return _ja("_policy_blocks_model")(*a, **kw)
def _retry_delay(*a: Any, **kw: Any) -> Any: return _ja("_retry_delay")(*a, **kw)
def _scrub_surrogates_in_messages(*a: Any, **kw: Any) -> Any: return _ja("_scrub_surrogates_in_messages")(*a, **kw)


class AgentProviderStepMixin:
    """Single-step model invocation, zero-event streaming retry, sticky failover and overflow recovery."""

    def _finalize_without_tools(self, prompt: str) -> str:
        """One toolless close; a clean finish, not a halted budget failure."""
        self._close_dangling_tool_calls("finalizing")
        self._append_message({"role": "user", "content": prompt})
        self.callbacks.on_thinking("[check-in complete — writing the summary, no more tools]")
        prev_locked = self._tools_filter_locked
        prev_tools = self._all_tools
        prev_finalizing = getattr(self, "_finalizing", False)
        self._finalizing = True
        self._tools_filter_locked = True
        self._all_tools = []
        msg = None
        try:
            for attempt in range(2):
                try:
                    candidate = self._one_model_step()
                except Exception:  # noqa: BLE001 — grace call is best-effort
                    candidate = None
                if ((candidate or {}).get("content") or "").strip():
                    msg = candidate
                    break
                if attempt == 0:
                    self.callbacks.on_thinking("[finalize response empty — retrying once without tools]")
        finally:
            self._tools_filter_locked = prev_locked
            self._all_tools = prev_tools
            self._finalizing = prev_finalizing
            self._pop_message()
        text = ((msg or {}).get("content") or "").strip()
        if text:
            text = self._apply_mutation_footer(text)
            summary = {"role": "assistant", "content": text}
            self._append_message(summary)
            self.callbacks.on_step(self.last_iteration_count + 1, summary)
            self.last_halt_reason = None
            return text
        return self._halt_turn()

    def _wind_down_summary(self) -> str:
        """Iteration budget exhausted: ask the model — WITHOUT tools —
        to summarise progress in one short reply. The synthetic prompt
        comes back off the history; the summary stays as the turn's
        final assistant message. Any failure degrades to the plain
        halt path."""
        self._close_dangling_tool_calls(self.last_halt_reason or "budget")
        self._append_message({
            "role": "user", "content": f"Execution stopped: {self.last_halt_reason}.\n{self._WIND_DOWN_PROMPT}",
        })
        self.callbacks.on_thinking(
            "[iteration budget exhausted — asking the model to wrap up]"
        )
        prev_locked = self._tools_filter_locked
        prev_tools = self._all_tools
        prev_finalizing = getattr(self, "_finalizing", False)
        self._finalizing = True
        self._tools_filter_locked = True
        self._all_tools = []
        msg = None
        try:
            # Hermes' bounded finalizer retries once because an empty or
            # transiently failed synthesis should not turn a safely stopped
            # tool loop into a raw internal halt. Tools remain unavailable on
            # both attempts, so this cannot reopen execution.
            for attempt in range(2):
                try:
                    candidate = self._one_model_step()
                except Exception:  # noqa: BLE001 — grace call is best-effort
                    candidate = None
                if ((candidate or {}).get("content") or "").strip():
                    msg = candidate
                    break
                if attempt == 0:
                    self.callbacks.on_thinking(
                        "[wind-down response empty — retrying once without tools]"
                    )
        finally:
            self._tools_filter_locked = prev_locked
            self._all_tools = prev_tools
            self._finalizing = prev_finalizing
            self._pop_message()  # the synthetic wind-down prompt
        text = ((msg or {}).get("content") or "").strip()
        if text:
            text = self._apply_mutation_footer(text)
            summary = {"role": "assistant", "content": text}
            self._append_message(summary)
            self.callbacks.on_step(self.last_iteration_count + 1, summary)
            return text
        return self._halt_turn()

    def _slim_tools_to_core_for_overflow(self) -> bool:
        """One-shot: shrink visible tools to CORE when schemas alone blow ctx.

        Returns True when the catalog changed and the caller should retry the
        turn. Locked / already-slimmed agents return False (fail closed to the
        existing ContextOverflow raise path).

        Scoping is OFF by default, so mutating ``ToolSelection.inferred`` alone
        does not hide tools (``tools`` fails open via ``_tool_visibility``).
        For this emergency retry we REPLACE ``_all_tools`` with the CORE
        subset and lock the filter for the rest of the turn.
        """
        if getattr(self, "_overflow_tools_slimmed", False):
            return False
        if self._tools_filter_locked:
            return False
        try:
            from jaeger_agent.skill_registry.toolset_scoping import CORE
        except Exception:
            return False
        before = {getattr(t, "name", None) for t in (self.tools or [])}
        before.discard(None)
        if not before or before <= set(CORE):
            return False
        slimmed = [t for t in (self._all_tools or []) if getattr(t, "name", None) in CORE]
        if not slimmed or len(slimmed) >= len(before):
            return False
        self._all_tools = slimmed
        self._dispatch_by_name = {t.name: t for t in self._all_tools}
        self._tool_selection.inferred = set(CORE)
        self._tools_filter_locked = True
        self._tools_filter_locked_reason = "overflow"
        self._overflow_tools_slimmed = True
        after = {getattr(t, "name", None) for t in (self.tools or [])}
        after.discard(None)
        return len(after) < len(before)

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

    def _accumulate_usage(self, raw: Any, adapter: Any = None) -> int:
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
            self.turn_budget.observe_usage(
                prompt_tokens=per_call_prompt,
                completion_tokens=int(c) if c is not None else 0,
            )
        except (TypeError, ValueError):
            return 0
        # Persist exact provider totals when available. OpenAI-compatible
        # Ollama reports cached prompt tokens as a subset of prompt_tokens,
        # so retain them separately rather than adding them twice.
        if adapter is not None:
            try:
                details = _get("prompt_tokens_details")
                if isinstance(details, dict):
                    cached = details.get("cached_tokens", 0)
                else:
                    cached = getattr(details, "cached_tokens", 0) if details else 0
                self.callbacks.on_record_model_usage(
                    str(getattr(adapter, "provider", "") or "unknown"),
                    str(getattr(adapter, "model", "") or "unknown"),
                    prompt_tokens=per_call_prompt,
                    cached_prompt_tokens=int(cached or 0),
                    completion_tokens=int(c or 0),
                )
            except Exception:  # noqa: BLE001 — telemetry is best-effort
                pass

        return per_call_prompt

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
        # Sticky failover (jaeger-models StickyFallbackModel pattern): if a
        # fallback adapter took over within the cooldown window, keep it first
        # so subsequent steps preserve KV prompt-cache prefixes instead of
        # re-hitting a failing primary on every iteration.
        sticky_adapter = getattr(self, "_sticky_adapter", None)
        sticky_until = float(getattr(self, "_sticky_adapter_until", 0.0) or 0.0)
        if sticky_adapter is not None and sticky_adapter in adapters and time.monotonic() < sticky_until:
            adapters = [sticky_adapter, *[a for a in adapters if a is not sticky_adapter]]
        elif sticky_adapter is not None:
            self._sticky_adapter = None
            self._sticky_adapter_until = 0.0

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
            if (
                trim.dropped_count > 0
                or trim.pruned_count > 0
                or trim.inflight_pruned_count > 0
            ):
                detail = (
                    f"[context-guard] pruned {trim.pruned_count} tool "
                    f"result(s), dropped {trim.dropped_count} old "
                    f"message(s) to fit ctx budget"
                )
                if trim.inflight_pruned_count > 0:
                    # Worth calling out separately: this turn's own
                    # results were compacted, so the model is now
                    # working from stubs + artifact paths for those.
                    detail += (
                        f"; compacted {trim.inflight_pruned_count} result(s) "
                        "from the current turn (full payloads remain on disk)"
                    )
                self.callbacks.on_thinking(detail)
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
        original_budget = self.context_guard.budget if self.context_guard is not None else None
        for adapter in adapters:
            if last_exc is not None and not _fallback_reachable(adapter):
                from jaeger_events import live as _live
                _live.emit("reliability.fallback_skipped", {"adapter": getattr(adapter, "describe", lambda: type(adapter).__name__)(), "reason": "unreachable"})
                continue
            if original_budget is not None:
                from dataclasses import replace
                window = getattr(adapter, "context_window", None) or original_budget.ctx_window
                reserve = min(getattr(adapter, "max_tokens", original_budget.reserve_for_completion), max(1, window // 2))
                self.context_guard.budget = replace(original_budget, ctx_window=window, reserve_for_completion=reserve)
            attempt = 0
            while True:
                try:
                    if original_budget is not None and self.context_guard.budget != original_budget:
                        _pre_flight_trim()
                    self._refresh_tool_catalog()
                    formatted = adapter.format_messages(
                        self.messages, self.tools, self.system_prompt,
                    )
                    attach = getattr(adapter, "attach_mcp_catalog", None)
                    if callable(attach):
                        # Loopback MCP gets the full dispatchable catalog so
                        # use_tool can invoke prompt-mentioned / on-demand
                        # tools, not only the scoped schema shown this turn.
                        attach(self.all_tools)
                    if self.context_guard is not None and isinstance(formatted, dict):
                        for key in ("max_tokens", "max_completion_tokens"):
                            if key in formatted:
                                formatted[key] = min(formatted[key], self.context_guard.budget.reserve_for_completion)
                    effort_override = getattr(self, "_thinking_effort_override", None)
                    if effort_override and isinstance(formatted, dict):
                        formatted["reasoning_effort"] = effort_override
                    if not getattr(self, "_finalizing", False):
                        self.callbacks.on_tool_selection(self._selection_receipt())
                    self.callbacks.on_model_input(formatted)
                    try:  # lets the host label the step before the call returns
                        self.callbacks.model_identity = _model_identity(adapter, None)
                    except Exception:  # noqa: BLE001
                        pass
                    self.callbacks.on_model_call_start()
                    from jaeger_agent.hooks import registry as _hooks
                    _model_t0 = time.monotonic()
                    _hooks.fire("pre_model", {"model": str(getattr(adapter, "model", "") or ""),
                                              "messages": len(self.messages)})
                    before_prompt_tokens = self.last_prompt_tokens
                    before_completion_tokens = self.last_completion_tokens
                    stream_emitted = False

                    def _guarded_delta(chunk: str) -> None:
                        nonlocal stream_emitted
                        if chunk:
                            stream_emitted = True
                        self.callbacks.on_stream_delta(chunk)

                    try:
                        raw = adapter.call(
                        formatted,
                        self._interrupt_event,
                        stale_timeout=self.stale_call_timeout_s,
                        first_progress_timeout_s=getattr(adapter, "first_progress_timeout_s", self.first_progress_timeout_s),
                        execute_tool=self._execute_cli_mcp_tool if getattr(adapter, "supports", lambda _f: False)("mcp_tools") else None,
                        on_heartbeat=self._on_call_heartbeat,
                        # Token-level deltas for live consumers (TTS
                        # sentence-chunking, TUI streaming). None when
                        # nobody is listening so adapters skip the
                        # per-chunk callback cost entirely.
                        on_delta=(
                            _guarded_delta
                            if self.callbacks.stream_delta is not None
                            else None
                        ),
                        # Deliberation, streamed on its own channel as it
                        # arrives. Without this a surface got the whole answer
                        # before any of the thinking behind it — see
                        # _streamed_reasoning below.
                        on_reasoning=(
                            self._emit_streamed_reasoning
                            if self.callbacks.reasoning is not None
                            else None
                        ),
                    )
                    except BaseException as _model_exc:
                        self.callbacks.on_model_call_done({"failed": 1, **_model_identity(adapter, None),
                                                           "error": type(_model_exc).__name__})  # type: ignore[dict-item]
                        _hooks.fire("post_model", {"ok": False, "error": type(_model_exc).__name__,
                                                   "duration_ms": int((time.monotonic() - _model_t0) * 1000)})
                        raise
                    if self.last_ttft_s is None:
                        adapter_ttft = getattr(adapter, "last_ttft_s", None)
                        if adapter_ttft:
                            self.last_ttft_s = float(adapter_ttft)
                    per_call_prompt = self._accumulate_usage(raw, adapter)
                    _usage = {
                        "prompt_tokens": max(0, self.last_prompt_tokens - before_prompt_tokens),
                        "completion_tokens": max(0, self.last_completion_tokens - before_completion_tokens),
                    }
                    _cost = raw.get("cost_usd") if isinstance(raw, dict) else None
                    if isinstance(_cost, (int, float)) and not isinstance(_cost, bool):
                        _usage["cost_usd"] = float(_cost)  # type: ignore[assignment]
                    self.callbacks.on_model_call_done({**_usage, **_model_identity(adapter, raw)})  # type: ignore[dict-item]
                    _hooks.fire("post_model", {"ok": True, "usage": dict(_usage),
                                               "duration_ms": int((time.monotonic() - _model_t0) * 1000)})
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
                    if self.last_halt_reason == "stalled":
                        # A stalled attempt was retried (or a fallback adapter
                        # answered): the step recovered, so the stale flag must
                        # not halt the loop after the next tool call.
                        self.last_halt_reason = None
                    # Pin healthy fallback adapter for 60s (sticky failover)
                    if adapter is not self.primary_adapter:
                        self._sticky_adapter = adapter
                        self._sticky_adapter_until = time.monotonic() + 60.0
                    parsed = adapter.parse_response(raw)
                    if isinstance(parsed, dict) and parsed.get("finish_reason") != "thinking_exhausted":
                        self._thinking_effort_override = None
                    return parsed
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
                    # Model stalled past the no-progress budget. Retry
                    # the SAME adapter once (a 30s cloud think is often
                    # a blip), then walk the fallback chain. If this
                    # was the last adapter, the caller sees ``stalled``.
                    last_exc = exc
                    self.last_halt_reason = "stalled"
                    from jaeger_events import live as _live
                    _live.emit("reliability.timeout", {"what": "model call", "adapter": adapter.describe(),
                                                       "after_s": self.stale_call_timeout_s})
                    if attempt < self._STALE_RETRIES and not self._interrupt_event.is_set():
                        attempt += 1
                        _live.emit("reliability.retry", {"adapter": adapter.describe(), "kind": "stalled",
                                                         "attempt": attempt, "of": self._STALE_RETRIES})
                        continue
                    _emit_fallback(adapters, adapter, "stalled")
                    break  # next adapter
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
                    kind = _classify_adapter_error(exc) if not _policy_blocks_model(exc) else "policy"
                    cap = {
                        "rate_limit": self._RATE_LIMIT_RETRIES,
                        "transient": self._TRANSIENT_RETRIES,
                    }.get(kind, 0)
                    # Zero-event-safe streaming invariant (jaeger-reliability):
                    # never retry once visible deltas were already emitted.
                    if not stream_emitted and attempt < cap and not self._interrupt_event.is_set():
                        attempt += 1
                        delay = _retry_delay(kind, attempt)
                        from jaeger_events import live as _live
                        _live.emit("reliability.retry", {"adapter": adapter.describe(), "kind": str(kind).lower(),
                                                         "attempt": attempt, "of": cap, "delay_s": round(delay, 2),
                                                         "error": type(exc).__name__})
                        # Wait ON the interrupt event so a barge-in cuts
                        # the backoff short instead of sleeping through.
                        if self._interrupt_event.wait(delay):
                            self.last_halt_reason = "interrupted"
                            return {"role": "assistant", "content": None}
                        continue
                    if _policy_blocks_model(exc):
                        raise
                    _emit_fallback(adapters, adapter, f"{type(exc).__name__} ({kind.lower()})")
                    break  # next adapter
        # Every adapter raised — surface the last exception so the
        # caller (REPL, daemon) can decide what to do.
        assert last_exc is not None
        raise last_exc
