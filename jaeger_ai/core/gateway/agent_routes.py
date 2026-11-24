"""Extracted Gateway agent catalog, handoff inbox & project routes mixin (Wave 3)."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web

from . import caller_auth

if TYPE_CHECKING:
    from .server import JaegerGatewayApp

logger = logging.getLogger("jaeger.gateway")


def _server_attr(name: str) -> Any:
    from . import server as _server
    return getattr(_server, name)


class GatewayAgentRoutesMixin:
    """Agent catalog, handoffs, projects and framework grant routes for _server_attr("JaegerGatewayApp")."""

    async def handle_list_frameworks(self, request: web.Request) -> web.Response:
        """Detected agent frameworks (presence and counts only) with the owner's grants."""
        from jaeger_ai.core.frameworks.discovery import detect
        from jaeger_ai.core.frameworks.grants import CAPABILITIES, FrameworkGrants

        now = time.monotonic()
        cached = _server_attr("JaegerGatewayApp")._frameworks_cache
        if cached is None or now - cached[0] > 30 or request.query.get("refresh"):
            _server_attr("JaegerGatewayApp")._frameworks_cache = (now, await asyncio.to_thread(detect))
        grants = FrameworkGrants().all()
        out = []
        for fw in _server_attr("JaegerGatewayApp")._frameworks_cache[1]:
            g = grants.get(fw["id"]) or {}
            out.append({**fw, "grants": {c: bool((g.get(c) or {}).get("granted")) for c in CAPABILITIES}})
        return web.json_response({"frameworks": out, "capabilities": list(CAPABILITIES)})

    async def handle_framework_grant(self, request: web.Request) -> web.Response:
        """Owner grants or revokes one capability for one framework (admin scope)."""
        from jaeger_ai.core.frameworks.discovery import by_id
        from jaeger_ai.core.frameworks.grants import CAPABILITIES, FrameworkGrants

        fid = request.match_info["id"]
        fw = by_id(fid)
        if fw is None:
            return web.json_response({"error": "Unknown framework"}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        cap = str((body or {}).get("capability") or "")
        granted = (body or {}).get("granted")
        if cap not in CAPABILITIES or not isinstance(granted, bool):
            return web.json_response({"error": "capability and boolean granted are required"}, status=400)
        if granted and cap != "delegate" and not fw.readable:
            return web.json_response({"error": f"{fw.name} has no read connector"}, status=400)
        caller = _server_attr('_REQUEST_CALLER').get()
        by = caller[1] if caller else "owner"
        state = FrameworkGrants().set(fid, cap, granted, by=by)
        return web.json_response({"framework": fid, "grants": {c: bool((state.get(c) or {}).get("granted")) for c in CAPABILITIES}})

    async def handle_list_agents(self, request: web.Request) -> web.Response:
        """List JaegerNativeAgent + ThirdPartyAgent for Mac app / WebUI.

        Query: ``?kind=`` and/or ``?role=lead|specialist|runtime``.
        Unfiltered response is the full catalog including ``lead``.
        """
        kind = request.query.get("kind")
        role = request.query.get("role")
        registry = self._registry()
        if kind or role:
            from jaeger_ai.core.agent_registry.registry import with_roster_flags
            agents = [
                with_roster_flags(a)
                for a in registry.list_agents(kind=kind or None, role=role or None)
            ]
            payload: dict[str, Any] = {"agents": self._with_skills(agents)}
            if kind:
                payload["kind"] = kind
            if role:
                payload["role"] = role
            return web.json_response(payload)
        return web.json_response(self._with_skills(registry.to_catalog()))

    async def handle_agent_peers(self, request: web.Request) -> web.Response:
        """Stable identities for resident, app, bridge, and worker agents.

        The caller registry is the authority for authentication, scopes, and
        session namespaces.  This endpoint is its read model, so Grok Bot,
        Muse, Hermes, and future peers cannot drift between bridge and UI
        definitions.
        """
        return web.json_response({
            "contract_version": 1,
            "peers": caller_auth.agent_peer_catalog(),
        })

    async def handle_agent_primary(self, request: web.Request) -> web.Response:
        """Operator presentation default only: never activate or rewrite an agent."""
        from jaeger_ai.core.gateway.agent_presentation import primary_eligible, PresentationConflict
        if request.method == 'GET':
            return web.json_response({'agent_id': self.store.primary_agent_id()})
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'agent_id', 'expected_agent_id'} or any(not isinstance(v, str) or not v for v in body.values()):
                raise ValueError('Canonical agent_id and expected_agent_id are required')
            record = self._registry().get_agent(body['agent_id'])
            if record is None or record.id != body['agent_id']:
                return web.json_response({'error': 'Agent not found'}, status=404)
            from jaeger_ai.core.gateway.agent_presentation import project
            row = project(record.to_dict(), self.store.agent_presentation(), primary_id=self.store.primary_agent_id())
            if not primary_eligible(row):
                return web.json_response({'error': 'Agent is not an exposed native lead/specialist'}, status=409)
            self.store.set_primary_agent(record.id, body['expected_agent_id'])
        except PresentationConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'primary_agent_id': record.id})
        return web.json_response({'agent_id': record.id})

    async def handle_agent_sections(self, request: web.Request) -> web.Response:
        if request.method == 'GET':
            return web.json_response({'sections': self.store.agent_sections()})
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'name'}:
                raise ValueError('Only section name accepted')
            section = self.store.create_agent_section(body['name'])
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'section_id': section['id']})
        return web.json_response(section, status=201)

    async def handle_agent_presentation(self, request: web.Request) -> web.Response:
        """Admin-scoped cosmetic update; never rewrites registry definitions or sessions."""
        from jaeger_ai.core.gateway.agent_presentation import validate_patch, protected, can_rename
        agent_id = request.match_info['id']
        record = self._registry().get_agent(agent_id)
        if record is None or record.id != agent_id:
            return web.json_response({'error': 'Agent not found'}, status=404)
        try:
            patch = validate_patch(await request.json())
            if {'display_name', 'icon_preset'} & patch.keys() and not can_rename(record.to_dict()):
                return web.json_response({'error': 'protected_agent'}, status=409)
            if protected(record.to_dict()) and (patch.get('archived') is True or patch.get('pinned') is True or patch.get('deleted') is True or 'section_id' in patch):
                return web.json_response({'error': 'protected_agent'}, status=409)
            prefs = self.store.patch_agent_presentation(record.id, patch)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'agent_id': record.id, 'presentation': prefs})
        return web.json_response(self._with_skills(record.to_dict()))

    async def handle_agent_pins(self, request: web.Request) -> web.Response:
        """Admin-scoped ordered pins for the existing single local operator."""
        from jaeger_ai.core.gateway.agent_presentation import MAX_AGENT_PINS, protected, PresentationConflict
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'agent_ids', 'expected_agent_ids'}:
                raise ValueError('agent_ids and expected_agent_ids are required; owner/profile is not client-selectable')
            ids = body['agent_ids']
            if not isinstance(ids, list) or len(ids) > MAX_AGENT_PINS or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError(f'agent_ids must be a unique list of at most {MAX_AGENT_PINS} agent IDs')
            for agent_id in ids:
                record = self._registry().get_agent(agent_id)
                if record is None or record.id != agent_id:
                    return web.json_response({'error': 'Agent not found'}, status=404)
                if protected(record.to_dict()):
                    return web.json_response({'error': 'protected_agent'}, status=409)
            self.store.set_agent_pins(ids, body['expected_agent_ids'])
        except PresentationConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'pins': ids})
        return web.json_response({'agent_ids': ids})

    async def handle_agent_message_search(self, request: web.Request) -> web.Response:
        agent_id = request.match_info['id']
        record = self._registry().get_agent(agent_id)
        if record is None or record.id != agent_id:
            return web.json_response({'error': 'Agent not found'}, status=404)
        query = str(request.query.get('q') or '').strip()
        try:
            if not 1 <= len(query) <= 200:
                raise ValueError('Search text must be 1–200 characters')
            before = int(request.query['before']) if request.query.get('before') else None
            if before is not None and not 1<=before<2**63:
                raise ValueError('before must be a positive SQLite message ID')
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        return web.json_response(self.store.search_agent_messages(agent_id, query, before=before))

    async def handle_agent_message_content(self, request: web.Request) -> web.Response:
        agent_id=request.match_info['id']
        record=self._registry().get_agent(agent_id)
        if record is None or record.id!=agent_id:return web.json_response({'error':'Agent not found'},status=404)
        try:
            value=self.store.agent_message_content(agent_id,int(request.match_info['message_id']),offset=int(request.query.get('offset','0')),expected_revision=request.query.get('revision'))
            if value is None:return web.json_response({'error':'Message not found in this agent scope'},status=404)
            return web.json_response(value)
        except ValueError as exc:return web.json_response({'error':str(exc)},status=409)

    async def handle_agent_template_export(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.configuration import export_template
        caller=request.get('caller')
        if caller is None or 'admin' not in caller.scopes or caller.session_prefix or not request['caller_actor'].startswith('owner:'):
            raise web.HTTPForbidden(text='Existing owner administration scope required')
        record=self._registry().get_agent(request.match_info['id'])
        if record is None or record.id!=request.match_info['id']:raise web.HTTPNotFound()
        try:
            revision=request.query.get('revision','')
            if not revision.isdecimal():raise ValueError('Reviewed source revision required')
            return web.json_response(export_template(record,int(revision)))
        except PermissionError as exc:return web.json_response({'error':str(exc)},status=403)
        except RuntimeError as exc:return web.json_response({'error':str(exc)},status=409)
        except ValueError as exc:return web.json_response({'error':str(exc)},status=400)

    async def handle_agent_templates(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.configuration import TEMPLATES
        templates=[dict(t,tools_granted=False,visibility='owner_local',export_policy='prompt_only_no_grants') for t in TEMPLATES]
        caller=request.get('caller');unavailable=[]
        if caller and 'admin' in caller.scopes and not caller.session_prefix and request['caller_actor'].startswith('owner:'):
            try:templates+= [{k:v for k,v in row.items() if k!='snapshot'} for row in self._registry().saved_templates(errors=unavailable)]
            except (ValueError,OSError):return web.json_response({'error':'Retained local template catalog unavailable; no version discarded'},status=409)
        return web.json_response({'templates':templates,'unavailable_saved_sources':unavailable})

    async def handle_agent_knowledge(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.configuration import editable, settings
        from jaeger_ai.features.knowledge_library.agent_context import pin_documents
        from jaeger_ai.contract.knowledge import MAX_KNOWLEDGE_DOCUMENTS, MAX_KNOWLEDGE_CONTEXT_CHARS
        from jaeger_ai.features.knowledge_library.tools import _library
        registry = self._registry()
        record = registry.get_agent(request.match_info['id'])
        if record is None or record.id != request.match_info['id']:
            return web.json_response({'error': 'Agent not found'}, status=404)
        if request.method == 'PATCH' and not editable(record):
            return web.json_response({'error': 'Protected specialist definition'}, status=403)
        try:
            library = _library()
            try:
                if request.method == 'PATCH':
                    body = await request.json()
                    if not isinstance(body, dict) or set(body) != {'expected_revision', 'document_ids'}:
                        raise ValueError('expected_revision and document_ids are required')
                    refs = pin_documents(library, body['document_ids'])
                    record = registry.assign_knowledge(record.id, refs, body['expected_revision'])
                catalog = library.managed_documents(include_archived=True)
            finally:
                library.close()
        except KeyError:
            return web.json_response({'error': 'Managed document not found'}, status=404)
        except PermissionError as exc:
            return web.json_response({'error': str(exc)}, status=403)
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        except RuntimeError as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except OSError:
            return web.json_response({'error': 'Instance knowledge library unavailable'}, status=503)
        if request.method == 'PATCH':
            self.event_bus.publish('*', 'agent.updated', {'agent_id': record.id, 'configuration_revision': settings(record)['revision']})
        caller = request.get('caller')
        return web.json_response({'agent_id': record.id, 'revision': settings(record)['revision'],
                                  'editable': editable(record) and bool(caller and 'admin' in caller.scopes),
                                  'documents': record.metadata.get('knowledge_documents') or [], 'available': catalog,
                                  'limits': {'max_documents': MAX_KNOWLEDGE_DOCUMENTS, 'context_chars': MAX_KNOWLEDGE_CONTEXT_CHARS}})

    async def handle_agent_configuration(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.configuration import editable, settings
        registry = self._registry()
        record = registry.get_agent(request.match_info['id'])
        if record is None or record.id != request.match_info['id']:
            return web.json_response({'error': 'Agent not found'}, status=404)
        if request.method == 'PATCH':
            try:
                body = await request.json()
                if not isinstance(body, dict) or set(body) != {'expected_revision', 'settings'}:
                    raise ValueError('expected_revision and settings are required')
                record = registry.configure_specialist(record.id, body['settings'], body['expected_revision'])
            except PermissionError as exc:
                return web.json_response({'error': str(exc)}, status=403)
            except RuntimeError as exc:
                return web.json_response({'error': str(exc)}, status=409)
            except (ValueError, TypeError) as exc:
                return web.json_response({'error': str(exc)}, status=400)
            self.event_bus.publish('*', 'agent.updated', {'agent_id': record.id, 'configuration_revision': settings(record)['revision']})
        caller = request.get('caller')
        return web.json_response({**settings(record), 'editable': editable(record) and bool(caller and 'admin' in caller.scopes)})

    async def handle_create_agent(self, request: web.Request) -> web.Response:
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Body must be an object"}, status=400)
        operation_id = body.get("operation_id")
        if operation_id is not None:
            if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 128:
                return web.json_response({"error": "Invalid operation_id"}, status=400)
            payload = {"action": "agent.create", "body": {k: v for k, v in body.items() if k != "operation_id"}}
            if body.get('template_snapshot') is not None:
                import hashlib
                # Snapshot may contain rejected private text. Retain identity, not content.
                payload={'action':'agent.create','body_digest':hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()}
            try:
                fresh = self.store.reserve_control_operation(operation_id, payload)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=409)
            if not fresh:
                saved = self.store.control_operation(operation_id) or {}
                receipt = saved.get("receipt")
                if receipt:
                    return web.json_response(receipt.get("agent") if receipt.get("ok") else {"error": receipt.get("error")}, status=receipt.get("http_status", 200))
                return web.json_response({"error": "Agent creation outcome unknown; reconcile the saved operation without retry", "operation_id": operation_id}, status=409)
        def failure(message: str, status: int = 400):
            if operation_id:
                self.store.finish_control_operation(operation_id, {"ok": False, "operation_id": operation_id, "error": message, "http_status": status})
            return web.json_response({"error": message}, status=status)
        template_snapshot=None
        if body.get('template_snapshot') is not None:
            from jaeger_ai.core.agent_registry.configuration import import_template
            try:template_snapshot=import_template(body['template_snapshot'])
            except (ValueError,TypeError) as exc:return failure(str(exc))
        name = str(body.get("name") or "").strip()
        if not name:
            return failure("name is required")
        kind = str(body.get("kind") or "jaeger_native").strip()
        # Explicit creation commands cannot silently rename/reconfigure an existing
        # discovered, built-in or registered identity. Legacy registration callers
        # retain their existing contract when no operation identity is supplied.
        candidate = f"native:{name}" if kind == "jaeger_native" else f"tp:{body.get('adapter') or name}"
        if operation_id and self._registry().get_agent(candidate) is not None:
            return failure("Agent identity already exists; choose another name", 409)
        metadata = body.get("metadata") or {}
        if not isinstance(metadata, dict):
            return failure("metadata must be an object")
        if template_snapshot is not None:
            if (kind!='jaeger_native' or body.get('role','specialist')!='specialist'
                    or set(body)-{'name','display_name','kind','role','operation_id','template_snapshot'}):
                return failure('Local templates create new specialists without inherited authority')
            metadata={'specialty':template_snapshot['specialty'],'summary':template_snapshot['summary'],
                      'operator_instructions':template_snapshot['instructions'],'configuration_revision':0,
                      'template':template_snapshot['template'],'allowed_tools':[]}
        if body.get('template_id') is not None:
            from jaeger_ai.core.agent_registry.configuration import TEMPLATES
            try:
                template = next((t for t in TEMPLATES if t['id'] == body['template_id'] and type(body.get('template_version')) is int and t['version'] == body['template_version']), None)
                if template is None:template=next((t for t in self._registry().saved_templates(errors=[]) if t['id']==body['template_id'] and type(body.get('template_version')) is int and t['version']==body['template_version']),None)
            except (ValueError,OSError):return failure('Retained template catalog unavailable',409)
            if template is None:
                return failure("Unknown template/version")
            if (kind != 'jaeger_native' or body.get('role', 'specialist') != 'specialist'
                    or set(body) - {'name', 'display_name', 'kind', 'role', 'metadata', 'operation_id', 'template_id', 'template_version'}
                    or set(metadata) - {'specialty'} or not isinstance(metadata.get('specialty', ''), str)):
                return failure("Templates create specialists without inherited grants or execution configuration")
            from jaeger_ai.core.agent_registry.configuration import validate_settings
            try:
                validate_settings({'specialty': metadata.get('specialty') or template['specialty'], 'summary': template['summary'], 'instructions': template['instructions']})
            except ValueError as exc:
                return failure(str(exc))
            metadata = {'specialty': metadata.get('specialty') or template['specialty'], 'summary': template['summary'],
                        'operator_instructions': template['instructions'], 'configuration_revision': 0,
                        'template': {'id': template['id'], 'version': template['version'], **({'source_bot':template['source_bot'],'visibility':'owner_local','export_policy':'prompt_only_no_grants','provenance':'owner_saved_snapshot'} if 'source_bot' in template else {})}, 'allowed_tools': []}
        creation_role="specialist" if template_snapshot is not None or body.get("template_id") is not None else (str(body["role"]) if body.get("role") else None)
        try:
            record = self._registry().create_agent(
                name,
                kind=kind,
                role=creation_role,
                display_name=(str(body["display_name"]) if body.get("display_name") else None),
                adapter=(str(body["adapter"]) if body.get("adapter") else None),
                profile_id=(str(body["profile_id"]) if body.get("profile_id") else None),
                endpoint=(str(body["endpoint"]) if body.get("endpoint") else None),
                port=(int(body["port"]) if body.get("port") is not None else None),
                metadata=metadata,
                make_active=bool(body.get("make_active", False)),
            )
        except (ValueError, TypeError) as exc:
            return failure(str(exc))
        if operation_id:
            self.store.finish_control_operation(operation_id, {"ok": True, "operation_id": operation_id, "agent": record.to_dict(), "http_status": 201})
        self.event_bus.publish("*", "agent.created", {"agent": record.to_dict()})
        return web.json_response(record.to_dict(), status=201)

    async def handle_agents_summary(self, request: web.Request) -> web.Response:
        """GET /v1/agents/summary — per-agent status for the sidebar and Tasks board.

        Computed, never stored: from durable tasks (agent_id/eta/runner),
        handoffs and the agent's direct-chat sessions. No agent_status table.
        """
        from jaeger_ai.core.gateway.agent_summary import summarize_agents
        from jaeger_ai.core.gateway.agent_presentation import project
        registry = self._registry()
        agents = [a for a in registry.list_agents() if a.role.value in {"lead", "specialist"}]
        tasks = [t.to_dict() for t in self.task_owner.store.list_tasks()] if self.task_owner else []
        presentation = self.store.agent_presentation()
        primary_id = self.store.primary_agent_id()
        return web.json_response(summarize_agents(
            [project(a.to_dict(), presentation, primary_id=primary_id) for a in agents],
            tasks=tasks,
            handoffs=self.store.list_handoffs(limit=500),
            sessions=self.store.list_sessions(),
            last_message=self._last_message_preview,
            seen=self.store.agents_seen(),
            requests=[r for status in ("admitted", "queued", "running", "awaiting_approval", "cancelling")
                      for r in self.store.list_requests(status=status)],
        ))

    async def handle_agent_seen(self, request: web.Request) -> web.Response:
        """POST /v1/agents/{id}/seen — mark an agent's activity read (summary ``unseen``).

        Body: optional seen_at/event_id and boolean unread. Explicit unread persists until open/read clears it.
        """
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None or record.id != agent_id:
            return web.json_response({"error": "Agent not found"}, status=404)
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        body = body if isinstance(body, dict) else {}
        try:
            seen_at = float(body["seen_at"]) if body.get("seen_at") is not None else time.time()
            event_id = int(body["event_id"]) if body.get("event_id") is not None else None
        except (TypeError, ValueError):
            return web.json_response({"error": "seen_at must be a number and event_id an integer"}, status=400)
        if set(body) - {'seen_at', 'event_id', 'unread'} or not isinstance(body.get('unread', False), bool) or not math.isfinite(seen_at):
            return web.json_response({'error': 'Only finite seen_at, event_id and boolean unread are accepted'}, status=400)
        value = self.store.mark_agent_seen(agent_id, seen_at=seen_at, event_id=event_id, unread=body.get('unread', False))
        self.event_bus.publish('*', 'agent.updated', {'agent_id': agent_id, 'read_marker': value})
        return web.json_response(value)

    async def handle_get_agent(self, request: web.Request) -> web.Response:
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        return web.json_response(self._with_skills(record.to_dict()))

    async def handle_activate_agent(self, request: web.Request) -> web.Response:
        """Switch active agent — never fee-gated (fundamentals stay open)."""
        agent_id = request.match_info["id"]
        try:
            record = self._registry().set_active(agent_id)
        except KeyError:
            return web.json_response({"error": "Agent not found"}, status=404)
        self.event_bus.publish("*", "agent.activated", {"agent": record.to_dict()})
        return web.json_response(record.to_dict())

    async def handle_agent_home(self, request: web.Request) -> web.Response:
        """GET /v1/agents/{id}/home — idempotent get-or-create of the agent's home chat."""
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        canonical = str(getattr(record, "id", None) or agent_id)
        sid, created = self._ensure_agent_home(canonical, getattr(record, "display_name", None))
        return web.json_response({"session_id": sid, "agent_id": canonical, "created": created})

    async def handle_list_handoffs(self, request: web.Request) -> web.Response:
        """GET /v1/handoffs[?agent_id=&session_id=&since=&limit=] — newest first."""
        query = request.query
        try:
            since = float(query["since"]) if query.get("since") else None
            limit = int(query["limit"]) if query.get("limit") else None
        except ValueError:
            return web.json_response({"error": "since must be epoch seconds and limit an integer"}, status=400)
        if limit is not None and not 1 <= limit <= 500:
            return web.json_response({"error": "limit must be between 1 and 500"}, status=400)
        task_id = (query.get("task_id") or "").strip()
        records = self.store.list_handoffs(
            agent_id=query.get("agent_id") or None,
            session_id=query.get("session_id") or None,
            since=since,
            limit=500 if task_id else limit,
        )
        if task_id:  # G5
            records = [r for r in records if r.get("task_id") == task_id][:limit or None]
        return web.json_response({"handoffs": records, "count": len(records)})

    async def handle_handoff_reply(self, request: web.Request) -> web.Response:
        """Explicit owner follow-up, always through existing handoff approval/admission."""
        from jaeger_ai.core.gateway.handoff_reply import reply_payload, ReplyConflict
        try:
            target, payload = reply_payload(self.store, request.match_info["id"], await request.json())
        except ReplyConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        class FollowupRequest(dict):
            can_read_body = True
            match_info = {"id": target}
            async def json(self):
                return payload
        return await self.handle_handoff_agent(FollowupRequest(request))

    async def handle_handoff_messages(self, request: web.Request) -> web.Response:
        """GET /v1/handoffs/{id}/messages — the specialist's side of one exchange.

        Hides the ``specialist:<agent>:<request>`` worker-session naming from
        clients; the exchange panel reads task + messages + summary in one call.
        """
        record = self.store.get_handoff(request.match_info["id"])
        if record is None:
            return web.json_response({"error": "Handoff not found"}, status=404)
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
        result = record.get("result") or {}
        worker = str(result.get("worker_session_id") or "") or specialist_session(
            record["to_agent_id"], record.get("request_id") or record["id"])
        session = self.store.get_session(worker) or {}
        messages = [
            {key: m.get(key) for key in ("id", "role", "content", "timestamp")}
            for m in session.get("messages") or []
        ]
        return web.json_response({
            "handoff_id": record["id"],
            "thread_handoff_id": (record.get("metadata") or {}).get("thread_handoff_id") or record["id"],
            "reply_to_handoff_id": (record.get("metadata") or {}).get("reply_to_handoff_id"),
            "from_agent_id": record["from_agent_id"],
            "request_id": record.get("request_id"),
            "session_id": record.get("session_id"),
            "to_agent_id": record["to_agent_id"],
            "status": record["status"],
            "task": record["task"],
            "worker_session_id": worker,
            "messages": messages,
            "summary": result.get("summary") or "",
        })

    async def handle_get_handoff(self, request: web.Request) -> web.Response:
        record = self.store.get_handoff(request.match_info["id"])
        if record is None:
            return web.json_response({"error": "Handoff not found"}, status=404)
        if record["status"] == "execution_unknown":
            from jaeger_ai.contract.handoffs import request_digest
            from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
            rid = record.get("request_id") or record["id"]
            session = specialist_session(record["to_agent_id"], rid)
            from .handoff_ownership import child_receipt
            session,_,canonical,bound=child_receipt(self,record)
            if canonical is not None:
                if not bound:
                    return web.json_response({**record,'recovery_error':'Retained child identity does not match this handoff; outcome remains unknown'})
                status=canonical['status']
                if status in {'completed','failed','cancelled'}:
                    result=canonical.get('result') or {}
                    record=self.store.save_handoff({**record,'status':status,'result':{
                        'ok':status=='completed','status':status,'summary':result.get('output') or result.get('error') or result.get('halt_reason') or '',
                        'worker_session_id':session,'metadata':{'gateway_request_id':canonical['request_id'],'recovered_from':'canonical_gateway_receipt','result_scope':'child_request_outcome','goal_verification':'not_inferred_from_turn_completion'}}})
                    self._publish_handoff('agent.handoff.finished',record)
                # A canonical admitted/running/unknown record cannot be replaced
                # by a different/older receipt source. Never restart that child.
                return web.json_response(record)
            # Read-only continuity for pre-Gateway native receipts; no old app,
            # runtime fallback or execution is started by this compatibility read.
            receipt = self._native_receipt(request_digest(rid), session)
            if receipt and not receipt.get("execution_unknown") and receipt.get("status") in {"completed", "failed", "cancelled"}:
                reply = receipt.get("reply") or {}
                record = self.store.save_handoff({**record, "status": receipt["status"],
                    "result": {"ok": receipt["status"] == "completed", "status": receipt["status"],
                               "summary": reply.get("text") or reply.get("error") or reply.get("halt_reason") or "",
                               "worker_session_id": session, "metadata": {"native_receipt": receipt}}})
                self._publish_handoff("agent.handoff.finished", record)
        return web.json_response(record)

    @staticmethod
    def _system_prompt_for_agent(agent) -> str:
        """Build the turn system prompt.

        Lead / default text-mode turns use readable SI sections:
        ``[Identity]`` from ``Character.character_block``, then optional
        ``[SOUL]`` from ``load_soul(InstanceLayout)`` (same
        ``resolve_instance_dir`` root). Empty SOUL is omitted. Specialist
        handoffs keep a thin specialty overlay — not a second soul.
        MCP native lead path does not use this prompt.
        """
        role = getattr(agent, "role", None) if agent is not None else None
        role_s = role.value if hasattr(role, "value") else (str(role) if role else "")

        if agent is not None and role_s == "specialist":
            display = str(
                getattr(agent, "display_name", None)
                or getattr(agent, "name", None)
                or "Specialist"
            )
            meta = getattr(agent, "metadata", None) or {}
            if not isinstance(meta, dict):
                meta = {}
            specialty = str(meta.get("specialty") or meta.get("role") or "").strip()
            summary = str(meta.get("summary") or "").strip()
            parts = [f"You are {display}."]
            parts.append(f"You are the {specialty or display} specialist.")
            parts.append(
                f"When asked for your display name, reply with exactly: SPECIALIST:{display}."
            )
            if summary:
                parts.append(summary.rstrip(".") + ".")
            instructions = str(meta.get("operator_instructions") or "").strip()
            if instructions:
                parts.append("[Operator specialist instructions]\n" + instructions)
            parts.append("Instructions describe the task; they do not grant tools, access or approval authority.")
            parts.append("Reply briefly and helpfully.")
            notes = _server_attr("JaegerGatewayApp")._agent_notes(agent)
            prompt = " ".join(parts)
            skills = _server_attr("JaegerGatewayApp")._skills_block(agent)
            if skills:
                prompt = f"{prompt}\n\n{skills}"
            return f"{prompt}\n\n[Your notes]\n{notes}" if notes else prompt

        sections: list[str] = []
        si = _server_attr("JaegerGatewayApp")._si_character_prompt()
        if si:
            sections.append(f"[Identity]\n{si}")
        soul = _server_attr("JaegerGatewayApp")._si_soul_prompt()
        if soul:
            sections.append(f"[SOUL]\n{soul}")
        if sections:
            return "\n\n".join(sections)

        if agent is None:
            return "You are Jaeger. Reply briefly and helpfully."
        display = str(
            getattr(agent, "display_name", None)
            or getattr(agent, "name", None)
            or "Jaeger"
        )
        meta = getattr(agent, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        summary = str(meta.get("summary") or "").strip()
        parts = [f"You are {display}."]
        if role_s == "lead":
            parts.append("You are the lead assistant.")
        if summary:
            parts.append(summary.rstrip(".") + ".")
        parts.append("Reply briefly and helpfully.")
        return " ".join(parts)

    async def handle_list_projects(self, request: web.Request) -> web.Response:
        return web.json_response({"projects": self.projects.list()})

    async def handle_get_project(self, request: web.Request) -> web.Response:
        project = self.projects.get(request.match_info["id"])
        if project is None:
            return web.json_response({"error": "Project not found"}, status=404)
        return web.json_response(project)

    async def handle_create_project(self, request: web.Request) -> web.Response:
        """POST /v1/projects {name, root, team?, grants?, limits?, bind_session_id?}."""
        from jaeger_ai.core.agent_registry.projects import ProjectError
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        known = {a.id for a in self._registry().list_agents()}
        try:
            project = self.projects.create(
                name=body.get("name"), root=body.get("root"), team=body.get("team"),
                grants=body.get("grants"), limits=body.get("limits"), known_agents=known,
            )
        except (ProjectError, TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        bind = str(body.get("bind_session_id") or "").strip()
        if bind:
            if self.store.get_session(bind) is None:
                return web.json_response({"error": "bind_session_id not found", "project": project}, status=404)
            self.store.update_metadata(bind, {"project_id": project["id"], "workspace": project["root"]})
        self.event_bus.publish("*", "project.created", {"project": project, "bound_session_id": bind or None})
        return web.json_response(project, status=201)

    async def handle_project_check(self, request: web.Request) -> web.Response:
        """POST /v1/projects/{id}/check {commands?, expect_files?, timeout_s?} — the
        build/test checker, run by the Gateway itself so a pass is recorded."""
        project = self.projects.get(request.match_info["id"])
        if project is None:
            return web.json_response({"error": "Project not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        commands = body.get("commands") or ["npm test"]
        files = body.get("expect_files") or []
        if not isinstance(commands, list) or not isinstance(files, list):
            return web.json_response({"error": "commands and expect_files must be lists"}, status=400)
        from importlib import import_module
        check_project = import_module("jaeger_ai.modules.build-check.build_check").check_project
        result = await asyncio.to_thread(check_project, project["root"], [str(c) for c in commands],
                                         [str(f) for f in files], float(body.get("timeout_s") or 300))
        result["project_id"] = project["id"]
        result["checked_at"] = time.time()
        self.event_bus.publish("*", "project.checked", {"project_id": project["id"], "result": result})
        return web.json_response(result)
