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

from jaeger_authority import MacOsSeatbeltSandbox, PolicyEngine, UnconfinedSandbox, redact_text
from jaeger_avatar import AvatarStore
from jaeger_business import BusinessStore
from jaeger_channels import ChannelHub
from jaeger_cognition import CharacterOverlay, CognitiveLifeLoop, IdentityStore, WorldModelStore
from jaeger_droid import HostDroidEmbodiment
from jaeger_embodiment_minecraft import MinecraftEmbodiment
from jaeger_events import EventBus
from jaeger_hardware import JP01Embodiment
from jaeger_loop import AgentLoop, TurnContext
from jaeger_mcp import (
    LiveMCPManager,
    MCPServerConfig,
    load_mcp_server_configs,
    remove_mcp_server_config,
    save_mcp_server_config,
)
from jaeger_memory import PersistentLearningStore, SqliteStateMemory
from jaeger_models import (
    ConversationCacheMarkStore,
    OllamaModel,
    bind_stream_sink,
    build_default_model,
)
from jaeger_orchestration import DryRunSimulator, PriorityTier, ResourceGovernor, WorkflowEngine
from jaeger_realtime import RealtimeVoiceSession
from jaeger_reliability import ReliabilityEngine
from jaeger_skills import scan_skill
from jaeger_tools import ToolRegistry, register_builtin_tools
from jaeger_vision import RollingFrameBuffer
from jaeger_youtube import MediaArchiveStore, YouTubeStudioStore

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
        streamed_any = False

        def _sink(kind: str, delta: str) -> None:
            nonlocal streamed_any
            streamed_any = True
            ev_name = "thinking.delta" if kind == "thinking" else "text.delta"
            self._hub.publish(
                self._session_id,
                ev_name,
                {"delta": delta, "step": ctx.step},
                generation=self._generation,
            )

        with bind_stream_sink(_sink):
            resp = call_next(ctx)

        if not streamed_any and not resp.get("streamed"):
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
                "output": redact_text(str(res.output or ""))[:2000],
                "error": redact_text(str(res.error)) if res.error else res.error,
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
        self.learning = PersistentLearningStore(self.state_dir)
        self.workflows = WorkflowEngine(self.state_dir / "workflows.sqlite3")
        self.dry_run = DryRunSimulator()
        self.governor = ResourceGovernor(memory_cap_gb=24.0, idle_cooldown_s=60.0)
        self.world = WorldModelStore(self.state_dir)
        self.identity = IdentityStore(self.state_dir)
        self.avatars = AvatarStore(self.state_dir)
        self.business = BusinessStore(self.state_dir)
        self.youtube = YouTubeStudioStore(self.state_dir)
        self.media_archive = MediaArchiveStore(self.state_dir)
        self.channels = ChannelHub(self.state_dir)
        self.minecraft = MinecraftEmbodiment(self.state_dir)
        self.jp01 = JP01Embodiment(dry_run=True)
        self.voice_presence = RealtimeVoiceSession()
        self.vision = RollingFrameBuffer(max_frames=6, max_total_mb=24.0)
        self.droid = HostDroidEmbodiment(vision_buffer=self.vision, world_model=self.world, probe_on_init=False)
        self.governor.register_idle_preempt_hook(lambda reason: self.minecraft.pause(reason=reason))
        self.cognition = CognitiveLifeLoop(
            world=self.world,
            governor=self.governor,
            tick_interval_s=15.0,
            on_state_change=lambda st: self.avatars.set_live_state(
                "jaeger",
                emotion=str(st.get("emotion") or "warm"),
                state=str(st.get("mode") or "observing"),
            ),
        )
        self.cognition.register_idle_life_handler("minecraft", lambda _snap: self.minecraft.act("idle_tick"))
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

        self.cache_health = ConversationCacheMarkStore()
        self._mcp_config_path = self.state_dir / "mcp_servers.json"
        mcp_configs = load_mcp_server_configs(self._mcp_config_path)
        self.mcp = LiveMCPManager(mcp_configs)
        if mcp_configs:
            try:
                self.mcp.register_into_registry(self.tools)
            except Exception:  # noqa: BLE001
                pass

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
        self.governor.begin_owner_work(reason=f"session:{session_id}")
        model_id = getattr(self.model, "model_id", self.model.name)
        self.governor.acquire_heavy_model(model_id, tier=PriorityTier.OWNER_WORK, owner_tag=session_id)
        try:
            loop = AgentLoop(
                model=self.model,
                tools=self.tools,
                memory=self.memory,
                reliability=self.reliability,
                events=self.events,
                middlewares=[_SseLoopMiddleware(session_id, generation, hub)],
                session_id=session_id,
                system_prompt=self.identity.compile_system_prompt(),
            )
            return loop.run_turn(prompt, max_steps=20)
        finally:
            self.governor.release_heavy_model(model_id)
            self.governor.end_owner_work()

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
                verdict = "safe"
                try:
                    verdict = scan_skill(md.parent, source="community").verdict
                except Exception:  # noqa: BLE001
                    verdict = "unknown"
                found.append({
                    "name": md.parent.name,
                    "path": str(md),
                    "security_verdict": verdict,
                })
        return found

    def _upsert_mcp_server(self, spec: Mapping[str, Any], *, connect: bool = True) -> list[dict[str, Any]]:
        name = str(spec.get("name") or "").strip()
        if not name:
            raise ValueError("MCP server name is required")
        url = str(spec.get("url") or "").strip()
        cmd = str(spec.get("command") or "").strip()
        transport = str(spec.get("transport") or ("streamable_http" if url else "stdio")).strip().lower()
        cfg = MCPServerConfig(
            name=name,
            transport=transport,
            command=cmd,
            args=tuple(str(a) for a in (spec.get("args") or ())),
            env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
            url=url,
            headers={str(k): str(v) for k, v in (spec.get("headers") or {}).items()},
            timeout_s=float(spec.get("timeout_s") or 30.0),
            enabled=bool(spec.get("enabled", True)),
            sandbox_workspace=str(spec.get("sandbox_workspace") or ""),
        )
        configs = save_mcp_server_config(self._mcp_config_path, cfg)
        if connect:
            return self.mcp.reload(configs, registry=self.tools)
        self.mcp._configs = {c.name: c for c in configs if c.enabled}  # noqa: SLF001
        return self.mcp.list_servers_health()

    def _delete_mcp_server(self, name: str) -> list[dict[str, Any]]:
        configs = remove_mcp_server_config(self._mcp_config_path, name)
        return self.mcp.reload(configs, registry=self.tools)

    def _reload_mcp_servers(self) -> list[dict[str, Any]]:
        configs = load_mcp_server_configs(self._mcp_config_path)
        return self.mcp.reload(configs, registry=self.tools)

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
            dry_run_simulator=self.dry_run,
            governor=self.governor,
            cognition_loop=self.cognition,
            world_model=self.world,
            identity_store=self.identity,
            avatar_store=self.avatars,
            business_store=self.business,
            youtube_store=self.youtube,
            media_archive=self.media_archive,
            channel_hub=self.channels,
            minecraft_embodiment=self.minecraft,
            jp01_embodiment=self.jp01,
            droid_embodiment=self.droid,
            voice_presence=self.voice_presence,
            vision_buffer=self.vision,
            memory_store=self.memory,
            learning_store=self.learning,
            skills_provider=self._discover_skills,
            mcp_provider=self.mcp.list_servers_health,
            mcp_upsert=self._upsert_mcp_server,
            mcp_delete=self._delete_mcp_server,
            mcp_reload=self._reload_mcp_servers,
            static_ui_dir=self.static_ui_dir if serve_ui else None,
        )

    def close(self) -> None:
        self.mcp.close()
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
