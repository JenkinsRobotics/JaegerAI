"""Full standalone aiohttp Gateway + WebUI server built 100% on modular jaeger-* packages."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from aiohttp import web
from jaeger_avatar import AvatarError, build_viseme_timeline
from jaeger_cognition import CharacterOverlay
from jaeger_youtube import export_episode_to_otio, plan_phased_research, probe_youtube_toolchain

from .auth import GatewayAuthPolicy
from .coordinator import RunCoordinator
from .store import MAIN_CHAT_SESSION_ID, GatewayStore, RequestConflictError
from .stream import SessionEventHub, format_sse

ACTOR_KEY: web.RequestKey[str] = web.RequestKey("actor", str)

# Inbound events are untrusted and are never dispatched as agent turns.
SUPPORTED_EXTERNAL_CHANNELS = frozenset({"telegram", "imessage", "webhook"})



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
    identity_store: Any = None,
    avatar_store: Any = None,
    business_store: Any = None,
    youtube_store: Any = None,
    media_archive: Any = None,
    channel_hub: Any = None,
    minecraft_embodiment: Any = None,
    jp01_embodiment: Any = None,
    droid_embodiment: Any = None,
    voice_presence: Any = None,
    vision_buffer: Any = None,
    memory_store: Any = None,
    learning_store: Any = None,
    skills_provider: Callable[[], list[dict[str, Any]]] | None = None,
    mcp_provider: Callable[[], list[dict[str, Any]]] | None = None,
    mcp_upsert: Callable[..., list[dict[str, Any]]] | None = None,
    mcp_delete: Callable[[str], list[dict[str, Any]]] | None = None,
    mcp_reload: Callable[[], list[dict[str, Any]]] | None = None,
    static_ui_dir: Path | None = None,
    browser_grant: Callable[[str, str], dict[str, Any]] | None = None,
    browser_stop: Callable[[str], dict[str, Any]] | None = None,
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
        sessions = store.list_sessions(limit=limit)
        if not _owner_local_only(request):
            # External-channel transcript sessions are private: filter them out
            # of non-owner-local listings so their existence is not disclosed.
            sessions = [
                s for s in sessions
                if not (isinstance(s.get("metadata"), dict)
                        and s["metadata"].get("source") == "external_channel")
            ]
        return web.json_response({"ok": True, "sessions": sessions})

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
        guard = _external_session_guard(request, sid)
        if guard is not None:
            return guard
        with store._lock, store._connect() as conn:  # noqa: SLF001
            cur = conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
        if cur.rowcount == 0:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        return web.json_response({"ok": True, "deleted": sid})

    async def chat_topics(request: web.Request) -> web.Response:
        query = request.query.get("q", "").strip()
        if len(query) > 200:
            return web.json_response({"ok": False, "error": "Search must be 200 characters or fewer."}, status=400)
        return web.json_response({"ok": True, "topics": store.list_chat_topics(query, include_external=_owner_local_only(request))})

    async def main_chat_session(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "session": store.main_chat_session()})

    async def list_messages(request: web.Request) -> web.Response:
        sid = request.match_info["session_id"]
        guard = _external_session_guard(request, sid)
        if guard is not None:
            return guard
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        return web.json_response({"ok": True, "messages": store.list_messages(sid)})

    async def submit_run(request: web.Request) -> web.Response:
        sid = request.match_info["session_id"]
        guard = _external_session_guard(request, sid)
        if guard is not None:
            return guard
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        body = await request.json()
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return web.json_response({"ok": False, "error": "prompt is required"}, status=400)
        req_id = body.get("request_id")
        strategy = str(body.get("multitask_strategy") or "enqueue")
        try:
            rid, fut = coordinator.submit(
                sid, prompt, request_id=req_id, multitask_strategy=strategy,
                owner_schedule_proposal_allowed=_owner_local_only(request),
            )
        except (RequestConflictError, RuntimeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        if body.get("wait"):
            res = await asyncio.to_thread(fut.result, 180.0)
            return web.json_response({"ok": True, "request_id": rid, "result": res})
        return web.json_response({"ok": True, "request_id": rid, "status": "queued"}, status=202)

    async def create_scheduled_job(request: web.Request) -> web.Response:
        if request[ACTOR_KEY] != "owner:loopback" or request.remote not in ("127.0.0.1", "::1"):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "application/json body required"}, status=400)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
        due_at_raw = body.get("due_at")
        if not isinstance(due_at_raw, (int, float)) or isinstance(due_at_raw, bool):
            return web.json_response({"ok": False, "error": "finite numeric due_at is required"}, status=400)
        try:
            due_at = float(due_at_raw)
        except (ValueError, OverflowError):
            return web.json_response({"ok": False, "error": "finite numeric due_at is required"}, status=400)
        if not math.isfinite(due_at):
            return web.json_response({"ok": False, "error": "finite numeric due_at is required"}, status=400)
        prompt = body.get("prompt")
        if not isinstance(prompt, str):
            return web.json_response({"ok": False, "error": "prompt must be a string"}, status=400)
        prompt = prompt.strip()
        if not prompt or len(prompt) > 16000:
            return web.json_response({"ok": False, "error": "prompt must be 1-16000 characters"}, status=400)
        recurrence = None
        if "interval_s" in body:
            interval_raw = body["interval_s"]
            if not isinstance(interval_raw, (int, float)) or isinstance(interval_raw, bool):
                return web.json_response({"ok": False, "error": "interval_s must be a finite number of seconds"}, status=400)
            try:
                interval_s = float(interval_raw)
            except (ValueError, OverflowError):
                return web.json_response({"ok": False, "error": "interval_s must be a finite number of seconds"}, status=400)
            if not math.isfinite(interval_s) or not 1.0 <= interval_s <= 31536000.0:
                return web.json_response({"ok": False, "error": "interval_s must be within 1 to 31536000 seconds"}, status=400)
            recurrence = {"interval_s": interval_s, "series_id": f"series_{uuid.uuid4().hex}"}
        depends_on = None
        if "depends_on" in body:
            depends_raw = body["depends_on"]
            if (
                not isinstance(depends_raw, list)
                or not 1 <= len(depends_raw) <= 16
                or any(
                    not isinstance(pid, str) or not pid.strip() or len(pid) > 128
                    for pid in depends_raw
                )
            ):
                return web.json_response(
                    {"ok": False, "error": "depends_on must be a list of 1-16 nonempty strings of at most 128 characters"},
                    status=400,
                )
            if recurrence is not None:
                return web.json_response(
                    {"ok": False, "error": "depends_on cannot be combined with interval_s recurrence"},
                    status=400,
                )
            depends_on = [pid.strip() for pid in depends_raw]
        try:
            job = store.create_scheduled_job(
                session_id=sid, prompt=prompt, due_at=float(due_at), recurrence=recurrence, depends_on=depends_on
            )
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid scheduled job"}, status=400)
        return web.json_response({"ok": True, "job": job}, status=201)

    async def get_scheduled_job(request: web.Request) -> web.Response:
        if request[ACTOR_KEY] != "owner:loopback" or request.remote not in ("127.0.0.1", "::1"):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        job = store.get_scheduled_job(request.match_info["job_id"])
        if job is None or job.get("session_id") != sid:
            return web.json_response({"ok": False, "error": "job not found"}, status=404)
        return web.json_response({"ok": True, "job": job, "dependencies": store.get_job_dependencies(job["job_id"], sid)})

    async def cancel_scheduled_job(request: web.Request) -> web.Response:
        if request[ACTOR_KEY] != "owner:loopback" or request.remote not in ("127.0.0.1", "::1"):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "application/json body required"}, status=400)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
        outcome = store.cancel_pending_job(request.match_info["job_id"], sid)
        if outcome.get("error") == "not_found":
            return web.json_response({"ok": False, "error": "job not found"}, status=404)
        if outcome.get("error") == "cannot_cancel":
            return web.json_response({"ok": False, "error": "job cannot be cancelled"}, status=409)
        return web.json_response({"ok": True, "job": outcome})

    async def get_job_series(request: web.Request) -> web.Response:
        if request[ACTOR_KEY] != "owner:loopback" or request.remote not in ("127.0.0.1", "::1"):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        series_id = request.match_info["series_id"]
        fires = store.list_series_jobs(series_id)
        if not fires or any(f.get("session_id") != sid for f in fires):
            return web.json_response({"ok": False, "error": "series not found"}, status=404)
        control = store.get_series_status(series_id, sid)
        return web.json_response({"ok": True, "series_id": series_id, "control": control, "jobs": fires})

    async def update_job_series(request: web.Request) -> web.Response:
        if request[ACTOR_KEY] != "owner:loopback" or request.remote not in ("127.0.0.1", "::1"):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        series_id = request.match_info["series_id"]
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "application/json body required"}, status=400)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
        status = body.get("status")
        if status not in ("active", "paused", "cancelled"):
            return web.json_response({"ok": False, "error": "status must be active, paused, or cancelled"}, status=400)
        fires = store.list_series_jobs(series_id)
        if not fires or any(f.get("session_id") != sid for f in fires):
            return web.json_response({"ok": False, "error": "series not found"}, status=404)
        current = store.get_series_status(series_id, sid)
        if current is not None and current.get("status") == "cancelled":
            return web.json_response({"ok": False, "error": "cancelled series cannot be reactivated"}, status=409)
        try:
            control = store.set_series_status(series_id, sid, status)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        return web.json_response({"ok": True, "series_id": series_id, "control": control})

    def _owner_local_only(request: web.Request) -> bool:
        return request[ACTOR_KEY] == "owner:loopback" and request.remote in ("127.0.0.1", "::1")

    async def _strict_json_object(request: web.Request) -> dict[str, Any] | web.Response:
        if request.content_type != "application/json":
            return web.json_response({"ok": False, "error": "application/json body required"}, status=400)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "JSON object required"}, status=400)
        return body

    async def grant_supervised_browser(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Browser grants are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        if browser_grant is None:
            return web.json_response({"ok": False, "error": "browser consent unavailable"}, status=503)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        url = body.get("url")
        if not isinstance(url, str) or not url.strip():
            return web.json_response({"ok": False, "error": "url is required and must be a string"}, status=400)
        try:
            result = await asyncio.to_thread(browser_grant, sid, url.strip())
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "browser grant failed"}, status=400)
        return web.json_response({"ok": True, "grant": result})

    async def stop_supervised_browser(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Browser stop is owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        if browser_stop is None:
            return web.json_response({"ok": False, "error": "browser consent unavailable"}, status=503)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        try:
            result = await asyncio.to_thread(browser_stop, sid)
        except Exception:  # noqa: BLE001
            return web.json_response({"ok": False, "error": "browser stop failed"}, status=400)
        return web.json_response({"ok": True, "stopped": result})

    async def stream_events(request: web.Request) -> web.StreamResponse:
        sid = request.match_info["session_id"]
        guard = _external_session_guard(request, sid)
        if guard is not None:
            return guard
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
        approvals = store.list_pending_approvals(session_id=sid)
        if not _owner_local_only(request):
            approvals = [row for row in approvals if row["tool_name"] != "schedule-proposal"]
        return web.json_response({"ok": True, "approvals": approvals})

    async def resolve_approval(request: web.Request) -> web.Response:
        aid = request.match_info["approval_id"]
        existing = store.get_approval(aid)
        schedule_proposal = existing is not None and existing["tool_name"] == "schedule-proposal"
        owner_local = _owner_local_only(request)
        if schedule_proposal:
            if not owner_local:
                return web.json_response({"ok": False, "error": "approval not found or already resolved"}, status=404)
            body = await _strict_json_object(request)
            if isinstance(body, web.Response):
                return body
            if body.get("decision") not in ("approve", "deny") or not set(body) <= {"decision", "note"}:
                return web.json_response({"ok": False, "error": "decision must be approve or deny"}, status=400)
        else:
            body = await request.json()
        decision = str(body.get("decision") or "deny")
        note = str(body.get("note") or "")
        row = store.resolve_approval(aid, decision=decision, note=note, allow_schedule_approval=owner_local)
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
        reason = str(body.get("reason") or "operator_api")
        if bool(body.get("active", True)):
            governor.trigger_estop(reason)
            if minecraft_embodiment is not None:
                minecraft_embodiment.estop(reason)
            if jp01_embodiment is not None:
                jp01_embodiment.estop(reason)
            if droid_embodiment is not None:
                droid_embodiment.estop(reason)
        else:
            governor.release_estop()
            if minecraft_embodiment is not None:
                minecraft_embodiment.release_estop()
            if jp01_embodiment is not None:
                jp01_embodiment.latch.release(source="operator")
            if droid_embodiment is not None:
                droid_embodiment.release_estop()
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

    async def channels_status(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Channel outbox is owner-local only."}, status=403)
        if channel_hub is None:
            return web.json_response({"ok": True, "channels": {}, "outbox": []})
        return web.json_response({
            "ok": True,
            "channels": channel_hub.status(),
            "outbox": [m.to_dict() for m in channel_hub.list_outbox(limit=25)],
        })

    async def channels_send(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Channel send is owner-local only."}, status=403)
        if channel_hub is None:
            return web.json_response({"ok": False, "error": "channel hub unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        channel = str(body.get("channel") or "local_log")
        # External channels always enqueue unapproved: a request body claiming
        # approved=True must never bypass owner approval.
        approved = bool(body.get("approved", False)) and channel == "local_log"
        msg = channel_hub.enqueue(
            channel=channel,
            recipient=str(body.get("recipient") or "owner"),
            body=str(body.get("body") or ""),
            approved=approved,
            dry_run=bool(body.get("dry_run", False)),
        )
        return web.json_response({"ok": True, "message": msg.to_dict()}, status=201)

    async def channels_approve(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Message approval is owner-local only."}, status=403)
        if channel_hub is None:
            return web.json_response({"ok": False, "error": "channel hub unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        message_id = request.match_info["message_id"]
        try:
            msg = await asyncio.to_thread(channel_hub.approve_delivery, message_id)
        except KeyError:
            return web.json_response({"ok": False, "error": "message not found"}, status=404)
        return web.json_response({"ok": True, "message": msg.to_dict()})

    async def channels_inbound(request: web.Request) -> web.Response:
        """Attribute one inbound external-channel message to a dedicated session.

        Owner-local only. Accepts exactly {channel, external_thread_id,
        external_message_id, sender, body} — any extra field (including a
        caller-provided session_id) is rejected. Pure store-layer attribution:
        no network, provider, tool call, model, or coordinator submission.
        """
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Inbound channel messages are owner-local only."}, status=403)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        expected = {"channel", "external_thread_id", "external_message_id", "sender", "body"}
        if set(body.keys()) != expected:
            return web.json_response(
                {"ok": False, "error": "body must contain exactly channel, external_thread_id, "
                 "external_message_id, sender, body"},
                status=400,
            )
        channel = body["channel"]
        if not isinstance(channel, str) or channel not in SUPPORTED_EXTERNAL_CHANNELS:
            return web.json_response(
                {"ok": False, "error": "channel must be one of telegram, imessage, webhook"}, status=400
            )
        for field in ("external_thread_id", "external_message_id", "sender", "body"):
            if not isinstance(body[field], str):
                return web.json_response({"ok": False, "error": f"{field} must be a string"}, status=400)
        try:
            result = await asyncio.to_thread(
                store.ingest_channel_message,
                channel,
                body["external_thread_id"],
                body["external_message_id"],
                body["sender"],
                body["body"],
            )
        except RequestConflictError:
            return web.json_response(
                {"ok": False, "error": "conflicting replay of an already-ingested external message"}, status=409
            )
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid inbound channel message"}, status=400)
        return web.json_response(
            {"ok": True, "message": result}, status=200 if result.get("replayed") else 201
        )

    async def channels_reply(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Channel replies are owner-local only."}, status=403)
        if channel_hub is None:
            return web.json_response({"ok": False, "error": "channel hub unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        content = body.get("body")
        if set(body) != {"body"} or not isinstance(content, str) or not content.strip() or len(content) > 20_000:
            return web.json_response({"ok": False, "error": "A nonempty body of up to 20000 characters is required."}, status=400)
        destination = await asyncio.to_thread(store.external_channel_destination, request.match_info["session_id"])
        if destination is None:
            return web.json_response({"ok": False, "error": "External conversation not found."}, status=404)
        channel, recipient = destination
        if channel not in SUPPORTED_EXTERNAL_CHANNELS or channel not in channel_hub.status()["configured_adapters"]:
            return web.json_response({"ok": False, "error": "External channel adapter unavailable."}, status=503)
        message = await asyncio.to_thread(channel_hub.enqueue, channel=channel, recipient=recipient, body=content)
        return web.json_response({"ok": True, "message": message.to_dict()}, status=201)

    def _is_external_channel_session(sid: str) -> bool:
        """True when the session was allocated for an external channel thread."""
        session = store.get_session(sid)
        if session is None:
            return False
        metadata = session.get("metadata")
        return isinstance(metadata, dict) and metadata.get("source") == "external_channel"

    def _external_session_guard(request: web.Request, sid: str) -> web.Response | None:
        """404 for non-owner-local access to an external-channel session.

        Returning 404 (not 403) keeps the existence and identity of external
        transcript sessions undisclosed to non-owner-local callers.
        """
        if _owner_local_only(request):
            return None
        if _is_external_channel_session(sid):
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        return None

    async def embodiment_status(_request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "droid": droid_embodiment.observe() if droid_embodiment is not None else None,
            "minecraft": minecraft_embodiment.observe() if minecraft_embodiment is not None else None,
            "jp01": jp01_embodiment.observe() if jp01_embodiment is not None else None,
            "voice": voice_presence.snapshot() if voice_presence is not None else None,
            "vision": vision_buffer.stats() if vision_buffer is not None else None,
        })

    async def embodiment_act(request: web.Request) -> web.Response:
        target = request.match_info["body"]
        body = await request.json()
        action = str(body.get("action") or "")
        params = dict(body.get("params") or {})
        emb = (
            minecraft_embodiment
            if target == "minecraft"
            else (jp01_embodiment if target == "jp01" else (droid_embodiment if target == "droid" else None))
        )
        if emb is None:
            return web.json_response({"ok": False, "error": f"unknown embodiment:{target}"}, status=404)
        res = emb.act(action, params)
        return web.json_response(dict(res), status=200 if res.get("ok") else 409)

    async def get_identity(_request: web.Request) -> web.Response:
        if identity_store is None:
            return web.json_response({"ok": False, "error": "identity store unavailable"}, status=501)
        return web.json_response({
            "ok": True,
            "identity": identity_store.get().to_dict(),
            "compiled_prompt": identity_store.compile_system_prompt(),
        })

    async def put_identity(request: web.Request) -> web.Response:
        if identity_store is None:
            return web.json_response({"ok": False, "error": "identity store unavailable"}, status=501)
        body = await request.json()
        prof = identity_store.update(**body)
        return web.json_response({"ok": True, "identity": prof.to_dict()})

    async def post_identity_character(request: web.Request) -> web.Response:
        if identity_store is None:
            return web.json_response({"ok": False, "error": "identity store unavailable"}, status=501)
        body = await request.json()
        if "activate_only" in body:
            try:
                prof = identity_store.set_active_character(body.get("character_id"))
                return web.json_response({"ok": True, "identity": prof.to_dict()})
            except KeyError as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=404)
        cid = str(body.get("character_id") or "").strip()
        if not cid:
            return web.json_response({"ok": False, "error": "character_id is required"}, status=400)
        overlay = CharacterOverlay(
            character_id=cid,
            name=str(body.get("name") or cid.capitalize()),
            style=str(body.get("style") or "Expressive companion"),
            voice_id=str(body.get("voice_id") or ""),
            avatar_preset=str(body.get("avatar_preset") or "studio_cel"),
            notes=str(body.get("notes") or ""),
        )
        prof = identity_store.upsert_character(overlay, activate=bool(body.get("activate", True)))
        return web.json_response({"ok": True, "identity": prof.to_dict()}, status=201)

    async def upsert_mcp_server(request: web.Request) -> web.Response:
        if mcp_upsert is None:
            return web.json_response({"ok": False, "error": "mcp upsert unavailable"}, status=501)
        body = await request.json()
        try:
            servers = mcp_upsert(body, connect=bool(body.get("connect", False)))
            return web.json_response({"ok": True, "servers": servers}, status=201)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def delete_mcp_server(request: web.Request) -> web.Response:
        if mcp_delete is None:
            return web.json_response({"ok": False, "error": "mcp delete unavailable"}, status=501)
        servers = mcp_delete(request.match_info["name"])
        return web.json_response({"ok": True, "servers": servers})

    async def reload_mcp_servers(_request: web.Request) -> web.Response:
        if mcp_reload is None:
            return web.json_response({"ok": False, "error": "mcp reload unavailable"}, status=501)
        servers = mcp_reload()
        return web.json_response({"ok": True, "servers": servers})

    async def droid_devices(request: web.Request) -> web.Response:
        if droid_embodiment is None:
            return web.json_response({"ok": False, "error": "droid embodiment unavailable"}, status=501)
        refresh = request.query.get("refresh", "0").lower() in ("1", "true", "yes")
        devs = droid_embodiment.refresh_devices() if refresh else droid_embodiment.observe()["devices"]
        return web.json_response({"ok": True, "devices": devs})

    async def droid_capture(request: web.Request) -> web.Response:
        if droid_embodiment is None:
            return web.json_response({"ok": False, "error": "droid embodiment unavailable"}, status=501)
        body = await request.json() if request.can_read_body else {}
        res = droid_embodiment.capture_frame(
            device_index=str(body.get("device_index") or "0"),
            summary=str(body.get("summary") or ""),
        )
        return web.json_response(res, status=200 if res.get("ok") else 409)

    async def youtube_export_otio(request: web.Request) -> web.Response:
        if youtube_store is None:
            return web.json_response({"ok": False, "error": "youtube store unavailable"}, status=501)
        ep = youtube_store.get_episode(request.match_info["episode_id"])
        if ep is None:
            return web.json_response({"ok": False, "error": "episode not found"}, status=404)
        fps = float(request.query.get("fps") or "24.0")
        return web.json_response({"ok": True, "otio": export_episode_to_otio(ep, fps=fps)})

    async def list_media_archive(request: web.Request) -> web.Response:
        if media_archive is None:
            return web.json_response({"ok": True, "items": []})
        items = media_archive.search(
            query=request.query.get("q") or "",
            project_id=request.query.get("project_id") or None,
            kind=request.query.get("kind") or None,
            limit=int(request.query.get("limit") or "50"),
        )
        return web.json_response({"ok": True, "items": [i.to_dict() for i in items], "count": len(items)})

    async def add_media_archive(request: web.Request) -> web.Response:
        if media_archive is None:
            return web.json_response({"ok": False, "error": "media archive unavailable"}, status=501)
        body = await request.json()
        item = media_archive.add(
            kind=str(body.get("kind") or "camera"),
            source_path=str(body.get("source_path") or ""),
            project_id=str(body.get("project_id") or "general"),
            channel_tag=str(body.get("channel_tag") or ""),
            scene_description=str(body.get("scene_description") or ""),
            transcript=str(body.get("transcript") or ""),
            is_reconstructed=bool(body.get("is_reconstructed", False)),
            tags=list(body.get("tags") or []),
        )
        return web.json_response({"ok": True, "item": item.to_dict()}, status=201)

    async def minecraft_checkpoint(request: web.Request) -> web.Response:
        if minecraft_embodiment is None:
            return web.json_response({"ok": False, "error": "minecraft unavailable"}, status=501)
        body = await request.json() if request.can_read_body else {}
        cp = minecraft_embodiment.checkpoint(reason=str(body.get("reason") or "manual"))
        return web.json_response(dict(cp))

    async def presence_voice_hear(request: web.Request) -> web.Response:
        if voice_presence is None:
            return web.json_response({"ok": False, "error": "voice presence unavailable"}, status=501)
        body = await request.json()
        dec = voice_presence.on_heard_transcript(
            str(body.get("transcript") or ""),
            in_active_dialog=bool(body.get("in_active_dialog", False)),
        )
        return web.json_response({"ok": True, "decision": dec.to_dict(), "voice": voice_presence.snapshot()})

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
    app.router.add_get("/v1/chat/session", main_chat_session)
    app.router.add_get("/v1/chat/topics", chat_topics)
    app.router.add_get("/v1/sessions", list_sessions)
    app.router.add_post("/v1/sessions", create_session)
    app.router.add_delete("/v1/sessions/{session_id}", delete_session)
    app.router.add_get("/v1/sessions/{session_id}/messages", list_messages)
    app.router.add_post("/v1/sessions/{session_id}/runs", submit_run)
    app.router.add_post("/v1/sessions/{session_id}/browser/grant", grant_supervised_browser)
    app.router.add_post("/v1/sessions/{session_id}/browser/stop", stop_supervised_browser)
    app.router.add_post("/v1/sessions/{session_id}/jobs", create_scheduled_job)
    app.router.add_get("/v1/sessions/{session_id}/jobs/{job_id}", get_scheduled_job)
    app.router.add_post("/v1/sessions/{session_id}/jobs/{job_id}/cancel", cancel_scheduled_job)
    app.router.add_get("/v1/sessions/{session_id}/job-series/{series_id}", get_job_series)
    app.router.add_patch("/v1/sessions/{session_id}/job-series/{series_id}", update_job_series)
    app.router.add_get("/v1/sessions/{session_id}/events", stream_events)
    app.router.add_get("/v1/approvals", list_approvals)
    app.router.add_post("/v1/approvals/{approval_id}/resolve", resolve_approval)
    app.router.add_get("/v1/tools", list_tools)
    app.router.add_get("/v1/models", list_models)
    app.router.add_post("/v1/models/select", select_model)
    app.router.add_get("/v1/skills", list_skills)
    app.router.add_get("/v1/mcp/servers", list_mcp_servers)
    app.router.add_post("/v1/mcp/servers", upsert_mcp_server)
    app.router.add_delete("/v1/mcp/servers/{name}", delete_mcp_server)
    app.router.add_post("/v1/mcp/reload", reload_mcp_servers)
    app.router.add_get("/v1/identity", get_identity)
    app.router.add_put("/v1/identity", put_identity)
    app.router.add_post("/v1/identity/character", post_identity_character)
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
    app.router.add_get("/v1/youtube/episodes/{episode_id}/otio", youtube_export_otio)
    app.router.add_post("/v1/youtube/research/plan", youtube_plan_research)
    app.router.add_get("/v1/media/archive", list_media_archive)
    app.router.add_post("/v1/media/archive", add_media_archive)
    app.router.add_get("/v1/channels/status", channels_status)
    app.router.add_post("/v1/channels/send", channels_send)
    app.router.add_post("/v1/channels/messages/{message_id}/approve", channels_approve)
    app.router.add_post("/v1/channels/inbound", channels_inbound)
    app.router.add_post("/v1/sessions/{session_id}/channel-reply", channels_reply)
    app.router.add_get("/v1/embodiment/status", embodiment_status)
    app.router.add_post("/v1/embodiment/{body}/act", embodiment_act)
    app.router.add_get("/v1/droid/devices", droid_devices)
    app.router.add_post("/v1/droid/capture", droid_capture)
    app.router.add_post("/v1/embodiment/minecraft/checkpoint", minecraft_checkpoint)
    app.router.add_post("/v1/presence/voice/hear", presence_voice_hear)

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
