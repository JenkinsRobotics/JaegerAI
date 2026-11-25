"""Standalone aiohttp HTTP + SSE Gateway server built on GatewayStore, RunCoordinator & GatewayAuthPolicy."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from .auth import GatewayAuthPolicy
from .coordinator import RunCoordinator
from .store import GatewayStore, RequestConflictError
from .stream import SessionEventHub, format_sse


def create_gateway_app(
    *,
    store: GatewayStore,
    coordinator: RunCoordinator,
    hub: SessionEventHub,
    auth: GatewayAuthPolicy | None = None,
) -> web.Application:
    """Create a standalone aiohttp Gateway application with fail-closed auth and cursor-replay SSE."""
    policy = auth or GatewayAuthPolicy(allow_loopback_unauthenticated=True)

    @web.middleware
    async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        if request.path == "/health":
            return await handler(request)
        decision = policy.verify_http(request.headers, remote_addr=request.remote or "")
        if not decision.allowed:
            return web.json_response({"ok": False, "error": decision.reason}, status=401)
        request["actor"] = decision.actor
        return await handler(request)

    app = web.Application(middlewares=[auth_middleware])

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "jaeger-gateway"})

    async def list_sessions(request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        return web.json_response({"ok": True, "sessions": store.list_sessions(limit=limit)})

    async def create_session(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        sess = store.create_session(
            title=str(body.get("title") or "New Session"),
            workspace=str(body.get("workspace") or ""),
            metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
        )
        return web.json_response({"ok": True, "session": sess}, status=201)

    async def list_messages(request: web.Request) -> web.Response:
        sid = request.match_info["session_id"]
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        return web.json_response({"ok": True, "messages": store.list_messages(sid)})

    async def submit_run(request: web.Request) -> web.Response:
        sid = request.match_info["session_id"]
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        body = await request.json()
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return web.json_response({"ok": False, "error": "prompt is required"}, status=400)
        req_id = body.get("request_id")
        try:
            rid, fut = coordinator.submit(sid, prompt, request_id=req_id)
        except RequestConflictError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        if body.get("wait"):
            res = await asyncio.to_thread(fut.result, 60.0)
            return web.json_response({"ok": True, "request_id": rid, "result": res})
        return web.json_response({"ok": True, "request_id": rid, "status": "queued"}, status=202)

    async def stream_events(request: web.Request) -> web.StreamResponse:
        sid = request.match_info["session_id"]
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        last_id_raw = request.headers.get("Last-Event-ID") or request.query.get("after_seq") or "0"
        try:
            after_seq = max(0, int(last_id_raw))
        except ValueError:
            after_seq = 0
        once = request.query.get("once") in ("1", "true", "yes")

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)
        items = hub.replay_after(sid, after_seq=after_seq)
        for ev in items:
            frame = format_sse(event=ev["event"], data=ev["payload"], seq=ev["seq"])
            await resp.write(frame.encode("utf-8"))
        if once:
            await resp.write_eof()
            return resp
        cursor = items[-1]["seq"] if items else after_seq
        nxt = await asyncio.to_thread(hub.wait_for_events, sid, cursor, timeout=1.0)
        for ev in nxt:
            frame = format_sse(event=ev["event"], data=ev["payload"], seq=ev["seq"])
            await resp.write(frame.encode("utf-8"))
        await resp.write_eof()
        return resp

    async def list_approvals(request: web.Request) -> web.Response:
        sid = request.query.get("session_id")
        return web.json_response({"ok": True, "approvals": store.list_pending_approvals(session_id=sid)})

    async def resolve_approval(request: web.Request) -> web.Response:
        aid = request.match_info["approval_id"]
        body = await request.json()
        decision = str(body.get("decision") or "deny")
        note = str(body.get("note") or "")
        row = store.resolve_approval(aid, decision=decision, note=note)
        if row is None:
            return web.json_response({"ok": False, "error": "approval not found or already resolved"}, status=404)
        return web.json_response({"ok": True, "approval": row})

    app.router.add_get("/health", health)
    app.router.add_get("/v1/sessions", list_sessions)
    app.router.add_post("/v1/sessions", create_session)
    app.router.add_get("/v1/sessions/{session_id}/messages", list_messages)
    app.router.add_post("/v1/sessions/{session_id}/runs", submit_run)
    app.router.add_get("/v1/sessions/{session_id}/events", stream_events)
    app.router.add_get("/v1/approvals", list_approvals)
    app.router.add_post("/v1/approvals/{approval_id}/resolve", resolve_approval)
    return app


__all__ = ["create_gateway_app"]
