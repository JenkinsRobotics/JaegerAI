"""JaegerAI's product runtime adapter for the reusable JaegerAgent module.

JaegerAgent owns lifecycle, sessions, bus routing, the turn loop, and provider
contracts. JaegerAI owns the concrete product configuration, tools, prompts,
memory, and personality pipeline supplied through this adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from contextlib import contextmanager
from typing import Any


def _install_bus_confirmation(bus: Any) -> Any:
    """Install approval routing without mutating JaegerOS's deny-all default."""
    from jaeger_agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider,
        PermissionPolicy,
        current_policy,
        install_policy,
    )

    policy = current_policy()
    if isinstance(policy.confirmation, AllowAllProvider):
        return None
    confirmation = BusConfirmationProvider(bus)
    # Carry the audit sink across the swap. This replaces the live policy to
    # route confirmations through the bus; rebuilding it without ``audit``
    # would silently stop the hash-chained decision log the moment the mind
    # node attached — the audit would appear to work right up until the
    # surface that actually asks the user came online.
    install_policy(PermissionPolicy(
        mode=policy.mode, confirmation=confirmation, audit=policy.audit,
    ))
    return confirmation


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
            self._confirmation = _install_bus_confirmation(bus)
        except Exception:  # noqa: BLE001 - confirmation routing is best effort
            self._confirmation = None

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        from jaeger_ai.main import _ensure_session_agent, run_for_voice

        if self._closed:
            return {"text": "", "error": "runtime is closed"}
        if session_key in getattr(self, "_conversation_owners", {}):
            agent = _ensure_session_agent(self.client, session_key)
            self._activate_conversation(session_key, agent)
        if self._confirmation is not None:
            self._confirmation.current_session = session_key
        return run_for_voice(self.client, text, session_key=session_key, output_mode="dynamic")

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
        self._activate_conversation(session_key, agent)
        self._apply_vision_handler(agent)
        return app.run_for_voice(
            self.client,
            text,
            session_key=session_key,
            content=content,
            system_prompt_addon=system_prompt,
            output_mode="dynamic",
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

    def _activate_conversation(self, session_key: str, agent: Any) -> None:
        """Transfer the current transcript when toggling tools, not the memory store.

        Keep tool/result pairs and media intact. Separate tool-free adapters
        prevent a hallucinated tool call from enabling tools in chatbot mode.
        Warmup never calls this method and cannot change conversation ownership.
        """
        from jaeger_ai.main import _jaeger_agents_by_session

        owners = getattr(self, "_conversation_owners", None)
        if owners is None:
            owners = self._conversation_owners = {}
        source = owners.get(session_key, _jaeger_agents_by_session.get(session_key))
        if source is not None and source is not agent and hasattr(source, "messages"):
            agent.messages = deepcopy(source.messages)
        owners[session_key] = agent

    @contextmanager
    def agentic_conversation(self, session_key: str):
        """Carry a tool-free turn back into the native agent session."""
        from jaeger_ai import main as app
        owners = getattr(self, "_conversation_owners", {})
        previous = owners.get(session_key)
        current = app._jaeger_agents_by_session.get(session_key)
        if previous is not None and previous is not current:
            if current is not None:
                current.messages = deepcopy(previous.messages)
            else:
                app._carried_session_messages[session_key] = deepcopy(previous.messages)
        try:
            yield
        finally:
            current = app._jaeger_agents_by_session.get(session_key)
            if current is not None:
                owners[session_key] = current
                self._conversation_owners = owners

    def _chatbot_agent(self, session_key: str, system_prompt: str = "", client: Any = None) -> Any:
        """Return a tool-free peer without mutating the product agent lane."""
        from jaeger_agent.loop.runtime_bridge import build_jaeger_agent

        sessions = getattr(self, "_chatbot_sessions", None)
        if sessions is None:
            sessions = self._chatbot_sessions = {}
        client = client or self.client
        agent = sessions.get(session_key)
        clients = getattr(self, "_chatbot_clients", None)
        if clients is None:
            clients = self._chatbot_clients = {}
        if agent is None or clients.get(session_key) is not client:
            previous = agent
            agent = build_jaeger_agent(
                client,
                system_prompt=system_prompt,
                tools_enabled=False,
            )
            if previous is not None:
                agent.messages = deepcopy(previous.messages)
            sessions[session_key] = agent
            clients[session_key] = client
        elif system_prompt:
            # Switching input/output policy must not retain a stale prompt.
            agent.system_prompt = system_prompt
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
        self, content: Any, *, text: str, system_prompt: str = "",
        session_key: str, output_mode: str | None = None,
        input_modality: str = "text", display_text: str | None = None,
        model: str | None = None, provider: str | None = None,
    ) -> dict[str, Any]:
        """Run a tool-free peer, retaining media, cancellation and durable history."""
        from jaeger_agent.loop.runtime_bridge import drive_one_turn
        from jaeger_agent.core.outputs import DYNAMIC_OUTPUT_PROMPT, decide_output
        from jaeger_ai.main import _pipeline

        if self._closed:
            return {"text": "", "error": "runtime is closed"}
        if output_mode not in {None, "dynamic", "text", "speech", "mirror"}:
            raise ValueError("invalid conversational output mode")
        if input_modality not in {"text", "speech"}:
            raise ValueError("input_modality must be text or speech")
        client = self.client
        if model or provider:
            from jaeger_ai.core.models.sensitivity_gate import apply_sensitivity_routing
            from jaeger_ai.core.models.session_selection import select_client
            model, provider, _ = apply_sensitivity_routing(
                text, config=_pipeline.get("config"), model=model, provider=provider)
            client = select_client(client, _pipeline.get("config"),
                                   _pipeline.get("layout"), model, provider)
        turn_text = text
        if output_mode == "dynamic":
            system_prompt = f"{system_prompt}\n{DYNAMIC_OUTPUT_PROMPT}"
            hint = f"[input: {input_modality}]"
            turn_text = f"{hint}\n{text}"
            content = ([{"type": "text", "text": hint}, *content]
                       if isinstance(content, list) else f"{hint}\n{content}")
        agent = self._chatbot_agent(session_key, system_prompt, client)
        try:
            from contextlib import nullcontext
            with (_pipeline.get("llm_lock") or nullcontext()):
                self._activate_conversation(session_key, agent)
                result = drive_one_turn(agent, turn_text, content=content)
        except Exception as exc:
            return {"text": "", "error": f"{type(exc).__name__}: {exc}"}
        response = {"text": str(result.get("answer") or ""),
                    "error": result.get("error")}
        if result.get("halt_reason"):
            response["halt_reason"] = result["halt_reason"]
        if "elapsed_s" in result:
            response["elapsed_s"] = result["elapsed_s"]
        if output_mode is not None:
            decision = decide_output(mode=output_mode, input_modality=input_modality,
                                     reply=response["text"])
            response.update(text=decision.display_text or decision.speech_text,
                            speech_text=decision.speech_text,
                            output_channels=decision.channels)
        try:
            from jaeger_ai.core.sessions import get_store
            store = get_store()
            if store is not None:
                store.record(session_key, "user", display_text if display_text is not None else text)
                if response["text"]:
                    store.record(session_key, "assistant", response["text"])
        except Exception:
            pass  # Storage failure must not prevent delivery of a completed turn.
        return response

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
        getattr(self, "_chatbot_sessions", {}).pop(session_key, None)
        getattr(self, "_conversation_owners", {}).pop(session_key, None)

    def clear_chatbot_session(self, session_key: str) -> None:
        """New chat clears both modes so switching back cannot resurrect it."""
        self.clear_session(session_key)

    def steer(self, text: str) -> bool:
        try:
            from jaeger_ai.main import _pipeline

            agent = _pipeline.get("active_jaeger_agent")
            return bool(agent.steer(text)) if agent is not None else False
        except Exception:  # noqa: BLE001 - steering falls back to the next queued turn
            return False

    def interrupt(self, *, session_key: str) -> None:
        """Same-process faces address their session, never the global active one."""
        from jaeger_ai.main import _jaeger_agents_by_session

        agent = getattr(self, "_conversation_owners", {}).get(session_key)
        if agent is None:
            agent = _jaeger_agents_by_session.get(session_key)
        if agent is not None:
            agent.interrupt()

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
        getattr(self, "_conversation_owners", {}).clear()
        self.boot.cleanup()


