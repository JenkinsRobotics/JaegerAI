"""Jaeger Unified Gateway Daemon.

Decouples the Agent Engine from any UI window. Runs as a persistent background
service. Multi-client: allows Mac App, Web UI, and CLI to connect simultaneously,
share sessions, and stream live events without process teardown.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web

from .event_bus import GatewayEventBus
from .session_store import GatewaySessionStore

logger = logging.getLogger("jaeger.gateway")

DEFAULT_GATEWAY_PORT = int(os.environ.get("JAEGER_GATEWAY_PORT", "8810"))
DEFAULT_GATEWAY_HOST = os.environ.get("JAEGER_GATEWAY_HOST", "127.0.0.1")


class JaegerGatewayApp:
    def __init__(
        self,
        store: GatewaySessionStore | None = None,
        event_bus: GatewayEventBus | None = None,
    ) -> None:
        self.store = store or GatewaySessionStore()
        self.event_bus = event_bus or GatewayEventBus()
        self.pending_approvals: dict[str, asyncio.Future[bool]] = {}
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self) -> None:
        self.app.router.add_get("/health", self.handle_health)
        # Agent catalog — persistence spine for Mac app + WebUI clients.
        self.app.router.add_get("/v1/agents", self.handle_list_agents)
        self.app.router.add_post("/v1/agents", self.handle_create_agent)
        self.app.router.add_get("/v1/agents/{id}", self.handle_get_agent)
        self.app.router.add_post("/v1/agents/{id}/activate", self.handle_activate_agent)
        self.app.router.add_get("/v1/sessions", self.handle_list_sessions)
        self.app.router.add_post("/v1/sessions", self.handle_create_session)
        self.app.router.add_get("/v1/sessions/{id}", self.handle_get_session)
        self.app.router.add_delete("/v1/sessions/{id}", self.handle_delete_session)
        self.app.router.add_post("/v1/sessions/{id}/turns", self.handle_send_turn)
        self.app.router.add_get("/v1/sessions/{id}/stream", self.handle_stream_events)
        self.app.router.add_post("/v1/approvals/{id}", self.handle_resolve_approval)

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "service": "jaeger-gateway",
            "version": "0.4.0",
            "architecture": "openclaw-parity",
            "persistence_spine": True,
            "agents_api": "/v1/agents",
            "fundamentals_fee_gated": False,
        })

    def _registry(self):
        from jaeger_ai.core.agent_registry import AgentRegistry

        return AgentRegistry()

    async def handle_list_agents(self, request: web.Request) -> web.Response:
        """List JaegerNativeAgent + ThirdPartyAgent for Mac app / WebUI."""
        kind = request.query.get("kind")
        registry = self._registry()
        if kind:
            agents = [a.to_dict() for a in registry.list_agents(kind=kind)]
            return web.json_response({"agents": agents, "kind": kind})
        return web.json_response(registry.to_catalog())

    async def handle_create_agent(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        name = str(body.get("name") or "").strip()
        if not name:
            return web.json_response({"error": "name is required"}, status=400)
        kind = str(body.get("kind") or "jaeger_native").strip()
        try:
            record = self._registry().create_agent(
                name,
                kind=kind,
                display_name=(str(body["display_name"]) if body.get("display_name") else None),
                adapter=(str(body["adapter"]) if body.get("adapter") else None),
                profile_id=(str(body["profile_id"]) if body.get("profile_id") else None),
                endpoint=(str(body["endpoint"]) if body.get("endpoint") else None),
                port=(int(body["port"]) if body.get("port") is not None else None),
                metadata=dict(body.get("metadata") or {}),
                make_active=bool(body.get("make_active", False)),
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        self.event_bus.publish("*", "agent.created", {"agent": record.to_dict()})
        return web.json_response(record.to_dict(), status=201)

    async def handle_get_agent(self, request: web.Request) -> web.Response:
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        return web.json_response(record.to_dict())

    async def handle_activate_agent(self, request: web.Request) -> web.Response:
        """Switch active agent — never fee-gated (fundamentals stay open)."""
        agent_id = request.match_info["id"]
        try:
            record = self._registry().set_active(agent_id)
        except KeyError:
            return web.json_response({"error": "Agent not found"}, status=404)
        self.event_bus.publish("*", "agent.activated", {"agent": record.to_dict()})
        return web.json_response(record.to_dict())

    async def handle_list_sessions(self, request: web.Request) -> web.Response:
        profile = request.query.get("profile")
        sessions = self.store.list_sessions(profile=profile)
        return web.json_response({"sessions": sessions})

    async def handle_create_session(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        session_id = str(body.get("session_id") or uuid.uuid4().hex)
        title = str(body.get("title") or "New Conversation")
        profile = str(body.get("profile") or "jaeger")
        workspace = str(body.get("workspace") or "")
        metadata = body.get("metadata") or {}

        session = self.store.ensure_session(
            session_id,
            title=title,
            profile=profile,
            workspace=workspace,
            metadata=metadata,
        )
        self.event_bus.publish(session_id, "session.created", {"session": session})
        return web.json_response(session, status=201)

    async def handle_get_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        session = self.store.get_session(session_id)
        if not session:
            return web.json_response({"error": "Session not found"}, status=404)
        return web.json_response(session)

    async def handle_delete_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        deleted = self.store.delete_session(session_id)
        if not deleted:
            return web.json_response({"error": "Session not found"}, status=404)
        self.event_bus.publish(session_id, "session.deleted", {"session_id": session_id})
        return web.json_response({"deleted": True})

    async def handle_send_turn(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        text = str(body.get("text") or body.get("input") or "").strip()
        if not text:
            return web.json_response({"error": "Missing turn text"}, status=400)

        # Ensure session exists
        self.store.ensure_session(session_id)
        self.store.update_status(session_id, "running")

        # Record user message
        msg_id = self.store.append_message(session_id, "user", text)
        turn_id = uuid.uuid4().hex

        # Publish turn.start to all subscribers (Mac App, Web UI, etc.)
        self.event_bus.publish(session_id, "turn.start", {
            "turn_id": turn_id,
            "message_id": msg_id,
            "text": text,
        })

        # Start autonomous execution in background task so API responds immediately
        asyncio.create_task(self._execute_turn(session_id, turn_id, text))

        return web.json_response({
            "session_id": session_id,
            "turn_id": turn_id,
            "status": "running",
        })

    async def _execute_turn(self, session_id: str, turn_id: str, text: str) -> None:
        """Background turn executor that emits live streaming events."""
        try:
            # Emit token stream
            self.event_bus.publish(session_id, "turn.delta", {
                "turn_id": turn_id,
                "delta": f"[Jaeger received: {text[:40]}...]",
            })
            await asyncio.sleep(0.05)

            response_text = f"Processed: {text}"
            self.store.append_message(session_id, "assistant", response_text)
            self.store.update_status(session_id, "idle")

            self.event_bus.publish(session_id, "turn.finish", {
                "turn_id": turn_id,
                "output": response_text,
                "status": "completed",
            })
        except Exception as exc:
            logger.exception("Turn execution failed: %s", exc)
            self.store.update_status(session_id, "failed")
            self.event_bus.publish(session_id, "turn.failed", {
                "turn_id": turn_id,
                "error": str(exc),
            })

    async def handle_stream_events(self, request: web.Request) -> web.StreamResponse:
        session_id = request.match_info["id"]
        last_event_id = int(request.query.get("last_event_id") or 0)

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        try:
            async for evt in self.event_bus.subscribe(session_id, since_event_id=last_event_id):
                payload = json.dumps({
                    "event_id": evt.event_id,
                    "session_id": evt.session_id,
                    "event": evt.event,
                    "data": evt.data,
                    "timestamp": evt.timestamp,
                })
                chunk = f"id: {evt.event_id}\nevent: {evt.event}\ndata: {payload}\n\n"
                await response.write(chunk.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass

        return response

    async def handle_resolve_approval(self, request: web.Request) -> web.Response:
        approval_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        approved = bool(body.get("approved", True))

        future = self.pending_approvals.pop(approval_id, None)
        if future and not future.done():
            future.set_result(approved)

        self.event_bus.publish("*", "approval.resolved", {
            "approval_id": approval_id,
            "approved": approved,
        })
        return web.json_response({"approval_id": approval_id, "resolved": True})


def create_gateway_server(
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
    store: GatewaySessionStore | None = None,
) -> tuple[JaegerGatewayApp, web.AppRunner]:
    gateway = JaegerGatewayApp(store=store)
    runner = web.AppRunner(gateway.app)
    return gateway, runner


async def run_gateway_forever(
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
) -> None:
    gateway, runner = create_gateway_server(host, port)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"[jaeger-gateway] Listening on http://{host}:{port}")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run_gateway_forever())
