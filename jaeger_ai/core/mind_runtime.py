"""JaegerAI's product runtime adapter for the reusable JaegerAgent module.

JaegerAgent owns lifecycle, sessions, bus routing, the turn loop, and provider
contracts. JaegerAI owns the concrete product configuration, tools, prompts,
memory, and personality pipeline supplied through this adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class _PipelineEventAdapter:
    """Map the JaegerAI pipeline event hook onto JaegerAgent runtime events."""

    def __init__(self, events: Any) -> None:
        self.events = events

    def publish(self, event: str, **payload: Any) -> None:
        if event == "tool.progress":
            self.events.tool(
                str(payload.get("name", "")),
                str(payload.get("phase", "start")),
                elapsed_s=float(payload.get("elapsed_s") or 0.0),
                detail=str(payload.get("detail", "")),
                session=str(payload.get("session", "")),
            )
        elif event == "tool.output":
            session = str(payload.get("session", ""))
            self.events.tool(
                str(payload.get("name", "")),
                "output" if payload.get("ok", True) else "error-output",
                elapsed_s=float(payload.get("elapsed_s") or 0.0),
                detail=str(payload.get("detail", "")),
                session=session,
            )
            for path in payload.get("artifacts", ()):
                self.events.activity("artifact", str(path), session=session)
        elif event == "agent.activity":
            self.events.activity(
                str(payload.get("kind", "status")),
                str(payload.get("text", "")),
                session=str(payload.get("session", "")),
            )


class JaegerAIRuntime:
    """Adapt JaegerAI's existing pipeline to ``jaeger_agent.AgentRuntime``."""

    def __init__(self, *, bus: Any, config: Mapping[str, Any] | None = None) -> None:
        from jaeger_ai.main import boot_for_tui

        self.bus = bus
        self.config = dict(config or {})
        self.boot = boot_for_tui(
            instance_name=self.config.get("instance_name"),
            with_memory=bool(self.config.get("with_memory", True)),
            warmup=bool(self.config.get("warmup", False)),
            prewarm_model=bool(self.config.get("prewarm_model", True)),
        )
        self.client = self.boot.client
        self._confirmation: Any = None
        self._vision_handler: Any = None
        self._chatbot_sessions: dict[str, Any] = {}
        self._closed = False

    @classmethod
    def from_boot(cls, boot: Any) -> JaegerAIRuntime:
        """Borrow an already-booted Jaeger AI brain without loading another.

        The native app bridge owns ``boot`` and its model/instance lock.  Thin
        faces (notably the attached multimodal workspace) use this adapter so
        text, image, and spoken turns reach that exact AgentRuntime rather than
        constructing a second Gemma process.
        """
        runtime = cls.__new__(cls)
        runtime.bus = None
        runtime.config = {}
        runtime.boot = boot
        runtime.client = boot.client
        runtime._confirmation = None
        runtime._vision_handler = None
        runtime._chatbot_sessions = {}
        runtime._closed = False
        return runtime

    def start(self, *, events: Any, bus: Any) -> None:
        from jaeger_ai.main import _pipeline

        _pipeline["event_bus"] = _PipelineEventAdapter(events)
        _pipeline["chassis_bus"] = bus
        try:
            from jaeger_agent.loop.bus_confirm import BusConfirmationProvider
            from jaeger_os.core.safety.permissions import (
                AllowAllProvider,
                current_policy,
                install_confirmation_provider,
            )

            policy = current_policy()
            if not isinstance(policy.confirmation, AllowAllProvider):
                self._confirmation = BusConfirmationProvider(bus)
                install_confirmation_provider(self._confirmation)
        except Exception:  # noqa: BLE001 - confirmation routing is best effort
            self._confirmation = None

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        from jaeger_ai.main import run_for_voice

        if self._confirmation is not None:
            self._confirmation.current_session = session_key
        return run_for_voice(self.client, text, session_key=session_key)

    def run_multimodal_turn(
        self,
        content: Any,
        *,
        text: str,
        system_prompt: str = "",
        session_key: str,
    ) -> dict[str, Any]:
        """Send provider-native image/text blocks through JaegerAI's one brain."""
        from jaeger_ai import main as app

        if self._closed:
            return {"text": "", "error": "runtime is closed"}
        if self._confirmation is not None:
            self._confirmation.current_session = session_key
        # Ensure the exact session adapter exists before applying the projector.
        # The engine configures vision before the first turn, while JaegerAI
        # builds session agents lazily on that first turn.
        agent = app._ensure_session_agent(
            self.client,
            session_key,
            scope_tools=True,
        )
        # Skip-final synthesizes a text answer outside the model after a
        # deterministic tool call. That is useful in text chat, but it would
        # bypass this face's model-selected OUTPUT channel. Keep the normal
        # agent optimization untouched and require the multimodal session's
        # post-tool model step to choose text/speech/both/silent itself.
        agent.skip_final_tools = frozenset()
        self._apply_vision_handler(agent)
        return app.run_for_voice(
            self.client,
            text,
            session_key=session_key,
            content=content,
            system_prompt_addon=system_prompt,
        )

    def warmup(
        self,
        *,
        session_key: str,
        system_prompt: str = "",
    ) -> bool:
        """Prewarm the exact scoped multimodal prompt without a fake turn."""
        from jaeger_ai import main as app

        if self._closed:
            return False
        agent = app._ensure_session_agent(
            self.client,
            session_key,
            scope_tools=True,
        )
        agent.skip_final_tools = frozenset()
        app._apply_multimodal_system_prompt(agent, system_prompt)
        self._apply_vision_handler(agent)
        warm = getattr(agent.primary_adapter, "warmup", None)
        if not callable(warm):
            return False
        lock = app._pipeline.get("llm_lock")
        if lock is None:
            return bool(warm(system_prompt=agent.system_prompt, tools=agent.tools))
        with lock:
            return bool(warm(system_prompt=agent.system_prompt, tools=agent.tools))

    def _chatbot_agent(self, session_key: str, system_prompt: str = "") -> Any:
        """Return a tool-free peer without mutating the product agent lane."""
        from jaeger_agent.loop.runtime_bridge import build_jaeger_agent

        sessions = getattr(self, "_chatbot_sessions", None)
        if sessions is None:
            sessions = self._chatbot_sessions = {}
        agent = sessions.get(session_key)
        if agent is None:
            agent = build_jaeger_agent(
                self.client,
                system_prompt=system_prompt,
                tools_enabled=False,
            )
            sessions[session_key] = agent
        self._apply_vision_handler(agent)
        return agent

    def warmup_chatbot(
        self,
        *,
        session_key: str,
        system_prompt: str = "",
    ) -> bool:
        """Prime the exact zero-tool prefix without adding a fake turn."""
        from jaeger_ai.main import _pipeline

        agent = self._chatbot_agent(session_key, system_prompt)
        warmup = getattr(agent.primary_adapter, "warmup", None)
        if not callable(warmup):
            return False
        lock = _pipeline.get("llm_lock")
        if lock is None:
            return bool(warmup(system_prompt=agent.system_prompt, tools=agent.tools))
        with lock:
            return bool(warmup(system_prompt=agent.system_prompt, tools=agent.tools))

    def run_chatbot_turn(
        self,
        text: str,
        *,
        session_key: str,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        return self.run_chatbot_multimodal_turn(
            text,
            text=text,
            system_prompt=system_prompt,
            session_key=session_key,
        )

    def run_chatbot_multimodal_turn(
        self,
        content: Any,
        *,
        text: str,
        system_prompt: str = "",
        session_key: str,
    ) -> dict[str, Any]:
        """Run the shared model as a conversational, explicitly tool-free LLM."""
        from jaeger_agent.loop.runtime_bridge import drive_one_turn
        from jaeger_ai.main import _pipeline

        if self._closed:
            return {"text": "", "error": "runtime is closed"}
        agent = self._chatbot_agent(session_key, system_prompt)
        try:
            lock = _pipeline.get("llm_lock")
            if lock is None:
                result = drive_one_turn(agent, text, content=content)
            else:
                with lock:
                    result = drive_one_turn(agent, text, content=content)
        except Exception as exc:  # noqa: BLE001 — match the AgentRuntime boundary
            return {"text": "", "error": f"{type(exc).__name__}: {exc}"}
        return {"text": str(result.get("answer") or ""), "error": None}

    def configure_vision(self, chat_handler: Any) -> None:
        """Attach the engine-owned projector to current and future local sessions."""
        self._vision_handler = chat_handler
        try:
            from jaeger_ai.main import _jaeger_agents_by_session

            for agent in list(_jaeger_agents_by_session.values()):
                self._apply_vision_handler(agent)
        except Exception:  # noqa: BLE001 — remote/text runtimes need no projector
            pass
        for agent in list(getattr(self, "_chatbot_sessions", {}).values()):
            self._apply_vision_handler(agent)

    def _apply_vision_handler(self, agent: Any) -> None:
        handler = self._vision_handler
        adapter = getattr(agent, "primary_adapter", None)
        kwargs = getattr(adapter, "llama_kwargs", None)
        if isinstance(kwargs, dict):
            # A session adapter may still be lazy. Seed construction as well
            # as updating an already-loaded shared llama below.
            if handler is None:
                kwargs.pop("chat_handler", None)
            else:
                kwargs["chat_handler"] = handler
        llama = getattr(adapter, "_llama", None)
        if llama is None:
            return
        # llama-cpp consults this attribute for every chat completion, so it
        # can be attached after JaegerAI's shared weights were loaded.
        llama.chat_handler = handler

    def clear_session(self, session_key: str) -> None:
        """Clear one multimodal conversation without closing the app runtime."""
        from jaeger_ai.main import evict_session

        evict_session(session_key)

    def clear_chatbot_session(self, session_key: str) -> None:
        """Forget only the isolated no-tools transcript."""
        sessions = getattr(self, "_chatbot_sessions", None)
        if sessions is not None:
            sessions.pop(session_key, None)

    def steer(self, text: str) -> bool:
        try:
            from jaeger_ai.main import _pipeline

            agent = _pipeline.get("active_jaeger_agent")
            return bool(agent.steer(text)) if agent is not None else False
        except Exception:  # noqa: BLE001 - steering falls back to the next queued turn
            return False

    def context_detail(self, session: str) -> str:
        try:
            from jaeger_ai.main import last_ctx_snapshot

            snapshot = last_ctx_snapshot(session)
        except Exception:  # noqa: BLE001 - status enrichment is best effort
            return ""
        return f"ctx {snapshot['pct']}%" if snapshot else ""

    def health(self) -> dict[str, Any]:
        return {
            "implementation": "jaeger-ai",
            "model": str(getattr(self.client, "model_name", "")),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        getattr(self, "_chatbot_sessions", {}).clear()
        self.boot.cleanup()


def create_runtime(
    *, bus: Any, config: Mapping[str, Any] | None = None
) -> JaegerAIRuntime:
    """Factory consumed by JaegerAgent's manifest/programmatic API."""

    return JaegerAIRuntime(bus=bus, config=config)


__all__ = ["JaegerAIRuntime", "create_runtime"]
