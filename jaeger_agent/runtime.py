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
                callbacks=self._callbacks(),
            )
            self._sessions[session_key] = agent
        return agent

    # ── AgentRuntime protocol ────────────────────────────────────────

    def run_turn(self, text: str, *, session_key: str = "default") -> TurnResult:
        if self._closed:
            return TurnResult(error="runtime is closed")
        try:
            return TurnResult(text=self.agent_for(session_key).run_turn(text))
        except Exception as exc:  # noqa: BLE001 — one bad turn must not kill the node
            return TurnResult(error=f"{type(exc).__name__}: {exc}")

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
