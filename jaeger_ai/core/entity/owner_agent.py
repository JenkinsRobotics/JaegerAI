"""How the OWNER process builds the agent for a Gateway turn.

The Gateway's turn path (``EntityRuntime.run_subordinate_react``) used to
build its ``JaegerAgent`` with only a client and callbacks. Compared with the
CLI session agent (``jaeger_ai.main._ensure_session_agent``) that meant:

* no system prompt at all — the model never saw the Three Laws, the
  framework directive, SOUL.md or AGENTS.md;
* every registered tool's schema on every call (119 tools, ~80k chars,
  ~20k tokens) — a local model spent most of its window and prefill time
  on schemas (local-capability run 2026-10-09: median 21.4k tokens/call);
* no context guard and no tool-result artifacts;
* none of main's built-in tools (``delegate_task``, ``list_delegate_runtimes``
  …), because they register through ``main._get_agent``, which the owner
  process never calls — ``delegate_task`` was "not found".

:func:`owner_agent_options` supplies the same ingredients the CLI agent gets.
The OWNER process never boots ``main._pipeline``; the few keys main's tools
read (``layout``, ``config``, ``system_prompt``) are filled in here, and only
when nothing else booted the pipeline.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_registered_for: tuple[Any, ...] | None = None
_prompt_cache: dict[str, str] = {}
_owns_pipeline: bool | None = None

#: Providers whose model runs on this host (or the operator's LAN box).
LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio", "lm_studio", "llamacpp", "llama.cpp",
                             "local", "mlx", "vllm-local"})


def is_local_client(client: Any) -> bool:
    """True when the turn is served by a local model (the lean lane)."""
    if getattr(client, "kind", None) not in (None, "external"):
        return True  # in-process llama.cpp / MLX worker
    provider = str(getattr(client, "provider", "") or "").strip().lower()
    model = str(getattr(client, "model_name", "") or "").strip().lower()
    if provider not in LOCAL_PROVIDERS:
        return False
    # Ollama also fronts cloud models (``glm-5.1:cloud``); those keep the
    # full surface.
    return not (model.endswith(":cloud") or model.endswith("-cloud"))


def _prompt_signature(layout: Any) -> str:
    try:
        from jaeger_ai.core.instance.instance import context_document_signature
        from jaeger_ai.features.personality.character import active_character_signature
        return f"{layout.root}:{active_character_signature(layout.root)}:{context_document_signature(layout.root)}"
    except Exception:  # noqa: BLE001 — signature is a cache key only
        return str(getattr(layout, "root", ""))


def _system_prompt(main: Any, layout: Any) -> str:
    sig = _prompt_signature(layout)
    cached = _prompt_cache.get(sig)
    if cached is None:
        cached = main.build_system_prompt(layout)
        _prompt_cache.clear()
        _prompt_cache[sig] = cached
    return cached


def owner_agent_options(layout: Any, cfg: Any, client: Any) -> dict[str, Any]:
    """Keyword arguments for ``build_jaeger_agent`` on the OWNER turn path."""
    global _registered_for, _owns_pipeline
    import jaeger_ai.main as main

    with _lock:
        pipeline = main._pipeline
        if _owns_pipeline is None:
            _owns_pipeline = pipeline.get("layout") is None
        prompt = _system_prompt(main, layout)
        if _owns_pipeline:
            pipeline["layout"] = layout
            pipeline["config"] = cfg
            pipeline["system_prompt"] = prompt
        key = (id(layout), getattr(client, "provider", None), getattr(client, "model_name", None))
        if _registered_for != key:
            # delegate_task & co. close over the client; re-register when the
            # serving model changes, as main._get_agent does.
            main._register_builtins(client)
            _registered_for = key
    try:
        ctx, reserve = main._context_budget_for(cfg)
    except Exception:  # noqa: BLE001 — budget is a guard, never a blocker
        ctx, reserve = None, None
    logs = Path(getattr(layout, "logs_dir", Path(layout.root) / "logs"))
    full_tools = os.environ.get("JAEGER_FULL_TOOLS", "").strip().lower() in {"1", "true", "yes"}
    return {
        "system_prompt": prompt,
        "ctx_window": ctx,
        "completion_reserve": reserve,
        "artifact_dir": logs / "tool_results",
        "skip_final_tools": getattr(main, "SKIP_FINAL_TOOLS", None),
        # Local models route far better over the curated CORE surface plus
        # list_tools/load_tools than over the full catalogue.
        "scope_tools": is_local_client(client) and not full_tools,
    }


def _reset_for_tests() -> None:
    global _registered_for, _owns_pipeline
    with _lock:
        _registered_for = None
        _owns_pipeline = None
        _prompt_cache.clear()


# ── observability: tool_calls rows + trace.jsonl on the OWNER turn path ──
# Both writers lived only on the CLI path (main's session-agent callbacks and
# boot), so after Gateway turns took over (2026-09-23) neither state.db
# ``tool_calls`` nor ``logs/trace.jsonl`` received a row.

def observe_tool_calls(callbacks: Any, session_key: str) -> Any:
    """Return ``callbacks`` with a ``tool_done`` that also persists a
    ``tool_calls`` row and a trace step, then calls the original observer."""
    from jaeger_agent import AgentCallbacks

    cb = callbacks if callbacks is not None else AgentCallbacks()
    original = getattr(cb, "tool_done", None)
    if getattr(original, "_owner_observed", False):
        return cb

    def tool_done(name: str, args: dict[str, Any], result: Any, ok: bool,
                  error: str | None, elapsed_s: float) -> None:
        try:
            from jaeger_agent.memory import memory as mem
            mem.record_tool_call(session_key=session_key, tool_name=name, args=args,
                                 result=result, ok=ok, error=error, elapsed_s=elapsed_s)
        except Exception:  # noqa: BLE001 — an observer never breaks a turn
            pass
        try:
            from jaeger_agent.core import trace as _trace
            _trace.trace_step("tool", name, dur_s=elapsed_s, ok=ok,
                              detail=f"{args} => {error if not ok else result}")
        except Exception:  # noqa: BLE001
            pass
        if original is not None:
            original(name, args, result, ok, error, elapsed_s)

    tool_done._owner_observed = True  # type: ignore[attr-defined]
    cb.tool_done = tool_done
    return cb


class traced_turn:
    """Context manager: one ``trace.jsonl`` turn (input → steps → answer)."""

    def __init__(self, layout: Any, session_key: str, user_text: str) -> None:
        self.layout, self.session_key, self.user_text = layout, session_key, user_text
        self.answer = ""
        self._t0 = 0.0

    def __enter__(self) -> "traced_turn":
        import time
        try:
            from jaeger_agent.core import trace as _trace
            _trace.start_trace_recorder(self.layout)
            _trace.trace_begin(self.session_key, self.user_text)
        except Exception:  # noqa: BLE001
            pass
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        import time
        try:
            from jaeger_agent.core import trace as _trace
            _trace.trace_end(self.answer, time.perf_counter() - self._t0, ok=exc_type is None)
        except Exception:  # noqa: BLE001
            pass
