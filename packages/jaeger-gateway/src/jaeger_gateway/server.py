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
from typing import Any, Callable, Mapping

from aiohttp import web
from jaeger_avatar import AvatarError, build_viseme_timeline
from jaeger_cognition import CharacterOverlay
from jaeger_mcp import list_mcp_presets
from jaeger_youtube import export_episode_to_otio, plan_phased_research, probe_youtube_toolchain

from .auth import GatewayAuthPolicy, _is_valid_local_host, _is_valid_ts_net_host
from .coordinator import RunCoordinator
from .droid_voice import detect_voice_intent, transcribe_clip
from .store import MAIN_CHAT_SESSION_ID, GatewayStore, RequestConflictError
from .stream import SessionEventHub, format_sse
from .tool_workspace import SourceConflict, ToolWorkspace

ACTOR_KEY: web.RequestKey[str] = web.RequestKey("actor", str)
SUPPORTED_EXTERNAL_CHANNELS = frozenset({"telegram", "discord", "slack", "imessage", "webhook"})

_ALWAYS_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "testserver"})


def _is_allowed_host(
    host_only: str,
    *,
    allow_private: bool,
    extra_hosts: frozenset[str] = frozenset(),
) -> bool:
    """Validate HTTP Host header against DNS rebinding while permitting Tailscale & opt-in LAN."""
    host = (host_only or "").strip().lower()
    if not host:
        return False
    if host in _ALWAYS_ALLOWED_HOSTS or host in extra_hosts:
        return True
    if _is_valid_ts_net_host(host):
        return True
    if allow_private:
        if _is_valid_local_host(host):
            return True
        ip_candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
        if GatewayAuthPolicy._is_private_or_tailscale(ip_candidate):
            return True
    return False


