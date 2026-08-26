"""The built-in agent runtime — a brain from configuration alone.

This is what makes ``jaeger-agent`` a MODULE rather than a library: an
application declares the mind slot in its ``jaeger.toml``, sets a
provider and model in the ``agent`` config group, and gets a working
agentic loop on the bus without writing any glue.

    [[node]]
    id = "mind"
    slot = "mind"
    config_key = "agent"

Applications that own their own model pipeline (JaegerAI does — it
manages instances, memory, personas, and in-process weights) point
``runtime_factory`` at their own ``create_runtime`` instead. Both paths
satisfy the same :class:`~jaeger_agent.contracts.AgentRuntime` protocol,
so :class:`~jaeger_agent.node.MindNode` never knows which it got.

SCOPE. This runtime builds adapters that can be described by config: the
Anthropic surface and every OpenAI-compatible one (OpenAI, Ollama,
LM Studio, Gemini). In-process GGUF/MLX weights cannot come from a
config string — they need a loaded model object — so an application
wanting those injects a pre-built adapter via ``adapter=`` or supplies
its own runtime. That is a real boundary, not a missing feature.

Tools are whatever is in the process-wide registry at turn time — the
host app, its skills, and any connected module register into it. This
runtime deliberately registers none of its own.
"""

from __future__ import annotations

import os
import pathlib
import time
from typing import Any, Mapping

from .config import AgentConfig
from .contracts import TurnResult
from .loop.callbacks import AgentCallbacks
from .loop.jaeger_agent import JaegerAgent
from .loop.turn_budget import TurnBudgetLimits


#: Conventional environment variable per provider, used when the config
#: does not name one explicitly. Local servers need no key at all.
_DEFAULT_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

#: Providers that load weights from disk rather than dialling an
#: endpoint. Spelled several ways because the config field, the
#: adapter's diagnostic name, and habit all differ.
_LOCAL_WEIGHT_PROVIDERS = frozenset({"llama_cpp", "llama-cpp", "local", "local-llama"})


def _load_skills(workspace: Any) -> Any:
    """Register the shipped skill corpus, the way tools self-register.

    The module ships 107 skills AND the loader, and until 0.11 nothing
    ran it: an embedder got a `use_skill` tool over an empty corpus,
    while `import jaeger_agent` had already armed ~94 tools. That
    asymmetry showed up as a measurable hole — skill cases in the
    benchmark failed against a bare module for no reason other than
    nobody having called the loader.

    Here rather than at import time because loading needs a workspace,
    and a workspace should not be minted by an import.

    Smoke tests are skipped: they fork a subprocess per code-skill and
    the corpus is the one shipped inside this package, already tested at
    release. An application installing UNTRUSTED instance skills should
    call ``load_and_register(..., run_smoke_tests=True)`` itself — that
    gate exists for skills whose provenance you do not control.
    """
    # JAEGER_AGENT_NO_TOOLS counts here too, and that is not a courtesy.
    # Skills register TOOLS — the shipped computer_use skill alone adds
    # ten, including computer_click, computer_type_text, computer_press_key
    # and computer_read_screen. An embedder that asked for a bare chat
    # loop and got desktop control back through the skill loader has been
    # handed a capability it declined, not merely ~1,000 tokens of schema
    # it did not budget for. Found reviewing Mochi, whose chat_only()
    # correctly suppressed 96 tools and then received 10 anyway.
    if os.environ.get("JAEGER_AGENT_NO_SKILLS") or os.environ.get("JAEGER_AGENT_NO_TOOLS"):
        return None
    try:
        from .skill_registry.skill_loader import load_and_register

        return load_and_register(None, workspace, run_smoke_tests=False)
    except Exception:  # noqa: BLE001 — a broken skill must not stop the brain
        return None


def _select_config(raw: Mapping[str, Any] | None) -> AgentConfig:
    """Build an :class:`AgentConfig` from a node's config mapping.

    Node config carries host-owned keys too (``instance_name``, and
    whatever else an app threads through), so unknown keys are dropped
    rather than rejected — ``AgentConfig`` itself stays ``extra="forbid"``
    so a typo inside the agent group is still caught.
    """
    data = dict(raw or {})
    known = {k: v for k, v in data.items() if k in AgentConfig.model_fields}
    return AgentConfig.model_validate(known)


