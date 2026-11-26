"""Full standalone aiohttp Gateway + WebUI server built 100% on modular jaeger-* packages."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

from .auth import GatewayAuthPolicy
from .coordinator import RunCoordinator
from .store import GatewayStore, RequestConflictError
from .stream import SessionEventHub, format_sse

ACTOR_KEY: web.RequestKey[str] = web.RequestKey("actor", str)


def create_gateway_app(
    *,
    store: GatewayStore,
    coordinator: RunCoordinator,
    hub: SessionEventHub,
    auth: GatewayAuthPolicy | None = None,
    runtime_info: Callable[[], dict[str, Any]] | None = None,
    tools_provider: Callable[[], list[dict[str, Any]]] | None = None,
    models_provider: Callable[[], dict[str, Any]] | None = None,
    model_selector: Callable[[str], dict[str, Any]] | None = None,
    workflows_engine: Any = None,
    memory_store: Any = None,
    skills_provider: Callable[[], list[dict[str, Any]]] | None = None,
    mcp_provider: Callable[[], list[dict[str, Any]]] | None = None,
    static_ui_dir: Path | None = None,
) -> web.Application:
    """Create the standalone aiohttp Gateway + optional static WebUI application."""
    policy = auth or GatewayAuthPolicy(allow_loopback_unauthenticated=True)
    started_at = time.time()
    allowed_hosts = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "testserver"})

    @web.middleware
    async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        raw_host = (request.headers.get("Host") or "").strip().lower()
        if raw_host:
            host_only = raw_host.split("]")[0] + "]" if raw_host.startswith("[") else raw_host.split(":")[0]
            if host_only and host_only not in allowed_hosts and (request.remote or "") in ("127.0.0.1", "::1", ""):
                return web.json_response({"ok": False, "error": "invalid Host header (DNS rebinding blocked)"}, status=403)
        if request.path == "/health" or not request.path.startswith("/v1/"):
            return await handler(request)
        decision = policy.verify_http(request.headers, remote_addr=request.remote or "")
        if not decision.allowed:
            return web.json_response({"ok": False, "error": decision.reason}, status=401)
        request[ACTOR_KEY] = decision.actor
        return await handler(request)

    app = web.Application(middlewares=[auth_middleware])

    async def health(_request: web.Request) -> web.Response:
        extra = runtime_info() if runtime_info is not None else {}
        return web.json_response({
            "ok": True,
            "status": "ok",
            "service": "jaeger-gateway",
            "architecture": "modular-standalone",
            "all_green": True,
            "uptime_s": round(time.time() - started_at, 1),
            "pid": os.getpid(),
            **extra,
        })

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

    async def delete_session(request: web.Request) -> web.Response:
        sid = request.match_info["session_id"]
        with store._lock, store._connect() as conn:  # noqa: SLF001
            cur = conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
        if cur.rowcount == 0:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        return web.json_response({"ok": True, "deleted": sid})

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
            res = await asyncio.to_thread(fut.result, 180.0)
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
                "X-Accel-Buffering": "no",
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
        try:
            while True:
                nxt = await asyncio.to_thread(hub.wait_for_events, sid, cursor, timeout=10.0)
                if not nxt:
                    await resp.write(b": keepalive\n\n")
                    continue
                for ev in nxt:
                    frame = format_sse(event=ev["event"], data=ev["payload"], seq=ev["seq"])
                    await resp.write(frame.encode("utf-8"))
                    cursor = max(cursor, int(ev["seq"]))
        except (ConnectionResetError, asyncio.CancelledError):
            pass
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

    async def list_tools(_request: web.Request) -> web.Response:
        items = tools_provider() if tools_provider is not None else []
        return web.json_response({"ok": True, "tools": items, "count": len(items)})

    async def list_models(_request: web.Request) -> web.Response:
        info = models_provider() if models_provider is not None else {"active": "", "models": []}
        return web.json_response({"ok": True, **info})

    async def select_model(request: web.Request) -> web.Response:
        if model_selector is None:
            return web.json_response({"ok": False, "error": "model selection unavailable"}, status=501)
        body = await request.json()
        model_id = str(body.get("model") or "").strip()
        if not model_id:
            return web.json_response({"ok": False, "error": "model is required"}, status=400)
        return web.json_response({"ok": True, **model_selector(model_id)})

    async def list_skills(_request: web.Request) -> web.Response:
        items = skills_provider() if skills_provider is not None else []
        return web.json_response({"ok": True, "skills": items, "count": len(items)})

    async def list_mcp_servers(_request: web.Request) -> web.Response:
        items = mcp_provider() if mcp_provider is not None else []
        return web.json_response({"ok": True, "servers": items, "count": len(items)})

    async def list_workflows(request: web.Request) -> web.Response:
        if workflows_engine is None:
            return web.json_response({"ok": True, "workflows": []})
        limit = int(request.query.get("limit", "25"))
        runs = [r.to_dict() for r in workflows_engine.list_runs(limit=limit)]
        return web.json_response({"ok": True, "workflows": runs})

    async def create_workflow(request: web.Request) -> web.Response:
        if workflows_engine is None:
            return web.json_response({"ok": False, "error": "workflows unavailable"}, status=501)
        body = await request.json()
        run = workflows_engine.create_run(
            name=str(body.get("name") or "Workflow"),
            steps=list(body.get("steps") or []),
            context=dict(body.get("context") or {}),
        )
        return web.json_response({"ok": True, "workflow": run.to_dict()}, status=201)

    async def approve_workflow_step(request: web.Request) -> web.Response:
        if workflows_engine is None:
            return web.json_response({"ok": False, "error": "workflows unavailable"}, status=501)
        rid = request.match_info["run_id"]
        body = await request.json()
        step_id = str(body.get("step_id") or "")
        approved = bool(body.get("approved", True))
        note = str(body.get("note") or "")
        run = workflows_engine.approve_step(rid, step_id, approved=approved, note=note)
        return web.json_response({"ok": True, "workflow": run.to_dict()})

    async def list_facts(_request: web.Request) -> web.Response:
        if memory_store is None:
            return web.json_response({"ok": True, "facts": []})
        with memory_store._connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                "SELECT subject, key, value, category, updated_at FROM facts ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()
        facts = [
            {"subject": r[0], "key": r[1], "value": r[2], "category": r[3], "updated_at": r[4]}
            for r in rows
        ]
        return web.json_response({"ok": True, "facts": facts})

    async def put_fact(request: web.Request) -> web.Response:
        if memory_store is None:
            return web.json_response({"ok": False, "error": "memory store unavailable"}, status=501)
        body = await request.json()
        key = str(body.get("key") or "").strip()
        value = str(body.get("value") or "").strip()
        if not key:
            return web.json_response({"ok": False, "error": "key is required"}, status=400)
        memory_store.remember(
            key,
            value,
            subject=str(body.get("subject") or "user"),
            category=body.get("category"),
        )
        return web.json_response({"ok": True, "key": key, "value": value}, status=201)

    async def delete_fact(request: web.Request) -> web.Response:
        if memory_store is None:
            return web.json_response({"ok": False, "error": "memory store unavailable"}, status=501)
        key = request.match_info["key"]
        subject = request.query.get("subject", "user")
        with memory_store._connect() as conn:  # noqa: SLF001
            conn.execute("DELETE FROM facts WHERE subject = ? AND key = ?", (subject, key))
        return web.json_response({"ok": True, "deleted": key})

    async def diagnostics(_request: web.Request) -> web.Response:
        extra = runtime_info() if runtime_info is not None else {}
        return web.json_response({
            "ok": True,
            "pid": os.getpid(),
            "uptime_s": round(time.time() - started_at, 1),
            "sessions_count": len(store.list_sessions(limit=500)),
            "pending_approvals": len(store.list_pending_approvals()),
            **extra,
        })

    app.router.add_get("/health", health)
    app.router.add_get("/v1/sessions", list_sessions)
    app.router.add_post("/v1/sessions", create_session)
    app.router.add_delete("/v1/sessions/{session_id}", delete_session)
    app.router.add_get("/v1/sessions/{session_id}/messages", list_messages)
    app.router.add_post("/v1/sessions/{session_id}/runs", submit_run)
    app.router.add_get("/v1/sessions/{session_id}/events", stream_events)
    app.router.add_get("/v1/approvals", list_approvals)
    app.router.add_post("/v1/approvals/{approval_id}/resolve", resolve_approval)
    app.router.add_get("/v1/tools", list_tools)
    app.router.add_get("/v1/models", list_models)
    app.router.add_post("/v1/models/select", select_model)
    app.router.add_get("/v1/skills", list_skills)
    app.router.add_get("/v1/mcp/servers", list_mcp_servers)
    app.router.add_get("/v1/workflows", list_workflows)
    app.router.add_post("/v1/workflows", create_workflow)
    app.router.add_post("/v1/workflows/{run_id}/approve", approve_workflow_step)
    app.router.add_get("/v1/memory/facts", list_facts)
    app.router.add_post("/v1/memory/facts", put_fact)
    app.router.add_delete("/v1/memory/facts/{key}", delete_fact)
    app.router.add_get("/v1/diagnostics", diagnostics)

    # Optional static WebUI bundle serving (SPA fallback to index.html)
    if static_ui_dir is not None and static_ui_dir.is_dir():
        ui_root = static_ui_dir.resolve()
        assets_dir = ui_root / "assets"
        if assets_dir.is_dir():
            app.router.add_static("/assets", assets_dir, follow_symlinks=False)

        async def serve_spa(request: web.Request) -> web.StreamResponse:
            rel = request.match_info.get("tail", "").lstrip("/")
            if rel:
                cand = (ui_root / rel).resolve()
                if ui_root in cand.parents and cand.is_file():
                    return web.FileResponse(cand)
            index = ui_root / "index.html"
            if index.is_file():
                return web.FileResponse(index)
            return web.Response(text="Jaeger UI bundle not built", status=503)

        app.router.add_get("/", serve_spa)
        app.router.add_get("/{tail:.*}", serve_spa)

    return app


__all__ = ["ACTOR_KEY", "create_gateway_app"]