def create_gateway_app(
    *,
    store: GatewayStore,
    coordinator: RunCoordinator,
    hub: SessionEventHub,
    auth: GatewayAuthPolicy | None = None,
    runtime_info: Callable[[], dict[str, Any]] | None = None,
    tools_provider: Callable[[], list[dict[str, Any]]] | None = None,
    tool_workspace: ToolWorkspace | None = None,
    models_provider: Callable[[], dict[str, Any]] | None = None,
    model_selector: Callable[[str], dict[str, Any]] | None = None,
    cookbook_provider: Callable[..., dict[str, Any]] | None = None,
    roundtable_runner: Callable[..., dict[str, Any]] | None = None,
    model_telemetry_provider: Callable[..., dict[str, Any]] | None = None,
    model_risk_provider: Callable[..., dict[str, Any]] | None = None,
    model_eval_runner: Callable[..., dict[str, Any]] | None = None,
    research_runner: Callable[..., dict[str, Any]] | None = None,
    research_lister: Callable[..., list[dict[str, Any]]] | None = None,
    mode_getter: Callable[[], dict[str, Any]] | None = None,
    mode_setter: Callable[[str], dict[str, Any]] | None = None,
    evidence_store: Any = None,
    agent_importer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    kanban_board: Any = None,
    reminder_store: Any = None,
    avatar_packs_provider: Callable[[], dict[str, Any]] | None = None,
    nexus_provider: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    routing_provider: Callable[[], dict[str, Any]] | None = None,
    routing_updater: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    onboarding_provider: Callable[[], dict[str, Any]] | None = None,
    onboarding_completer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    briefing_provider: Callable[[], dict[str, Any]] | None = None,
    workflows_engine: Any = None,
    dry_run_simulator: Any = None,
    governor: Any = None,
    cognition_loop: Any = None,
    initiative_engine: Any = None,
    elevated_toggler: Callable[[bool], dict[str, Any]] | None = None,
    world_model: Any = None,
    identity_store: Any = None,
    avatar_store: Any = None,
    business_store: Any = None,
    office_provider: Callable[[], dict[str, Any]] | None = None,
    global_bus: Any = None,
    awareness_provider: Callable[[], dict[str, Any]] | None = None,
    youtube_store: Any = None,
    media_archive: Any = None,
    channel_hub: Any = None,
    channel_config: Any = None,
    channel_ingress: Any = None,
    remote_hosts: Any = None,
    authorized_tasks: Any = None,
    minecraft_embodiment: Any = None,
    jp01_embodiment: Any = None,
    droid_embodiment: Any = None,
    voice_presence: Any = None,
    vision_buffer: Any = None,
    memory_store: Any = None,
    learning_store: Any = None,
    wiki_store: Any = None,
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
    extra_hosts = frozenset(
        h.strip().lower()
        for h in (os.environ.get("JAEGER_ALLOWED_HOSTS") or "").split(",")
        if h.strip()
    )

    @web.middleware
    async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        raw_host = (request.headers.get("Host") or "").strip().lower()
        if raw_host:
            host_only = ""
            if raw_host.startswith("["):
                end_bracket = raw_host.find("]")
                if end_bracket == -1:
                    return web.json_response(
                        {"ok": False, "error": "invalid Host header (DNS rebinding blocked)"},
                        status=403,
                    )
                rest = raw_host[end_bracket + 1 :]
                if rest and not (rest.startswith(":") and rest[1:].isdigit()):
                    return web.json_response(
                        {"ok": False, "error": "invalid Host header (DNS rebinding blocked)"},
                        status=403,
                    )
                host_only = raw_host[: end_bracket + 1]
            elif raw_host.count(":") == 1:
                host_only, _, port_str = raw_host.partition(":")
                if not port_str.isdigit():
                    return web.json_response(
                        {"ok": False, "error": "invalid Host header (DNS rebinding blocked)"},
                        status=403,
                    )
            else:
                host_only = raw_host
            if not _is_allowed_host(
                host_only,
                allow_private=policy.allow_private_network_unauthenticated,
                extra_hosts=extra_hosts,
            ):
                return web.json_response(
                    {"ok": False, "error": "invalid Host header (DNS rebinding blocked)"},
                    status=403,
                )
        if request.path == "/health" or not request.path.startswith("/v1/"):
            return await handler(request)
        decision = policy.verify_http(request.headers, remote_addr=request.remote or "")
        if not decision.allowed:
            return web.json_response({"ok": False, "error": decision.reason}, status=401)
        request[ACTOR_KEY] = decision.actor
        return await handler(request)

    app = web.Application(middlewares=[auth_middleware])

    async def health(_request: web.Request) -> web.Response:
        extra = await asyncio.to_thread(runtime_info) if runtime_info is not None else {}
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

    def _owner_local_only(request: web.Request) -> bool:
        return request[ACTOR_KEY] == "owner:loopback" and request.remote in ("127.0.0.1", "::1")

    def _is_owner_actor(request: web.Request) -> bool:
        return request[ACTOR_KEY].startswith("owner:")

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

    def _is_external_channel_session(sid: str) -> bool:
        session = store.get_session(sid)
        if session is None:
            return False
        metadata = session.get("metadata")
        return isinstance(metadata, dict) and metadata.get("source") == "external_channel"

    def _external_session_guard(request: web.Request, sid: str) -> web.Response | None:
        if _owner_local_only(request):
            return None
        if _is_external_channel_session(sid):
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        return None

    async def list_sessions(request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        sessions = store.list_sessions(limit=limit)
        if not _owner_local_only(request):
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

    async def chat_search(request: web.Request) -> web.Response:
        query = request.query.get("q", "").strip()
        if not query or len(query) > 200:
            return web.json_response({"ok": False, "error": "Query must be 1-200 characters."}, status=400)
        sid = request.query.get("session_id") or None
        limit = int(request.query.get("limit") or "15")
        hits = store.search_messages(query, session_id=sid, limit=limit, include_external=_owner_local_only(request))
        return web.json_response({"ok": True, "results": hits, "count": len(hits)})

    async def main_chat_session(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "session": store.main_chat_session()})

    async def list_messages(request: web.Request) -> web.Response:
        sid = request.match_info["session_id"]
        guard = _external_session_guard(request, sid)
        if guard is not None:
            return guard
        if store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        if request.query.get("page") != "latest":
            return web.json_response({"ok": True, "messages": store.list_messages(sid)})
        try:
            before = int(request.query["before_id"]) if "before_id" in request.query else None
            after = int(request.query["after_id"]) if "after_id" in request.query else None
            if before is not None and after is not None:
                raise ValueError("Choose one message cursor")
        except ValueError:
            return web.json_response({"ok": False, "error": "Invalid message cursor."}, status=400)
        scope = None if sid == MAIN_CHAT_SESSION_ID else sid
        if after is not None:
            rows = store.list_messages(scope, limit=60, after_id=after, include_presentation=True)
            return web.json_response({"ok": True, "messages": rows, "has_older": False, "after_seq": 0})
        cursor = hub.history_cursor(sid)
        rows = store.list_messages(scope, limit=61, latest=True, before_id=before, include_presentation=True)
        return web.json_response({"ok": True, "messages": rows[-60:], "has_older": len(rows) > 60, "after_seq": cursor})

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

    async def list_scheduled_jobs_route(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        status_filter = (request.query.get("status") or "").strip() or None
        jobs = store.list_scheduled_jobs(sid, status=status_filter)
        return web.json_response({"ok": True, "jobs": jobs, "count": len(jobs)})

    async def create_scheduled_job(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        prompt = body.get("prompt")
        if not isinstance(prompt, str):
            return web.json_response({"ok": False, "error": "prompt must be a string"}, status=400)
        prompt = prompt.strip()
        if not prompt or len(prompt) > 16000:
            return web.json_response({"ok": False, "error": "prompt must be 1-16000 characters"}, status=400)
        recurrence = None
        if "interval_s" in body and "cron_expr" in body:
            return web.json_response({"ok": False, "error": "cannot specify both interval_s and cron_expr"}, status=400)
        if "cron_expr" in body:
            cron_raw = body["cron_expr"]
            if not isinstance(cron_raw, str) or not cron_raw.strip():
                return web.json_response({"ok": False, "error": "cron_expr must be a nonempty 5-field cron string"}, status=400)
            recurrence = {"cron_expr": cron_raw.strip(), "series_id": f"series_{uuid.uuid4().hex}"}
        elif "interval_s" in body:
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
        due_at: float | None = None
        if "due_at" in body and body["due_at"] is not None:
            due_at_raw = body["due_at"]
            if not isinstance(due_at_raw, (int, float)) or isinstance(due_at_raw, bool):
                return web.json_response({"ok": False, "error": "finite numeric due_at is required"}, status=400)
            try:
                due_at = float(due_at_raw)
            except (ValueError, OverflowError):
                return web.json_response({"ok": False, "error": "finite numeric due_at is required"}, status=400)
            if not math.isfinite(due_at):
                return web.json_response({"ok": False, "error": "finite numeric due_at is required"}, status=400)
        elif recurrence is None or "cron_expr" not in recurrence:
            return web.json_response({"ok": False, "error": "finite numeric due_at is required"}, status=400)
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
                    {"ok": False, "error": "depends_on cannot be combined with recurrence"},
                    status=400,
                )
            depends_on = [pid.strip() for pid in depends_raw]
        try:
            job = store.create_scheduled_job(
                session_id=sid, prompt=prompt, due_at=due_at, recurrence=recurrence, depends_on=depends_on
            )
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid scheduled job"}, status=400)
        return web.json_response({"ok": True, "job": job}, status=201)

    async def get_scheduled_job(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        job = store.get_scheduled_job(request.match_info["job_id"])
        if job is None or job.get("session_id") != sid:
            return web.json_response({"ok": False, "error": "job not found"}, status=404)
        return web.json_response({"ok": True, "job": job, "dependencies": store.get_job_dependencies(job["job_id"], sid)})

    async def cancel_scheduled_job(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        outcome = store.cancel_pending_job(request.match_info["job_id"], sid)
        if outcome.get("error") == "not_found":
            return web.json_response({"ok": False, "error": "job not found"}, status=404)
        if outcome.get("error") == "cannot_cancel":
            return web.json_response({"ok": False, "error": "job cannot be cancelled"}, status=409)
        return web.json_response({"ok": True, "job": outcome})

    async def get_job_series(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
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
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Scheduled jobs are owner-local only."}, status=403)
        sid = request.match_info["session_id"]
        if sid != MAIN_CHAT_SESSION_ID or store.get_session(sid) is None:
            return web.json_response({"ok": False, "error": "session not found"}, status=404)
        series_id = request.match_info["series_id"]
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
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
        interactive = bool(body.get("interactive", False))
        try:
            if interactive:
                result = await asyncio.to_thread(browser_grant, sid, url.strip(), True)
            else:
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

    async def tool_catalog(_request: web.Request) -> web.Response:
        return web.json_response(tool_workspace.catalog() if tool_workspace else {"sources": [], "slash_commands": []})

    async def tool_source(request: web.Request) -> web.Response:
        if tool_workspace is None:
            return web.json_response({"error": "Tool source editor unavailable."}, status=501)
        if request[ACTOR_KEY] != "owner:loopback" or request.remote not in ("127.0.0.1", "::1"):
            return web.json_response({"error": "Tool source editing is available in the owner’s local WebUI."}, status=403)
        if request.headers.get("Sec-Fetch-Site") != "same-origin":
            return web.json_response({"error": "Open the tool editor from the local WebUI."}, status=403)
        try:
            if request.method == "GET":
                return web.json_response(tool_workspace.read(request.query.get("path", "")))
            if request.headers.get("Origin") != f"{request.scheme}://{request.host}" or request.content_type != "application/json":
                return web.json_response({"error": "Source saves require a same-origin JSON request."}, status=403)
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("path"), str) or not isinstance(body.get("source"), str):
                raise ValueError("A source path and Python source are required.")
            revision = body.get("revision")
            if revision is not None and not isinstance(revision, str):
                raise ValueError("Invalid source revision.")
            return web.json_response(tool_workspace.save(body["path"], body["source"], revision))
        except SourceConflict as error:
            return web.json_response({"error": str(error)}, status=409)
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)
        except FileNotFoundError:
            return web.json_response({"error": "Source file not found."}, status=404)
        except OSError:
            return web.json_response({"error": "The repository source could not be accessed."}, status=500)

    async def list_models(_request: web.Request) -> web.Response:
        info = models_provider() if models_provider is not None else {"active": "", "models": []}
        active = str(info.get("active") or "")
        raw_models = list(info.get("models") or [])
        openai_data: list[dict[str, Any]] = [
            {"id": "jaeger", "object": "model", "owned_by": "jaeger", "default": True}
        ]
        seen_ids = {"jaeger"}
        for m in raw_models:
            mid = str(m.get("id") or "").strip() if isinstance(m, dict) else ""
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                openai_data.append({
                    "id": f"jaeger/{mid}",
                    "object": "model",
                    "owned_by": str(m.get("provider") or "local"),
                    "default": mid == active,
                })
        return web.json_response({"ok": True, "object": "list", "data": openai_data, "default": "jaeger", **info})

    async def openai_chat_completions(request: web.Request) -> web.StreamResponse:
        """OpenAI-compatible /v1/chat/completions endpoint for jaeger-chat (VS Code) & SDKs."""
        body = await request.json()
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return web.json_response({"error": {"message": "messages list is required", "type": "invalid_request_error"}}, status=400)
        prompt = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and str(msg.get("role") or "") == "user":
                content = msg.get("content")
                if isinstance(content, str):
                    prompt = content.strip()
                elif isinstance(content, list):
                    prompt = " ".join(
                        str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                    ).strip()
                if prompt:
                    break
        if not prompt:
            return web.json_response({"error": {"message": "non-empty user message is required", "type": "invalid_request_error"}}, status=400)

        req_sid = (request.headers.get("X-Jaeger-Session-Id") or "").strip()
        if req_sid and store.get_session(req_sid) is not None:
            sid = req_sid
        else:
            sid = store.main_chat_session()["session_id"]

        model_name = str(body.get("model") or "jaeger")
        want_stream = bool(body.get("stream", False))
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        _, fut = coordinator.submit(
            sid,
            prompt,
            owner_schedule_proposal_allowed=_owner_local_only(request),
        )
        outcome = await asyncio.to_thread(fut.result, 180.0)
        reply_text = str(outcome.get("content") or "")

        if not want_stream:
            return web.json_response({
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model_name,
                "session_id": sid,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply_text},
                        "finish_reason": "stop",
                    }
                ],
            })

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Jaeger-Session-Id": sid,
            },
        )
        await resp.prepare(request)
        chunk1 = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply_text}, "finish_reason": None}],
        }
        chunk2 = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        await resp.write(f"data: {json.dumps(chunk1)}\n\n".encode("utf-8"))
        await resp.write(f"data: {json.dumps(chunk2)}\n\n".encode("utf-8"))
        await resp.write(b"data: [DONE]\n\n")
        await resp.write_eof()
        return resp

    async def select_model(request: web.Request) -> web.Response:
        if model_selector is None:
            return web.json_response({"ok": False, "error": "model selection unavailable"}, status=501)
        body = await request.json()
        model_id = str(body.get("model") or "").strip()
        if not model_id:
            return web.json_response({"ok": False, "error": "model is required"}, status=400)
        return web.json_response({"ok": True, **model_selector(model_id)})

    async def get_model_cookbook(request: web.Request) -> web.Response:
        if cookbook_provider is None:
            return web.json_response({"ok": False, "error": "model cookbook unavailable"}, status=501)
        modality = (request.query.get("modality") or "all").strip().lower()
        ram_raw = (request.query.get("ram_gb") or "").strip()
        host_ram: float | None = None
        if ram_raw:
            try:
                host_ram = float(ram_raw)
            except ValueError:
                return web.json_response({"ok": False, "error": "invalid ram_gb"}, status=400)
        include_unfit = (request.query.get("include_unfit") or "true").strip().lower() not in ("0", "false", "no")
        try:
            payload = await asyncio.to_thread(
                cookbook_provider,
                modality=modality,
                host_ram_gb=host_ram,
                include_unfit=include_unfit,
            )
            return web.json_response(payload)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def run_model_roundtable(request: web.Request) -> web.Response:
        if roundtable_runner is None:
            return web.json_response({"ok": False, "error": "roundtable unavailable"}, status=501)
        body = await request.json()
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            return web.json_response({"ok": False, "error": "prompt is required"}, status=400)
        models = body.get("models") if isinstance(body.get("models"), list) else []
        try:
            res = await asyncio.to_thread(
                roundtable_runner,
                prompt=prompt,
                models=[str(m) for m in models],
                blind=bool(body.get("blind", False)),
                critique_round=bool(body.get("critique_round", False)),
                consensus=bool(body.get("consensus", True)),
            )
            return web.json_response(res)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def get_model_telemetry(request: web.Request) -> web.Response:
        if model_telemetry_provider is None:
            return web.json_response({"ok": False, "error": "model telemetry unavailable"}, status=501)
        try:
            window_days = float(request.query.get("window_days") or "7")
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid window_days"}, status=400)
        include_live = (request.query.get("live") or "true").strip().lower() not in ("0", "false", "no")
        include_or = (request.query.get("openrouter_catalog") or "false").strip().lower() in ("1", "true", "yes")
        payload = await asyncio.to_thread(
            model_telemetry_provider,
            window_days=window_days,
            include_live_providers=include_live,
            include_openrouter_catalog=include_or,
        )
        return web.json_response(payload)

    async def get_model_risk_cards(request: web.Request) -> web.Response:
        if model_risk_provider is None:
            return web.json_response({"ok": False, "error": "model risk cards unavailable"}, status=501)
        mid = (request.query.get("model") or "").strip() or None
        payload = await asyncio.to_thread(model_risk_provider, model_id=mid)
        return web.json_response(payload)

    async def run_model_eval(request: web.Request) -> web.Response:
        if model_eval_runner is None:
            return web.json_response({"ok": False, "error": "model eval suite unavailable"}, status=501)
        body = await request.json()
        models = body.get("models") if isinstance(body.get("models"), list) else []
        try:
            res = await asyncio.to_thread(model_eval_runner, models=[str(m) for m in models])
            return web.json_response(res)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def run_deep_research(request: web.Request) -> web.Response:
        if research_runner is None:
            return web.json_response({"ok": False, "error": "deep research unavailable"}, status=501)
        body = await request.json()
        topic = str(body.get("topic") or "").strip()
        if not topic:
            return web.json_response({"ok": False, "error": "topic is required"}, status=400)
        try:
            res = await asyncio.to_thread(
                research_runner,
                topic=topic,
                max_queries=int(body.get("max_queries") or 3),
                max_sources=int(body.get("max_sources") or 6),
                fetch_pages=bool(body.get("fetch_pages", True)),
            )
            return web.json_response(res)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def list_research_reports_route(request: web.Request) -> web.Response:
        if research_lister is None:
            return web.json_response({"ok": True, "reports": []})
        limit = int(request.query.get("limit") or "25")
        rows = await asyncio.to_thread(research_lister, limit)
        return web.json_response({"ok": True, "reports": rows, "count": len(rows)})

    async def get_system_mode(_request: web.Request) -> web.Response:
        if mode_getter is None:
            return web.json_response({"ok": True, "mode": "build"})
        return web.json_response(mode_getter())

    async def set_system_mode(request: web.Request) -> web.Response:
        if mode_setter is None:
            return web.json_response({"ok": False, "error": "execution mode unavailable"}, status=501)
        body = await request.json()
        mode = str(body.get("mode") or "").strip()
        try:
            return web.json_response(mode_setter(mode))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def list_evidence_route(request: web.Request) -> web.Response:
        if evidence_store is None:
            return web.json_response({"ok": True, "items": []})
        limit = int(request.query.get("limit") or "20")
        items = evidence_store.list_recent(limit=limit)
        return web.json_response({"ok": True, "items": items, "count": len(items)})

    async def inspect_evidence_route(request: web.Request) -> web.Response:
        if evidence_store is None:
            return web.json_response({"ok": False, "error": "evidence store unavailable"}, status=501)
        ev_id = request.match_info["evidence_id"]
        offset = int(request.query.get("offset") or "0")
        limit = int(request.query.get("limit") or "4000")
        search = request.query.get("search") or ""
        res = evidence_store.inspect(ev_id, offset=offset, limit=limit, search=search)
        return web.json_response(res, status=200 if res.get("ok") else 404)

    async def list_importers_route(_request: web.Request) -> web.Response:
        if agent_importer is None:
            return web.json_response({"ok": True, "sources": [], "count": 0})
        return web.json_response(await asyncio.to_thread(agent_importer, {"action": "discover"}))

    async def run_importer_route(request: web.Request) -> web.Response:
        if agent_importer is None:
            return web.json_response({"ok": False, "error": "agent importer unavailable"}, status=501)
        body = await request.json()
        try:
            res = await asyncio.to_thread(
                agent_importer,
                {
                    "action": "import",
                    "source": str(body.get("source") or ""),
                    "dry_run": bool(body.get("dry_run", True)),
                },
            )
            return web.json_response(res)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def get_avatar_packs(_request: web.Request) -> web.Response:
        if avatar_packs_provider is None:
            return web.json_response({"ok": True, "packs": [], "count": 0})
        return web.json_response(await asyncio.to_thread(avatar_packs_provider))

    async def get_nexus_jp01_channels(_request: web.Request) -> web.Response:
        if nexus_provider is None:
            return web.json_response({"ok": False, "error": "nexus bridge unavailable"}, status=501)
        return web.json_response(await asyncio.to_thread(nexus_provider, {"action": "jp01_channels"}))

    async def get_nexus_info(request: web.Request) -> web.Response:
        if nexus_provider is None:
            return web.json_response({"ok": False, "error": "nexus bridge unavailable"}, status=501)
        url = request.query.get("station_url") or "http://127.0.0.1:8000"
        try:
            return web.json_response(await asyncio.to_thread(nexus_provider, {"action": "info", "station_url": url}))
        except (PermissionError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(exc), "station_url": url}, status=502)

    async def get_nexus_snapshot(request: web.Request) -> web.Response:
        if nexus_provider is None:
            return web.json_response({"ok": False, "error": "nexus bridge unavailable"}, status=501)
        url = request.query.get("station_url") or "http://127.0.0.1:8000"
        try:
            return web.json_response(await asyncio.to_thread(nexus_provider, {"action": "snapshot", "station_url": url}))
        except (PermissionError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(exc), "station_url": url}, status=502)

    async def get_board(_request: web.Request) -> web.Response:
        if kanban_board is None:
            return web.json_response({"ok": True, "columns": {}, "counts": {}, "total": 0})
        return web.json_response(kanban_board.summary())

    async def create_board_card(request: web.Request) -> web.Response:
        if kanban_board is None:
            return web.json_response({"ok": False, "error": "board unavailable"}, status=501)
        body = await request.json()
        try:
            card = kanban_board.create_card(
                str(body.get("title") or ""),
                column=str(body.get("column") or "todo"),
                priority=int(body.get("priority") or 2),
                tags=body.get("tags") if isinstance(body.get("tags"), list) else (),
                notes=str(body.get("notes") or ""),
            )
            return web.json_response({"ok": True, "card": card.to_dict()}, status=201)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def move_board_card(request: web.Request) -> web.Response:
        if kanban_board is None:
            return web.json_response({"ok": False, "error": "board unavailable"}, status=501)
        cid = request.match_info["card_id"]
        body = await request.json()
        try:
            card = kanban_board.move_card(
                cid,
                str(body.get("column") or "in_progress"),
                notes=str(body["notes"]) if body.get("notes") is not None else None,
            )
            return web.json_response({"ok": True, "card": card.to_dict()})
        except KeyError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def delete_board_card(request: web.Request) -> web.Response:
        if kanban_board is None:
            return web.json_response({"ok": False, "error": "board unavailable"}, status=501)
        cid = request.match_info["card_id"]
        ok = kanban_board.delete_card(cid)
        return web.json_response({"ok": ok, "deleted": cid}, status=200 if ok else 404)

    async def list_reminders_route(request: web.Request) -> web.Response:
        if reminder_store is None:
            return web.json_response({"ok": True, "reminders": [], "count": 0})
        status_filter = request.query.get("status", "pending") or None
        rows = [r.to_dict() for r in reminder_store.list_reminders(status=status_filter)]
        return web.json_response({"ok": True, "reminders": rows, "count": len(rows)})

    async def create_reminder_route(request: web.Request) -> web.Response:
        if reminder_store is None:
            return web.json_response({"ok": False, "error": "reminders unavailable"}, status=501)
        body = await request.json()
        try:
            rem = reminder_store.schedule(
                str(body.get("message") or ""),
                in_minutes=float(body["in_minutes"]) if body.get("in_minutes") is not None else None,
                at_iso=str(body["at_iso"]) if body.get("at_iso") else None,
            )
            return web.json_response({"ok": True, "reminder": rem.to_dict()}, status=201)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def cancel_reminder_route(request: web.Request) -> web.Response:
        if reminder_store is None:
            return web.json_response({"ok": False, "error": "reminders unavailable"}, status=501)
        rid = request.match_info["reminder_id"]
        ok = reminder_store.cancel(rid)
        return web.json_response({"ok": ok, "cancelled": rid}, status=200 if ok else 404)

    async def get_model_routing(_request: web.Request) -> web.Response:
        if routing_provider is None:
            return web.json_response({"ok": True, "active": "", "routing": {}})
        return web.json_response({"ok": True, **routing_provider()})

    async def put_model_routing(request: web.Request) -> web.Response:
        if not _is_owner_actor(request):
            return web.json_response({"ok": False, "error": "Model routing requires owner access."}, status=403)
        if routing_updater is None:
            return web.json_response({"ok": False, "error": "model routing unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        return web.json_response({"ok": True, **routing_updater(body)})

    async def get_onboarding_status(_request: web.Request) -> web.Response:
        if onboarding_provider is None:
            return web.json_response({"ok": True, "completed": True})
        return web.json_response({"ok": True, **onboarding_provider()})

    async def post_onboarding_complete(request: web.Request) -> web.Response:
        if not _is_owner_actor(request):
            return web.json_response({"ok": False, "error": "Onboarding requires owner access."}, status=403)
        if onboarding_completer is None:
            return web.json_response({"ok": False, "error": "onboarding unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        return web.json_response({"ok": True, **onboarding_completer(body)})

    async def get_cognition_briefing(_request: web.Request) -> web.Response:
        if briefing_provider is None:
            return web.json_response({"ok": True, "summary": "", "recent_actions": [], "active_goals": []})
        return web.json_response({"ok": True, **briefing_provider()})

    async def list_skills(_request: web.Request) -> web.Response:
        items = skills_provider() if skills_provider is not None else []
        return web.json_response({"ok": True, "skills": items, "count": len(items)})

    async def list_mcp_servers(_request: web.Request) -> web.Response:
        items = mcp_provider() if mcp_provider is not None else []
        return web.json_response({"ok": True, "servers": items, "count": len(items), "presets": list_mcp_presets()})

    async def get_mcp_presets(_request: web.Request) -> web.Response:
        presets = list_mcp_presets()
        return web.json_response({"ok": True, "presets": presets, "count": len(presets)})

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
            "autonomy": initiative_engine.status() if initiative_engine is not None else {},
            "world": world_model.snapshot() if world_model is not None else {},
            "perceptions": [p.to_dict() for p in (world_model.recent_perceptions(limit=12) if world_model else [])],
        })

    async def get_cognition_actions(request: web.Request) -> web.Response:
        if initiative_engine is None:
            return web.json_response({"ok": True, "actions": [], "status": {}})
        limit = int(request.query.get("limit", "30"))
        return web.json_response({
            "ok": True,
            "status": initiative_engine.status(),
            "actions": initiative_engine.list_actions(limit=limit),
        })

    async def post_cognition_autonomy(request: web.Request) -> web.Response:
        if not _is_owner_actor(request):
            return web.json_response({"ok": False, "error": "Autonomy control requires owner access."}, status=403)
        if initiative_engine is None:
            return web.json_response({"ok": False, "error": "initiative engine unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        if "elevated" in body and not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Elevated mode toggle is owner-local only."}, status=403)
        updated = False
        kwargs: dict[str, Any] = {}
        for k in ("enabled", "cooldown_s", "max_actions_per_hour", "active_start_hour", "active_end_hour"):
            if k in body:
                kwargs[k] = body[k]
                updated = True
        if updated:
            initiative_engine.update_config(**kwargs)
        elevated_res: dict[str, Any] | None = None
        if "elevated" in body and elevated_toggler is not None:
            elevated_res = elevated_toggler(bool(body["elevated"]))
        triggered: dict[str, Any] | None = None
        if body.get("trigger_now"):
            if _governor_estop_active():
                return web.json_response({"ok": False, "error": "estop_active"}, status=409)
            ctx = {
                "world": world_model.snapshot() if world_model is not None else {},
                "resources": governor.snapshot() if governor is not None else {},
                "trigger": "owner_manual_step",
            }
            triggered = await initiative_engine.evaluate_tick(ctx, force=True)
        return web.json_response({
            "ok": True,
            "status": initiative_engine.status(),
            **({"execution_mode": elevated_res} if elevated_res is not None else {}),
            **({"triggered": triggered} if triggered is not None else {}),
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

    def _emit_global(event: str, payload: Mapping[str, Any] | None = None) -> None:
        if global_bus is not None:
            try:
                global_bus.publish(event, dict(payload or {}))
            except Exception:  # noqa: BLE001
                pass

    async def stream_global_events(request: web.Request) -> web.StreamResponse:
        if global_bus is None:
            return web.json_response({"ok": False, "error": "global event bus unavailable"}, status=501)
        raw_after = request.headers.get("Last-Event-ID") or request.query.get("after_seq") or "0"
        try:
            after_seq = max(0, int(raw_after))
        except ValueError:
            after_seq = 0

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
        queue, _ = global_bus.subscribe()
        try:
            if after_seq > 0:
                for ev in global_bus.recent(after_seq=after_seq, limit=40):
                    frame = format_sse(event=str(ev["event"]), data=ev["payload"], seq=int(ev["seq"]))
                    await resp.write(frame.encode("utf-8"))
            else:
                hello = format_sse(
                    event="global.connected",
                    data={"seq": global_bus.latest_seq(), "timestamp": time.time()},
                    seq=global_bus.latest_seq(),
                )
                await resp.write(hello.encode("utf-8"))
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    frame = format_sse(event=str(ev["event"]), data=ev["payload"], seq=int(ev["seq"]))
                    await resp.write(frame.encode("utf-8"))
                except asyncio.TimeoutError:
                    await resp.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError, OSError):
            pass
        finally:
            global_bus.unsubscribe(queue)
        return resp

    async def list_recent_global_events(request: web.Request) -> web.Response:
        if global_bus is None:
            return web.json_response({"ok": True, "events": [], "latest_seq": 0})
        try:
            after_seq = max(0, int(request.query.get("after_seq") or "0"))
            limit = max(1, min(int(request.query.get("limit") or "40"), 120))
        except ValueError:
            after_seq, limit = 0, 40
        return web.json_response({
            "ok": True,
            "latest_seq": global_bus.latest_seq(),
            "events": global_bus.recent(after_seq=after_seq, limit=limit),
        })

    async def get_cognition_awareness(_request: web.Request) -> web.Response:
        if awareness_provider is not None:
            return web.json_response({"ok": True, **awareness_provider()})
        return web.json_response({
            "ok": True,
            "brief": "",
            "recent_reflections": [],
            "droid_reflex": droid_embodiment.reflex.status() if droid_embodiment is not None and hasattr(droid_embodiment, "reflex") else None,
            "world_perceptions": [],
            "global_event_seq": global_bus.latest_seq() if global_bus is not None else 0,
        })

    async def get_office_state(_request: web.Request) -> web.Response:
        if office_provider is not None:
            return web.json_response({"ok": True, **office_provider()})
        now = time.time()
        return web.json_response({
            "ok": True,
            "agents": [],
            "activityFeed": [],
            "budgets": business_store.budget_summary() if business_store is not None else {},
            "pendingApprovals": len(store.list_pending_approvals()),
            "activeSubagents": 0,
            "estopActive": bool(governor.snapshot().get("estop_active")) if governor is not None else False,
            "autonomyEnabled": bool(initiative_engine.status().get("config", {}).get("enabled", True)) if initiative_engine is not None else False,
            "minecraftConnected": False,
            "droidAwake": False,
            "updatedAt": now,
        })

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
        await asyncio.to_thread(store.stage_notification_emails, channel_hub)
        return web.json_response({
            "ok": True,
            "email_preferences": store.email_preferences(),
            "channels": channel_hub.status(),
            "config": channel_config.public_summary() if channel_config is not None else {},
            "ingress": channel_ingress.status() if channel_ingress is not None else {"pollers": {}},
            "outbox": [m.to_dict() for m in channel_hub.list_outbox(limit=25)],
        })

    async def email_preferences(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"error": "owner-local settings only"}, status=403)
        data = await _strict_json_object(request)
        if isinstance(data, web.Response):
            return data
        if not isinstance(data.get("responses"), bool) or not isinstance(data.get("tasks"), bool):
            return web.json_response({"error": "expected boolean preferences"}, status=400)
        from jaeger_channels.email_transport import mailbox
        try:
            address = mailbox(data["recipient"]) if data.get("recipient") else ""
            if not address and (data["responses"] or data["tasks"]):
                raise ValueError("recipient required")
        except (ValueError, TypeError, AttributeError):
            return web.json_response({"error": "invalid recipient"}, status=400)
        store.save_email_preferences(address, data["responses"], data["tasks"])
        return web.json_response({"ok": True})

    async def channels_send(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Channel send is owner-local only."}, status=403)
        if channel_hub is None:
            return web.json_response({"ok": False, "error": "channel hub unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        channel = str(body.get("channel") or "local_log")
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
                {"ok": False, "error": f"channel must be one of {sorted(SUPPORTED_EXTERNAL_CHANNELS)}"}, status=400
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

    async def list_remote_hosts(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Remote hosts are owner-local only."}, status=403)
        if remote_hosts is None:
            return web.json_response({"ok": True, "hosts": []})
        return web.json_response({"ok": True, "hosts": remote_hosts.list_public()})

    async def discover_remote_routes_route(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Remote discovery is owner-local only."}, status=403)
        if remote_hosts is None:
            return web.json_response({"ok": False, "error": "remote hosts unavailable"}, status=501)
        from jaeger_tools import discover_remote_routes
        return web.json_response(await asyncio.to_thread(discover_remote_routes, remote_hosts))

    async def connect_remote_host_route(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Remote connect is owner-local only."}, status=403)
        if remote_hosts is None:
            return web.json_response({"ok": False, "error": "remote hosts unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        target = str(body.get("target") or "").strip()
        if not target:
            return web.json_response({"ok": False, "error": "target is required"}, status=400)
        from jaeger_tools import RemoteExecError, connect_remote_host
        try:
            res = await asyncio.to_thread(
                connect_remote_host,
                remote_hosts,
                target,
                alias=str(body.get("alias") or ""),
                user=str(body.get("user") or ""),
                probe=bool(body.get("probe", True)),
            )
            return web.json_response(res, status=200 if res.get("ok") else 404)
        except RemoteExecError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def authorized_run_route(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Authorized workflows are owner-local only."}, status=403)
        if authorized_tasks is None:
            return web.json_response({"ok": False, "error": "authorized task engine unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        workflow = str(body.get("workflow") or "").strip()
        params = body.get("params") if isinstance(body.get("params"), Mapping) else {}
        origin = str(body.get("origin") or "owner")
        rec = await asyncio.to_thread(authorized_tasks.run_workflow, workflow, params, origin=origin)
        payload = rec.to_dict()
        status = 200 if rec.status in ("verified_success", "ambiguous_selection", "blocked_prerequisite") else (
            403 if rec.status == "denied_grant" else 404
        )
        return web.json_response(payload, status=status)

    async def authorized_grants_get(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Authorized grants are owner-local only."}, status=403)
        if authorized_tasks is None:
            return web.json_response({"ok": False, "error": "authorized task engine unavailable"}, status=501)
        return web.json_response({
            "ok": True,
            "settings": authorized_tasks.grants.get_settings().to_dict(),
            "folder_grants": [g.to_dict() for g in authorized_tasks.grants.list_folder_grants()],
        })

    async def authorized_grants_post(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Authorized grants are owner-local only."}, status=403)
        if authorized_tasks is None:
            return web.json_response({"ok": False, "error": "authorized task engine unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        root = str(body.get("root") or "").strip()
        ops = body.get("operations") if isinstance(body.get("operations"), list) else ["find_metadata"]
        origin = str(body.get("origin") or "owner")
        try:
            grant = await asyncio.to_thread(
                authorized_tasks.grants.grant_folder,
                root,
                operations=[str(o) for o in ops],
                origin=origin,
            )
            return web.json_response({"ok": True, "grant": grant.to_dict()})
        except PermissionError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=403)
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def authorized_grants_delete(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Authorized grants are owner-local only."}, status=403)
        if authorized_tasks is None:
            return web.json_response({"ok": False, "error": "authorized task engine unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        root = str(body.get("root") or "").strip()
        removed = await asyncio.to_thread(authorized_tasks.grants.revoke_folder, root, origin=str(body.get("origin") or "owner"))
        return web.json_response({"ok": removed, "root": root}, status=200 if removed else 404)

    async def authorized_settings_get(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Authorized settings are owner-local only."}, status=403)
        if authorized_tasks is None:
            return web.json_response({"ok": False, "error": "authorized task engine unavailable"}, status=501)
        return web.json_response({"ok": True, "settings": authorized_tasks.grants.get_settings().to_dict()})

    async def authorized_settings_put(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Authorized settings are owner-local only."}, status=403)
        if authorized_tasks is None:
            return web.json_response({"ok": False, "error": "authorized task engine unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        try:
            updated = await asyncio.to_thread(
                authorized_tasks.grants.update_settings,
                direct_chat=body.get("direct_chat") if "direct_chat" in body else None,
                owner_autonomy=body.get("owner_autonomy") if "owner_autonomy" in body else None,
                origin=str(body.get("origin") or "owner"),
            )
            return web.json_response({"ok": True, "settings": updated.to_dict()})
        except PermissionError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=403)

    async def upsert_remote_host(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Remote hosts are owner-local only."}, status=403)
        if remote_hosts is None:
            return web.json_response({"ok": False, "error": "remote hosts unavailable"}, status=501)
        body = await _strict_json_object(request)
        if isinstance(body, web.Response):
            return body
        from jaeger_tools import RemoteExecError, RemoteHostConfig
        alias = request.match_info["alias"]
        try:
            cfg = RemoteHostConfig(
                alias=alias,
                hostname=str(body.get("hostname") or "").strip(),
                user=str(body.get("user") or "").strip(),
                port=int(body.get("port") or 22),
                identity_file=str(body.get("identity_file") or "").strip(),
                strict_host_key=str(body.get("strict_host_key") or "accept-new").strip(),
                allowed_prefixes=tuple(str(p).strip() for p in (body.get("allowed_prefixes") or ()) if str(p).strip()),
                enabled=bool(body.get("enabled", True)),
                notes=str(body.get("notes") or "")[:240],
            )
            saved = remote_hosts.upsert(cfg)
        except (RemoteExecError, ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "host": saved.to_public_dict()})

    async def delete_remote_host(request: web.Request) -> web.Response:
        if not _owner_local_only(request):
            return web.json_response({"ok": False, "error": "Remote hosts are owner-local only."}, status=403)
        if remote_hosts is None:
            return web.json_response({"ok": False, "error": "remote hosts unavailable"}, status=501)
        alias = request.match_info["alias"]
        if not remote_hosts.remove(alias):
            return web.json_response({"ok": False, "error": "host not found"}, status=404)
        return web.json_response({"ok": True, "deleted": alias})

    async def embodiment_status(_request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "droid": droid_embodiment.observe() if droid_embodiment is not None else None,
            "minecraft": minecraft_embodiment.observe() if minecraft_embodiment is not None else None,
            "jp01": jp01_embodiment.observe() if jp01_embodiment is not None else None,
            "voice": voice_presence.snapshot() if voice_presence is not None else None,
            "vision": vision_buffer.stats() if vision_buffer is not None else None,
        })

    def _governor_estop_active() -> bool:
        if governor is None:
            return False
        if hasattr(governor, "estop_active"):
            return bool(governor.estop_active)
        if hasattr(governor, "_estop_active"):
            return bool(governor._estop_active)
        if hasattr(governor, "snapshot"):
            return bool(governor.snapshot().get("estop_active"))
        return False

    async def _optional_json_body(request: web.Request) -> dict[str, Any]:
        if not request.can_read_body:
            return {}
        try:
            raw = await request.read()
            if not raw or not raw.strip():
                return {}
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

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
        if target == "droid":
            if action == "wake" and _governor_estop_active():
                obs = emb.observe()
                return web.json_response(
                    {
                        "ok": False,
                        "error": "estop_active",
                        "awake": False,
                        "sleeping": bool(obs.get("sleeping", False)),
                    },
                    status=409,
                )
            res = await asyncio.to_thread(emb.act, action, params)
            _emit_global("droid.changed", {"action": action, "ok": bool(res.get("ok"))})
        else:
            res = emb.act(action, params)
            if target == "minecraft":
                _emit_global("minecraft.changed", {"action": action, "ok": bool(res.get("ok"))})
        return web.json_response(dict(res), status=200 if res.get("ok") else 409)

    async def minecraft_radar(request: web.Request) -> web.Response:
        if minecraft_embodiment is None:
            return web.json_response({"ok": False, "error": "minecraft embodiment unavailable"}, status=501)
        try:
            radius = max(4, min(int(request.query.get("radius") or "8"), 10))
        except ValueError:
            radius = 8
        data = await asyncio.to_thread(minecraft_embodiment.get_radar, radius=radius)
        return web.json_response(data)

    async def get_droid_reflex(_request: web.Request) -> web.Response:
        if droid_embodiment is None or not hasattr(droid_embodiment, "reflex"):
            return web.json_response({"ok": False, "error": "droid reflex unavailable"}, status=501)
        return web.json_response({"ok": True, "reflex": droid_embodiment.reflex.status()})

    async def post_droid_reflex(request: web.Request) -> web.Response:
        if not _is_owner_actor(request):
            return web.json_response({"ok": False, "error": "Droid reflex settings require owner access."}, status=403)
        if droid_embodiment is None or not hasattr(droid_embodiment, "reflex"):
            return web.json_response({"ok": False, "error": "droid reflex unavailable"}, status=501)
        body = await _optional_json_body(request)
        if body.get("touch"):
            droid_embodiment.reflex.touch(str(body.get("reason") or "owner_ping"))
        updated = droid_embodiment.reflex.update_config(
            auto_park_enabled=bool(body["auto_park_enabled"]) if "auto_park_enabled" in body else None,
            idle_park_s=float(body["idle_park_s"]) if "idle_park_s" in body else None,
        )
        _emit_global("droid.reflex_updated", updated)
        return web.json_response({"ok": True, "reflex": updated})

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

    async def droid_status(_request: web.Request) -> web.Response:
        if droid_embodiment is None:
            return web.json_response({"ok": False, "error": "droid embodiment unavailable"}, status=501)
        obs = dict(droid_embodiment.observe())
        estop_active = _governor_estop_active() if governor is not None else bool(obs.get("estop_latched"))
        return web.json_response({"ok": True, **obs, "estop_active": estop_active})

    async def droid_sleep(request: web.Request) -> web.Response:
        """Fail-safe privacy sleep/park route: NEVER blocked by E-Stop."""
        if droid_embodiment is None:
            return web.json_response({"ok": False, "error": "droid embodiment unavailable"}, status=501)
        body = await _optional_json_body(request)
        reason = str(body.get("reason") or "operator")
        res = await asyncio.to_thread(droid_embodiment.sleep, reason=reason)
        _emit_global("droid.changed", {"action": "sleep", "awake": False, "reason": reason})
        return web.json_response(dict(res), status=200)

    async def droid_wake(request: web.Request) -> web.Response:
        """Wake Droid and center gimbal; blocked fail-closed under E-Stop."""
        if droid_embodiment is None:
            return web.json_response({"ok": False, "error": "droid embodiment unavailable"}, status=501)
        obs = droid_embodiment.observe()
        estop_latched = bool(getattr(droid_embodiment, "_estop_latched", False) or obs.get("estop_latched"))
        if _governor_estop_active() or estop_latched:
            return web.json_response(
                {
                    "ok": False,
                    "error": "estop_active",
                    "awake": False,
                    "sleeping": bool(obs.get("sleeping", False)),
                },
                status=409,
            )
        body = await _optional_json_body(request)
        reason = str(body.get("reason") or "operator")
        res = await asyncio.to_thread(droid_embodiment.wake, reason=reason)
        _emit_global("droid.changed", {"action": "wake", "awake": bool(res.get("awake"))})
        return web.json_response(dict(res), status=200 if res.get("ok") else 409)

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
        res = await asyncio.to_thread(
            droid_embodiment.capture_frame,
            device_index=str(body.get("device_index") or "0"),
            summary=str(body.get("summary") or ""),
            include_preview=body.get("include_preview") is True,
        )
        return web.json_response(res, status=200 if res.get("ok") else 409)

    voice_lock = asyncio.Lock()

    async def droid_transcribe(request: web.Request) -> web.Response:
        if voice_lock.locked():
            return web.json_response({"error": "A voice clip is already being transcribed."}, status=409)
        async with voice_lock:
            audio = bytearray()
            async for chunk in request.content.iter_chunked(64 * 1024):
                audio.extend(chunk)
                if len(audio) > 2 * 1024 * 1024:
                    return web.json_response({"error": "Voice clip is too large."}, status=413)
            if not audio:
                return web.json_response({"error": "No voice audio received."}, status=400)
            try:
                result = await asyncio.to_thread(transcribe_clip, bytes(audio), enroll=request.query.get("enroll") == "1")
            except RuntimeError as exc:
                return web.json_response({"error": str(exc)}, status=422)
            if isinstance(result, dict) and "intent" not in result:
                intent = detect_voice_intent(str(result.get("transcript") or ""))
                if intent:
                    result = {**result, "intent": intent}
            if droid_embodiment is not None and hasattr(droid_embodiment, "reflex"):
                droid_embodiment.reflex.touch("voice_clip")
            if isinstance(result, dict) and result.get("transcript"):
                _emit_global("droid.voice_heard", {"transcript": str(result.get("transcript") or "")[:120]})
            return web.json_response(result)

    camera_preview_lock = asyncio.Lock()

    async def droid_camera_stream(request: web.Request) -> web.StreamResponse:
        if droid_embodiment is None:
            return web.Response(status=501)
        if camera_preview_lock.locked():
            return web.Response(status=409, text="Camera preview already open")
        async with camera_preview_lock:
            frames = droid_embodiment.stream_camera()
            response = web.StreamResponse(headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-store",
            })
            try:
                async for frame in frames:
                    if request.transport is None or request.transport.is_closing():
                        break
                    if not response.prepared:
                        await response.prepare(request)
                    header = f"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n"
                    await response.write(header.encode("ascii") + frame + b"\r\n")
            except (ConnectionError, asyncio.TimeoutError, RuntimeError):
                if not response.prepared:
                    return web.Response(status=503, text="Camera preview unavailable")
            finally:
                await frames.aclose()
            if not response.prepared:
                return web.Response(status=503, text="Camera preview unavailable")
            return response

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

    async def list_wiki_pages(request: web.Request) -> web.Response:
        if wiki_store is None:
            return web.json_response({"ok": True, "pages": []})
        path = (request.query.get("path") or "").strip()
        if path:
            try:
                page = wiki_store.read_page(path)
                return web.json_response({"ok": True, "page": page})
            except Exception as exc:  # noqa: BLE001
                return web.json_response({"ok": False, "error": str(exc)}, status=404)
        q = (request.query.get("q") or "").strip()
        if q:
            hits = wiki_store.search(q, limit=int(request.query.get("limit", "15")))
            return web.json_response({"ok": True, "results": hits, "count": len(hits)})
        section = (request.query.get("section") or "").strip() or None
        pages = wiki_store.browse(section=section)
        return web.json_response({"ok": True, "pages": pages, "count": len(pages)})

    async def write_wiki_page(request: web.Request) -> web.Response:
        if wiki_store is None:
            return web.json_response({"ok": False, "error": "wiki store unavailable"}, status=501)
        body = await request.json()
        try:
            saved = wiki_store.write_page(
                section=str(body.get("section") or "notes"),
                name=str(body.get("name") or ""),
                content=str(body.get("content") or ""),
            )
            return web.json_response({"ok": True, "page": saved}, status=201)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

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
    app.router.add_post("/v1/chat/session", main_chat_session)
    app.router.add_get("/v1/chat/topics", chat_topics)
    app.router.add_get("/v1/chat/search", chat_search)
    app.router.add_get("/v1/sessions", list_sessions)
    app.router.add_post("/v1/sessions", create_session)
    app.router.add_delete("/v1/sessions/{session_id}", delete_session)
    app.router.add_get("/v1/sessions/{session_id}/messages", list_messages)
    app.router.add_post("/v1/sessions/{session_id}/runs", submit_run)
    app.router.add_post("/v1/sessions/{session_id}/browser/grant", grant_supervised_browser)
    app.router.add_post("/v1/sessions/{session_id}/browser/stop", stop_supervised_browser)
    app.router.add_get("/v1/sessions/{session_id}/jobs", list_scheduled_jobs_route)
    app.router.add_post("/v1/sessions/{session_id}/jobs", create_scheduled_job)
    app.router.add_get("/v1/sessions/{session_id}/jobs/{job_id}", get_scheduled_job)
    app.router.add_post("/v1/sessions/{session_id}/jobs/{job_id}/cancel", cancel_scheduled_job)
    app.router.add_get("/v1/sessions/{session_id}/job-series/{series_id}", get_job_series)
    app.router.add_patch("/v1/sessions/{session_id}/job-series/{series_id}", update_job_series)
    app.router.add_get("/v1/sessions/{session_id}/events", stream_events)
    app.router.add_get("/v1/sessions/{session_id}/stream", stream_events)
    app.router.add_post("/v1/chat/completions", openai_chat_completions)
    app.router.add_get("/v1/approvals", list_approvals)
    app.router.add_post("/v1/approvals/{approval_id}/resolve", resolve_approval)
    app.router.add_get("/v1/tools", list_tools)
    app.router.add_get("/v1/tools/catalog", tool_catalog)
    app.router.add_get("/v1/tools/source", tool_source)
    app.router.add_put("/v1/tools/source", tool_source)
    app.router.add_get("/v1/models", list_models)
    app.router.add_post("/v1/models/select", select_model)
    app.router.add_get("/v1/models/cookbook", get_model_cookbook)
    app.router.add_post("/v1/models/roundtable", run_model_roundtable)
    app.router.add_get("/v1/models/telemetry", get_model_telemetry)
    app.router.add_get("/v1/models/risk-cards", get_model_risk_cards)
    app.router.add_post("/v1/models/eval", run_model_eval)
    app.router.add_post("/v1/research/run", run_deep_research)
    app.router.add_get("/v1/research/reports", list_research_reports_route)
    app.router.add_get("/v1/system/mode", get_system_mode)
    app.router.add_post("/v1/system/mode", set_system_mode)
    app.router.add_get("/v1/evidence", list_evidence_route)
    app.router.add_get("/v1/evidence/{evidence_id}", inspect_evidence_route)
    app.router.add_get("/v1/skills/importers", list_importers_route)
    app.router.add_post("/v1/skills/import", run_importer_route)
    app.router.add_get("/v1/avatars/packs", get_avatar_packs)
    app.router.add_get("/v1/hardware/nexus/jp01-channels", get_nexus_jp01_channels)
    app.router.add_get("/v1/hardware/nexus/info", get_nexus_info)
    app.router.add_get("/v1/hardware/nexus/snapshot", get_nexus_snapshot)
    app.router.add_get("/v1/board", get_board)
    app.router.add_post("/v1/board/cards", create_board_card)
    app.router.add_post("/v1/board/cards/{card_id}/move", move_board_card)
    app.router.add_delete("/v1/board/cards/{card_id}", delete_board_card)
    app.router.add_get("/v1/reminders", list_reminders_route)
    app.router.add_post("/v1/reminders", create_reminder_route)
    app.router.add_delete("/v1/reminders/{reminder_id}", cancel_reminder_route)
    app.router.add_get("/v1/models/routing", get_model_routing)
    app.router.add_put("/v1/models/routing", put_model_routing)
    app.router.add_get("/v1/onboarding/status", get_onboarding_status)
    app.router.add_post("/v1/onboarding/complete", post_onboarding_complete)
    app.router.add_get("/v1/skills", list_skills)
    app.router.add_get("/v1/mcp/servers", list_mcp_servers)
    app.router.add_get("/v1/mcp/presets", get_mcp_presets)
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
    app.router.add_get("/v1/cognition/actions", get_cognition_actions)
    app.router.add_get("/v1/cognition/briefing", get_cognition_briefing)
    app.router.add_post("/v1/cognition/autonomy", post_cognition_autonomy)
    app.router.add_post("/v1/cognition/perceive", post_perception)
    app.router.add_get("/v1/avatars/assets", list_avatar_assets)
    app.router.add_post("/v1/avatars/assets", upload_avatar_asset)
    app.router.add_get("/v1/avatars/assets/{sha}/file", serve_avatar_asset)
    app.router.add_get("/v1/avatars/{agent_id}", get_avatar)
    app.router.add_put("/v1/avatars/{agent_id}", put_avatar)
    app.router.add_put("/v1/avatars/{agent_id}/live", put_avatar_live)
    app.router.add_get("/v1/avatars/{agent_id}/visemes", get_avatar_visemes)
    app.router.add_get("/v1/events/global", stream_global_events)
    app.router.add_get("/v1/events/recent", list_recent_global_events)
    app.router.add_get("/v1/cognition/awareness", get_cognition_awareness)
    app.router.add_get("/v1/office/state", get_office_state)
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
    app.router.add_put("/v1/channels/email/preferences", email_preferences)
    app.router.add_post("/v1/channels/send", channels_send)
    app.router.add_post("/v1/channels/messages/{message_id}/approve", channels_approve)
    app.router.add_post("/v1/channels/inbound", channels_inbound)
    app.router.add_post("/v1/sessions/{session_id}/channel-reply", channels_reply)
    app.router.add_get("/v1/remote/hosts", list_remote_hosts)
    app.router.add_get("/v1/remote/discover", discover_remote_routes_route)
    app.router.add_post("/v1/remote/connect", connect_remote_host_route)
    app.router.add_post("/v1/authorized/run", authorized_run_route)
    app.router.add_get("/v1/authorized/grants", authorized_grants_get)
    app.router.add_post("/v1/authorized/grants", authorized_grants_post)
    app.router.add_delete("/v1/authorized/grants", authorized_grants_delete)
    app.router.add_get("/v1/authorized/settings", authorized_settings_get)
    app.router.add_put("/v1/authorized/settings", authorized_settings_put)
    app.router.add_put("/v1/remote/hosts/{alias}", upsert_remote_host)
    app.router.add_delete("/v1/remote/hosts/{alias}", delete_remote_host)
    app.router.add_get("/v1/embodiment/status", embodiment_status)
    app.router.add_post("/v1/embodiment/{body}/act", embodiment_act)
    app.router.add_get("/v1/droid/status", droid_status)
    app.router.add_get("/v1/droid/reflex", get_droid_reflex)
    app.router.add_post("/v1/droid/reflex", post_droid_reflex)
    app.router.add_post("/v1/droid/sleep", droid_sleep)
    app.router.add_post("/v1/droid/wake", droid_wake)
    app.router.add_get("/v1/droid/devices", droid_devices)
    app.router.add_post("/v1/droid/capture", droid_capture)
    app.router.add_post("/v1/droid/transcribe", droid_transcribe)
    app.router.add_get("/v1/droid/camera-stream", droid_camera_stream, allow_head=False)
    app.router.add_get("/v1/embodiment/minecraft/radar", minecraft_radar)
    app.router.add_post("/v1/embodiment/minecraft/checkpoint", minecraft_checkpoint)
    app.router.add_post("/v1/presence/voice/hear", presence_voice_hear)

    if cognition_loop is not None:
        async def _start_cognition(_app: web.Application) -> None:
            cognition_loop.start()

        async def _stop_cognition(_app: web.Application) -> None:
            await cognition_loop.stop()

        app.on_startup.append(_start_cognition)
        app.on_cleanup.append(_stop_cognition)
    if channel_ingress is not None:
        async def _start_ingress(_app: web.Application) -> None:
            channel_ingress.start()

        async def _stop_ingress(_app: web.Application) -> None:
            await channel_ingress.stop()

        app.on_startup.append(_start_ingress)
        app.on_cleanup.append(_stop_ingress)
    app.router.add_get("/v1/memory/facts", list_facts)
    app.router.add_post("/v1/memory/facts", put_fact)
    app.router.add_delete("/v1/memory/facts/{key}", delete_fact)
    app.router.add_get("/v1/memory/learning", list_learning)
    app.router.add_post("/v1/memory/learning", add_learning)
    app.router.add_delete("/v1/memory/learning/{entry_id}", forget_learning)
    app.router.add_get("/v1/memory/goals", list_goals)
    app.router.add_post("/v1/memory/goals", upsert_goal)
    app.router.add_get("/v1/memory/wiki", list_wiki_pages)
    app.router.add_post("/v1/memory/wiki", write_wiki_page)
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
