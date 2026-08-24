"""JaegerAI product adapter for the reusable JaegerAgent runtime.

Builds a :class:`JaegerAgent` from an existing JROS client and drives
one turn through it. JaegerAgent owns the loop and provider contracts;
this application-owned file selects JaegerAI's configured client, prompt,
tool policy, and persistence callbacks.

The bridge owns these decisions:

  • adapter selection from a JROS client (``LocalLlamaAdapter`` for the
    in-process ``LlamaCppPythonClient`` shape; ``AnthropicAdapter`` /
    ``OpenAIAdapter`` for ``ExternalModelClient``)
  • per-session ``JaegerAgent`` caching — one agent per session key so
    history accumulates across turns
  • the skip-final finalizer that calls back into ``client.chat`` for
    the bounded paraphrasing pass (same shape as the legacy
    ``_fast_finalize_sync``)
  • the latency-row payload shape returned to the caller, so
    ``run_command`` writes the same JSONL schema the benchmark reads.

It does **not** own the print formatting, the latency-report dataclass
construction, the episodic-memory write, or session-history clamping —
those stay in ``main.py`` so legacy and new paths share one set of
side effects.
"""

from __future__ import annotations

import os
import time
from typing import Any

from jaeger_agent import AgentCallbacks, JaegerAgent
from jaeger_agent.adapters.anthropic import AnthropicAdapter
from jaeger_agent.adapters.base import ProviderAdapter
from jaeger_agent.adapters.local_llama import LocalLlamaAdapter
from jaeger_agent.adapters.openai import OpenAIAdapter
from jaeger_agent.schemas.message_types import Message


def _resolve_local_max_tokens() -> int:
    """Read ``model.max_tokens`` off the active pipeline config so the
    in-process adapter honours it. Falls back to the
    :class:`LocalLlamaAdapter` default (4096) when there's no config to
    read — same behaviour as 0.1.0, so a missing pipeline (early boot,
    unit tests with no config) doesn't surprise anyone.

    This closes a real 0.1.0 hole: the local model adapter accepted
    ``max_tokens`` in its constructor but no caller actually passed it,
    so every agent turn was capped at the hardcoded 4096 regardless of
    what the user put in ``config.yaml:model.max_tokens``. The field
    didn't even exist on the local ``ModelConfig`` schema — added in
    0.2.0 alongside this plumbing."""
    try:
        from jaeger_ai.main import _pipeline
        cfg = _pipeline.get("config")
        if cfg is None:
            return 4096
        return int(cfg.model.max_tokens)
    except Exception:  # noqa: BLE001 — never block adapter construction
        return 4096


def _resolve_thinking_env() -> bool | None:
    """``JAEGER_BENCH_THINKING`` env → ``enable_thinking`` adapter arg.

    Values (case-insensitive):
      * ``""`` / ``auto`` / ``default`` → ``None`` (model's default mode,
        unchanged behaviour — this is the baseline)
      * ``on`` / ``true`` / ``1`` → ``True`` (force thinking ON)
      * ``off`` / ``false`` / ``0`` → ``False`` (force thinking OFF)

    Lets the benchmark run a hybrid model twice — once each mode — and
    show the deep-think vs direct-mode tradeoff side-by-side, the way
    Claude / GPT-o1 expose ``thinking`` per call."""
    raw = (os.environ.get("JAEGER_BENCH_THINKING") or "").strip().lower()
    if raw in ("", "auto", "default", "none"):
        return None
    if raw in ("on", "true", "1", "yes"):
        return True
    if raw in ("off", "false", "0", "no"):
        return False
    return None  # unrecognised value → safe default


