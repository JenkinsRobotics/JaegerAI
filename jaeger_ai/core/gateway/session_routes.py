"""Extracted Gateway session, queue, topic, clarify & attachment routes mixin (Wave 3)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

from jaeger_ai.contract.sessions import normalise_surface
from .session_store import RequestBusy, RequestConflict, StateConflict

logger = logging.getLogger("jaeger.gateway")


def _server_attr(name: str) -> Any:
    from . import server as _server
    return getattr(_server, name)


class GatewaySessionRoutesMixin:
    """Session CRUD, turn admission, queue, topics, clarify and attachments for JaegerGatewayApp."""

    async def handle_list_topics(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        include = request.query.get("include_archived") in {"1", "true", "yes"}
        return web.json_response({"session_id": session_id, "topics": self.store.list_topics(session_id, include_archived=include)})

    async def handle_create_topic(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        from jaeger_ai.core.gateway.session_topics import start_new_topic
        topic = await asyncio.to_thread(start_new_topic, self.store, session_id, event_bus=self.event_bus)
        return web.json_response({"session_id": session_id, "topic": topic}, status=201)

    async def handle_home_new_topic(self, request: web.Request) -> web.Response:
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        canonical = str(getattr(record, "id", None) or agent_id)
        sid, created = self._ensure_agent_home(canonical, getattr(record, "display_name", None) or "Jaeger")
        from jaeger_ai.core.gateway.session_topics import start_new_topic
        topic = await asyncio.to_thread(start_new_topic, self.store, sid, event_bus=self.event_bus)
        return web.json_response({"session_id": sid, "agent_id": canonical, "created": created, "topic": topic}, status=201)

    async def handle_patch_topic(self, request: web.Request) -> web.Response:
        topic_id = request.match_info["topic_id"]
        if topic_id.startswith("topic:"):
            topic_id = topic_id[6:]
        topic = self.store.get_topic(topic_id)
        if topic is None:
            return web.json_response({"error": "Topic not found"}, status=404)
        body = await request.json()
        if not isinstance(body, dict):
            return web.json_response({"error": "JSON object required"}, status=400)
        kwargs = {}
        meta = {}
        if "title" in body:
            title = str(body.get("title") or "").strip()
            if not title:
                return web.json_response({"error": "Title required"}, status=400)
            kwargs["title"] = title[:200]
            kwargs["title_source"] = "user"
        if "archived" in body:
            kwargs["archived"] = bool(body["archived"])
        if "pinned" in body:
            meta["pinned"] = bool(body["pinned"])
        if "project_id" in body:
            meta["project_id"] = body["project_id"]
        if meta:
            kwargs["metadata"] = meta
        updated = self.store.update_topic(topic_id, **kwargs) if kwargs else topic
        self.event_bus.publish(topic["session_id"], "session.updated", {"session_id": topic["session_id"], "topic": updated})
        return web.json_response({"topic": updated})

    async def handle_delete_topic(self, request: web.Request) -> web.Response:
        topic_id = request.match_info["topic_id"]
        if topic_id.startswith("topic:"):
            topic_id = topic_id[6:]
        topic = self.store.get_topic(topic_id)
        if topic is None:
            return web.json_response({"error": "Topic not found"}, status=404)
        self.store.delete_topic(topic_id)
        self.event_bus.publish(topic["session_id"], "session.updated", {"session_id": topic["session_id"], "topic_id": topic_id, "deleted": True})
        return web.json_response({"deleted": True, "topic_id": topic_id})

    async def handle_list_messages(self, request: web.Request) -> web.Response:
        """GET /v1/sessions/{id}/messages?before=<message_id>&limit=50 — newest first."""
        session_id = request.match_info["id"]
        try:
            before = int(request.query["before"]) if request.query.get("before") else None
            limit = int(request.query.get("limit") or 50)
        except ValueError:
            return web.json_response({"error": "before and limit must be integers"}, status=400)
        if not 1 <= limit <= 200:
            return web.json_response({"error": "limit must be between 1 and 200"}, status=400)
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        after = until = None
        topic_id = request.query.get("topic")
        if topic_id:
            ident = topic_id[6:] if topic_id.startswith("topic:") else topic_id
            topic = self.store.get_topic(ident)
            if topic is None or topic["session_id"] != session_id:
                return web.json_response({"error": "Topic not found"}, status=404)
            after = int(topic["start_message_id"])
            until = int(topic["end_message_id"]) if topic.get("end_message_id") is not None else None
        return web.json_response(self.store.list_messages(session_id, before=before, limit=limit, after=after, until=until))

    async def handle_upload_attachment(self, request: web.Request) -> web.Response:
        """POST /v1/sessions/{id}/attachments/upload — stage bytes gateway-side.

        multipart ``file`` (+ ``name``) or JSON ``{name, mime, data_base64}``.
        25 MB per file (413 over). ``Idempotency-Key`` replays the same attachment.
        Staged uploads join a turn only when its ``attachment_ids`` names them."""
        import base64
        import hashlib
        import mimetypes

        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        idem = (request.headers.get("Idempotency-Key") or "").strip()[:200]
        if idem:
            for row in self.store.list_attachments(session_id):
                if (row.get("metadata") or {}).get("idempotency_key") == idem:
                    return web.json_response({**self._upload_view(row), "replayed": True}, status=201)
        limit = self.UPLOAD_MAX_BYTES
        too_big = web.json_response({"error": f"attachment exceeds {limit // (1024 * 1024)} MB"}, status=413)
        att_id = f"att_{uuid.uuid4().hex[:16]}"
        stage = self._staged_upload_dir(session_id) / att_id
        stage.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = stage / ".upload"
        digest, size = hashlib.sha256(), 0
        name, mime = "", ""
        ctype = request.content_type or ""
        try:
            if ctype.startswith("multipart/"):
                if request.content_length and request.content_length > limit + 1024 * 1024:
                    return too_big
                reader = await request.multipart()
                got_file = False
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == "file" and not got_file:
                        got_file = True
                        name = name or (part.filename or "")
                        mime = part.headers.get("Content-Type", "") or mime
                        with tmp.open("wb") as out:
                            while True:
                                chunk = await part.read_chunk(1024 * 1024)
                                if not chunk:
                                    break
                                size += len(chunk)
                                if size > limit:
                                    return too_big
                                digest.update(chunk)
                                out.write(chunk)
                    elif part.name == "name":
                        name = (await part.text()).strip() or name
                    elif part.name == "mime":
                        mime = (await part.text()).strip() or mime
                if not got_file:
                    return web.json_response({"error": "multipart field 'file' is required"}, status=400)
            elif ctype in {"application/json", ""}:
                cap = limit * 4 // 3 + 64 * 1024
                if request.content_length and request.content_length > cap:
                    return too_big
                raw = await request.content.read(cap + 1)
                if len(raw) > cap:
                    return too_big
                try:
                    body = json.loads(raw or b"{}")
                    data = base64.b64decode(str(body.get("data_base64") or ""), validate=True)
                except (ValueError, TypeError) as exc:
                    return web.json_response({"error": f"invalid JSON upload: {exc}"}, status=400)
                if not data:
                    return web.json_response({"error": "data_base64 is required"}, status=400)
                if len(data) > limit:
                    return too_big
                name, mime = str(body.get("name") or ""), str(body.get("mime") or "")
                size = len(data)
                digest.update(data)
                tmp.write_bytes(data)
            else:
                return web.json_response({"error": "use multipart/form-data or application/json"}, status=415)
            safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name or "upload.bin").name).strip(" .")[:200] or "upload.bin"
            mime = mime or mimetypes.guess_type(safe)[0] or "application/octet-stream"
            final = stage / safe
            tmp.replace(final)
            os.chmod(final, 0o600)
        finally:
            if tmp.exists():
                tmp.unlink()
                try:
                    stage.rmdir()
                except OSError:
                    pass
        row = self.store.add_attachment(session_id, {
            "attachment_id": att_id, "original_filename": safe, "stored_filename": safe,
            "safe_path": str(final), "mime_type": mime, "size_bytes": size,
            "sha256": digest.hexdigest(), "provenance": "upload_staged",
            "metadata": {"staged": True, **({"idempotency_key": idem} if idem else {})},
        })
        self.event_bus.publish(session_id, "attachment.added", {"attachment": row})
        return web.json_response(self._upload_view(row), status=201)

    async def handle_chat_organization(self, request: web.Request) -> web.Response:
        """One organization API for owner clients and the owner agent."""
        from .chat_organization import OrganizationConflict
        owner = self._owner_session_state_allowed(request)
        agent = getattr(self._request_caller(request), 'name', '') == 'jaegerd'
        if not owner and not agent:
            return web.json_response({'error': 'Chat organization belongs to the owner'}, status=403)
        if request.method == 'GET':
            return web.json_response(self.chat_organization.snapshot())
        try:
            body = await request.json()
            if not isinstance(body, dict): raise ValueError('JSON object required')
            action = body.get('action')
            agent_full_auto = False
            if agent and action in ('apply', 'undo'):
                try:
                    from jaeger_ai.core.runtime.autonomy import auto_approves, effective_autonomy
                    agent_full_auto = auto_approves(effective_autonomy(self._config_path()))
                except Exception:
                    agent_full_auto = False
            if not owner and action != 'propose' and not agent_full_auto:
                return web.json_response({'error': 'The agent may propose organization changes; only the owner (or Full Auto) may apply them'}, status=403)
            if action == 'apply':
                result = self.chat_organization.apply(body.get('revision'), body.get('actions'), body.get('operation_id'))
            elif action == 'undo':
                result = self.chat_organization.undo(body.get('operation_id'))
            elif action == 'suggest':
                if self._organization_ai_lock.locked():
                    return web.json_response({'error': 'Suggestions are already being generated. Try again shortly.'}, status=409)
                async with self._organization_ai_lock:
                    result = await asyncio.to_thread(self.chat_organization.suggest, body.get('session_ids'), body.get('instruction', 'Suggest descriptive names and project groups. Preserve manually named chats.'), body.get('rename_manual') is True)
            elif action == 'propose':
                result = self.chat_organization.propose(body.get('actions'), body.get('label', 'Jaeger suggestions'), body.get('revision'))
            elif action == 'dismiss':
                self.chat_organization.dismiss(body.get('proposal_id'))
                result = {'dismissed': True}
            else:
                raise ValueError('Unknown organization action')
            self.event_bus.publish('*', 'chat.organization.updated', {'action': action})
            return web.json_response(result)
        except OrganizationConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except (ValueError, TypeError, KeyError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        except Exception:
            logger.exception('Chat organization failed')
            return web.json_response({'error': 'Could not complete this organization action. No AI suggestions were applied.'}, status=503)

    async def handle_list_sessions(self, request: web.Request) -> web.Response:
        profile = request.query.get("profile")
        sessions = self.store.list_sessions(profile=profile, query=request.query.get("q"),
                                            agent_id=(request.query.get("agent_id") or "").strip() or None)
        return web.json_response({"sessions": sessions})

    async def handle_operator_session_state(self, request: web.Request) -> web.Response:
        """GET/PATCH the one active conversation shared across owner devices."""
        if not self._owner_session_state_allowed(request):
            return web.json_response({"error": "Owner access required"}, status=403)
        if request.method == "GET":
            return web.json_response(self.store.active_session_state())
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        allowed = {"active_session_id", "surface", "expected_revision"}
        if not isinstance(body, dict) or "active_session_id" not in body or set(body) - allowed:
            return web.json_response({
                "error": "active_session_id is required; only surface and expected_revision are optional",
            }, status=400)
        session_id = body["active_session_id"]
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            return web.json_response({"error": "active_session_id must be a non-empty string or null"}, status=400)
        session_id = session_id.strip() if isinstance(session_id, str) else None
        surface = body.get("surface")
        if surface is not None and (not isinstance(surface, str) or not surface.strip() or len(surface) > 64):
            return web.json_response({"error": "surface must be 1-64 characters or null"}, status=400)
        expected = body.get("expected_revision")
        if expected is not None and (type(expected) is not int or expected < 0):
            return web.json_response({"error": "expected_revision must be a non-negative integer"}, status=400)
        try:
            state = self.store.save_active_session(
                session_id,
                actor=str(request["caller_actor"]),
                surface=surface.strip() if isinstance(surface, str) else None,
                expected_revision=expected,
            )
        except ValueError:
            return web.json_response({"error": "Session not found"}, status=404)
        except StateConflict as exc:
            return web.json_response({
                "error": str(exc),
                "state": self.store.active_session_state(),
            }, status=409)
        self._last_human_session = session_id or "desktop-app"
        self.event_bus.publish("*", "session.active.changed", {"state": state})
        return web.json_response(state)

    async def handle_create_session(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        # The Gateway owns the session namespace, but an explicitly supplied
        # id is honored: durable contracts (task replay, cross-client
        # continuation, restart recovery) address the SAME session row after
        # a Gateway restart, and `ensure_session` is idempotent, so a stable
        # client-supplied id is one row, never a second store.
        session_id = str(body.get("session_id") or "").strip() or uuid.uuid4().hex
        caller = request.get("caller")
        prefix = getattr(caller, "session_prefix", None)
        if prefix and not body.get("session_id"):
            session_id = prefix + session_id
        if prefix and not session_id.startswith(prefix):
            return web.json_response(
                {"error": f"Caller {caller.name!r} may only create sessions starting {prefix!r}"}, status=403,
            )
        title = str(body.get("title") or "New Conversation")
        workspace = str(body.get("workspace") or "")
        metadata = dict(body.get("metadata") or {})
        if body.get("workspace_folder") is not None:
            # The client's open folder (IDE / Mac app) becomes the session's
            # existing ``workspace``: the turn's project_root for file and
            # shell tools and the ide_context fallback. Same field, validated.
            folder, error = self._validate_workspace_folder(body.get("workspace_folder"))
            if error:
                return web.json_response({"error": error, "field": "workspace_folder"}, status=400)
            workspace = folder
            metadata = {**metadata, "workspace_folder": folder}
        # Profile binding is enforced HERE, gateway-side. The client may name a
        # profile; the gateway validates it against the framework registry and
        # stamps it — the id no longer carries the profile, so a client cannot
        # mint a "hermes" session by shaping its id.
        profile = str(body.get("profile") or "").strip()
        if not profile:
            profile = "jaeger"
        from jaeger_ai.contract.frameworks import canonical_runtime, UnknownFramework
        try:
            profile = canonical_runtime(profile)
        except UnknownFramework:
            return web.json_response({"error": f"Unknown profile: {profile}"}, status=400)
        # Record where it was started so the sidebar can split browser from
        # terminal conversations for each framework.
        surface = normalise_surface(body.get("source") or metadata.get("source"))
        if surface and "source" not in metadata:
            metadata = {**metadata, "source": surface}

        metadata = self._bind_requested_agent(body, metadata)
        def _create_session_sync():
            existed = self.store.get_session(session_id) is not None
            sess = self.store.ensure_session(
                session_id,
                title=title,
                profile=profile,
                workspace=workspace,
                metadata=metadata,
            )
            if not existed:
                from jaeger_ai.core.gateway.session_hygiene import archive_on_create
                sess = archive_on_create(self.store, sess)
            return sess

        session = await asyncio.to_thread(_create_session_sync)
        self.event_bus.publish(session_id, "session.created", {"session": session})
        self._activate_owner_session(
            request,
            session_id,
            surface=surface or getattr(self._request_caller(request), "name", None),
        )
        return web.json_response(session, status=201)

    async def handle_get_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        conversation = request.query.get("view") == "conversation"
        def _read_session_sync():
            sess = self.store.get_session(session_id, conversation=True) if conversation else self.store.get_session(session_id)
            if not sess:
                return None, None
            lat = None if conversation else self.store.latest_request(session_id)
            return sess, lat
        session, latest = await asyncio.to_thread(_read_session_sync)
        if not session:
            return web.json_response({"error": "Session not found"}, status=404)
        # Surfaces chrome polls GET without SSE — stamp role/display_name
        # after handoff so the UI can render the active agent identity.
        payload = self._enrich_session_agent(session)
        if conversation:
            return web.json_response(payload)
        # Recovery clients need a scoped control identity even when they did
        # not submit this turn. Do not expose input/output through this field.
        payload["latest_request"] = ({
            key: latest.get(key) for key in (
                "session_id", "request_id", "turn_id", "status", "updated_at", "finished_at",
            )
        } if latest else None)
        if request.query.get("view") == "control":
            return web.json_response({key: payload.get(key) for key in (
                "session_id", "status", "latest_request",
            )})
        if request.query.get("view") == "settings":
            metadata = payload.get("metadata") or {}
            try:
                revision=self.store.model_choice_revision(metadata)
            except ValueError as exc:return web.json_response({'error':str(exc)},status=409)
            return web.json_response({"session_id": session_id, "model": metadata.get("model"), "provider": metadata.get("provider"), "model_choice_revision": revision, "atomic_model_operations": True})
        return web.json_response(payload)

    async def handle_branch_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        keep_count = body.get("keep_count")
        if keep_count is None and body.get("message_id") is not None:
            source = self.store.get_session(session_id)
            try:
                wanted = int(body["message_id"])
                match = next((i for i, row in enumerate(source.get("messages", []))
                              if int(row.get("id", -1)) == wanted), None) if source else None
                if match is not None:
                    keep_count = match + 1
            except (TypeError, ValueError):
                return web.json_response({"error": "message_id must be an integer"}, status=400)
        if keep_count is not None:
            try:
                keep_count = int(keep_count)
            except (TypeError, ValueError):
                return web.json_response({"error": "keep_count must be an integer"}, status=400)
            if keep_count < 0:
                return web.json_response({"error": "keep_count must be non-negative"}, status=400)
        branch = self.store.branch_session(
            session_id,
            title=str(body.get("title") or "").strip() or None,
            keep_count=keep_count,
        )
        if branch is None:
            return web.json_response({"error": "Session not found"}, status=404)
        self.event_bus.publish(session_id, "session.branched", {
            "session_id": branch["session_id"], "parent_session_id": session_id,
        })
        return web.json_response(branch, status=201)

    async def handle_message_read_state(self, request: web.Request) -> web.Response:
        session_id = request.match_info['id']
        try:
            if request.method == 'GET':
                return web.json_response(self.store.message_read_state(session_id))
            body = None
            if request.method == 'POST':
                body = await request.json() if request.can_read_body else {}
                if not isinstance(body, dict):
                    raise ValueError('JSON object required')
            snapshot = self.store.set_message_read_state(session_id, body)
        except KeyError as exc:
            return web.json_response({'error': exc.args[0]}, status=404)
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        event = snapshot.pop('_event', None)
        if event:
            self.event_bus.fanout(event)
        return web.json_response(snapshot)

    async def handle_voice_transcript(self, request: web.Request) -> web.Response:
        """Record one spoken line from a speech-to-speech voice session (Gemini Live).

        The local voice engine sends real turns; a realtime model answers on its
        own, so its transcript is written here to keep the chat complete. The row
        is a plain message with ``meta.voice``; no turn runs."""
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return web.json_response({"error": "JSON object required"}, status=400)
        role, text = body.get("role"), str(body.get("text") or "").strip()
        engine = str(body.get("engine") or "realtime")[:40]
        if role not in {"user", "assistant"} or not text:
            return web.json_response({"error": "role user|assistant and text required"}, status=400)
        meta = {"voice": {"engine": engine, "interrupted": bool(body.get("interrupted"))}}
        message_id = self.store.append_message(session_id, role, text[:8000], meta=meta)
        return web.json_response({"message_id": message_id})

    async def handle_message_feedback(self, request: web.Request) -> web.Response:
        from jaeger_ai.contract.message_feedback import REACTION_EMOJIS
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        if request.method == "GET":
            return web.json_response({"feedback": self.store.message_feedback(session_id), **self.store.message_reactions(session_id), 'allowed_emojis': REACTION_EMOJIS})
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            return web.json_response({'error': 'JSON object required'}, status=400)
        if not isinstance(body, dict):
            return web.json_response({'error': 'JSON object required'}, status=400)
        if isinstance(body, dict) and 'emoji' in body:
            if set(body) != {'request_id', 'role', 'emoji', 'active'} or body['emoji'] not in REACTION_EMOJIS or not isinstance(body['role'], str) or body['role'] not in {'user', 'assistant'} or type(body['active']) is not bool or not isinstance(body['request_id'], str):
                return web.json_response({'error': 'Valid request_id, role, emoji and boolean active required'}, status=400)
            target = self.store.get_request(body['request_id'])
            if target is None or target['session_id'] != session_id:
                return web.json_response({'error': 'Request not found in this conversation'}, status=404)
            snapshot = self.store.set_message_reaction(session_id, target['request_id'], body['role'], body['emoji'], body['active'])
            event = snapshot.pop('_event', None)
            if event:
                self.event_bus.fanout(event)
            return web.json_response({**snapshot, 'allowed_emojis': REACTION_EMOJIS})
        rating = str(body.get("rating") or "").strip().lower()
        if rating not in {"positive", "negative"}:
            return web.json_response({"error": "rating must be positive or negative"}, status=400)
        message_id = body.get("message_id")
        event = self.store.append_event(session_id, "message.feedback", {
            "message_id": message_id, "rating": rating,
            "comment": str(body.get("comment") or "")[:1000],
        })
        self.event_bus.publish(session_id, "message.feedback", event)
        return web.json_response({"ok": True, "feedback": event})

    async def handle_retry_session(self, request: web.Request) -> web.Response:
        """Replay the last completed request with a new durable identity."""
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        previous = self.store.latest_request(session_id)
        if previous is None:
            return web.json_response({"error": "No previous request to retry"}, status=404)
        if previous.get("status") in {"running", "admitted", "cancelling"}:
            return web.json_response({"error": "The previous request is still running"}, status=409)
        body = {
            "text": previous.get("input_text") or "",
            "request_id": uuid.uuid4().hex,
        }
        execution = previous.get("execution") or {}
        for key in ("model", "provider", "workspace", "options", "allowed_tools",
                    "interaction_tier"):
            if key in execution:
                body[key] = execution[key]
        attachments = execution.get("attachments") or []
        if isinstance(attachments, list):
            body["attachment_ids"] = [item.get("attachment_id") for item in attachments
                                       if isinstance(item, dict) and item.get("attachment_id")]
        # Reuse the normal admission and execution path so retry has the same
        # receipts, locking, approvals, and SSE behavior as a new turn.
        # Invoke the shared admission path through a tiny internal dispatch
        # payload instead of duplicating the normal turn handler.
        return await self._admit_and_start_retry(session_id, body, previous["request_id"])

    async def handle_patch_session(self, request: web.Request) -> web.Response:
        """PATCH /v1/sessions/{id} — the one place title, archive state and the
        session's default ``model`` change. ``model`` must be a reachable
        /v1/runtime/models entry (or null to clear); turns use it unless the
        turn names its own model."""
        session_id = request.match_info["id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict) or not body:
            return web.json_response({"error": "Nothing to update"}, status=400)

        title = body.get("title")
        if "title" in body and (not isinstance(title, str) or not title.strip()):
            return web.json_response({"error": "title must be a non-empty string"}, status=400)
        archived = body.get("archived")
        if "archived" in body and not isinstance(archived, bool):
            return web.json_response({"error": "archived must be a boolean"}, status=400)
        model = body.get("model")
        if "model" in body and model is not None and (not isinstance(model, str) or not model.strip()):
            return web.json_response({"error": "model must be a non-empty string or null"}, status=400)

        session = self.store.get_session(session_id)
        if session is None:
            return web.json_response({"error": "Session not found"}, status=404)
        if 'cancel_model_choice' in body:
            try:
                command=body['cancel_model_choice']
                if set(body)!={'cancel_model_choice'} or not isinstance(command,dict) or set(command)!={'model','operation_id','expected_model_revision'}:raise ValueError('Exact original model command required')
                receipt=self.store.cancel_model_choice(session_id,operation_id=command['operation_id'],expected_revision=command['expected_model_revision'],actor=request['caller_actor'],requested_model=command['model'])
                return web.json_response(receipt) # Cancellation readback can be a prior committed success.
            except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)
        modern = 'operation_id' in body or 'expected_model_revision' in body
        if modern:
            if set(body)!={'model','operation_id','expected_model_revision'}:
                return web.json_response({'error':'Versioned model command cannot change other session fields'},status=400)
            # Resolve through existing provider inventory; no credentials/configuration edits.
            try:
                previous=self.store.model_choice_operation(session_id,operation_id=body['operation_id'],expected_revision=body['expected_model_revision'],actor=request['caller_actor'],requested_model=model)
                if previous is not None:return web.json_response(previous,status=previous['http_status'])
                try:
                    choice={'model':None,'provider':None} if model is None else await asyncio.to_thread(self._session_model_choice,model.strip())
                except Exception:
                    choice=None  # No metadata effect; commit an explicit rejection receipt.
                receipt=self.store.save_model_choice(session_id,choice,operation_id=body['operation_id'],expected_revision=body['expected_model_revision'],actor=request['caller_actor'],requested_model=model)
            except (ValueError,TypeError) as exc:return web.json_response({'error':str(exc)},status=409)
            if receipt['ok']:
                self.event_bus.publish(session_id,'session.updated',{'session':self.store.get_session(session_id)})
            return web.json_response(receipt,status=receipt['http_status'])
        if "model" in body:
            if model is None:
                choice = {"model": None, "provider": None}
            else:
                choice = await asyncio.to_thread(self._session_model_choice, model.strip())
                if choice is None:
                    return web.json_response(
                        {"error": f"Unknown or unreachable model {model.strip()!r} (see /v1/runtime/models)"},
                        status=400)
            session = self.store.update_metadata(session_id, choice) or session
        if "title" in body:
            session = self.store.rename_session(session_id, title.strip()[:200])
        if "archived" in body:
            session = self.store.set_session_archived(session_id, archived)
        self.event_bus.publish(session_id, "session.updated", {"session": session})
        return web.json_response(session)

    async def handle_delete_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        active_state = self.store.active_session_state()
        was_active = active_state.get("active_session_id") == session_id
        # Retire owned resources before losing the session needed to address them.
        # A shutdown error leaves the conversation available for a safe retry.
        browser = getattr(self, "browser_runtime", None)
        if browser is not None:
            await browser.close_session(session_id)
        deleted = self.store.delete_session(session_id)
        if not deleted:
            return web.json_response({"error": "Session not found"}, status=404)
        self.event_bus.publish(session_id, "session.deleted", {"session_id": session_id})
        if was_active and self._owner_session_state_allowed(request):
            try:
                state = self.store.save_active_session(
                    None,
                    actor=str(request["caller_actor"]),
                    surface=getattr(request.get("caller"), "name", None),
                    expected_revision=int(active_state["revision"]),
                )
            except StateConflict:
                # Another device selected a conversation while deletion was
                # in flight. Its newer selection wins and must not be cleared.
                pass
            else:
                self._last_human_session = "desktop-app"
                self.event_bus.publish("*", "session.active.changed", {"state": state})
        return web.json_response({"deleted": True})

    async def handle_session_transfer(self, request: web.Request) -> web.Response:
        """Removed. Jaeger stays the lead; use delegate for a bounded helper run."""
        return web.json_response(
            {"ok": False, "error": "Chat transfer is no longer available. Jaeger stays the lead; use delegate for a helper.",
             "status": "removed"},
            status=410,
        )

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
            # Surfaces: missing agent must be a clean 404 (not 500 / empty body).
            return web.json_response({"error": "Agent not found"}, status=404)
        # Lead ↔ specialist (and runtime) handoffs are all allowed; role is not gated.

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
            # An explicit handoff is the owner's choice: auto-routing never overrides it.
            "agent_pinned": True,
            "routed_by": "owner",
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
        # The same handoff, globally: the sidebar learns an agent now has a
        # direct chat without subscribing to every session (D4).
        self.event_bus.publish("*", "agent.direct_chat", {
            "session_id": session_id,
            "agent_id": target.id,
            "from_agent_id": previous_agent_id,
            "title": updated.get("title"),
            "reason": reason,
        })
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

    async def handle_edit_message(self, request: web.Request) -> web.Response:
        """Switch a user message to another edit version, or admit a new edit."""
        session_id = request.match_info["id"]
        try:
            message_id = int(request.match_info["message_id"])
        except (TypeError, ValueError):
            return web.json_response({"error": "Invalid message id"}, status=400)
        body = await request.json() if request.can_read_body else {}
        if "index" in body and "text" not in body:
            session = self.store.get_session(session_id)
            if session is None:
                return web.json_response({"error": "Session not found"}, status=404)
            if session.get("status") in {"running", "execution_unknown", "cancelling"}:
                return web.json_response({"error": "Stop the current turn before switching versions"}, status=409)
            try:
                updated = self.store.switch_message_version(session_id, message_id, int(body["index"]))
            except (TypeError, ValueError) as exc:
                return web.json_response({"error": str(exc)}, status=400)
            if updated is None:
                return web.json_response({"error": "User message not found"}, status=404)
            return web.json_response(updated)
        text = str(body.get("text") or body.get("input") or "").strip()
        if not text:
            return web.json_response({"error": "Missing turn text"}, status=400)
        request_id = body.get("request_id")
        if request_id is not None:
            request_id = str(request_id).strip() or None
        requested = self._requested_from_body(body)
        try:
            model_revision = await self._turn_model_revision(session_id, requested, request_id)
            timing_admitted_at = time.monotonic()
            admitted = self.store.admit_request(
                session_id, text, request_id=request_id, requested=requested,
                expected_model_revision=model_revision, edit_message_id=message_id,
            )
        except RequestConflict as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except RequestBusy as exc:
            session = self.store.get_session(session_id) or {}
            return web.json_response({"error": str(exc), "session_id": session_id, "status": session.get("status")}, status=409)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if not admitted.get("replayed"):
            admitted["timing_admitted_at"] = timing_admitted_at
        self._activate_owner_session(
            request, session_id,
            surface=body.get("source") or getattr(self._request_caller(request), "name", None),
        )
        if not (admitted.get("execution") or {}).get("options", {}).get("background"):
            self._last_human_at = time.monotonic()
            self._last_human_session = session_id
        self._start_admitted_turn(admitted, session_id, text)
        payload = {
            "session_id": session_id,
            "turn_id": admitted["turn_id"],
            "request_id": admitted["request_id"],
            "status": admitted["status"] if admitted.get("replayed") else "running",
            "replayed": bool(admitted.get("replayed")),
            "message_id": admitted.get("message_id") or message_id,
        }
        if admitted.get("event"):
            payload["start_event_id"] = admitted["event"]["event_id"]
        return web.json_response(payload)

    async def handle_send_turn(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        text = str(body.get("text") or body.get("input") or "").strip()
        if not text:
            return web.json_response({"error": "Missing turn text"}, status=400)
        # Profile binding is enforced gateway-side: a turn may not switch the
        # profile a session was created with. Cross-client continuation
        # (start on the phone, finish in the IDE) works because both clients
        # address the same gateway-owned session id.
        requested_profile = str(body.get("profile") or "").strip()
        if requested_profile:
            session = self.store.get_session(session_id)
            if session is None:
                return web.json_response({"error": "Session not found"}, status=404)
            bound = str(session.get("profile") or "").strip().lower()
            if bound and bound != requested_profile.strip().lower():
                return web.json_response(
                    {"error": f"This conversation belongs to {bound}; start a new chat to talk to {requested_profile}"},
                    status=409,
                )
        request_id = body.get("request_id")
        if request_id is not None:
            request_id = str(request_id).strip() or None

        requested = self._requested_from_body(body)
        from jaeger_ai.core.runtime.cron_turns import apply_cron_turn
        text, requested = apply_cron_turn(
            text, session_id=session_id, requested=requested,
            source=str(((requested.get("options") or {}).get("source") or body.get("source") or "")),
        )
        try:
            model_revision=await self._turn_model_revision(session_id,requested,request_id)
            timing_admitted_at = time.monotonic()
            edit_message_id = body.get("edit_message_id")
            if edit_message_id is not None:
                try:
                    edit_message_id = int(edit_message_id)
                except (TypeError, ValueError) as exc:
                    raise ValueError("edit_message_id must be an integer") from exc
            admitted = self.store.admit_request(
                session_id, text, request_id=request_id, requested=requested,
                expected_model_revision=model_revision,
                edit_message_id=edit_message_id,
            )
        except RequestConflict as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except RequestBusy as exc:
            session = self.store.get_session(session_id) or {}
            return web.json_response(
                {
                    "error": str(exc),
                    "session_id": session_id,
                    "status": session.get("status"),
                    "agent_id": self._session_agent_id(session),
                },
                status=409,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        if not admitted.get("replayed"):
            admitted["timing_admitted_at"] = timing_admitted_at
        self._activate_owner_session(
            request,
            session_id,
            surface=body.get("source") or getattr(self._request_caller(request), "name", None),
        )
        turn_id = admitted["turn_id"]
        rid = admitted["request_id"]
        options = (admitted.get("execution") or {}).get("options") or {}
        if not options.get("background"):
            self._last_human_at = time.monotonic()
            self._last_human_session = session_id
        self._start_admitted_turn(admitted, session_id, text)

        result = admitted.get("result") or {}
        payload = {
            "session_id": session_id,
            "turn_id": turn_id,
            "request_id": rid,
            "status": admitted["status"] if admitted.get("replayed") else "running",
            "replayed": bool(admitted.get("replayed")),
        }
        if result.get("output") is not None:
            payload["output"] = result.get("output")
        if admitted.get("event"):
            # Durable cursor of this turn's turn.start: a client streams
            # ``?last_event_id=<start_event_id - 1>`` to follow just this turn.
            payload["start_event_id"] = admitted["event"]["event_id"]
        if admitted.get("message_id") is not None:
            payload["message_id"] = admitted["message_id"]
        return web.json_response(payload)

    async def handle_get_queue(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        items = self.store.list_queue(session_id)
        return web.json_response({"session_id": session_id, "items": items})

    async def handle_add_queue(self, request: web.Request) -> web.Response:
        """Add Gateway-owned follow-up work for a session."""
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "Missing queue text"}, status=400)
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        requested_profile = str(body.get("profile") or "").strip()
        if requested_profile:
            session = self.store.get_session(session_id) or {}
            bound = str(session.get("profile") or "").strip().lower()
            if bound and bound != requested_profile.strip().lower():
                return web.json_response(
                    {"error": f"This conversation belongs to {bound}; start a new chat to talk to {requested_profile}"},
                    status=409,
                )
        request_id = body.get("request_id")
        if request_id is not None:
            request_id = str(request_id).strip() or None
        requested = self._requested_from_body(body)
        try:
            item = self.store.enqueue_request(
                session_id, text, request_id=request_id, requested=requested,
            )
        except RequestConflict as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except RequestBusy as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        self._activate_owner_session(
            request,
            session_id,
            surface=body.get("source") or getattr(self._request_caller(request), "name", None),
        )

        promoted = self.store.promote_next_queue_item(session_id)
        self._queue_updated(session_id)
        if promoted is not None:
            self._start_admitted_turn(
                promoted, session_id, str(promoted.get("input_text") or ""),
            )
        current_item = self.store.get_request(item['request_id']) or item
        own_promotion = promoted is not None and promoted['request_id'] == item['request_id']
        payload = {
            "session_id": session_id,
            "request_id": item["request_id"],
            "turn_id": current_item.get("turn_id"),
            "status": current_item["status"],
            "queued": current_item['status'] in {'queued', 'paused'},
            "replayed": bool(item.get("replayed")),
        }
        if own_promotion and promoted.get("event"):
            payload["start_event_id"] = promoted["event"]["event_id"]
        return web.json_response(payload, status=202)

    async def handle_update_queue(self, request: web.Request) -> web.Response:
        """Edit text, position, or pause/resume a still-queued item."""
        session_id = request.match_info["id"]
        request_id = request.match_info["request_id"]
        body = await request.json() if request.can_read_body else {}
        fields = {key: body.get(key) for key in ("text", "status", "position") if key in body}
        if not fields:
            return web.json_response({"error": "Nothing to update"}, status=400)
        try:
            updated = self.store.update_queue_item(
                session_id,
                request_id,
                text=fields.get("text"),
                status=fields.get("status"),
                position=fields.get("position"),
                expected_updated_at=body.get('expected_updated_at'),
            )
        except RequestConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if updated is None:
            return web.json_response({"error": "Queued request not found"}, status=404)
        promoted = None
        if fields.get("status") == "queued":
            promoted = self.store.promote_next_queue_item(session_id)
        self._queue_updated(session_id)
        if promoted is not None:
            self._start_admitted_turn(
                promoted, session_id, str(promoted.get("input_text") or ""),
            )
        return web.json_response({
            "session_id": session_id,
            "item": promoted or updated,
            "promoted": promoted is not None,
        })

    async def handle_reorder_queue(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        order = body.get("order")
        if not isinstance(order, list) or not all(isinstance(v, str) for v in order):
            return web.json_response({"error": "order must be a list of request ids"}, status=400)
        try:
            items = self.store.reorder_queue(session_id, order)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        self._queue_updated(session_id)
        return web.json_response({"session_id": session_id, "items": items})

    async def handle_delete_queue(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        request_id = request.match_info["request_id"]
        if not self.store.delete_queue_item(session_id, request_id):
            return web.json_response({"error": "Queued request not found"}, status=404)
        self._queue_updated(session_id)
        return web.json_response({"session_id": session_id, "deleted": True})

    async def handle_file_changes(self, request: web.Request) -> web.Response:
        sid, rid = request.match_info["id"], request.match_info["request_id"]
        row = self.store.get_request(rid)
        if not row or row.get("session_id") != sid:
            return web.json_response({"error": "Request not found"}, status=404)
        if request.method == "POST" and row.get("status") not in {"completed", "failed", "cancelled"}:
            return web.json_response({"error": "Wait for the turn to settle before undoing"}, status=409)
        if request.method == "POST" and any(not task.done() for task in self._running_tasks.values()):
            return web.json_response({"error": "Wait for active Gateway turns to finish before undoing"}, status=409)
        try:
            if self.agent_safety.has_turn(sid, rid):
                # Agent-mode turn with a checkpoint: covers every file the turn
                # touched (tools and shell), not only file-tool edits.
                if request.method == "POST":
                    data = await asyncio.to_thread(self.agent_safety.undo, sid, rid)
                    self.event_bus.publish(sid, "files.changed", {"request_id": rid, **data})
                else:
                    data = await asyncio.to_thread(self.agent_safety.describe, sid, rid)
                return web.json_response(data)
            if request.method == "POST":
                data = await asyncio.to_thread(self.file_changes.undo, sid, rid)
                self.event_bus.publish(sid, "files.changed", {"request_id": rid, **data})
            else:
                data = await asyncio.to_thread(self.file_changes.describe, sid, rid,
                                               contents=request.query.get("contents") == "1")
            return web.json_response(data)
        except (ValueError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    async def handle_agent_worktree(self, request: web.Request) -> web.Response:
        """GET/POST /v1/sessions/{id}/worktree[/apply|/discard] — the chat's agent worktree."""
        sid = request.match_info["id"]
        if self.store.get_session(sid) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        action = request.match_info.get("action")
        try:
            if request.method == "GET":
                data = await asyncio.to_thread(self.agent_safety.worktree_status, sid)
            elif action in {"apply", "discard"}:
                if any(not task.done() for task in self._running_tasks.values()):
                    return web.json_response({"error": "Wait for active turns to finish first"}, status=409)
                data = await asyncio.to_thread(getattr(self.agent_safety, action), sid)
                self.event_bus.publish(sid, "files.changed", {"worktree": data})
            else:
                return web.json_response({"error": "Unknown action"}, status=404)
            return web.json_response(data)
        except (ValueError, OSError, RuntimeError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    def _clarify_sink(self, session_id: str, request_id: str) -> Callable[[str, str, tuple[str, ...]], str]:
        """Interaction sink for an in-process turn: park a revisioned clarify form and wait.

        Runs on the tool's worker thread. Returns the owner's answer, or "" (the
        clarify tool then falls back to its plain-text question) on timeout,
        cancellation or a missing loop. Secret requests are not brokered here.
        """
        def sink(kind: str, prompt: str, options: tuple[str, ...] = ()) -> str:
            loop = getattr(self, "_loop", None)
            question = str(prompt or "").strip()
            if kind == "secret" and question and loop is not None and loop.is_running():
                return self._secret_wait(session_id, request_id, question, options)
            if kind != "clarify" or not question or loop is None or not loop.is_running():
                return ""
            box: dict[str, Any] = {"done": threading.Event(), "answer": "", "row": None}

            def _arm() -> None:
                row = self.store.create_clarify(session_id=session_id, request_id=request_id,
                                                question=question, choices=[str(o) for o in options or ()])
                box["row"] = row
                fut = loop.create_future()
                self.pending_clarify[row["clarify_id"]] = fut
                self.event_bus.publish(session_id, "clarify.request", {
                    "clarify_id": row["clarify_id"], "revision": row["revision"], "question": question,
                    "choices": row["choices"], "session_id": session_id, "request_id": request_id,
                })

                def _done(f: asyncio.Future) -> None:
                    try:
                        box["answer"] = str(f.result() or "")
                    except Exception:
                        box["answer"] = ""
                    box["done"].set()
                fut.add_done_callback(_done)

            loop.call_soon_threadsafe(_arm)
            scope = self._cancellations.get(request_id)
            deadline = time.monotonic() + _server_attr('CLARIFY_WAIT_S')
            outcome = ""
            while not box["done"].wait(timeout=0.05):
                if scope is not None and scope.cancelled:
                    outcome = "cancelled"; break
                if time.monotonic() >= deadline:
                    outcome = "expired"; break
            row = box["row"]
            if outcome and row is not None:
                self.pending_clarify.pop(row["clarify_id"], None)
                if self.store.resolve_clarify(row["clarify_id"], revision=row["revision"], status=outcome):
                    self.event_bus.publish(session_id, "clarify.resolved",
                                           {"clarify_id": row["clarify_id"], "status": outcome})
                return ""
            return box["answer"]
        return sink

    async def handle_list_clarify(self, request: web.Request) -> web.Response:
        """GET /v1/sessions/{id}/clarify → pending forms (reload/reconnect recovery)."""
        sid = request.match_info["id"]
        clarify_id = str(request.query.get("clarify_id") or "").strip()
        if clarify_id:
            form = self.store.get_clarify(clarify_id)
            if not form or form["session_id"] != sid:
                return web.json_response({"error": "Clarify form not found"}, status=404)
            return web.json_response({"form": form})
        include_resolved = request.query.get("include_resolved") == "true"
        return web.json_response({"forms": self.store.list_clarify(sid, pending_only=not include_resolved)})

    async def handle_answer_clarify(self, request: web.Request) -> web.Response:
        """POST /v1/sessions/{id}/clarify/{clarify_id} {revision, response}: resolve exactly once.

        404 unknown/foreign form, 400 bad body, 409 stale revision or already resolved."""
        sid, cid = request.match_info["id"], request.match_info["clarify_id"]
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        row = self.store.get_clarify(cid)
        if not row or row["session_id"] != sid:
            return web.json_response({"error": "Clarify form not found"}, status=404)
        response = str((body or {}).get("response") or "").strip()
        revision = (body or {}).get("revision")
        if not response or not isinstance(revision, int) or isinstance(revision, bool):
            return web.json_response({"error": "revision (int) and a non-empty response are required"}, status=400)
        if row["status"] != "pending":
            return web.json_response({"error": "Clarify form already resolved", "status": row["status"],
                                      "clarify_id": cid, "revision": row["revision"]}, status=409)
        if revision != row["revision"]:
            return web.json_response({"error": "Stale clarify revision", "stale": True,
                                      "clarify_id": cid, "revision": row["revision"]}, status=409)
        settled = self.store.resolve_clarify(cid, revision=revision, status="answered", answer=response)
        if settled is None:
            current = self.store.get_clarify(cid) or {}
            return web.json_response({"error": "Clarify form already resolved", "status": current.get("status"),
                                      "clarify_id": cid, "revision": current.get("revision")}, status=409)
        fut = self.pending_clarify.pop(cid, None)
        if fut is not None and not fut.done():
            fut.set_result(response)
        self.event_bus.publish(sid, "clarify.resolved", {"clarify_id": cid, "status": "answered"})
        return web.json_response({"clarify_id": cid, "revision": revision, "status": "answered",
                                  "delivered": fut is not None})

    async def handle_session_files(self, request: web.Request) -> web.Response:
        session_id = request.match_info['id']
        session = self.store.get_session(session_id)
        if session is None:
            return web.json_response({'error': 'Session not found'}, status=404)
        from .attachment_access import resolve
        rows = []
        media = request.query.get('kind') == 'media'
        next_after = None
        if media:
            query, after = request.query.get('q', ''), request.query.get('after', '')
            if len(query) > 200 or len(after) > 128 or any(ord(c) < 32 for c in query + after):
                return web.json_response({'error': 'Bounded literal media search required'}, status=400)
            candidates, next_after = self.store.search_session_media(session_id, query, after=after)
        else:
            candidates = self.store.list_attachments(session_id)
        for row in candidates:
            reason = None
            try:
                resolve(row, staged_root=self._staged_upload_dir(session_id), workspace=session.get('workspace') or '')
                if row['size_bytes'] > self.UPLOAD_MAX_BYTES:
                    reason = 'Attachment exceeds supported read size'
            except ValueError as exc:
                reason = str(exc)
            rows.append({**self._upload_view(row), 'readable': reason is None, 'unavailable_reason': reason})
        return web.json_response({'session_id': session_id, 'files': rows, 'max_bytes': self.UPLOAD_MAX_BYTES, **({'query': query, 'next_after': next_after, 'source': 'existing_session_attachments', 'licensing': 'not_verified', 'selection_attaches': False} if media else {})})

    async def handle_session_file(self, request: web.Request) -> web.Response:
        session_id = request.match_info['id']
        session = self.store.get_session(session_id)
        rows = self.store.list_attachments(session_id) if session else []
        row = next((r for r in rows if r['attachment_id'] == request.match_info['attachment_id']), None)
        if row is None:
            return web.json_response({'error': 'Session attachment not found'}, status=404)
        return await self._session_file_response(request, row, session)

    async def handle_list_attachments(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        return web.json_response({"attachments": self.store.list_attachments(session_id)})

    async def handle_add_attachment(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        session = self.store.get_session(session_id)
        if session is None:
            return web.json_response({"error": "Session not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        path = Path(str(body.get("safe_path") or body.get("path") or ""))
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.instance.instance import InstanceLayout
            rt_layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            if rt_layout is not None:
                root = rt_layout.workspace_dir.resolve()
            else:
                from jaeger_ai.core.instance.instance import resolve_instance_dir
                root = InstanceLayout(root=resolve_instance_dir()).workspace_dir.resolve()
            resolved = path.resolve()
            session_ws = Path(session["workspace"]).resolve() if session.get("workspace") else None
            valid = resolved.is_relative_to(root) or (session_ws and resolved.is_relative_to(session_ws))
            if not valid:
                return web.json_response({"error": "attachment path escapes workspace"}, status=400)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)
        # The Gateway receives a workspace file reference, not verified client
        # metadata. Freeze the bytes' actual size/hash here for every surface.
        def file_metadata():
            import hashlib

            if not resolved.is_file():
                raise ValueError("attachment must reference an existing regular file")
            digest = hashlib.sha256()
            size = 0
            with resolved.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            return {"safe_path": str(resolved), "size_bytes": size, "sha256": digest.hexdigest()}

        try:
            metadata = await asyncio.to_thread(file_metadata)
        except (OSError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        row = self.store.add_attachment(session_id, {**body, **metadata})
        self.event_bus.publish(session_id, "attachment.added", {"attachment": row})
        return web.json_response(row, status=201)
