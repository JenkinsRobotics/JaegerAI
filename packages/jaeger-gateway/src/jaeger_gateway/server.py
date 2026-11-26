"""Full standalone aiohttp Gateway + WebUI server built 100% on modular jaeger-* packages."""

from __future__ import annotations

import asyncio
import base64
import os
import time
from pathlib import Path
from typing import Any, Callable

from aiohttp import web
from jaeger_avatar import AvatarError, build_viseme_timeline
from jaeger_youtube import plan_phased_research, probe_youtube_toolchain

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
    dry_run_simulator: Any = None,
    governor: Any = None,
    cognition_loop: Any = None,
    world_model: Any = None,
    avatar_store: Any = None,
    business_store: Any = None,
    youtube_store: Any = None,
    channel_hub: Any = None,
    memory_store: Any = None,
    learning_store: Any = None,
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
        strategy = str(body.get("multitask_strategy") or "enqueue")
        try:
            rid, fut = coordinator.submit(sid, prompt, request_id=req_id, multitask_strategy=strategy)
        except (RequestConflictError, RuntimeError) as exc:
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

    async def dry_run_workflow(request: web.Request) -> web.Response:
        if dry_run_simulator is None:
            return web.json_response({"ok": False, "error": "dry-run simulator unavailable"}, status=501)
        body = await request.json()
        report = dry_run_simulator.simulate_workflow(
            str(body.get("name") or "Workflow"),
            list(body.get("steps") or []),
            initial_context=dict(body.get("context") or {}),
        )
        return web.json_response({"ok": True, "dry_run": report.to_dict()})

    async def system_resources(_request: web.Request) -> web.Response:
        if governor is None:
            return web.json_response({"ok": True, "resources": {}})
        return web.json_response({"ok": True, "resources": governor.snapshot()})

    async def set_idle_life(request: web.Request) -> web.Response:
        if governor is None:
            return web.json_response({"ok": False, "error": "governor unavailable"}, status=501)
        body = await request.json()
        governor.set_idle_life_enabled(bool(body.get("enabled", True)))
        return web.json_response({"ok": True, "resources": governor.snapshot()})

    async def set_estop(request: web.Request) -> web.Response:
        if governor is None:
            return web.json_response({"ok": False, "error": "governor unavailable"}, status=501)
        body = await request.json()
        if bool(body.get("active", True)):
            governor.trigger_estop(str(body.get("reason") or "operator_api"))
        else:
            governor.release_estop()
        return web.json_response({"ok": True, "resources": governor.snapshot()})

    async def get_cognition_state(_request: web.Request) -> web.Response:
        if cognition_loop is None:
            return web.json_response({"ok": True, "cognition": {}, "world": {}})
        return web.json_response({
            "ok": True,
            "cognition": cognition_loop.state.to_dict(),
            "world": world_model.snapshot() if world_model is not None else {},
            "perceptions": [p.to_dict() for p in (world_model.recent_perceptions(limit=12) if world_model else [])],
        })

    async def post_perception(request: web.Request) -> web.Response:
        if cognition_loop is None:
            return web.json_response({"ok": False, "error": "cognition loop unavailable"}, status=501)
        body = await request.json()
        ev = cognition_loop.ingest_perception(
            modality=str(body.get("modality") or "owner"),
            kind=str(body.get("kind") or "event"),
            payload=dict(body.get("payload") or {}),
            salience=float(body.get("salience", 0.6)),
        )
        return web.json_response({"ok": True, "perception": ev.to_dict()}, status=201)

    async def get_avatar(request: web.Request) -> web.Response:
        if avatar_store is None:
            return web.json_response({"ok": False, "error": "avatar store unavailable"}, status=501)
        try:
            data = avatar_store.get_agent_avatar(request.match_info["agent_id"])
            return web.json_response({"ok": True, **data})
        except AvatarError as exc:
            return web.json_response({"ok": False, **exc.payload}, status=exc.status)

    async def put_avatar(request: web.Request) -> web.Response:
        if avatar_store is None:
            return web.json_response({"ok": False, "error": "avatar store unavailable"}, status=501)
        body = await request.json()
        try:
            data = avatar_store.set_agent_avatar(
                request.match_info["agent_id"],
                asset_sha=body.get("asset_sha"),
                mode=str(body.get("mode") or "2d_character"),
                display_name=str(body.get("display_name") or request.match_info["agent_id"].capitalize()),
                accent_color=str(body.get("accent_color") or "#5B8DEF"),
                preset=str(body.get("preset") or "studio_cel"),
            )
            return web.json_response({"ok": True, **data})
        except AvatarError as exc:
            return web.json_response({"ok": False, **exc.payload}, status=exc.status)

    async def put_avatar_live(request: web.Request) -> web.Response:
        if avatar_store is None:
            return web.json_response({"ok": False, "error": "avatar store unavailable"}, status=501)
        body = await request.json()
        try:
            live = avatar_store.set_live_state(
                request.match_info["agent_id"],
                emotion=body.get("emotion"),
                intensity=body.get("intensity"),
                state=body.get("state"),
                amplitude=body.get("amplitude"),
            )
            return web.json_response({"ok": True, "live": live})
        except AvatarError as exc:
            return web.json_response({"ok": False, **exc.payload}, status=exc.status)

    async def get_avatar_visemes(request: web.Request) -> web.Response:
        text = str(request.query.get("text") or "Hello, Jaeger is online.")
        timeline = build_viseme_timeline(text)
        return web.json_response({"ok": True, **timeline})

    async def list_avatar_assets(_request: web.Request) -> web.Response:
        if avatar_store is None:
            return web.json_response({"ok": True, "assets": []})
        return web.json_response({"ok": True, "assets": avatar_store.list_assets()})

    async def upload_avatar_asset(request: web.Request) -> web.Response:
        if avatar_store is None:
            return web.json_response({"ok": False, "error": "avatar store unavailable"}, status=501)
        body = await request.json()
        b64 = str(body.get("data_base64") or "")
        name = str(body.get("name") or "avatar.vrm")
        if "," in b64 and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        try:
            raw = base64.b64decode(b64, validate=True)
            rec = avatar_store.add_asset(raw, name)
            return web.json_response({"ok": True, "asset": rec}, status=201)
        except AvatarError as exc:
            return web.json_response({"ok": False, **exc.payload}, status=exc.status)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def serve_avatar_asset(request: web.Request) -> web.StreamResponse:
        if avatar_store is None:
            return web.json_response({"ok": False, "error": "avatar store unavailable"}, status=501)
        hit = avatar_store.get_asset_file(request.match_info["sha"])
        if hit is None:
            return web.json_response({"ok": False, "error": "asset not found"}, status=404)
        path, mime = hit
        return web.FileResponse(path, headers={"Content-Type": mime})

    async def get_business_team(_request: web.Request) -> web.Response:
        if business_store is None:
            return web.json_response({"ok": True, "team": [], "budgets": {}})
        return web.json_response({
            "ok": True,
            "team": business_store.list_team(),
            "budgets": business_store.budget_summary(),
            "projects": [p.to_dict() for p in business_store.list_projects()],
        })

    async def create_business_project(request: web.Request) -> web.Response:
        if business_store is None:
            return web.json_response({"ok": False, "error": "business store unavailable"}, status=501)
        body = await request.json()
        proj = business_store.create_project(
            name=str(body.get("name") or "New Initiative"),
            kind=str(body.get("kind") or "youtube_channel"),
            stage=str(body.get("stage") or "planning"),
            owner_role=str(body.get("owner_role") or "producer"),
            budget_usd=float(body.get("budget_usd", 50.0)),
            approval_required=bool(body.get("approval_required", True)),
            metadata=dict(body.get("metadata") or {}),
        )
        return web.json_response({"ok": True, "project": proj.to_dict()}, status=201)

    async def record_business_spend(request: web.Request) -> web.Response:
        if business_store is None:
            return web.json_response({"ok": False, "error": "business store unavailable"}, status=501)
        body = await request.json()
        ok, reason = business_store.record_spend(
            project_id=str(body.get("project_id") or ""),
            role_id=str(body.get("role_id") or "ops"),
            amount_usd=float(body.get("amount_usd", 0.0)),
            description=str(body.get("description") or ""),
            approved_by=str(body.get("approved_by") or ""),
        )
        return web.json_response(
            {"ok": ok, "reason": reason, "budgets": business_store.budget_summary()},
            status=200 if ok else 403,
        )

    async def youtube_tools(_request: web.Request) -> web.Response:
        models_info = models_provider() if models_provider is not None else {}
        model_ids = [str(m.get("id") or "") for m in (models_info.get("models") or []) if isinstance(m, dict)]
        return web.json_response({"ok": True, "tools": probe_youtube_toolchain(model_ids)})

    async def youtube_list_episodes(_request: web.Request) -> web.Response:
        if youtube_store is None:
            return web.json_response({"ok": True, "episodes": []})
        return web.json_response({"ok": True, "episodes": [e.to_dict() for e in youtube_store.list_episodes()]})

    async def youtube_create_episode(request: web.Request) -> web.Response:
        if youtube_store is None:
            return web.json_response({"ok": False, "error": "youtube store unavailable"}, status=501)
        body = await request.json()
        ep = youtube_store.create_episode(
            title=str(body.get("title") or "Untitled Episode"),
            topic=str(body.get("topic") or ""),
            target_duration_s=int(body.get("target_duration_s", 480)),
            hook=str(body.get("hook") or ""),
            script_md=str(body.get("script_md") or ""),
        )
        return web.json_response({"ok": True, "episode": ep.to_dict()}, status=201)

    async def youtube_advance_episode(request: web.Request) -> web.Response:
        if youtube_store is None:
            return web.json_response({"ok": False, "error": "youtube store unavailable"}, status=501)
        eid = request.match_info["episode_id"]
        body = await request.json()
        ok, reason, ep = youtube_store.advance_stage(
            eid,
            target_stage=str(body.get("stage") or ""),
            owner_approved=body.get("owner_approved"),
            approval_note=str(body.get("approval_note") or ""),
        )
        return web.json_response(
            {"ok": ok, "reason": reason, "episode": ep.to_dict() if ep else None},
            status=200 if ok else (404 if reason == "episode_not_found" else 403),
        )

    async def youtube_plan_research(request: web.Request) -> web.Response:
        body = await request.json()
        plan = plan_phased_research(
            str(body.get("source") or ""),
            video_ids=list(body.get("video_ids") or []),
            llm_model=str(body.get("llm_model") or "gemma4:12b"),
            vlm_model=str(body.get("vlm_model") or "qwen3-vl:8b"),
        )
        return web.json_response({"ok": True, "plan": plan})

    async def channels_status(_request: web.Request) -> web.Response:
        if channel_hub is None:
            return web.json_response({"ok": True, "channels": {}, "outbox": []})
        return web.json_response({
            "ok": True,
            "channels": channel_hub.status(),
            "outbox": [m.to_dict() for m in channel_hub.list_outbox(limit=25)],
        })

    async def channels_send(request: web.Request) -> web.Response:
        if channel_hub is None:
            return web.json_response({"ok": False, "error": "channel hub unavailable"}, status=501)
        body = await request.json()
        msg = channel_hub.enqueue(
            channel=str(body.get("channel") or "local_log"),
            recipient=str(body.get("recipient") or "owner"),
            body=str(body.get("body") or ""),
            approved=bool(body.get("approved", False)),
            dry_run=bool(body.get("dry_run", False)),
        )
        return web.json_response({"ok": True, "message": msg.to_dict()}, status=201)

    async def list_learning(request: web.Request) -> web.Response:
        if learning_store is None:
            return web.json_response({"ok": True, "entries": []})
        q = (request.query.get("q") or "").strip()
        scope = (request.query.get("scope") or "").strip() or None
        limit = int(request.query.get("limit", "50"))
        items = (
            learning_store.recall(q, scopes=[scope] if scope else None, limit=limit)
            if q
            else learning_store.list_entries(scope=scope, limit=limit)
        )
        return web.json_response({"ok": True, "entries": [e.to_dict() for e in items], "count": len(items)})

    async def add_learning(request: web.Request) -> web.Response:
        if learning_store is None:
            return web.json_response({"ok": False, "error": "learning store unavailable"}, status=501)
        body = await request.json()
        content = str(body.get("content") or "").strip()
        if not content:
            return web.json_response({"ok": False, "error": "content is required"}, status=400)
        entry = learning_store.add(
            scope=str(body.get("scope") or "learned_knowledge"),
            subject=str(body.get("subject") or "owner"),
            content=content,
            importance=float(body.get("importance", 0.6)),
            tags=list(body.get("tags") or []),
            parent_ids=list(body.get("parent_ids") or []),
        )
        return web.json_response({"ok": True, "entry": entry.to_dict()}, status=201)

    async def forget_learning(request: web.Request) -> web.Response:
        if learning_store is None:
            return web.json_response({"ok": False, "error": "learning store unavailable"}, status=501)
        eid = request.match_info["entry_id"]
        cascade = request.query.get("cascade", "true").lower() not in ("0", "false", "no")
        removed = learning_store.forget(eid, cascade=cascade)
        return web.json_response({"ok": True, "removed": removed, "count": len(removed)})

    async def list_goals(request: web.Request) -> web.Response:
        if learning_store is None:
            return web.json_response({"ok": True, "goals": []})
        domain = (request.query.get("domain") or "").strip() or None
        status = (request.query.get("status") or "").strip() or None
        goals = learning_store.list_goals(domain=domain, status=status)
        return web.json_response({"ok": True, "goals": [g.to_dict() for g in goals], "count": len(goals)})

    async def upsert_goal(request: web.Request) -> web.Response:
        if learning_store is None:
            return web.json_response({"ok": False, "error": "learning store unavailable"}, status=501)
        body = await request.json()
        title = str(body.get("title") or "").strip()
        if not title:
            return web.json_response({"ok": False, "error": "title is required"}, status=400)
        goal = learning_store.upsert_goal(
            goal_id=body.get("goal_id"),
            domain=str(body.get("domain") or "business"),
            title=title,
            status=str(body.get("status") or "active"),
            priority=int(body.get("priority", 2)),
            checkpoint=dict(body.get("checkpoint") or {}),
            notes=str(body.get("notes") or ""),
        )
        return web.json_response({"ok": True, "goal": goal.to_dict()}, status=201)

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
    app.router.add_post("/v1/workflows/dry-run", dry_run_workflow)
    app.router.add_post("/v1/workflows/{run_id}/approve", approve_workflow_step)
    app.router.add_get("/v1/system/resources", system_resources)
    app.router.add_post("/v1/system/idle-life", set_idle_life)
    app.router.add_post("/v1/system/estop", set_estop)
    app.router.add_get("/v1/cognition/state", get_cognition_state)
    app.router.add_post("/v1/cognition/perceive", post_perception)
    app.router.add_get("/v1/avatars/assets", list_avatar_assets)
    app.router.add_post("/v1/avatars/assets", upload_avatar_asset)
    app.router.add_get("/v1/avatars/assets/{sha}/file", serve_avatar_asset)
    app.router.add_get("/v1/avatars/{agent_id}", get_avatar)
    app.router.add_put("/v1/avatars/{agent_id}", put_avatar)
    app.router.add_put("/v1/avatars/{agent_id}/live", put_avatar_live)
    app.router.add_get("/v1/avatars/{agent_id}/visemes", get_avatar_visemes)
    app.router.add_get("/v1/business/team", get_business_team)
    app.router.add_post("/v1/business/projects", create_business_project)
    app.router.add_post("/v1/business/spend", record_business_spend)
    app.router.add_get("/v1/youtube/tools", youtube_tools)
    app.router.add_get("/v1/youtube/episodes", youtube_list_episodes)
    app.router.add_post("/v1/youtube/episodes", youtube_create_episode)
    app.router.add_post("/v1/youtube/episodes/{episode_id}/advance", youtube_advance_episode)
    app.router.add_post("/v1/youtube/research/plan", youtube_plan_research)
    app.router.add_get("/v1/channels/status", channels_status)
    app.router.add_post("/v1/channels/send", channels_send)

    if cognition_loop is not None:
        async def _start_cognition(_app: web.Application) -> None:
            cognition_loop.start()

        async def _stop_cognition(_app: web.Application) -> None:
            await cognition_loop.stop()

        app.on_startup.append(_start_cognition)
        app.on_cleanup.append(_stop_cognition)
    app.router.add_get("/v1/memory/facts", list_facts)
    app.router.add_post("/v1/memory/facts", put_fact)
    app.router.add_delete("/v1/memory/facts/{key}", delete_fact)
    app.router.add_get("/v1/memory/learning", list_learning)
    app.router.add_post("/v1/memory/learning", add_learning)
    app.router.add_delete("/v1/memory/learning/{entry_id}", forget_learning)
    app.router.add_get("/v1/memory/goals", list_goals)
    app.router.add_post("/v1/memory/goals", upsert_goal)
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
