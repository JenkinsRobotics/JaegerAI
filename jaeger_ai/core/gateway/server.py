"""Jaeger Unified Gateway Daemon.

Decouples the Agent Engine from any UI window. Runs as a persistent background
service. Multi-client: allows Mac App, Web UI, and CLI to connect simultaneously,
share sessions, and stream live events without process teardown.
"""

from __future__ import annotations

import asyncio
import time
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

from .event_bus import GatewayEventBus
from .session_store import GatewaySessionStore

logger = logging.getLogger("jaeger.gateway")

DEFAULT_GATEWAY_PORT = int(os.environ.get("JAEGER_GATEWAY_PORT", "8810"))
DEFAULT_GATEWAY_HOST = os.environ.get("JAEGER_GATEWAY_HOST", "127.0.0.1")

# Locked spine endpoints (docs/spine-acceptance.md M10). Chat does not use :8813.
LOCKED_OLLAMA_URL = os.environ.get("JAEGER_OLLAMA_URL", "http://192.168.64.1:11434").rstrip("/")
LOCKED_BRIDGE_HEALTH_URL = os.environ.get(
    "JAEGER_BRIDGE_HEALTH_URL", "http://127.0.0.1:8791/health"
).rstrip("/")
LOCKED_WEBUI_URL = os.environ.get("JAEGER_WEBUI_URL", "http://100.74.2.15:8790").rstrip("/")
DEFAULT_OLLAMA_MODEL = os.environ.get("JAEGER_GATEWAY_OLLAMA_MODEL", "qwen2.5:3b")


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
        self.app.router.add_post("/v1/agents/{id}/handoff", self.handle_handoff_agent)
        self.app.router.add_get("/v1/handoffs", self.handle_list_handoffs)
        self.app.router.add_get("/v1/sessions", self.handle_list_sessions)
        self.app.router.add_post("/v1/sessions", self.handle_create_session)
        self.app.router.add_get("/v1/sessions/{id}", self.handle_get_session)
        self.app.router.add_delete("/v1/sessions/{id}", self.handle_delete_session)
        self.app.router.add_post("/v1/sessions/{id}/turns", self.handle_send_turn)
        self.app.router.add_post("/v1/sessions/{id}/handoff", self.handle_session_handoff)
        self.app.router.add_get("/v1/sessions/{id}/stream", self.handle_stream_events)
        self.app.router.add_post("/v1/approvals/{id}", self.handle_resolve_approval)

    async def _probe_http(self, url: str, *, timeout_s: float = 2.0) -> dict[str, Any]:
        """Probe a dependency; never raises — fail-closed callers inspect ok=False.

        HTTP 2xx alone is not enough: bridge may answer 200 with ``{"ok": false}``.
        """
        try:
            timeout = ClientTimeout(total=timeout_s)
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    body = await resp.text()
                    payload_ok: bool | None = None
                    try:
                        parsed = json.loads(body)
                        if isinstance(parsed, dict) and "ok" in parsed:
                            payload_ok = bool(parsed.get("ok"))
                        elif isinstance(parsed, dict) and "status" in parsed:
                            payload_ok = str(parsed.get("status")).lower() in {
                                "ok", "healthy", "up", "ready",
                            }
                    except Exception:  # noqa: BLE001
                        payload_ok = None
                    http_ok = 200 <= resp.status < 300
                    ok = http_ok if payload_ok is None else (http_ok and payload_ok)
                    return {
                        "ok": ok,
                        "status_code": resp.status,
                        "url": url,
                        "payload_ok": payload_ok,
                        "body_excerpt": body[:200],
                    }
        except Exception as exc:  # noqa: BLE001 — health must never crash
            return {"ok": False, "status_code": 0, "url": url, "error": str(exc)}

    async def _probe_webui_legacy_chat(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Probe locked WebUI legacy ``/api/chat``. HTTP 500 ⇒ fail-closed (M8).

        Non-500 responses (including 400/404 validation) mean the route is alive.
        Connection errors also fail closed — chat surface unreachable.
        """
        url = f"{LOCKED_WEBUI_URL}/api/chat"
        try:
            timeout = ClientTimeout(total=timeout_s)
            async with ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json={"session_id": "__jaeger_health_probe__", "message": "ping"},
                ) as resp:
                    body = await resp.text()
                    # CoS: must not claim all_green while legacy /api/chat returns 500.
                    ok = resp.status != 500
                    return {
                        "ok": ok,
                        "status_code": resp.status,
                        "url": url,
                        "required": True,
                        "body_excerpt": body[:200],
                        "note": (
                            "legacy /api/chat returned 500"
                            if resp.status == 500
                            else "legacy /api/chat reachable (non-500)"
                        ),
                    }
        except Exception as exc:  # noqa: BLE001 — health must never crash
            return {
                "ok": False,
                "status_code": 0,
                "url": url,
                "required": True,
                "error": str(exc),
                "note": "legacy /api/chat unreachable",
            }

    async def handle_health(self, request: web.Request) -> web.Response:
        """Fail-closed health: gateway + bridge + ollama + WebUI legacy chat (not :8813).

        When brain/bridge is dead OR legacy /api/chat returns 500, status is
        unhealthy and all_green is false (HTTP 503).
        """
        bridge = await self._probe_http(LOCKED_BRIDGE_HEALTH_URL)
        ollama = await self._probe_http(f"{LOCKED_OLLAMA_URL}/api/tags")
        webui_chat = await self._probe_webui_legacy_chat()
        checks = {
            "gateway": {"ok": True, "url": f"http://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}"},
            "bridge": bridge,
            "ollama": ollama,
            "webui_legacy_chat": webui_chat,
            "ares_agentgateway_8813": {
                "ok": None,
                "required": False,
                "note": "not on chat spine; M9 does not require :8813",
            },
        }
        required_ok = (
            bool(bridge.get("ok"))
            and bool(ollama.get("ok"))
            and bool(webui_chat.get("ok"))
        )
        all_green = required_ok
        status = "ok" if all_green else "unhealthy"
        payload = {
            "status": status,
            "service": "jaeger-gateway",
            "version": "0.4.1",
            "architecture": "openclaw-parity",
            "persistence_spine": True,
            "agents_api": "/v1/agents",
            "fundamentals_fee_gated": False,
            "fail_closed": True,
            "all_green": all_green,
            "checks": checks,
            "locked_endpoints": {
                "ollama": LOCKED_OLLAMA_URL,
                "webui": LOCKED_WEBUI_URL,
                "gateway": f"http://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}",
            },
        }
        return web.json_response(payload, status=200 if all_green else 503)

    def _registry(self):
        from jaeger_ai.core.agent_registry import AgentRegistry

        return AgentRegistry()

    async def handle_list_agents(self, request: web.Request) -> web.Response:
        """List JaegerNativeAgent + ThirdPartyAgent for Mac app / WebUI.

        Query: ``?kind=`` and/or ``?role=lead|specialist|runtime``.
        Unfiltered response is the full catalog including ``lead``.
        """
        kind = request.query.get("kind")
        role = request.query.get("role")
        registry = self._registry()
        if kind or role:
            agents = [
                a.to_dict()
                for a in registry.list_agents(kind=kind or None, role=role or None)
            ]
            payload: dict[str, Any] = {"agents": agents}
            if kind:
                payload["kind"] = kind
            if role:
                payload["role"] = role
            return web.json_response(payload)
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
                role=(str(body["role"]) if body.get("role") else None),
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

    async def handle_handoff_agent(self, request: web.Request) -> web.Response:
        """Lead → specialist handoff stub (agents-as-tools).

        Body: ``{task, from_agent_id?, require_approval?}``. Reuses Gateway
        ``pending_approvals`` when approval is required. Does not run a live
        multi-agent turn — returns a structured stub record.
        """
        from jaeger_ai.core.agent_registry.handoff import get_handoff_stub

        to_agent_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        task = str(body.get("task") or "").strip()
        if not task:
            return web.json_response({"error": "task is required"}, status=400)
        registry = self._registry()
        target = registry.get_agent(to_agent_id)
        if target is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        from_id = str(body.get("from_agent_id") or "native:jaeger").strip()
        require_approval = bool(body.get("require_approval", True))
        stub = get_handoff_stub()
        record = stub.create(
            from_agent_id=from_id,
            to_agent_id=target.id,
            task=task,
            require_approval=require_approval,
            metadata={"target_display": target.display_name, "target_role": (target.metadata or {}).get("role")},
        )
        if require_approval and record.approval_id:
            loop = asyncio.get_running_loop()
            self.pending_approvals[record.approval_id] = loop.create_future()
            self.event_bus.publish(
                "*",
                "approval.request",
                {
                    "approval_id": record.approval_id,
                    "handoff_id": record.id,
                    "kind": "handoff",
                    "from_agent_id": from_id,
                    "to_agent_id": target.id,
                    "task": task,
                    "options": ["once", "deny"],
                    "prompt": f"Allow handoff to {target.display_name}?",
                },
            )
        self.event_bus.publish("*", "agent.handoff", {"handoff": record.to_dict()})
        return web.json_response(record.to_dict(), status=202 if require_approval else 200)

    async def handle_list_handoffs(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.handoff import get_handoff_stub

        records = [r.to_dict() for r in get_handoff_stub().list_records()]
        return web.json_response({"handoffs": records, "count": len(records)})

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

    async def handle_session_handoff(self, request: web.Request) -> web.Response:
        """Transfer a session to another agent (P6) — never fee-gated.

        Body: ``{to_agent_id, reason?, keep_history?: true}``.
        Updates session ``agent_id`` metadata; optionally clears transcript.
        """
        session_id = request.match_info["id"]
        session = self.store.get_session(session_id)
        if not session:
            return web.json_response({"error": "Session not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        to_agent_id = str(body.get("to_agent_id") or "").strip()
        if not to_agent_id:
            return web.json_response({"error": "to_agent_id is required"}, status=400)
        keep_history = bool(body.get("keep_history", True))
        reason = str(body.get("reason") or "").strip() or None

        registry = self._registry()
        target = registry.get_agent(to_agent_id)
        if target is None:
            return web.json_response({"error": "Agent not found"}, status=404)

        previous_agent_id = session.get("agent_id") or (session.get("metadata") or {}).get(
            "agent_id"
        )
        if not keep_history:
            self.store.clear_messages(session_id)

        patch = {
            "agent_id": target.id,
            "previous_agent_id": previous_agent_id,
            "handoff_reason": reason,
            "handed_off_at": time.time(),
        }
        updated = self.store.update_metadata(session_id, patch)
        if updated is None:
            return web.json_response({"error": "Session not found"}, status=404)

        agent = target.to_dict()
        self.event_bus.publish(
            session_id,
            "session.handoff",
            {
                "session_id": session_id,
                "from_agent_id": previous_agent_id,
                "to_agent_id": target.id,
                "agent": agent,
                "reason": reason,
                "keep_history": keep_history,
            },
        )
        return web.json_response(
            {
                "session_id": session_id,
                "agent_id": target.id,
                "previous_agent_id": previous_agent_id,
                "agent": agent,
                "session": updated,
                "keep_history": keep_history,
                "reason": reason,
            }
        )

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

    def _session_agent_id(self, session: dict[str, Any] | None) -> str | None:
        """Resolve session agent_id from top-level or metadata (handoff patch)."""
        if not session:
            return None
        aid = session.get("agent_id")
        if aid:
            return str(aid)
        meta = session.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("agent_id"):
            return str(meta["agent_id"])
        return None

    def _resolve_session_agent(self, session_id: str):
        """Look up the session's AgentRecord via AgentRegistry (or None)."""
        session = self.store.get_session(session_id)
        agent_id = self._session_agent_id(session)
        if not agent_id:
            return None
        try:
            return self._registry().get_agent(agent_id)
        except Exception:  # noqa: BLE001 — chat must not fail closed on registry
            logger.exception("Failed to resolve session agent %s", agent_id)
            return None

    @staticmethod
    def _system_prompt_for_agent(agent) -> str:
        """Build a brief identity system prompt from catalog agent fields.

        Used so post-handoff turns speak as the specialist (display_name /
        role / specialty), not a hard-coded "You are Jaeger".
        """
        if agent is None:
            return "You are Jaeger. Reply briefly and helpfully."
        display = str(
            getattr(agent, "display_name", None)
            or getattr(agent, "name", None)
            or "Jaeger"
        )
        role = getattr(agent, "role", None)
        role_s = role.value if hasattr(role, "value") else (str(role) if role else "runtime")
        meta = getattr(agent, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        specialty = str(meta.get("specialty") or meta.get("role") or "").strip()
        summary = str(meta.get("summary") or "").strip()
        parts = [f"You are {display}."]
        if role_s == "lead":
            parts.append("You are the lead assistant.")
        elif role_s == "specialist":
            parts.append(f"You are the {specialty or display} specialist.")
            parts.append(
                f"When asked for your display name, reply with exactly: SPECIALIST:{display}."
            )
        if summary:
            parts.append(summary.rstrip(".") + ".")
        parts.append("Reply briefly and helpfully.")
        return " ".join(parts)

    async def _ollama_chat(self, text: str, *, system_prompt: str | None = None) -> str:
        """Live text turn via locked Ollama — never routes through :8813."""
        model = DEFAULT_OLLAMA_MODEL
        sys_content = system_prompt or "You are Jaeger. Reply briefly and helpfully."
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": sys_content,
                },
                {"role": "user", "content": text},
            ],
            "stream": False,
            "options": {"num_predict": 128},
        }
        timeout = ClientTimeout(total=90)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(f"{LOCKED_OLLAMA_URL}/api/chat", json=payload) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Ollama chat HTTP {resp.status}: {body[:500]}"
                    )
                data = json.loads(body)
        message = (data.get("message") or {})
        content = str(message.get("content") or "").strip()
        if not content:
            raise RuntimeError(f"Ollama returned empty content: {body[:500]}")
        return content

    async def _execute_turn(self, session_id: str, turn_id: str, text: str) -> None:
        """Background turn executor: real Ollama HTTP, not mocks, not :8813."""
        agent = self._resolve_session_agent(session_id)
        system_prompt = self._system_prompt_for_agent(agent)
        agent_fields: dict[str, Any] = {}
        if agent is not None:
            role = getattr(agent, "role", None)
            agent_fields = {
                "agent_id": agent.id,
                "role": role.value if hasattr(role, "value") else str(role),
                "display_name": agent.display_name,
            }
        try:
            self.event_bus.publish(session_id, "turn.delta", {
                "turn_id": turn_id,
                "delta": "",
                "model": DEFAULT_OLLAMA_MODEL,
                "backend": LOCKED_OLLAMA_URL,
                **agent_fields,
            })
            response_text = await self._ollama_chat(text, system_prompt=system_prompt)
            self.store.append_message(session_id, "assistant", response_text)
            self.store.update_status(session_id, "idle")
            self.event_bus.publish(session_id, "turn.finish", {
                "turn_id": turn_id,
                "output": response_text,
                "status": "completed",
                "backend": LOCKED_OLLAMA_URL,
                "model": DEFAULT_OLLAMA_MODEL,
                **agent_fields,
            })
        except Exception as exc:
            logger.exception("Turn execution failed: %s", exc)
            self.store.update_status(session_id, "failed")
            self.event_bus.publish(session_id, "turn.failed", {
                "turn_id": turn_id,
                "error": str(exc),
                **agent_fields,
            })

    async def handle_stream_events(self, request: web.Request) -> web.StreamResponse:
        """SSE for session + global (``*``) events.

        Surfaces P8 — approval request payload on the stream::

            event: approval.request
            data: {
              "approval_id": "approval_…",
              "kind": "handoff" | "tool" | str,
              "prompt": "Allow …?",
              "options": ["once", "deny"],
              "session_id": "…" | null,
              "handoff_id": "…" | null,
              "from_agent_id": "…" | null,
              "to_agent_id": "…" | null,
              "task": "…" | null
            }

        Resolve with ``POST /v1/approvals/{approval_id}`` body
        ``{"approved": true|false}`` → emits ``approval.resolved``.
        """
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

        from jaeger_ai.core.agent_registry.handoff import get_handoff_stub

        handoff = get_handoff_stub().resolve_approval(approval_id, approved=approved)

        self.event_bus.publish("*", "approval.resolved", {
            "approval_id": approval_id,
            "approved": approved,
            "handoff": handoff.to_dict() if handoff else None,
        })
        return web.json_response({
            "approval_id": approval_id,
            "resolved": True,
            "approved": approved,
            "handoff": handoff.to_dict() if handoff else None,
        })


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