def _adapter_for_client(
    client: Any,
    *,
    system_prompt: str = "",
) -> ProviderAdapter:
    """Map a JROS client object onto the adapter that owns its wire
    format. Three branches today; one per concrete client class.

    The detection is **duck-typed** rather than class-checked so we
    don't drag in optional dependencies just to ``isinstance`` against
    them. ``client.llm`` is the in-process llama-cpp ``Llama``;
    ``client.ext`` is the dataclass on the external client.
    """
    # In-process llama-cpp: there's no HTTP, no API key, the model is
    # already loaded and warmed.
    llm = getattr(client, "llm", None)
    if llm is not None:
        return LocalLlamaAdapter(
            model=getattr(client, "model_name", "local"),
            llama=llm,
            enable_thinking=_resolve_thinking_env(),
            max_tokens=_resolve_local_max_tokens(),
            # Run GGUF generation on the client's persistent single thread
            # (uniform with MLX; serializes decode on the shared llama-cpp
            # instance). A 4-round A/B (2026-06-18) confirmed no throughput
            # cost vs. the old fresh-thread-per-call path — so it's the
            # default. Both local backends now share one inference-worker model.
            executor=getattr(client, "_executor", None),
        )

    # In-process MLX (config ``model.backend: mlx_lm`` →
    # ``MlxClient``): reuse the client's already-loaded model+tokenizer
    # pair so the weights never load twice. Previously this client
    # shape fell through to the RuntimeError below — the MLX backend
    # could not reach the agent loop at all.
    mlx_model = getattr(client, "_mlx_model", None)
    if mlx_model is not None:
        from jaeger_agent.adapters.mlx import MLXAdapter
        return MLXAdapter(
            model=mlx_model,
            tokenizer=getattr(client, "_tokenizer", None),
            model_name=getattr(client, "model_name", "mlx"),
            defaults={"max_tokens": _resolve_local_max_tokens()},
            # MLX is thread-affine — generation must run on the SAME thread
            # the model loaded on (the client's single-worker executor).
            mlx_executor=getattr(client, "_executor", None),
            # mlx-vlm clients (multimodal / unified models) route generation
            # through mlx-vlm instead of mlx-lm; the adapter detects this.
            is_vlm=getattr(client, "is_vlm", False),
            vlm_config=getattr(client, "_config", None),
        )

    ext = getattr(client, "ext", None)
    if ext is not None:
        provider = getattr(ext, "provider", "openai")
        model = getattr(ext, "model", "")
        api_key = getattr(client, "_api_key", "") or ""
        timeout_s = float(getattr(ext, "timeout_s", 60.0) or 60.0)
        if provider == "anthropic":
            return AnthropicAdapter(
                api_key=api_key,
                model=model,
                timeout_s=timeout_s,
            )
        # Everything else (openai, gemini, ollama, ollama-cloud,
        # lmstudio) rides the OpenAI-compat surface.
        return OpenAIAdapter(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=getattr(ext, "base_url", None),
            num_ctx=getattr(client, "num_ctx", None),
            timeout_s=timeout_s,
        )

    # Unknown client shape — caller should have caught this; raise here
    # rather than silently building the wrong adapter.
    raise RuntimeError(
        f"runtime_bridge cannot select an adapter for client "
        f"{type(client).__name__}; expected ``.llm`` or ``.ext``."
    )


def _fallback_adapters_for(client: Any) -> list[ProviderAdapter]:
    """Configured ``external_model.fallback`` → extra adapters.

    Same API key / timeout as the primary client. Skips the serving
    model so a stall actually walks to a *different* brain.
    """
    try:
        from jaeger_ai.main import _pipeline
        cfg = _pipeline.get("config")
        rows = list(getattr(getattr(cfg, "external_model", None), "fallback", None) or [])
    except Exception:  # noqa: BLE001 — missing config is "no fallback"
        return []
    if not rows:
        return []
    ext = getattr(client, "ext", None)
    primary_model = str(getattr(ext, "model", "") or "")
    primary_provider = str(getattr(ext, "provider", "") or "openai")
    api_key = getattr(client, "_api_key", "") or ""
    timeout_s = float(getattr(ext, "timeout_s", 60.0) or 60.0) if ext else 60.0
    num_ctx = getattr(client, "num_ctx", None)
    primary_base = getattr(ext, "base_url", None) if ext is not None else None
    out: list[ProviderAdapter] = []
    for row in rows:
        if isinstance(row, dict):
            provider = str(row.get("provider") or primary_provider)
            model = str(row.get("model") or "")
            base_url = row.get("base_url") or primary_base
        else:
            provider = str(getattr(row, "provider", None) or primary_provider)
            model = str(getattr(row, "model", "") or "")
            base_url = getattr(row, "base_url", None) or primary_base
        if not model or model == primary_model:
            continue
        if provider == "anthropic":
            out.append(AnthropicAdapter(
                api_key=api_key, model=model, timeout_s=timeout_s,
            ))
        else:
            out.append(OpenAIAdapter(
                provider=provider, model=model, api_key=api_key,
                base_url=base_url or None, num_ctx=num_ctx,
                timeout_s=timeout_s,
            ))
    return out