def create_runtime(*, bus: Any, config: Mapping[str, Any] | None = None) -> Any:
    """Factory consumed by JaegerAgent's manifest/programmatic API.

    Prefer the resident Gateway, then a live ``run/bridge.sock``, and only
    then boot a local agent. ``JAEGER_NO_ATTACH`` skips both remote owners
    so tests reach their own ``boot_for_tui`` patch.
    """

    cfg = dict(config or {})
    from jaeger_ai.core.runtime import attach_policy
    from jaeger_ai.core.runtime.attached import try_attach_runtime
    from jaeger_ai.core.runtime.gateway_runtime import try_gateway_runtime

    if not attach_policy.attach_disabled():
        gateway = try_gateway_runtime()
        if gateway is not None:
            return gateway
        attached = try_attach_runtime(instance_name=cfg.get("instance_name"))
        if attached is not None:
            return attached
        raise RuntimeError(
            "Jaeger Gateway is unavailable and no live bridge socket answered; "
            "refusing to boot a second local agent. Start `jaeger gateway daemon`, "
            "connect the bridge, or set JAEGER_NO_ATTACH=1 for isolated local testing."
        )
    try:
        return JaegerAIRuntime(bus=bus, config=cfg)
    except RuntimeError as exc:
        if "locked by pid" not in str(exc):
            raise
        raise RuntimeError(
            "Local runtime is locked by another process and attach mode is disabled; "
            "start the Jaeger Gateway or unset JAEGER_NO_ATTACH to attach to a live owner."
        ) from exc


__all__ = ["JaegerAIRuntime", "create_runtime"]