def build_adapter(cfg: AgentConfig) -> Any:
    """Config → provider adapter. Raises if the provider needs a key it can't find."""
    provider = (cfg.provider or "llama_cpp").strip().lower()
    key_env = cfg.api_key_env or _DEFAULT_KEY_ENV.get(provider, "")
    api_key = os.environ.get(key_env, "") if key_env else ""
    base_url = cfg.base_url or None

    # The default. Weights load in-process — no server, no key, no
    # network — which is what makes a robot with this module installed
    # able to think on its own hardware.
    if provider in _LOCAL_WEIGHT_PROVIDERS:
        if not cfg.model_path:
            raise RuntimeError(
                f"agent.provider={provider!r} runs GGUF weights in-process and "
                f"needs agent.model_path pointing at a .gguf file. To use a "
                f"served model instead, set provider to lmstudio/ollama/"
                f"anthropic/openai."
            )
        path = pathlib.Path(cfg.model_path).expanduser()
        if not path.exists():
            raise RuntimeError(f"agent.model_path does not exist: {path}")
        from .adapters.local_llama import LocalLlamaAdapter

        return LocalLlamaAdapter(
            # Under llama_cpp `model` is only a diagnostic label; the
            # path is what selects the weights. Default it to the
            # filename so /runtime shows something recognisable.
            model=cfg.model or path.stem,
            model_path=path,
            llama_kwargs={"n_ctx": cfg.ctx, "n_gpu_layers": cfg.gpu_layers},
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
        )

    if provider == "anthropic":
        if not api_key:
            raise RuntimeError(
                f"agent.provider='anthropic' needs an API key; set "
                f"${key_env or 'ANTHROPIC_API_KEY'} or agent.api_key_env"
            )
        from .adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter(
            api_key=api_key,
            model=cfg.model or "claude-sonnet-4-6",
            max_tokens=cfg.max_tokens,
            timeout_s=cfg.timeout_s,
            base_url=base_url,
        )

    # Everything else rides the OpenAI-compatible surface. Local servers
    # (ollama / lmstudio) authenticate with nothing, so a missing key is
    # only fatal when talking to a hosted endpoint.
    if not api_key and not base_url and provider in _DEFAULT_KEY_ENV:
        raise RuntimeError(
            f"agent.provider={provider!r} needs an API key; set "
            f"${key_env} or agent.api_key_env, or point agent.base_url "
            f"at a local server"
        )
    from .adapters.openai import OpenAIAdapter

    return OpenAIAdapter(
        provider=provider,
        model=cfg.model or "gpt-4o-mini",
        api_key=api_key or None,
        base_url=base_url,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
        timeout_s=cfg.timeout_s,
    )


