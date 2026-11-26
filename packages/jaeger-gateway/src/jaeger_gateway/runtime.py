"""Modular standalone Jaeger Gateway Runtime wiring all 15 jaeger-* packages together."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from aiohttp import web

from jaeger_authority import MacOsSeatbeltSandbox, PolicyEngine, UnconfinedSandbox
from jaeger_events import EventBus
from jaeger_loop import AgentLoop, TurnContext
from jaeger_memory import SqliteStateMemory
from jaeger_models import OllamaModel, build_default_model
from jaeger_orchestration import WorkflowEngine
from jaeger_reliability import ReliabilityEngine
from jaeger_tools import ToolRegistry, register_builtin_tools

from .auth import GatewayAuthPolicy
from .coordinator import RunCoordinator
from .server import create_gateway_app
from .store import GatewayStore
from .stream import SessionEventHub


class _SseLoopMiddleware:
    """Bridges AgentLoop model/tool events live into SessionEventHub SSE frames."""

    def __init__(self, session_id: str, generation: int, hub: SessionEventHub) -> None:
        self._session_id = session_id
        self._generation = generation
        self._hub = hub

    def on_model_call(self, ctx: TurnContext, call_next: Any) -> Mapping[str, Any]:
        resp = call_next(ctx)
        thinking = str(resp.get("thinking") or "").strip()
        if thinking:
            self._hub.publish(
                self._session_id,
                "thinking.delta",
                {"delta": thinking, "step": ctx.step},
                generation=self._generation,
            )
        content = str(resp.get("content") or "")
        if content and not resp.get("tool_calls"):
            self._hub.publish(
                self._session_id,
                "text.delta",
                {"delta": content, "step": ctx.step},
                generation=self._generation,
            )
        return resp

    def on_tool_call(self, ctx: TurnContext, tool_name: str, arguments: Mapping[str, Any], call_next: Any) -> Any:
        call_id = f"tc_{uuid.uuid4().hex[:8]}"
        t0 = time.monotonic()
        self._hub.publish(
            self._session_id,
            "tool.started",
            {"call_id": call_id, "tool": tool_name, "arguments": dict(arguments), "step": ctx.step},
            generation=self._generation,
        )
        res = call_next(tool_name, arguments)
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._hub.publish(
            self._session_id,
            "tool.completed" if res.ok else "tool.failed",
            {
                "call_id": call_id,
                "tool": tool_name,
                "ok": res.ok,
                "output": str(res.output or "")[:2000],
                "error": res.error,
                "duration_ms": duration_ms,
                "step": ctx.step,
            },
            generation=self._generation,
        )
        return res


class ModularGatewayRuntime:
    """Self-contained modular agentic runtime backed exclusively by standalone jaeger-* packages."""

    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        workspace: Path | None = None,
        model_id: str | None = None,
        static_ui_dir: Path | None = None,
        auth: GatewayAuthPolicy | None = None,
    ) -> None:
        env_state = os.environ.get("JAEGER_STATE_DIR", "").strip()
        self.state_dir = (
            Path(state_dir).expanduser().resolve()
            if state_dir is not None
            else (Path(env_state).expanduser().resolve() if env_state else (Path.home() / ".jaeger"))
        )
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = (
            Path(workspace).expanduser().resolve()
            if workspace is not None
            else Path(os.environ.get("JAEGER_WORKSPACE") or os.getcwd()).expanduser().resolve()
        )

        self.events = EventBus()
        self.memory = SqliteStateMemory(self.state_dir)
        self.workflows = WorkflowEngine(self.state_dir / "workflows.sqlite3")
        self.store = GatewayStore(self.state_dir / "modular_gateway.sqlite3")
        self.hub = SessionEventHub()
        self.reliability = ReliabilityEngine(repeat_threshold=4)

        safe_read_roots = (
            self.state_dir / "offload",
            self.state_dir / "instances" / "truth" / "logs" / "tool_results",
        )
        self.policy = PolicyEngine(read_allowed_roots=safe_read_roots)
        self.sandbox = MacOsSeatbeltSandbox() if sys.platform == "darwin" else UnconfinedSandbox()
        self.tools = ToolRegistry(
            workspace=self.workspace,
            policy=self.policy,
            sandbox=self.sandbox,
        )
        register_builtin_tools(
            self.tools,
            workspace=self.workspace,
            memory=self.memory,
            workflows=self.workflows,
            extra_read_roots=safe_read_roots,
        )

        self.model = build_default_model(model=model_id)
        self.static_ui_dir = static_ui_dir or self._default_ui_dir()
        self.auth = auth or GatewayAuthPolicy(allow_loopback_unauthenticated=True)
        self.coordinator = RunCoordinator(
            store=self.store,
            hub=self.hub,
            executor=self._execute_turn,
        )

    @staticmethod
    def _default_ui_dir() -> Path | None:
        cand = Path.home() / ".cache" / "jaeger" / "ui-rebuild-mainscreen" / "dist"
        return cand if cand.is_dir() else None

    def _execute_turn(
        self,
        session_id: str,
        prompt: str,
        generation: int,
        hub: SessionEventHub,
    ) -> Mapping[str, Any]:
        loop = AgentLoop(
            model=self.model,
            tools=self.tools,
            memory=self.memory,
            reliability=self.reliability,
            events=self.events,
            middlewares=[_SseLoopMiddleware(session_id, generation, hub)],
            session_id=session_id,
            system_prompt=(
                "You are Jaeger, a standalone modular autonomous engineering and personal assistant. "
                "Use tools accurately, verify edits, and be concise and honest."
            ),
        )
        return loop.run_turn(prompt, max_steps=20)

    def _runtime_info(self) -> dict[str, Any]:
        ollama_probe = self.model.probe() if isinstance(self.model, OllamaModel) else {"ok": True}
        return {
            "model": getattr(self.model, "model_id", self.model.name),
            "workspace": str(self.workspace),
            "state_dir": str(self.state_dir),
            "tools_count": len(self.tools.list_tools(limit=200)),
            "checks": {
                "gateway": {"ok": True},
                "ollama": ollama_probe,
                "webui": {"ok": bool(self.static_ui_dir and self.static_ui_dir.is_dir())},
            },
        }

    def _models_info(self) -> dict[str, Any]:
        models = self.model.list_models() if isinstance(self.model, OllamaModel) else []
        active = getattr(self.model, "model_id", self.model.name)
        if active and not any(m.get("id") == active for m in models):
            models = [{"id": active, "provider": "active"}, *models]
        return {"active": active, "models": models}

    def _select_model(self, model_id: str) -> dict[str, Any]:
        self.model = build_default_model(model=model_id)
        return {"active": getattr(self.model, "model_id", self.model.name)}

    def _discover_skills(self) -> list[dict[str, Any]]:
        skills_dirs = [
            self.state_dir / "skills",
            self.workspace / "skills",
        ]
        found: list[dict[str, Any]] = []
        for root in skills_dirs:
            if not root.is_dir():
                continue
            for md in sorted(root.rglob("SKILL.md"))[:100]:
                found.append({
                    "name": md.parent.name,
                    "path": str(md),
                })
        return found

    def build_app(self, *, serve_ui: bool = False) -> web.Application:
        return create_gateway_app(
            store=self.store,
            coordinator=self.coordinator,
            hub=self.hub,
            auth=self.auth,
            runtime_info=self._runtime_info,
            tools_provider=lambda: list(self.tools.list_tools(limit=200)),
            models_provider=self._models_info,
            model_selector=self._select_model,
            workflows_engine=self.workflows,
            memory_store=self.memory,
            skills_provider=self._discover_skills,
            static_ui_dir=self.static_ui_dir if serve_ui else None,
        )

    def close(self) -> None:
        self.coordinator.close()


async def serve_modular_gateway(
    *,
    host: str | None = None,
    port: int | None = None,
    webui_port: int | None = None,
    state_dir: Path | None = None,
    workspace: Path | None = None,
) -> None:
    """Boot the standalone modular Gateway API + WebApp listeners."""
    gw_host = host or os.environ.get("JAEGER_GATEWAY_HOST") or "127.0.0.1"
    gw_port = int(port or os.environ.get("JAEGER_GATEWAY_PORT") or "33418")
    ui_port = int(webui_port or os.environ.get("JAEGER_WEBUI_PORT") or "8790")

    runtime = ModularGatewayRuntime(state_dir=state_dir, workspace=workspace)
    api_app = runtime.build_app(serve_ui=False)
    ui_app = runtime.build_app(serve_ui=True)

    api_runner = web.AppRunner(api_app)
    ui_runner = web.AppRunner(ui_app)
    await api_runner.setup()
    await ui_runner.setup()

    api_site = web.TCPSite(api_runner, gw_host, gw_port)
    ui_site = web.TCPSite(ui_runner, gw_host, ui_port)
    await api_site.start()
    await ui_site.start()

    print(f"[jaeger-gateway] Modular API listening on http://{gw_host}:{gw_port}", flush=True)
    print(f"[jaeger-gateway] Modular WebUI listening on http://{gw_host}:{ui_port}", flush=True)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        runtime.close()
        await ui_runner.cleanup()
        await api_runner.cleanup()


__all__ = ["ModularGatewayRuntime", "serve_modular_gateway"]