def _make_fast_finalize_finalizer(client: Any) -> Any:
    """Wrap the legacy ``_fast_finalize_sync`` so it satisfies the
    :data:`SkipFinalFinalizer` callable signature.

    Looked up **lazily on every call** rather than captured at build
    time — keeps the bridge compatible with ``main.py`` hot-reload (the
    test suite monkey-patches the legacy formatter to exercise error
    paths) and avoids an import-cycle if ``main.py`` is mid-import when
    the bridge is first reached.
    """
    def _finalize(tool_name: str, tool_result: Any, user_message: str) -> str:
        # ``tool_result`` from the agent loop is a stringified JSON
        # blob; decode if possible so the legacy formatter sees the
        # original dict it expects.
        decoded: Any = tool_result
        if isinstance(tool_result, str):
            try:
                import json
                decoded = json.loads(tool_result)
            except (TypeError, ValueError):
                decoded = tool_result
        try:
            from jaeger_ai.main import _fast_finalize_sync  # late-bind
            return _fast_finalize_sync(client, user_message, tool_name, decoded)
        except Exception as exc:  # noqa: BLE001 — finalizer must never crash a turn
            return f"[finalize fallback: {type(exc).__name__}] {decoded}"

    return _finalize


def build_jaeger_agent(
    client: Any,
    *,
    system_prompt: str = "",
    toolsets: set[str] | frozenset[str] | list[str] | None = None,
    skip_final_tools: set[str] | frozenset[str] | None = None,
    callbacks: AgentCallbacks | None = None,
    max_iterations: int = 24,
    ctx_window: int | None = None,
    completion_reserve: int | None = None,
    artifact_dir: Any = None,
    stale_call_timeout_s: float | None = None,
    context_summarizer: Any = None,
) -> JaegerAgent:
    """Construct a :class:`JaegerAgent` wired against the provided
    JROS client. The skip-final finalizer is the legacy bounded-chat
    paraphraser so phrasing stays identical to the pre-refactor path.

    ``max_iterations=24`` matches the legacy ``_MAX_TOOL_CALLS`` ceiling
    so the loop backstop trips at the same point and the benchmark
    measures the same boundary.

    ``toolsets`` (Phase 7): when provided, the agent's tool catalogue
    is filtered to just those Hermes-style groups. When ``None``
    (default) every registered tool is exposed — useful for the
    transition period but burns ~10K tokens of schema per turn.

    ``ctx_window`` plumbs the SERVING model's context window into the
    agent's pre-flight :class:`ContextGuard` — ``external_model.ctx``
    when a cloud model is answering, ``model.ctx`` for the local worker
    lane. When ``None`` the caller wants the guard disabled (legacy
    bench paths); otherwise a :class:`ContextGuard` with the matching
    budget is installed and every turn's prompt is trimmed/refused
    before it hits the model.

    ``completion_reserve`` is the configured ``max_tokens`` for that
    same lane, held back from the prompt budget so the answer has room
    inside the one window the server counts both against.

    ``artifact_dir`` (when set) is where oversized tool results are
    persisted before the in-prompt body is replaced with a preview +
    on-disk path. Typically ``<instance>/logs/tool_results``. When
    ``None``, oversized results are truncated to a preview only —
    the legacy behaviour, fine for bench / tests with no layout bound.
    """
    from jaeger_agent.schemas.tool_bundles import resolve_toolsets
    from jaeger_agent.skill_registry.toolset_scoping import tool_visible
    from jaeger_agent.util.context_guard import ContextBudget, ContextGuard

    def _reset_turn_state() -> None:
        from jaeger_agent.tools.files import reset_read_tracker

        reset_read_tracker()

    adapter = _adapter_for_client(client, system_prompt=system_prompt)
    guard = None
    if ctx_window:
        # ``completion_reserve`` is the caller's configured ``max_tokens``.
        # The server counts prompt + completion against ONE window, so a
        # reserve smaller than the answer we asked for overflows at
        # generation time even though the prompt itself fit. Falls back to
        # the dataclass default when the caller has nothing to say.
        reserve_kwargs: dict[str, Any] = {}
        if completion_reserve and completion_reserve > 0:
            # Never let the reserve eat the whole window: a misconfigured
            # max_tokens >= ctx would leave a zero prompt budget and refuse
            # every turn. Half the window is the most an answer may claim.
            reserve_kwargs["reserve_for_completion"] = min(
                int(completion_reserve), max(1, ctx_window // 2),
            )
        budget = ContextBudget(
            ctx_window=ctx_window, artifact_dir=artifact_dir, **reserve_kwargs,
        )
        # Scale the per-tool-result cap to the window. The dataclass
        # default (24K chars ≈ 8K tokens) EXCEEDS the entire prompt
        # budget at ctx=8192 — one big ``run_shell`` dump would blow
        # the window in a single result and crash the turn with a
        # mid-flight overflow. Cap a single result at ~¼ of the
        # prompt budget instead, floored so tiny test windows still
        # keep something useful.
        per_result_cap = int(
            budget.prompt_budget * budget.chars_per_token / 4
        )
        per_result_cap = max(2_000, per_result_cap)
        if per_result_cap < budget.max_tool_result_chars:
            budget = ContextBudget(
                ctx_window=ctx_window,
                artifact_dir=artifact_dir,
                max_tool_result_chars=per_result_cap,
                **reserve_kwargs,
            )
        # ``context_summarizer`` upgrades stage-2 compaction from the
        # deterministic digest to an LLM-written one. Costs a model
        # call — callers wire it ONLY for latency-free contexts
        # (deep think), never the voice path.
        guard = ContextGuard(budget, summarizer=context_summarizer)
    # Default stall timeout depends on the backend. HTTP adapters do
    # well with 30s (the SDK is usually streaming or about to error
    # out). In-process llama.cpp on Metal can sit in a long prefill
    # for 60-90s on a cold load of a big model, so the default for
    # the local backend is more generous. The caller can override.
    if stale_call_timeout_s is None:
        if adapter.__class__.__name__ in ("LocalLlamaAdapter", "MLXAdapter"):
            # Cold prefill on a 30B Q4 can take ~60s; allow headroom
            # for an unusual prompt without false-positive stall
            # alarms during legitimate slow decodes. The pathological
            # hang we're guarding against is multi-minute, so 120s
            # catches it cleanly while letting normal work finish.
            stale_call_timeout_s = 120.0
        else:
            stale_call_timeout_s = 30.0
    agent = JaegerAgent(
        adapter=adapter,
        fallback_adapters=_fallback_adapters_for(client),
        system_prompt=system_prompt,
        toolsets=toolsets,
        skip_final_tools=frozenset(skip_final_tools or ()),
        skip_final_finalizer=_make_fast_finalize_finalizer(client),
        callbacks=callbacks or AgentCallbacks(),
        max_iterations=max_iterations,
        context_guard=guard,
        toolset_resolver=resolve_toolsets,
        tool_visibility=tool_visible,
        turn_start_hook=_reset_turn_state,
    )
    agent.stale_call_timeout_s = stale_call_timeout_s
    return agent


def _tool_activity_lines(messages: list[Message]) -> list[str]:
    """Render the same one-line-per-tool-call activity strings the
    legacy ``_walk_new_messages`` printed. Matches the ``▸ tool(args)``
    shape so the TUI / latency log stays unchanged across the
    migration."""
    lines: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in (msg.get("tool_calls") or []):
            name = tc.get("name") or ""
            args = tc.get("arguments") or {}
            if isinstance(args, dict) and args:
                args_repr = ", ".join(
                    f"{k}={v!r}" for k, v in list(args.items())[:2]
                )
            else:
                args_repr = ""
            lines.append(f"  ▸ {name}({args_repr})")
    return lines


def _first_decision_from(messages: list[Message]) -> dict[str, Any] | None:
    """Pluck the (tool, args) of the first tool call this turn. Used by
    the latency log to record the model's first routing decision —
    mirrors the legacy ``first_decision`` field byte-for-byte so the
    benchmark's per-prompt analysis still keys off the same field."""
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            tc = tool_calls[0]
            return {"tool": tc.get("name", ""), "args": tc.get("arguments") or {}}
    return None


def _run_turn_with_executive(agent: JaegerAgent, user_text: str) -> str:
    """Persist the run when state.db is bound; otherwise just the loop."""
    from jaeger_agent.memory import sqlite_store

    if not sqlite_store.is_bound():
        return agent.run_turn(user_text)
    from jaeger_agent.cognition.executive import TurnExecutive
    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore

    return TurnExecutive(
        agent,
        SqliteRunStore(),
        SqliteCommitmentStore(),
        provider=getattr(agent.primary_adapter, "name", None),
        claims=SqliteKnowledgeStore(),
    ).run_turn(user_text)


def drive_one_turn(
    agent: JaegerAgent,
    user_text: str,
) -> dict[str, Any]:
    """Run one turn through the new agent and return a dict shaped like
    the legacy ``_run_with_fix_loop`` output (the bits the latency log
    cares about). The schema:

      • ``answer``         — final assistant text
      • ``tool_activity``  — ``["  ▸ tool(args)", …]``
      • ``first_decision`` — ``{"tool": name, "args": dict} | None``
      • ``elapsed_s``      — wall-clock for the turn
      • ``skipped``        — True when skip-final fired
      • ``halt_reason``    — None on clean finish; string on backstop hit
      • ``iterations``     — agent-loop iteration count
      • ``new_messages``   — the ``Message`` slice produced this turn
        (for history extension)
    """
    from jaeger_agent.errors import friendly_overflow_text
    from jaeger_agent.util.context_guard import ContextOverflow

    started = time.perf_counter()
    try:
        answer = _run_turn_with_executive(agent, user_text)
    except ContextOverflow as overflow:
        # Pre-flight refusal — the prompt couldn't be trimmed enough to
        # fit. Surface an actionable message and end the turn cleanly
        # so the TUI doesn't see a backtrace.
        elapsed = time.perf_counter() - started
        return {
            "answer": friendly_overflow_text(
                estimated=overflow.estimated,
                budget=overflow.budget,
                system_prompt_tokens=overflow.system_prompt_tokens,
                tools_tokens=overflow.tools_tokens,
                latest_user_tokens=overflow.latest_user_tokens,
            ),
            "tool_activity": [],
            "first_decision": None,
            "elapsed_s": elapsed,
            "skipped": False,
            "halt_reason": "context_overflow",
            "iterations": 0,
            "new_messages": [],
        }
    elapsed = time.perf_counter() - started

    # The per-turn slice comes from the agent's own bookkeeping, NOT
    # from ``messages[pre_len:]`` — the context guard can rebind
    # ``agent.messages`` to a head-trimmed copy mid-turn, which made a
    # length recorded at turn start overshoot and silently drop this
    # turn's messages from the slice (history extension then lost the
    # turn entirely).
    new_messages = agent.last_turn_messages
    return {
        "answer": answer,
        "tool_activity": _tool_activity_lines(new_messages),
        "first_decision": _first_decision_from(new_messages),
        "elapsed_s": elapsed,
        "skipped": agent.last_skip_final,
        "halt_reason": agent.last_halt_reason,
        "iterations": agent.last_iteration_count,
        "new_messages": new_messages,
        # Real token counts when the adapter reported usage; 0 when
        # the adapter doesn't expose it (the bench falls back to a
        # whitespace-split estimate in that case).
        "prompt_tokens": agent.last_prompt_tokens,
        "completion_tokens": agent.last_completion_tokens,
        # Real time-to-first-token of the turn's first model call —
        # None when no adapter reported one (test stubs, plain create).
        "ttft_s": agent.last_ttft_s,
    }


__all__ = [
    "build_jaeger_agent",
    "drive_one_turn",
]
