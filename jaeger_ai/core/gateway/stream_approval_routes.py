"""Extracted Gateway SSE stream, approvals, IDE bridge & project-grant mixin (Wave 10).

Owns `/v1/events/stream`, approval resolution & inbox projection, secret-vault
waits, IDE bridge roundtrips, project grants, and attachment preview streaming
for :class:`JaegerGatewayApp`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web

from jaeger_ai.core.gateway.event_bus import ReplayGap

logger = logging.getLogger(__name__)


def _server_attr(name: str) -> Any:
    from . import server as _server
    return getattr(_server, name)


class GatewayStreamApprovalRoutesMixin:
    """SSE stream, approval resolution, IDE bridge, and file preview handlers."""

    async def handle_global_stream(self, request: web.Request) -> web.StreamResponse:
        """GET /v1/events/stream — global (``*``) events only: agent.*, approvals,
        task.*, connect_app.updated. Same framing, resume (``last_event_id``) and
        410 rules as the session stream; session-prefixed callers (mcp/a2a) are
        refused by the scope middleware (not in PREFIXED_READ_ROUTES)."""
        return await self._sse_stream(request, "*", live_without_cursor=True)

    async def _sse_stream(self, request: web.Request, session_id: str, live_without_cursor: bool = False) -> web.StreamResponse:
        try:
            last_event_id = int(request.query.get("last_event_id") or request.headers.get("Last-Event-ID") or 0)
        except ValueError:
            return web.json_response({"error": "last_event_id must be an integer"}, status=400)
        session_only = session_id != "*" and request.query.get("scope") == "session"
        window = self.event_bus.replay_window(session_id, last_event_id)
        if live_without_cursor and "last_event_id" not in request.query and "Last-Event-ID" not in request.headers:
            last_event_id = int(window.get("latest_event_id") or 0)
        if window.get("cursor_expired"):
            return web.json_response(
                {
                    "error": "Resume cursor is no longer retained",
                    "oldest_event_id": window.get("oldest_event_id"),
                    "latest_event_id": window.get("latest_event_id"),
                    "valid_cursor": False,
                },
                status=410,
            )

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        async def _flush(data: bytes) -> None:
            await response.write(data)

        await _flush(b"retry: 2000\n\n")

        events = (
            self.event_bus.subscribe(session_id, since_event_id=last_event_id, session_only=True)
            if session_only
            else self.event_bus.subscribe(session_id, since_event_id=last_event_id)
        )
        if session_only:
            status = {
                "event": "stream.status",
                "session_id": session_id,
                "timestamp": time.time(),
                "data": {
                    "state": "resumed" if last_event_id else "connected",
                    "resumed_from": last_event_id,
                    "latest_event_id": window.get("latest_event_id"),
                    "oldest_event_id": window.get("oldest_event_id"),
                    "replaying": max(0, int(window.get("latest_event_id") or 0) - int(last_event_id or 0)),
                },
            }
            await _flush(f"event: stream.status\ndata: {json.dumps(status)}\n\n".encode("utf-8"))
        pending = asyncio.create_task(anext(events))
        try:
            while True:
                ready, _ = await asyncio.wait({pending}, timeout=getattr(self, "_sse_keepalive_seconds", 10.0))
                if not ready:
                    await _flush(b": keepalive\n\n")
                    continue
                evt = pending.result()
                payload = json.dumps({
                    "event_id": evt.event_id,
                    "session_id": evt.session_id,
                    "event": evt.event,
                    "data": evt.data,
                    "timestamp": evt.timestamp,
                    **({"trace": evt.trace} if evt.trace else {}),
                })
                chunk = f"id: {evt.event_id}\nevent: {evt.event}\ndata: {payload}\n\n"
                await _flush(chunk.encode("utf-8"))
                pending = asyncio.create_task(anext(events))
        except ReplayGap:
            gap = {
                "event": "stream.status",
                "session_id": session_id,
                "timestamp": time.time(),
                "data": {"state": "gap", "resumed_from": last_event_id},
            }
            try:
                await _flush(f"event: stream.status\ndata: {json.dumps(gap)}\n\n".encode("utf-8"))
            except Exception:  # noqa: BLE001
                pass
        except (asyncio.CancelledError, ConnectionError, StopAsyncIteration):
            pass
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await events.aclose()

        return response

    def _approval_origin(self, session_id: str | None) -> dict[str, Any] | None:
        if not session_id:
            return None
        try:
            session = self.store.get_session(session_id) or {}
        except Exception:  # noqa: BLE001
            return None
        meta = session.get("metadata") or {}
        parent = str(meta.get("parent_session_id") or "")
        if not parent or parent == session_id:
            return None
        return {
            "task_id": meta.get("task_id"),
            "child_session_id": session_id,
            "agent_id": session.get("agent_id") or meta.get("agent_id") or "native:jaeger",
            "parent_session_id": parent,
        }

    def _publish_approval_request(
        self,
        session_id: str,
        origin: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> None:
        if origin:
            payload = {**payload, "origin": origin}
        if not payload.get("agent_id"):
            payload = {
                **payload,
                "agent_id": (origin or {}).get("agent_id")
                or self._session_agent_id(self.store.get_session(session_id))
                or "native:jaeger",
            }
        self.event_bus.publish(session_id, "approval.request", payload)
        if origin and origin.get("parent_session_id"):
            self.event_bus.publish(origin["parent_session_id"], "approval.request", payload)

    def _with_origin(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("kind") == "handoff":
            handoff = self.store.get_handoff((row.get("metadata") or {}).get("handoff_id") or "")
            if handoff:
                row = {**row, "session_id": handoff.get("session_id"), "task": handoff.get("task")}
        origin = (row.get("metadata") or {}).get("origin")
        return {**row, "origin": origin} if origin else row

    def _secret_wait(self, session_id: str, request_id: str, prompt: str, options: tuple[str, ...]) -> str:
        name = str((options or ("",))[0] or "").strip()
        if not name:
            return ""
        try:
            from jaeger_agent.core import credentials as creds
            from jaeger_agent.core.workspace import _require_layout
            layout = _require_layout()
            before = set(creds.list_credentials(layout))
        except Exception:  # noqa: BLE001
            return ""
        self.event_bus.publish(session_id, "secret.request", {
            "name": name, "prompt": prompt, "session_id": session_id, "request_id": request_id,
            "replace": name in before,
        })
        try:
            path = creds._credential_path(layout, name)
            start_mtime = path.stat().st_mtime if path.exists() else 0.0
        except Exception:  # noqa: BLE001
            return ""
        scope = self._cancellations.get(request_id)
        deadline = time.monotonic() + _server_attr("CLARIFY_WAIT_S")
        while time.monotonic() < deadline:
            if scope is not None and scope.cancelled:
                break
            try:
                if path.exists() and path.stat().st_mtime > start_mtime:
                    return "__stored__"
            except OSError:
                pass
            time.sleep(0.5)
        self.event_bus.publish(session_id, "secret.resolved", {"name": name, "status": "expired"})
        return ""

    async def handle_list_approvals(self, request: web.Request) -> web.Response:
        from . import approvals_inbox
        approvals_inbox.sweep_expired(self)
        pending = approvals_inbox.pending_items(self)
        sid = (request.query.get("session_id") or "").strip()
        if sid:
            pending = [
                row for row in pending
                if row.get("session_id") == sid
                or ((row.get("origin") or {}).get("parent_session_id") == sid)
            ]
        request_id = (request.query.get("request_id") or "").strip()
        if request_id:
            pending = [row for row in pending if row.get("request_id") == request_id]
        pending = approvals_inbox.filter_sort(pending, request.query)
        return web.json_response({"approvals": pending})

    async def handle_get_approval(self, request: web.Request) -> web.Response:
        approval = self.store.get_approval(request.match_info["id"])
        caller = request.get("caller")
        prefix = getattr(caller, "session_prefix", None)
        if approval is None or (prefix and not str(approval.get("session_id") or "").startswith(prefix)):
            return web.json_response({"error": "Approval not found"}, status=404)
        return web.json_response({
            key: approval.get(key)
            for key in ("approval_id", "session_id", "request_id", "kind", "prompt",
                        "options", "status", "decision", "created_at", "resolved_at")
        })

    _IDE_KINDS = frozenset({"context", "open_file", "diagnostics"})

    def _ide_request(self, session_id: str, request_id: str, kind: str, args: dict, timeout: float) -> dict[str, Any]:
        import concurrent.futures

        loop = getattr(self, "_loop", None)
        if kind not in self._IDE_KINDS or loop is None or not loop.is_running():
            return self._ide_context_fallback(session_id, kind, {"ok": False, "error": "The IDE bridge is unavailable"})
        ide_request_id = uuid.uuid4().hex[:12]
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._ide_pending[ide_request_id] = (session_id, future)
        payload = {
            "ide_request_id": ide_request_id,
            "request_id": request_id,
            "kind": kind,
            "args": {k: (v if isinstance(v, (int, float)) else str(v)[:500]) for k, v in (args or {}).items()},
        }
        loop.call_soon_threadsafe(self.event_bus.publish, session_id, "ide.request", payload)
        try:
            answer = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            answer = {"ok": False, "error": "The IDE did not answer. Is the Jaeger panel open in your editor?"}
        finally:
            self._ide_pending.pop(ide_request_id, None)
        return self._ide_context_fallback(session_id, kind, answer)

    def _ide_context_fallback(self, session_id: str, kind: str, answer: dict[str, Any]) -> dict[str, Any]:
        if kind != "context":
            return answer
        folder = str((self.store.get_session(session_id) or {}).get("workspace") or "")
        if answer.get("ok") and isinstance(answer.get("result"), dict):
            from jaeger_ai.core.entity.ide_context import clean as clean_ide_context
            result = clean_ide_context(answer["result"]) or {}
            if folder and not result.get("workspace_folder"):
                result["workspace_folder"] = folder
            return {**answer, "result": result}
        if folder:
            return {
                "ok": True,
                "result": {"workspace_folder": folder, "workspace_folders": [folder]},
                "fallback": True,
                "ide_error": answer.get("error"),
            }
        return answer

    async def handle_ide_result(self, request: web.Request) -> web.Response:
        pending = self._ide_pending.get(request.match_info["ide_request_id"])
        if pending is None or pending[0] != request.match_info["id"]:
            return web.json_response({"error": "No such pending IDE request"}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Body must be an object"}, status=400)
        answer = {
            "ok": bool(body.get("ok")),
            **({"result": body["result"]} if body.get("ok") else {"error": str(body.get("error") or "IDE request failed")[:300]}),
        }
        if not pending[1].done():
            pending[1].set_result(answer)
        return web.json_response({"delivered": True})

    def _config_path(self) -> Path | None:
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir

        try:
            layout = getattr(EntityRuntime.get_singleton(), "layout", None)
        except Exception:  # noqa: BLE001
            rt = getattr(EntityRuntime, "_instance", None)
            layout = getattr(rt, "layout", None) if rt is not None else None
        if layout is None:
            inst = os.environ.get("JAEGER_INSTANCE_DIR")
            layout = InstanceLayout(root=Path(inst) if inst else resolve_instance_dir())
        return getattr(layout, "config_path", None)

    def _collaboration_mode(self) -> str:
        return "one_mind"

    async def handle_get_collaboration(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.collaboration import snapshot
        return web.json_response(snapshot(self._collaboration_mode()))

    async def handle_set_collaboration(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "error": "Collaboration mode is no longer a setting. Jaeger always runs as one lead with internal helpers.",
                "mode": "one_mind",
            },
            status=410,
        )

    def _migrate_retired_interaction_tier(self) -> None:
        from jaeger_ai.contract.modes import normalize_interaction_tier
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml

        path = self._config_path()
        if path is None or not Path(path).is_file():
            return
        config = load_yaml(Path(path), Config)
        import yaml
        saved = yaml.safe_load(Path(path).read_text()) or {}
        raw = (saved.get("automation") or {}).get("interaction_tier")
        wanted = normalize_interaction_tier(raw)
        if raw == wanted:
            return
        config.automation.interaction_tier = wanted
        dump_yaml(Path(path), config)

    def _current_tier(self) -> str:
        from jaeger_ai.contract.modes import DEFAULT_INTERACTION_TIER, normalize_interaction_tier

        path = self._config_path()
        if path is not None and Path(path).is_file():
            try:
                from jaeger_ai.core.instance.schemas import Config, load_yaml

                cfg = load_yaml(Path(path), Config)
                return normalize_interaction_tier(
                    getattr(cfg.automation, "interaction_tier", DEFAULT_INTERACTION_TIER)
                )
            except Exception:
                pass
        return DEFAULT_INTERACTION_TIER

    def _plan_mode_execution(self, execution: dict[str, Any] | None) -> dict[str, Any]:
        from jaeger_ai.contract.modes import plan_tool_allowed

        current = dict(execution or {})
        grant = current.get("allowed_tools")
        if grant is None:
            names = self._catalog_tool_names()
        else:
            names = [str(t) for t in grant]
        current["allowed_tools"] = [name for name in names if plan_tool_allowed(name)]
        current["interaction_tier"] = "plan"
        return current

    def _catalog_tool_names(self) -> list[str]:
        try:
            from jaeger_agent.skill_registry.tool_discovery import catalog
            rows = catalog()
            names = []
            for row in rows or []:
                name = getattr(row, "name", None) or (row.get("name") if isinstance(row, dict) else None)
                if name:
                    names.append(str(name))
            if names:
                return names
        except Exception:  # noqa: BLE001
            logger.debug("plan-mode tool catalog unavailable", exc_info=True)
        return [
            "read_file", "list_skill_dir", "list_dir", "list_directory",
            "search_files", "grep", "glob", "web_search", "retrieve",
            "memory_get", "get_file", "get_time", "get_weather",
        ]

    async def _session_file_response(self, request, row, session):
        session_id = session["session_id"]
        from .attachment_access import read
        try:
            result = await asyncio.to_thread(
                read,
                row,
                staged_root=self._staged_upload_dir(session_id),
                workspace=session.get("workspace") or "",
                limit=self.UPLOAD_MAX_BYTES,
            )
        except (OSError, ValueError):
            return web.json_response(
                {"error": "Attachment missing, changed, or outside its originating workspace; bytes withheld"},
                status=409,
            )
        if request.query.get("view") == "preview":
            import base64
            from .attachment_preview import spreadsheet
            from .pdf_preview import pdf
            from jaeger_ai.contract.file_previews import PDF_MAX_PREVIEW_PAGES
            try:
                if result["name"].lower().endswith(".pdf"):
                    raw_page = request.query.get("page", "1")
                    if not raw_page.isdecimal() or not 1 <= int(raw_page) <= PDF_MAX_PREVIEW_PAGES:
                        raise ValueError("Unsupported PDF preview page")
                    key = (result["sha256"], result["mime"], result["name"], int(raw_page))
                    previous_key, work = getattr(self, "_pdf_preview_work", (None, None))
                    if work is not None and not work.done() and previous_key != key:
                        preview = {
                            "format": "unsupported",
                            "notice": "Another PDF page preview is being prepared. Retry after it settles; no additional renderer was started.",
                        }
                    else:
                        if work is None or previous_key != key or work.done() and (work.cancelled() or work.exception() is not None):
                            work = asyncio.create_task(
                                asyncio.to_thread(pdf, base64.b64decode(result["data_base64"]), result["mime"], result["name"], page=int(raw_page))
                            )
                            work.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
                            self._pdf_preview_work = (key, work)
                        preview = await asyncio.shield(work)
                else:
                    preview = await asyncio.to_thread(spreadsheet, base64.b64decode(result["data_base64"]), result["mime"], result["name"])
            except Exception as exc:
                logger.debug("Bounded attachment preview unavailable: %s", type(exc).__name__)
                preview = {
                    "format": "unsupported",
                    "notice": "This file or page has no available bounded preview. Download verified bytes to use an appropriate viewer.",
                }
            return web.json_response({"session_id": session_id, **{k: v for k, v in result.items() if k != "data_base64"}, "preview": preview})
        return web.json_response({"session_id": session_id, **result})

    async def handle_resolve_approval(self, request: web.Request) -> web.Response:
        """Resolve a pending approval. First writer wins; denial prevents effects."""
        approval_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        approved = bool(body.get("approved", True))
        decision = str(body.get("decision") or body.get("choice") or ("once" if approved else "deny"))
        if decision not in {"once", "session", "deny", "always", "allow", "yes"}:
            return web.json_response({"error": "Unsupported approval decision"}, status=400)
        approved = decision != "deny"

        if getattr(request, "path", "").endswith("/decision") and not all(
            body.get(key) for key in ("expected_session_id", "expected_request_id", "expected_profile")
        ):
            return web.json_response({"error": "Scoped approval context is required"}, status=400)
        for key in ("expected_session_id", "expected_request_id", "expected_profile"):
            if key in body and (not isinstance(body[key], str) or not body[key].strip()):
                return web.json_response({"error": "Invalid approval context"}, status=400)
        payload = GatewayStreamApprovalRoutesMixin.resolve_pending(
            self,
            approval_id,
            approved=approved,
            decision=decision,
            context={key: body[key] for key in ("expected_session_id", "expected_request_id", "expected_profile") if key in body},
        )
        if payload is None:
            existing = self.store.get_approval(approval_id) or {}
            if existing.get("decision") == "cancelled":
                return web.json_response(
                    {"error": "Request was cancelled; approval no longer applies"}, status=409,
                )
            return web.json_response(
                {"error": "Approval is stale, expired, or its permission context changed"},
                status=409 if existing else 404,
            )
        return web.json_response(payload)

    def resolve_pending(
        self,
        approval_id: str,
        *,
        approved: bool,
        decision: str,
        context: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        resolved = self.store.resolve_approval(approval_id, approved=approved, decision=decision, **(context or {}))
        if resolved is None:
            return None
        future = self.pending_approvals.pop(approval_id, None)
        if future is not None and not future.done():
            future.set_result(approved)

        handoff_row = None
        if resolved is not None and (resolved.get("metadata") or {}).get("task_id"):
            try:
                self.task_owner.resolve(resolved["metadata"]["task_id"], approved)
            except KeyError:
                logger.warning("approval %s names unknown task %s", approval_id, resolved["metadata"]["task_id"])
        if resolved is not None:
            hid = (resolved.get("metadata") or {}).get("handoff_id")
            if hid:
                handoff_row = self.store.get_handoff(str(hid))
            if handoff_row is None:
                for item in self.store.list_handoffs():
                    if item.get("approval_id") == approval_id:
                        handoff_row = item
                        break
            if handoff_row is not None:
                if approved:
                    handoff_row = self.store.save_handoff({**handoff_row, "status": "approved"})
                    rid = handoff_row.get("request_id") or handoff_row["id"]
                    if rid not in self._running_tasks:
                        self._running_tasks[rid] = asyncio.create_task(
                            self._execute_handoff(handoff_row["id"])
                        )
                else:
                    handoff_row = self.store.save_handoff({
                        **handoff_row,
                        "status": "denied",
                        "result": {"ok": False, "status": "denied", "summary": "Handoff denied by operator."},
                    })

        payload = {
            "approval_id": approval_id,
            "resolved": True,
            "approved": approved,
            "decision": decision,
            "handoff": handoff_row,
        }
        row_origin = ((resolved or {}).get("metadata") or {}).get("origin")
        if resolved is not None:
            payload["session_id"] = resolved.get("session_id")
            payload["request_id"] = resolved.get("request_id")
            call_id = ((resolved or {}).get("metadata") or {}).get("call_id")
            if call_id:
                payload["call_id"] = call_id
        if row_origin:
            payload["origin"] = row_origin
        for key, value in (extra or {}).items():
            if value is not None:
                payload[key] = value
        self.event_bus.publish("*", "approval.resolved", payload)
        return payload

    def _project_for_session(self, session_id: str) -> dict[str, Any] | None:
        meta = (self.store.get_session(session_id) or {}).get("metadata") or {}
        pid = meta.get("project_id")
        return self.projects.get(pid) if pid else None

    _PROJECT_SHELL_TOOLS = frozenset({"terminal", "run_shell", "exec_command"})
    _PROJECT_WRITE_TOOLS = frozenset({
        "write_file", "file_write", "append_file", "patch", "edit_file",
        "move_file", "copy_file", "make_directory", "mkdir",
    })
    _PROJECT_PATH_KEYS = ("path", "file_path", "dest", "destination", "src", "source", "target", "new_path")

    def _project_grant_allows(self, session_id: str, request: Any) -> bool:
        project = self._project_for_session(session_id)
        if not project:
            return False
        from jaeger_ai.core.agent_registry.projects import command_allowed, path_in_project
        names = {str(getattr(request, "skill", "") or ""), str(getattr(request, "operation", "") or "")}
        args = getattr(request, "arguments", None) or {}
        grants = project.get("grants") or {}
        allowed, why = False, ""
        if names & self._PROJECT_SHELL_TOOLS:
            cmd = str(args.get("command") or args.get("cmd") or "")
            workdir = args.get("workdir")
            if workdir and not path_in_project(project, str(workdir)):
                allowed, why = False, "workdir outside project"
            else:
                allowed, why = command_allowed(project, cmd)
        elif names & self._PROJECT_WRITE_TOOLS and grants.get("writes"):
            paths = [str(args[k]) for k in self._PROJECT_PATH_KEYS if args.get(k)]
            allowed = bool(paths) and all(path_in_project(project, p) for p in paths)
            why = "write inside project root" if allowed else "path outside project root"
        elif "run_build_check" in names:
            root = str(args.get("root") or project["root"])
            allowed, why = path_in_project(project, root), "build check inside project root"
        if allowed:
            logger.info(
                "project grant %s allowed %s %s (%s)",
                project["id"],
                sorted(n for n in names if n),
                _server_attr("_approval_target")(request),
                why,
            )
        return allowed
