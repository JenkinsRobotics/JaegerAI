"""Phase-6 migration runtime bridge.

Builds a :class:`JaegerAgent` from an existing JROS client and drives
one turn through it. Designed to drop in alongside the legacy
``_run_via_iter`` path so the benchmark can A/B both — same client,
same model, same tools, different loop.

This file is **migration-only**. When pydantic-ai is gone the bridge
collapses into ``main.py`` directly and this module is deleted.

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

from jaeger_os.agent.adapters.anthropic import AnthropicAdapter
from jaeger_os.agent.adapters.base import ProviderAdapter
from jaeger_os.agent.adapters.local_llama import LocalLlamaAdapter
from jaeger_os.agent.adapters.openai import OpenAIAdapter
from jaeger_os.agent.loop.callbacks import AgentCallbacks
from jaeger_os.agent.loop.jaeger_agent import JaegerAgent
from jaeger_os.agent.schemas.message_types import Message


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
        from jaeger_os.main import _pipeline  # noqa: PLC0415 — lazy
        cfg = _pipeline.get("config")
        if cfg is None:
            return 4096
        return int(getattr(cfg.model, "max_tokens", 4096))
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
            timeout_s=timeout_s,
        )

    # Unknown client shape — caller should have caught this; raise here
    # rather than silently building the wrong adapter.
    raise RuntimeError(
        f"runtime_bridge cannot select an adapter for client "
        f"{type(client).__name__}; expected ``.llm`` or ``.ext``."
    )


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
            from jaeger_os.main import _fast_finalize_sync  # late-bind
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
    artifact_dir: Any = None,
    stale_call_timeout_s: float | None = None,
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

    ``ctx_window`` plumbs ``config.model.ctx`` into the agent's
    pre-flight :class:`ContextGuard`. When ``None`` the caller wants
    the guard disabled (legacy bench paths); otherwise a
    :class:`ContextGuard` with the matching budget is installed and
    every turn's prompt is trimmed/refused before it hits the model.

    ``artifact_dir`` (when set) is where oversized tool results are
    persisted before the in-prompt body is replaced with a preview +
    on-disk path. Typically ``<instance>/logs/tool_results``. When
    ``None``, oversized results are truncated to a preview only —
    the legacy behaviour, fine for bench / tests with no layout bound.
    """
    from jaeger_os.agent.util.context_guard import ContextBudget, ContextGuard

    adapter = _adapter_for_client(client, system_prompt=system_prompt)
    guard = (
        ContextGuard(ContextBudget(ctx_window=ctx_window, artifact_dir=artifact_dir))
        if ctx_window else None
    )
    # Default stall timeout depends on the backend. HTTP adapters do
    # well with 30s (the SDK is usually streaming or about to error
    # out). In-process llama.cpp on Metal can sit in a long prefill
    # for 60-90s on a cold load of a big model, so the default for
    # the local backend is more generous. The caller can override.
    if stale_call_timeout_s is None:
        if adapter.__class__.__name__ == "LocalLlamaAdapter":
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
        system_prompt=system_prompt,
        toolsets=toolsets,
        skip_final_tools=frozenset(skip_final_tools or ()),
        skip_final_finalizer=_make_fast_finalize_finalizer(client),
        callbacks=callbacks or AgentCallbacks(),
        max_iterations=max_iterations,
        context_guard=guard,
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
    from jaeger_os.agent.util.context_guard import ContextOverflow
    from jaeger_os.core.runtime.cloud_errors import friendly_overflow_text

    pre_len = len(agent.messages)
    started = time.perf_counter()
    try:
        answer = agent.run_turn(user_text)
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

    new_messages = agent.messages[pre_len:]
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
    }


def jaeger_agent_enabled() -> bool:
    """Single source of truth for the feature flag. Off by default —
    a stray env var won't accidentally flip production-routed runs onto
    the migration path.

    Set ``JAEGER_USE_NEW_AGENT=1`` to opt in; useful values
    (``1``, ``true``, ``yes``, ``on``) all flip it on, anything else
    keeps the legacy loop."""
    val = os.environ.get("JAEGER_USE_NEW_AGENT", "").strip().lower()
    return val in ("1", "true", "yes", "on")


__all__ = [
    "build_jaeger_agent",
    "drive_one_turn",
    "jaeger_agent_enabled",
]