class DefaultAgentRuntime:
    """A config-built agent loop, one conversation per session key.

    :class:`JaegerAgent` owns its transcript, so a session is an agent.
    They are built lazily — a bus with five idle sessions costs nothing
    until each one speaks.
    """

    def __init__(
        self,
        *,
        bus: Any = None,
        config: Mapping[str, Any] | None = None,
        adapter: Any = None,
    ) -> None:
        self.bus = bus
        self.config = _select_config(config)
        # Building an agent is the moment a workspace becomes necessary —
        # ~40 tools resolve paths through it. Doing it here rather than
        # lazily inside _require_layout keeps directory creation out of
        # read-only status probes, and keeps it to one predictable place.
        #
        # Lands at <cwd>/.jaeger_agent: with the project, never in the
        # home directory or a temp dir. An application that binds its own
        # instance first keeps it — ensure_bound is idempotent.
        from .workspace import ensure_bound

        workspace = ensure_bound()
        self.skills = _load_skills(workspace)
        # A caller-supplied adapter wins — this is the seam for
        # in-process weights the config language cannot describe.
        self._adapter = adapter
        self._sessions: dict[str, JaegerAgent] = {}
        self._events: Any = None
        self._closed = False

    def start(self, *, events: Any = None, bus: Any = None) -> None:
        """Optional lifecycle hook — the bridge hands us its event sink.

        Without this, ``module.yaml``'s ``produces: [/sense/tool,
        /sense/activity]`` would be a promise nothing keeps: the loop
        fires callbacks, but with nowhere to send them a surface sees a
        turn as one silent gap between question and answer.
        """
        self._events = events
        if bus is not None:
            self.bus = bus

    def _callbacks(self) -> AgentCallbacks:
        """Forward loop callbacks onto the bus as typed events."""
        events = self._events
        if events is None:
            return AgentCallbacks()

        started: dict[str, float] = {}

        def tool_progress(name: str, phase: str, data: Any) -> None:
            if phase == "start":
                started[name] = time.monotonic()
                events.tool(name, "start")
                return
            # The loop times the call itself and passes the number in
            # ``data``; prefer it over timing from here, which also
            # counts however long this callback waited to be scheduled.
            elapsed = 0.0
            if isinstance(data, Mapping) and "elapsed_s" in data:
                elapsed = float(data["elapsed_s"] or 0.0)
            else:
                elapsed = time.monotonic() - started.pop(name, time.monotonic())
            started.pop(name, None)
            events.tool(name, phase, elapsed_s=elapsed)

        def thinking(state: str) -> None:
            events.activity("thinking", str(state)[:200])

        return AgentCallbacks(tool_progress=tool_progress, thinking=thinking)

    @property
    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = build_adapter(self.config)
        return self._adapter

    def agent_for(self, session_key: str) -> JaegerAgent:
        """The agent owning ``session_key``'s transcript, built on first use."""
        agent = self._sessions.get(session_key)
        if agent is None:
            agent = JaegerAgent(
                adapter=self.adapter,
                system_prompt=self.config.system_prompt,
                max_iterations=self.config.max_iterations,
                turn_budget_limits=TurnBudgetLimits(
                    max_iterations=self.config.max_iterations,
                    max_elapsed_s=self.config.turn_max_elapsed_s or None,
                    max_tokens=self.config.turn_max_tokens or None,
                    max_tool_cost=self.config.turn_max_tool_cost or None,
                ),
                callbacks=self._callbacks(),
            )
            self._sessions[session_key] = agent
        return agent

    # ── AgentRuntime protocol ────────────────────────────────────────

    def run_turn(self, text: str, *, session_key: str = "default") -> TurnResult:
        if self._closed:
            return TurnResult(error="runtime is closed")
        try:
            return TurnResult(text=self._run_bound_turn(session_key, text))
        except Exception as exc:  # noqa: BLE001 — one bad turn must not kill the node
            return TurnResult(error=f"{type(exc).__name__}: {exc}")

    def _run_bound_turn(self, session_key: str, text: str) -> str:
        agent = self.agent_for(session_key)
        from jaeger_agent.memory import sqlite_store
        if not sqlite_store.is_bound():
            return agent.run_turn(text)
        from jaeger_agent.cognition.executive import TurnExecutive
        from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
        from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
        from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore
        return TurnExecutive(
            agent, SqliteRunStore(), SqliteCommitmentStore(),
            provider=getattr(self.adapter, "name", None),
            claims=SqliteKnowledgeStore(),
        ).run_turn(text)

    def steer(self, text: str) -> bool:
        """Mid-turn redirect. Only a session actually running can take one."""
        return any(agent.steer(text) for agent in self._sessions.values())

    def health(self) -> dict[str, Any]:
        # Report the ADAPTER's model label, not the config field. Under
        # llama_cpp the config names a path and leaves `model` empty, so
        # reading config here showed a blank model on the default
        # provider — the one case where an operator most needs to know
        # which weights actually loaded.
        model = self.config.model
        if self._adapter is not None:
            model = str(getattr(self._adapter, "model", "") or model)
        return {
            "implementation": "jaeger-agent",
            "provider": self.config.provider,
            "model": model,
            "sessions": len(self._sessions),
            "tools": len(self.agent_for("default").tool_names()) if self._sessions else 0,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for agent in self._sessions.values():
            agent.interrupt()
        self._sessions.clear()


def create_runtime(
    *, bus: Any = None, config: Mapping[str, Any] | None = None, **kwargs: Any
) -> DefaultAgentRuntime:
    """Factory named by ``module.yaml`` and by :class:`MindNode`'s default."""

    return DefaultAgentRuntime(bus=bus, config=config, **kwargs)


__all__ = ["DefaultAgentRuntime", "create_runtime", "build_adapter"]
