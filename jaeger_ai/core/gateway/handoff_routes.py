"""Extracted Gateway agent handoff & specialist delegation mixin (Wave 2).

Handles ``POST /v1/agents/{id}/handoff``, delegate progress publishing,
bounded specialist handoff execution, and specialist chat invocations.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


def _server_attr(name: str) -> Any:
    from . import server as _server
    return getattr(_server, name)


def _collab_timeout(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_collab_timeout")(*args, **kwargs)


def _handoff_tool_scope(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("_handoff_tool_scope")(*args, **kwargs)


def current_request_actor(*args: Any, **kwargs: Any) -> Any:
    return _server_attr("current_request_actor")(*args, **kwargs)


class GatewayHandoffRoutesMixin:
    """Agent handoff admission and specialist execution methods for JaegerGatewayApp."""

    async def handle_handoff_agent(self, request: web.Request) -> web.Response:
        """Lead → specialist handoff using a real isolated child run."""
        to_agent_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        if not isinstance(body,dict):
            return web.json_response({'error':'Handoff must be an object'},status=400)
        requested_model=body.get('model')
        if requested_model is not None and (not isinstance(requested_model,str) or not 1<=len(requested_model.strip())<=200):
            return web.json_response({'error':'Model must be a bounded configured model ID or null'},status=400)
        requested_model=requested_model.strip() if requested_model else None
        if body.get('permission_mode','inherit')!='inherit':
            return web.json_response({'error':'Permission-mode overrides are unavailable; existing caller and tool ceilings remain'},status=403)
        if 'background' in body and body['background'] is not True:
            return web.json_response({'error':'This owner supports durable background handoffs only; foreground execution is unavailable'},status=400)
        task = str(body.get("task") or "").strip()
        if not task:
            return web.json_response({"error": "task is required"}, status=400)
        registry = self._registry()
        target = registry.get_agent(to_agent_id)
        if target is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        from_id = str(body.get("from_agent_id") or "native:jaeger").strip()
        require_approval = bool(body.get("require_approval", True))
        caller = request.get("caller")
        if not require_approval and getattr(caller, "name", None) == "jaegerd":
            # The agent asks through jaegerd's credential and cannot waive the
            # owner's approval itself; only the owner's autonomy=auto does.
            from jaeger_ai.core.runtime.autonomy import auto_approves, effective_autonomy
            require_approval = not auto_approves(effective_autonomy(self._config_path()))
        # Collaboration mode (core/runtime/collaboration.py): ``delegate`` runs the
        # target as an inner helper of the lead — fresh context from a brief, the
        # lead's tools narrowed, result returned to the lead only. ``call_agent``
        # is an alias of it unless the mode is ``team`` (or ``auto`` and the owner
        # @mentioned that agent in the asking message).
        collab_mode = self._collaboration_mode()
        delegate_mode = str(body.get("mode") or "").strip().lower() == "delegate"
        if not delegate_mode and str(body.get("via") or "") == "call_agent":
            delegate_mode = True
        if delegate_mode and body.get("reply_to_handoff_id"):
            return web.json_response({"error": "An inner helper has no thread to reply to; delegate a new brief"}, status=400)
        if delegate_mode:
            # The helper's tools are a subset of the lead's and every tool call
            # keeps its own policy/approval gate, so starting it is not a new grant.
            require_approval = False
        reply_parent = None
        if body.get("reply_to_handoff_id"):
            if not isinstance(body["reply_to_handoff_id"], str):
                return web.json_response({"error": "reply_to_handoff_id must be text"}, status=400)
            from jaeger_ai.core.gateway.handoff_reply import reply_context, ReplyConflict
            try:
                reply_parent = reply_context(self.store, body["reply_to_handoff_id"], source=from_id, target=target.id, session=body.get("session_id"))
            except ReplyConflict as exc:
                return web.json_response({"error": str(exc)}, status=409)
            require_approval = True
        request_id = str(body.get("request_id") or uuid.uuid4().hex)
        if not request.get('_owner_handoff_command'):
            from .handoff_controls import command_key
            kind='handoff_reply' if reply_parent else 'handoff_request'
            resource=reply_parent['id'] if reply_parent else target.id
            if self.store.control_operation(command_key(kind,resource,request_id,request.get('caller_actor'))):
                return web.json_response({'error':'Original owner command retained; inspect its receipt, do not resubmit through another route'},status=409)
        parent_run_id = body.get("parent_run_id") or body.get("parent_request_id")
        parent_chain = list(body.get("parent_chain") or [])
        depth = int(body.get("delegation_depth") or len(parent_chain))
        permitted_context = str(body.get("permitted_context") or "")
        timeout_s = int(body.get("timeout_seconds") or 120)
        allowed_tools = body.get("allowed_tools") or []
        if not isinstance(allowed_tools, list) or any(not isinstance(x, str) or not x.strip() for x in allowed_tools):
            return web.json_response({"error": "allowed_tools must be a list of tool names"}, status=400)
        if "dispatcher" in permitted_context.lower() and "dispatcher transcript" in permitted_context.lower():
            return web.json_response({"error": "dispatcher transcript is not permitted specialist context"}, status=403)
        # Project: shared root, team membership, limits and the owner's
        # handoff grant. Without a project_id the origin chat's project is used.
        from jaeger_ai.core.agent_registry.projects import default_limits
        project_id = str(body.get("project_id") or "").strip() or None
        hint_session = str(body.get("session_id") or "").strip() or None
        if project_id is None and hint_session:
            project_id = ((self.store.get_session(hint_session) or {}).get("metadata") or {}).get("project_id") or None
        project = self.projects.get(project_id) if project_id else None
        if project_id and project is None:
            return web.json_response({"error": f"Project not found: {project_id}"}, status=404)
        if project and project.get("team") and target.id not in project["team"]:
            return web.json_response({"error": f"{target.id} is not on project {project['name']}'s team"}, status=403)
        workspace = project["root"] if project else (str(body.get("workspace") or "").strip() or None)
        if workspace and not os.path.isabs(workspace):
            return web.json_response({"error": "workspace must be an absolute path"}, status=400)
        limits = dict(project["limits"]) if project else default_limits()
        timeout_s = max(1, min(timeout_s, int(limits["child_timeout_s"])))
        approved_by = None
        if require_approval and not reply_parent and project and (project.get("grants") or {}).get("handoffs"):
            # The owner approved this team when creating the project.
            require_approval = False
            approved_by = "project_grant"

        if delegate_mode:
            allowed_tools = self._delegate_tool_grant(body.get("lead_allowed_tools"), allowed_tools)
            if not workspace and hint_session:
                workspace = str(((self.store.get_session(hint_session) or {}).get("workspace")) or "").strip() or None
            timeout_s = min(timeout_s, int(body.get("timeout_seconds") or 0) or _collab_timeout())

        # Preserve the authenticated actor and a durable bridge root across
        # approval/restart; a child must not become an internal owner turn.
        from jaeger_ai.features.agent_bridge.delegation import prepare_handoff
        from jaeger_ai.features.agent_bridge.service import BridgeError
        actor = current_request_actor()
        try:
            bridge_origin, allowed_tools = prepare_handoff(
                self, actor, body, workspace, allowed_tools,
            )
        except (BridgeError, PermissionError) as exc:
            return web.json_response({"error": str(exc)}, status=403)
        if bridge_origin is not None:
            require_approval = True
            approved_by = None
            parent_session = self.store.get_session(str(body.get("session_id") or "")) or {}
            parent_meta = parent_session.get("metadata") or {}
            parent_handoff = (self.store.get_handoff(parent_meta["handoff_id"])
                              if parent_meta.get("handoff_id") else None)
            # Root goals cannot forge a chain through editable session metadata.
            is_root = parent_run_id == bridge_origin["request_id"]
            parent_chain = ([] if is_root else list(
                ((parent_handoff or {}).get("metadata") or {}).get("parent_chain") or []
            ))
            depth = len(parent_chain)
            from_id = "native:jaeger" if is_root else str(parent_meta.get("agent_id") or "")

        model_choice=None
        if requested_model and not target.disabled and self.store.get_handoff_by_request(request_id) is None:
            try:model_choice=await asyncio.to_thread(self._session_model_choice,requested_model)
            except Exception:
                return web.json_response({'error':'Model availability could not be established; no handoff admitted','admitted':False},status=503)
        # Re-read after discovery yields, before synchronous admission. Concurrent
        # duplicate callers cannot both create children for the same request ID.
        from .handoff_ownership import parent_context
        parent=parent_context(self,parent_run_id,hint_session,actor)
        existing = self.store.get_handoff_by_request(request_id)
        if parent and (existing is None or (existing.get('metadata') or {}).get('parent_binding')):
            from_id=parent['binding']['source_agent_id']
            parent_run_id=parent['binding']['request_id']
            parent_chain=parent['parent_chain']
            depth=len(parent_chain)
        if existing:
            prior = existing.get("metadata") or {}
            if (existing["task"] != task or existing["to_agent_id"] != target.id
                or existing["from_agent_id"] != from_id
                or existing.get("parent_run_id") != parent_run_id
                or existing["require_approval"] != require_approval
                or prior.get("permitted_context", "") != permitted_context
                or ("caller_actor" in prior and prior["caller_actor"] != actor)
                or prior.get("bridge_origin") != bridge_origin
                or (bridge_origin is not None and prior.get("workspace") != workspace)
                or sorted(prior.get("allowed_tools") or []) != sorted(allowed_tools)
                or prior.get("requested_model") != requested_model
                or prior.get("timeout_seconds", 120) != timeout_s
                or prior.get("reply_to_handoff_id") != (reply_parent["id"] if reply_parent else None)):
                return web.json_response(
                    {"error": "Request identity was already used for different input"},
                    status=409,
                )
            return web.json_response(existing, status=200)

        if parent and (parent['root']['status'] in {'cancelling','cancelled','execution_unknown','failed'} or self._cancellations.is_cancelled(parent['root']['request_id'])):
            return web.json_response({'error':'Parent request is stopped or uncertain; no new child admitted'},status=409)
        if target.disabled:
            return web.json_response({"error":"Specialist is disabled; no new handoff admitted"},status=403)
        if requested_model and model_choice is None:
            return web.json_response({'error':'Selected handoff model is not available in the current configured catalog'},status=400)
        if delegate_mode:
            cap_error = self._delegate_cap_error(hint_session, parent_run_id, depth, parent_chain)
            if cap_error:
                return web.json_response({"error": cap_error, "ok": False, "status": "rejected"}, status=409)
        from jaeger_ai.core.agent_registry.specialist_runtime import check_delegation_limits
        limit_error = check_delegation_limits(
            from_agent_id=from_id,
            to_agent_id=target.id,
            parent_chain=parent_chain,
            depth=depth,
            active_children=self.store.count_active_handoffs(parent_run_id=str(parent_run_id) if parent_run_id else None),
            max_depth=int(limits["max_depth"]),
            max_fanout=int(limits["max_fanout"]),
        )
        if limit_error:
            return web.json_response({"error": limit_error, "ok": False, "status": "rejected"}, status=409)

        approval_id = f"approval_{uuid.uuid4().hex[:12]}" if require_approval else None
        handoff_id = f"handoff_{uuid.uuid4().hex[:12]}"
        origin_session = str(body.get("session_id") or "").strip() or None
        if origin_session is None and parent:origin_session=parent['binding']['session_id']
        if origin_session is None and parent_run_id:
            parent_row = (self.store.get_request(str(parent_run_id))
                          or self.store.get_request_by_turn(str(parent_run_id)))
            origin_session = (parent_row or {}).get("session_id")
        record = {
            "id": handoff_id,
            "session_id": origin_session,
            "request_id": request_id,
            "from_agent_id": from_id,
            "to_agent_id": target.id,
            "parent_run_id": parent_run_id,
            "child_run_id": None,
            "task": task,
            "status": "pending_approval" if require_approval else "admitted",
            "require_approval": require_approval,
            "approval_id": approval_id,
            "result": {},
            "metadata": {
                "task_id": str(body.get("task_id") or "").strip()[:128] or None,  # G5
                # The asking tool call: the Process view nests this agent under it.
                "call_id": self._activity_call_id(str(body.get("call_id") or "").strip()[:128] or None, parent_run_id),
                "collaboration": "delegate" if delegate_mode else "handoff",
                "collaboration_mode": collab_mode,
                "via": str(body.get("via") or ("delegate" if delegate_mode else "handoff"))[:32],
                "delegate_context": str(body.get("context") or "")[:8000] if delegate_mode else None,
                "reply_to_handoff_id": reply_parent["id"] if reply_parent else None,
                "thread_handoff_id": ((reply_parent.get("metadata") or {}).get("thread_handoff_id") or reply_parent["id"]) if reply_parent else handoff_id,
                "caller_actor": actor,
                "parent_binding": parent['binding'] if parent else None,
                "parent_binding_state": 'qualified' if parent else 'unqualified' if parent_run_id else 'independent',
                "bridge_origin": bridge_origin,
                "requested_model": requested_model,
                "model_choice": model_choice,
                "background": True,
                "permission_mode": "inherit",
                "target_display": target.display_name,
                "target_role": (target.metadata or {}).get("role"),
                "specialty": (target.metadata or {}).get("specialty"),
                "permitted_context": permitted_context,
                "allowed_tools": list(allowed_tools),
                **_handoff_tool_scope(target, allowed_tools),
                "timeout_seconds": timeout_s,
                "parent_chain": [*parent_chain, from_id],
                "delegation_depth": depth + 1,
                "project_id": project["id"] if project else None,
                "project_name": project["name"] if project else None,
                "workspace": workspace,
                "max_child_timeout_s": int(limits["child_timeout_s"]),
                "approved_by": approved_by,
                "wake_lead": bool(body.get("wake_lead", project is not None)),
            },
        }
        saved = self.store.save_handoff(record)
        if require_approval and approval_id:
            approval_prompt=f"Allow handoff to {target.display_name}"+(f" using requested model {requested_model}" if requested_model else "")+"?"
            self.store.create_approval(
                approval_id=approval_id,
                kind="handoff",
                session_id=origin_session,
                prompt=approval_prompt,
                options=["once", "deny"],
                request_id=request_id,
                metadata={"handoff_id": handoff_id, "to_agent_id": target.id},
            )
            loop = asyncio.get_running_loop()
            self.pending_approvals[approval_id] = loop.create_future()
            request_payload = {
                "approval_id": approval_id,
                "handoff_id": handoff_id,
                "kind": "handoff",
                "agent_id": from_id,  # the agent asking (Agents tab G1)
                "from_agent_id": from_id,
                "to_agent_id": target.id,
                "task": task,
                "options": ["once", "deny"],
                "prompt": approval_prompt,
            }
            self.event_bus.publish("*", "approval.request", request_payload)
            origin = self._origin_turn(saved)
            if origin:
                # The approval card shows in the chat that asked for the handoff.
                self.event_bus.publish(origin[0], "approval.request", {
                    **request_payload, "title": f"Hand off to {target.display_name}?",
                    "prompt": task, "request_id": origin[1],
                })
        else:
            self._running_tasks[request_id] = asyncio.create_task(self._execute_handoff(handoff_id))
        self._publish_handoff("agent.handoff", saved)
        return web.json_response(saved, status=202 if require_approval else 200)

    def _publish_delegate(self, event: str, record: dict[str, Any]) -> None:
        """An inner helper's lifecycle (one-mind collaboration).

        Globally it is still a handoff row (Team page / Inner workings list it).
        On the chat that asked, it is a ``delegate.started`` /
        ``delegate.finished`` / ``delegate.failed`` span under the asking tool
        call — the Process view draws it as a helper node. Nothing is posted to
        the chat transcript or the helper's home chat, no ``agent.message`` is
        emitted and no backlog task is created: the lead answers in one voice."""
        self.event_bus.publish("*", event, {"handoff": record})
        meta = record.get("metadata") or {}
        result = record.get("result") or {}
        rmeta = result.get("metadata") or {}
        status = str(record.get("status") or "")
        finished = event == "agent.handoff.finished"
        name = "delegate.started" if not finished else (
            "delegate.finished" if status == "completed" else "delegate.failed")
        hid = str(record.get("id") or "")
        emitted = self.__dict__.setdefault("_delegate_terminal_emitted", set())
        if finished:
            # Exactly one terminal span per helper, whichever path ends it
            # (executor, cancel cascade, Stop, restart recovery).
            if hid in emitted:
                return
            emitted.add(hid)
            if len(emitted) > 5000:
                emitted.clear()
        elif hid in emitted:
            return  # a late "started" after the terminal event would reopen the node
        origin = self._origin_turn(record)
        if not origin:
            return
        call_id = meta.get("call_id")
        payload: dict[str, Any] = {
            "request_id": origin[1], "handoff_id": record.get("id"), "subagent_id": record.get("id"),
            "agent_id": record.get("to_agent_id"), "agent_name": meta.get("target_display"),
            "profile": meta.get("target_display") or record.get("to_agent_id"),
            "from_agent_id": record.get("from_agent_id"), "status": status, "call_id": call_id,
            "parent_step_id": self._step_for_call(origin[0], call_id),
            "parent_span_id": f"tool:{call_id}" if call_id else f"run:{origin[1]}",
            "brief": str(record.get("task") or "")[:500],
            "tools": [t for t in (meta.get("effective_tools") or meta.get("allowed_tools") or [])
                      if t != "__helper_no_tools__"][:60],
            "collaboration_mode": meta.get("collaboration_mode"), "via": meta.get("via"),
        }
        if finished:
            tokens = rmeta.get("tokens") if isinstance(rmeta.get("tokens"), dict) else None
            timing = getattr(self, "_turn_timings", {}).get(origin[1])
            if timing is not None and hasattr(timing, "helper_done"):
                timing.helper_done(hid, tokens, status)
            started = record.get("created_at")
            payload.update({
                "ok": status == "completed", "summary": str(result.get("summary") or "")[:4000],
                "tokens": tokens, "cost_usd": (tokens or {}).get("cost_usd"),
                "result_path": rmeta.get("result_path"),
                "duration_ms": int((time.time() - float(started)) * 1000) if isinstance(started, (int, float)) else None,
            })
            if status != "completed":
                payload["error"] = str(result.get("summary") or status)[:1000]
        self.event_bus.publish(origin[0], name, payload)

    async def _execute_handoff(self, handoff_id: str) -> None:
        record = self.store.get_handoff(handoff_id)
        if record is None:
            return
        if record["status"] not in {"admitted", "approved"}:
            return
        try:
            target_record=self._registry().get_agent(record["to_agent_id"])
            if target_record is None or target_record.disabled:
                raise ValueError("Specialist unavailable or disabled; no child started")
            self.store.save_handoff({**record, "status": "running"})
            from jaeger_agent.cognition.runs import InMemoryRunStore
            from jaeger_agent.delegates.contracts import DelegateRequest
            from jaeger_agent.delegates.executor import DelegateExecutor, DelegateExecutionError
            from jaeger_agent.delegates.registry import DelegateRegistry
            from jaeger_ai.core.agent_registry.specialist_runtime import (
                NativeSpecialistRuntime, bounded_prompt, DEFAULT_TIMEOUT_S,
            )

            meta = dict(record.get("metadata") or {})
            registry = self._registry()
            target = registry.get_agent(record["to_agent_id"])
            display = getattr(target, "display_name", None) or record["to_agent_id"]
            specialty = meta.get("specialty") or (getattr(target, "metadata", None) or {}).get("specialty") or display
            allowed = meta.get("allowed_tools") or []
            is_helper = meta.get("collaboration") == "delegate"
            if is_helper:
                from jaeger_ai.core.agent_registry.specialists import expand_tool_patterns, specialist_tools
                from jaeger_ai.core.runtime.collaboration import helper_prompt, memory_excerpt, scrub_excerpt
                try:
                    excerpt = await asyncio.wait_for(asyncio.to_thread(memory_excerpt, record["task"]), timeout=8)
                except Exception:  # noqa: BLE001 — a helper still runs from its brief alone
                    excerpt = ""
                profile_tools = specialist_tools(target)
                shown = [t for t in allowed if t != "__helper_no_tools__"]
                if profile_tools:
                    shown = [t for t in expand_tool_patterns(profile_tools, set(shown)) if t in set(shown)]
                prompt = helper_prompt(
                    display_name=str(display), specialty=str(specialty), brief=record["task"],
                    context=str(meta.get("delegate_context") or meta.get("permitted_context") or ""),
                    memory_excerpt=scrub_excerpt(excerpt), tools=shown,
                    workspace=meta.get("workspace") or None,
                )
            else:
                prompt = bounded_prompt(
                    display_name=str(display),
                    specialty=str(specialty),
                    task=record["task"],
                    permitted_context=str(meta.get("permitted_context") or ""),
                    allowed_tools=frozenset(str(x) for x in allowed) if allowed else None,
                    workspace=meta.get("workspace") or None,
                    project_name=meta.get("project_name") or None,
                )
            timeout = int(meta.get("timeout_seconds") or DEFAULT_TIMEOUT_S)
            runs = InMemoryRunStore()
            child = runs.create(
                f"handoff:{record['id']}",
                owner_pid=os.getpid(),
                payload={"handoff_id": record["id"], "to_agent_id": record["to_agent_id"]},
                parent_run_id=None,
                relation="delegate",
            )
            running = self.store.save_handoff({**record, "status": "running", "child_run_id": child.id})
            if is_helper:
                # An inner helper's brief is not a chat message anywhere.
                self._publish_handoff("agent.handoff", running)
            else:
                self._post_handoff_request(record)
            runtime = NativeSpecialistRuntime(self._specialist_chat)
            delegates = DelegateRegistry()
            delegates.register(runtime, replace=True)
            executor = DelegateExecutor(delegates, runs)
            request = DelegateRequest(
                task_id=child.id,
                prompt=prompt,
                parent_task_id=str(record.get("parent_run_id") or "") or None,
                timeout_seconds=max(1, timeout),
                idempotency_key=str(record.get("request_id") or record["id"]),
                allowed_tools=frozenset(str(x) for x in allowed),
                metadata={
                    "to_agent_id": record["to_agent_id"],
                    "handoff_id": record["id"],
                    "from_agent_id": record["from_agent_id"],
                    "max_child_timeout_s": int(meta.get("max_child_timeout_s") or 1800),
                    "chat_kwargs": {
                        "workspace": meta.get("workspace") or None,
                        "agent_id": record["to_agent_id"],
                        "project_id": meta.get("project_id") or None,
                        "parent_session_id": record.get("session_id"),
                        "handoff_id": record["id"],
                    },
                },
            )
            result = await executor.execute(runtime.runtime_id, request)
            status = "execution_unknown" if result.metadata.get("execution_unknown") else result.status
            from .handoff_ownership import child_receipt
            current=self.store.get_handoff(handoff_id) or record
            _,_,canonical,bound=child_receipt(self,current)
            summary=result.summary;result_meta=dict(result.metadata)
            if canonical is not None and bound:
                status=canonical['status'] if canonical['status'] in {'completed','failed','cancelled'} else 'execution_unknown'
                actual=canonical.get('result') or {}
                summary=actual.get('output') or actual.get('error') or summary
                result_meta.update(execution_unknown=status=='execution_unknown',gateway_request_id=canonical['request_id'],confirmation_scope='canonical_child_request')
            elif canonical is not None:
                status='execution_unknown';summary='Retained child identity is unqualified; outcome remains unknown'
                result_meta={'execution_unknown':True,'confirmation_scope':'unqualified_child'}
            elif canonical is None and (current.get('metadata') or {}).get('cancel_requested'):
                status='cancelled';summary='Cancelled before child admission; no child execution started'
                result_meta.update(execution_unknown=False,cancellation_confirmed=True,confirmation_scope='pre_admission')
                record={**record,'metadata':{**(record.get('metadata') or {}),'cancelled_before_admission':True}}
            elif current.get('status')=='cancelled':status='cancelled'
            ok = status == "completed"
            result_path = None
            if is_helper:
                result_meta["tokens"] = self._helper_usage(result.worker_session_id)
                result_path = self._store_helper_output(record["id"], str(summary or ""))
                if result_path:
                    result_meta["result_path"] = result_path
            saved = self.store.save_handoff({
                **record,
                "status": status,
                "child_run_id": child.id,
                "result": {
                    "ok": ok,
                    "status": status,
                    "summary": summary,
                    "evidence": list(result.evidence),
                    "metadata": result_meta,
                    "worker_session_id": result.worker_session_id,
                },
            })
            self._publish_handoff("agent.handoff.finished", saved)
        except asyncio.CancelledError:
            # Stop / parent cancel cancels this task. Without this branch the
            # row stayed "running" forever and no delegate.finished/failed
            # was ever emitted (live: 4 delegate.started, 2 finished).
            current = self.store.get_handoff(handoff_id) or record
            if current.get("status") not in {"completed", "failed", "cancelled", "denied", "execution_unknown"}:
                saved = self.store.save_handoff({
                    **current, "status": "cancelled",
                    "result": {"ok": False, "status": "cancelled", "summary": "Stopped before the helper finished",
                               "metadata": {"cancellation_confirmed": True, "confirmation_scope": "task_cancelled"}},
                })
                self._publish_handoff("agent.handoff.finished", saved)
            raise
        except Exception as exc:  # noqa: BLE001 — specialist failure must not kill the gateway
            logger.exception("specialist handoff failed: %s", exc)
            saved = self.store.save_handoff({
                **record,
                "status": "failed",
                "result": {"ok": False, "status": "failed", "summary": f"{type(exc).__name__}: {exc}"},
            })
            self._publish_handoff("agent.handoff.finished", saved)
        finally:
            self._running_tasks.pop(record.get("request_id") or handoff_id, None)

    async def _specialist_chat(self, session_id: str, text: str, *, request_id: str,
                               allowed_tools: list[str] | None = None,
                               workspace: str | None = None, agent_id: str | None = None,
                               project_id: str | None = None, parent_session_id: str | None = None,
                               handoff_id: str | None = None) -> tuple[str, str]:
        """Run a handoff child as a real Gateway turn in this process.

        It used to relay to the native MCP server on :8792, which is a
        different process (on a test gateway, the live one). The child is now
        an admitted request on its own session, executed by the same
        ``_execute_turn`` path as a chat turn: the specialist's standing tools
        (``allowed_tools=None``) or the granted subset, its own skills, its
        notes, the project root as the bound workspace, approvals parked on
        that child turn, and a durable receipt in client_requests."""
        from jaeger_ai.contract.handoffs import child_request_id
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_agent

        child_rid = child_request_id(request_id)
        current_handoff=self.store.get_handoff(handoff_id) if handoff_id else None
        if (current_handoff or {}).get('metadata',{}).get('cancel_requested') or (current_handoff or {}).get('status')=='cancelled':
            raise ValueError('Handoff cancelled before child admission')
        target_record=self._registry().get_agent(agent_id or specialist_agent(session_id) or '')
        if target_record is not None and target_record.disabled:
            raise ValueError('Specialist disabled; no new child admission')
        meta = {
            "agent_id": agent_id or specialist_agent(session_id), "agent_pinned": True,
            "route_checked": True, "handoff_child": True, "handoff_id": handoff_id,
            "parent_session_id": parent_session_id, "project_id": project_id,
        }
        self.store.ensure_session(
            session_id, title=f"Handoff {handoff_id}" if handoff_id else "Specialist task",
            profile="jaeger", workspace=workspace or "",
            metadata={k: v for k, v in meta.items() if v is not None},
        )
        requested: dict[str, Any] = {"interaction_tier": self._current_tier(), "is_subordinate": True}
        # Approved handoffs execute later, often in an owner's HTTP context.
        # Identity comes from durable admission, never from that later context.
        handoff = self.store.get_handoff(handoff_id) if handoff_id else None
        if handoff is not None:
            handoff_meta=handoff.get('metadata') or {}
            requested["caller"] = handoff_meta.get("caller_actor")
            choice=handoff_meta.get('model_choice')
            if choice is not None:
                if not isinstance(choice,dict) or set(choice)!={'model','provider'} or any(not isinstance(v,str) or not v for v in choice.values()):
                    raise ValueError('Retained handoff model choice is malformed; no new turn admitted')
                requested.update(choice)
        if allowed_tools is not None:
            requested["allowed_tools"] = list(allowed_tools)
        if workspace:
            requested["workspace"] = workspace
        revision=await self._turn_model_revision(session_id,requested,child_rid) if requested.get('model') else None
        current_handoff=self.store.get_handoff(handoff_id) if handoff_id else None
        binding=((current_handoff or {}).get('metadata') or {}).get('parent_binding')
        parent_row=self.store.get_request(binding['request_id']) if binding else None
        if (current_handoff or {}).get('metadata',{}).get('cancel_requested') or (current_handoff or {}).get('status')=='cancelled':
            raise ValueError('Handoff cancelled before child admission')
        if parent_row and (parent_row['status'] in {'cancelling','cancelled','execution_unknown','failed'} or self._cancellations.is_cancelled(parent_row['request_id'])):
            raise ValueError('Parent request stopped or uncertain; no child admission')
        admitted = self.store.admit_request(session_id, text, request_id=child_rid, requested=requested,expected_model_revision=revision)
        mirror = getattr(self, "team_mirror", None)
        origin = self._origin_turn(current_handoff) if (mirror is not None and current_handoff) else None
        if origin:
            mirror.bind(session_id, origin[0], origin[1], current_handoff["id"])
        try:
            self._start_admitted_turn(admitted, session_id, text)
            rid = admitted["request_id"]
            task = self._running_tasks.get(rid)
            if task is not None:
                await task
        finally:
            if origin:
                mirror.unbind(session_id)
        row = self.store.get_request(rid) or {}
        result = row.get("result") or {}
        if row.get("status") != "completed":
            raise RuntimeError(f"specialist turn {row.get('status')}: {result.get('error') or 'no result'}")
        return str(result.get("output") or ""), f"{result.get('backend') or 'owner-react'}:{result.get('model') or ''}"
