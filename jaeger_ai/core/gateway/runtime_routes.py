"""Extracted Gateway runtime status, health, probes, autonomy & first-run routes mixin (Wave 3)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

logger = logging.getLogger("jaeger.gateway")


def _server_attr(name: str) -> Any:
    from . import server as _server
    return getattr(_server, name)


class GatewayRuntimeRoutesMixin:
    """Health, version, global stop, runtime diagnostics, autonomy and first-run routes."""

    async def handle_version(self, request: web.Request) -> web.Response:
        """Stable, read-only identity for clients and deployment checks."""
        return web.json_response({
            "component": "jaeger-gateway",
            "version": _server_attr('JAEGER_VERSION'),
            "protocol_version": "1",
        })

    async def _probe_bridge(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Probe the agent bridge over its Unix socket; never raises."""
        client = self._background_client
        if client is None:
            from jaeger_ai.interfaces.bridge_client import jaeger_bridge
            client = jaeger_bridge()
        try:
            res = await asyncio.wait_for(asyncio.to_thread(client.health), timeout=timeout_s)
            return {"ok": bool((res or {}).get("ok")), "transport": "unix-socket"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "transport": "unix-socket", "error": type(exc).__name__}

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
        url = f"{_server_attr('LOCKED_WEBUI_URL')}/api/chat"
        try:
            timeout = ClientTimeout(total=timeout_s)
            async with ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json={"session_id": "__jaeger_health_probe__", "message": "ping"},
                ) as resp:
                    body = await resp.text()
                    # CoS: must not claim all_green while legacy /api/chat returns 500.
                    # Validation errors establish reachability only, not readiness.
                    ok = 200 <= resp.status < 300
                    return {
                        "ok": ok,
                        "status_code": resp.status,
                        "url": url,
                        "required": True,
                        "body_excerpt": body[:200],
                        "note": (
                            "legacy /api/chat returned 500"
                            if resp.status == 500
                            else "legacy chat readiness is not verified by a validation response"
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

    async def _probe_native_mcp(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Read-only MCP and native-agent readiness; never executes chat.

        Positive (ok=True) probe results are cached briefly (default 5s,
        configured via JAEGER_MCP_PROBE_CACHE_TTL_S) and coalesced under a
        per-app asyncio.Lock so high-frequency /health polls from the menu bar
        and WebUI do not open/close multiple MCP HTTP sessions per second.
        Failures (ok=False) are never cached so recovery is observed immediately.
        """
        from jaeger_ai.core.gateway.native_mcp import (
            MCP_URL, MCP_HOST_HEADER, mcp_api_key,
        )
        try:
            cache_ttl = float(os.environ.get("JAEGER_MCP_PROBE_CACHE_TTL_S", "5.0"))
        except ValueError:
            cache_ttl = 5.0
        key = mcp_api_key()
        cache_key = (MCP_URL, MCP_HOST_HEADER, hashlib.sha256(key.encode("utf-8")).hexdigest()[:12] if key else "")
        lock = getattr(self, "_native_mcp_probe_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._native_mcp_probe_lock = lock
        if cache_ttl > 0:
            cached = getattr(self, "_native_mcp_probe_cache", None)
            if (
                isinstance(cached, tuple)
                and len(cached) == 3
                and cached[0] == cache_key
                and (time.monotonic() - cached[1]) < cache_ttl
            ):
                return dict(cached[2])

        async with lock:
            if cache_ttl > 0:
                cached = getattr(self, "_native_mcp_probe_cache", None)
                if (
                    isinstance(cached, tuple)
                    and len(cached) == 3
                    and cached[0] == cache_key
                    and (time.monotonic() - cached[1]) < cache_ttl
                ):
                    return dict(cached[2])
            result = await self._probe_native_mcp_uncached(
                MCP_URL=MCP_URL, MCP_HOST_HEADER=MCP_HOST_HEADER, key=key, timeout_s=timeout_s,
            )
            if cache_ttl > 0 and result.get("ok"):
                self._native_mcp_probe_cache = (cache_key, time.monotonic(), dict(result))
            else:
                self._native_mcp_probe_cache = None
            return result

    async def _probe_native_mcp_uncached(
        self,
        *,
        MCP_URL: str,
        MCP_HOST_HEADER: str,
        key: str,
        timeout_s: float = 3.0,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json, text/event-stream", "Host": MCP_HOST_HEADER}

        async def terminate_session() -> None:
            """Release the stdio backend allocated by the MCP handshake."""
            if "Mcp-Session-Id" not in headers:
                return
            try:
                timeout = ClientTimeout(total=min(1.0, timeout_s))
                async with ClientSession(timeout=timeout) as client:
                    async with client.delete(MCP_URL, headers=headers) as response:
                        # Session termination is best-effort health-check cleanup. A
                        # proxy may answer 404 after already reaping the session.
                        if response.status not in {200, 202, 204, 404}:
                            response.raise_for_status()
            except Exception:  # noqa: BLE001 — cleanup must not hide probe health
                pass

        async def rpc(client, method, params, identity):
            async with client.post(MCP_URL, headers=headers, json={
                "jsonrpc": "2.0", "id": identity, "method": method, "params": params,
            }) as response:
                response.raise_for_status()
                if response.headers.get("Mcp-Session-Id"):
                    headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                # A server may keep SSE open after the response; consume only
                # the matching RPC result, with a bounded total body and timeout.
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    size = 0
                    async for line in response.content:
                        size += len(line)
                        if size > 1_000_000:
                            raise ValueError("MCP catalog response too large")
                        if line.startswith(b"data:"):
                            value = json.loads(line[5:])
                            if value.get("id") == identity:
                                break
                    else:
                        raise ValueError("MCP returned no matching result")
                else:
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > 1_000_000:
                            raise ValueError("MCP catalog response too large")
                    value = json.loads(raw)
                if value.get("error") or value.get("id") != identity:
                    raise ValueError("MCP rejected readiness probe")
                return value.get("result", {})

        try:
            if key:
                headers["Authorization"] = f"Bearer {key}"
            async with asyncio.timeout(timeout_s):
                async with ClientSession(timeout=ClientTimeout(total=timeout_s)) as client:
                    await rpc(client, "initialize", {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "jaeger-health", "version": "1"},
                    }, 1)
                    async with client.post(MCP_URL, headers=headers, json={
                        "jsonrpc": "2.0", "method": "notifications/initialized",
                    }) as response:
                        response.raise_for_status()
                    catalog = await rpc(client, "tools/list", {}, 2)
                    names = {t.get("name") for t in catalog.get("tools", [])}
                    chat_available = bool(names & {"chat", "jaeger_chat"})
                    health_tool = next((n for n in ("jaeger_bridge_health", "bridge_health") if n in names), None)
                    agent_ready = False
                    readiness_source = None
                    if chat_available and health_tool:
                        health_result = await rpc(client, "tools/call", {"name": health_tool, "arguments": {}}, 3)
                        if not health_result.get("isError"):
                            health = health_result.get("structuredContent")
                            if not isinstance(health, dict):
                                health = json.loads(self._mcp_chat_text(health_result))
                            agent_ready = bool(health.get("ok")) and health.get("ready", {}).get("agent") == "ready"
                            readiness_source = "mcp_bridge_health"
                    elif chat_available:
                        # HTTP MCP started in gateway-fallback mode has `chat`
                        # but not `bridge_health`. The chat tool still reaches
                        # the agent through the Gateway; use the live bridge
                        # socket for the same readiness check.
                        from jaeger_ai.interfaces.bridge_client import bridge_health
                        health = await asyncio.to_thread(bridge_health)
                        agent_ready = bool(health.get("ok")) and (
                            health.get("ready", {}) or {}
                        ).get("agent") == "ready"
                        readiness_source = "unix_bridge_health"
                    transport_ready = chat_available
                    ok = chat_available and agent_ready
                    note = "Native bridge readiness; model execution not probed"
                    if readiness_source == "unix_bridge_health":
                        note = "MCP chat is up; agent readiness from the live bridge socket"
                    return {
                        "ok": ok, "required": True, "url": MCP_URL,
                        "transport_ready": transport_ready,
                        "chat_tool_available": chat_available,
                        "agent_ready": agent_ready,
                        "execution_verified": False,
                        "readiness_source": readiness_source,
                        "note": note,
                    }
        except Exception as exc:
            return {
                "ok": False, "required": True, "url": MCP_URL,
                "error": type(exc).__name__,
                "transport_ready": False,
                "chat_tool_available": False,
                "agent_ready": False,
                "execution_verified": False,
            }
        finally:
            await terminate_session()

    async def handle_stop_status(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError
        latch = GlobalStop.load()
        try:
            state = latch.read()
        except GlobalStopError:
            return web.json_response({
                "engaged": True, "reason": "unreadable latch", "engaged_by": "", "unconfirmed": [],
            })
        return web.json_response({
            "engaged": state.engaged,
            "reason": state.reason,
            "engaged_by": state.engaged_by,
            "unconfirmed": list(state.unconfirmed),
            "cancellation_confirmed": not state.unconfirmed,
        })

    async def handle_engage_stop(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.gateway.global_stop import GlobalStop
        spec = request["caller"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        reason = str(body.get("reason") or "stop")
        state = GlobalStop.load().engage(
            spec.name, reason=reason, unconfirmed=await self._halt_for_stop(),
        )
        return web.json_response({
            "engaged": state.engaged,
            "reason": state.reason,
            "engaged_by": state.engaged_by,
            "unconfirmed": list(state.unconfirmed),
            "cancellation_confirmed": not state.unconfirmed,
        })

    async def handle_release_stop(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.devices.registry import allow_device_commands
        from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError
        spec = request["caller"]
        try:
            state = GlobalStop.load().release(spec)
        except GlobalStopError as exc:
            return web.json_response({"error": str(exc)}, status=403)
        allow_device_commands()
        return web.json_response({"engaged": state.engaged, "released_by": spec.name})

    async def handle_health(self, request: web.Request) -> web.Response:
        """Backend readiness is independent of optional HTTP adapters and UIs."""
        from .health_probes import build_health_response

        return await build_health_response(
            self,
            locked_ollama_url=_server_attr('LOCKED_OLLAMA_URL'),
            locked_webui_url=_server_attr('LOCKED_WEBUI_URL'),
            default_gateway_host=_server_attr('DEFAULT_GATEWAY_HOST'),
            default_gateway_port=_server_attr('DEFAULT_GATEWAY_PORT'),
            jaeger_version=_server_attr('JAEGER_VERSION'),
        )

    @staticmethod
    def _probe_owner_runtime() -> dict[str, Any]:
        """Check the same resident OWNER used by turn execution, without a turn."""
        from jaeger_ai.core.entity.ownership import EntityRuntimeMode
        from jaeger_ai.core.entity.runtime import EntityRuntime

        try:
            runtime = EntityRuntime.get_singleton()
            resident = bool(getattr(runtime, "is_resident", False))
            owner = runtime.mode == EntityRuntimeMode.OWNER
            runtime.event_store.count()
            return {"ok": owner and resident, "resident": resident, "owner": owner,
                    "execution_verified": False}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "execution_verified": False}

    async def handle_first_run_status(self, request: web.Request) -> web.Response:
        return web.json_response(self._first_run_payload(self._first_run_layout()),
                                 headers={"Cache-Control": "no-store"})

    async def handle_first_run_setup(self, request: web.Request) -> web.Response:
        if not self._first_run_mutation_allowed(request):
            return web.json_response({"error": "Local owner access required"}, status=403)
        layout = self._first_run_layout()
        current = self._first_run_payload(layout)
        if current["completed"]:
            return web.json_response(current, headers={"Cache-Control": "no-store"})
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object")
            # Expose only bounded first-run setup choices, never arbitrary config edits.
            required = {"character_id", "awake_provider", "awake_model"}
            optional = {
                "display_name", "voice_profile", "interaction_posture", "user_name",
                "audio_input", "audio_output", "camera_device", "vision_enabled",
                "local_fallback_model", "privacy_local_only", "autonomy", "computer_access",
                "heartbeat_interval_minutes", "quiet_start_hour", "quiet_end_hour",
                "disabled_dimensions", "proactive_enabled", "digest_enabled", "initial_goals",
            }
            if set(body) - (required | optional):
                raise ValueError("Unknown setup field")
            if not all(str(body.get(key) or "").strip() for key in required):
                raise ValueError("character_id, awake_provider and awake_model are required")
            from jaeger_ai.core.instance.onboarding_setup import complete_setup
            from jaeger_ai.core.instance import first_boot
            complete_setup(layout, body)
            if first_boot.status(layout) is not first_boot.FirstBootStatus.COMPLETED:
                doc = first_boot._read(layout)
                doc["status"] = first_boot.FirstBootStatus.COMPLETED.value
                doc.setdefault("completed_at", first_boot._now())
                first_boot._write(layout, doc)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(self._first_run_payload(layout),
                                 headers={"Cache-Control": "no-store"})

    async def handle_first_run_skip(self, request: web.Request) -> web.Response:
        if not self._first_run_mutation_allowed(request):
            return web.json_response({"error": "Local owner access required"}, status=403)
        layout = self._first_run_layout()
        current = self._first_run_payload(layout)
        if not current["completed"]:
            from jaeger_ai.core.instance.first_boot import skip
            skip(layout)
        return web.json_response(self._first_run_payload(layout),
                                 headers={"Cache-Control": "no-store"})

    async def handle_runtime_status(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.entity.runtime_status import collect_runtime_status
        payload = collect_runtime_status(include_network=True)
        payload["interaction_tier"] = self._current_tier()
        return web.json_response(payload, status=200 if payload.get("ready") else 503)

    async def handle_connect_apps(self, request: web.Request) -> web.Response:
        """GET /v1/connect-apps — registry + live (30 s cached, read-only) state."""
        return web.json_response(await asyncio.to_thread(self._connect_apps().listing))

    async def handle_connect_app_state(self, request: web.Request) -> web.Response:
        app_id = request.match_info["id"]
        refresh = request.query.get("refresh") in {"1", "true"}
        state = await asyncio.to_thread(self._connect_apps().state, app_id, refresh=refresh)
        if state is None:
            return web.json_response({"error": "Unknown app"}, status=404)
        return web.json_response({"id": app_id, "state": state})

    async def handle_connect_app_install(self, request: web.Request) -> web.Response:
        """POST /v1/connect-apps/{id}/install ``{"confirm": true}`` — owner callers only.

        202 then ``connect_app.updated`` {id, state, audit} on the global stream
        (the durable event row is the audit record). Fixed argv, shell=False.
        """
        from jaeger_ai.core.gateway.connect_apps import OWNER_INSTALL_CALLERS
        caller = request.get("caller")
        if getattr(caller, "name", None) not in OWNER_INSTALL_CALLERS:
            return web.json_response({"error": "Only the owner's apps may install"}, status=403)
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            body = {}
        if not isinstance(body, dict) or body.get("confirm") is not True:
            return web.json_response({"error": "confirm: true is required"}, status=400)
        app_id = request.match_info["id"]
        service = self._connect_apps()
        status, payload, plan = await asyncio.to_thread(service.begin_install, app_id)
        if plan is None:
            return web.json_response(payload, status=status)
        self.event_bus.publish("*", "connect_app.updated", {
            "id": app_id, "state": {"value": "installing", "checked_at": time.time()}})

        async def _run() -> None:
            result = await asyncio.to_thread(service.run_install, app_id, plan, caller=caller.name)
            logger.info("connect-apps install audit: %s", result["audit"])
            self.event_bus.publish("*", "connect_app.updated", {"id": app_id, **result})

        task = asyncio.create_task(_run())
        self._connect_install_task = task
        return web.json_response(payload, status=202)

    async def handle_runtime_frameworks(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import framework_inventory
        return web.json_response({"frameworks": framework_inventory()})

    async def handle_runtime_models(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import provider_model_inventory, webui_model_catalog
        return web.json_response({
            **await asyncio.to_thread(provider_model_inventory),
            "webui_catalog": await asyncio.to_thread(webui_model_catalog),
        })

    async def handle_runtime_capabilities(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import capability_snapshot
        return web.json_response(capability_snapshot())

    async def handle_get_autonomy(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/autonomy: how much the agent asks before acting (saved setting)."""
        from jaeger_ai.core.runtime.autonomy import AUTONOMY, effective_autonomy

        return web.json_response({"autonomy": effective_autonomy(self._config_path()), "options": list(AUTONOMY)})

    async def handle_set_autonomy(self, request: web.Request) -> web.Response:
        """POST /v1/runtime/autonomy ``{"autonomy": "full|auto|scoped|ask"}``: saved to the
        instance config and applied immediately to the running approval provider."""
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
        from jaeger_ai.core.runtime.autonomy import AUTONOMY, set_autonomy

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        mode = str((body or {}).get("autonomy") or "").strip().lower() if isinstance(body, dict) else ""
        if mode not in AUTONOMY:
            return web.json_response({"error": f"autonomy must be one of {list(AUTONOMY)}"}, status=400)
        path = self._config_path()
        if path is None or not Path(path).is_file():
            return web.json_response({"error": "No instance config to save to"}, status=409)
        config = load_yaml(Path(path), Config)
        config.automation.autonomy = mode
        from jaeger_ai.core.runtime.autonomy import permissions_mode_for
        config.permissions.mode = permissions_mode_for(mode)
        dump_yaml(Path(path), config)
        receipt = set_autonomy(mode)
        if not receipt.get("ok"):
            return web.json_response({"error": "Autonomy was saved but the running agent did not accept it"}, status=500)
        return web.json_response({"autonomy": mode, "options": list(AUTONOMY)})

    async def handle_get_tier(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/tier: normal conversation ('agent') or read-only 'plan'."""
        from jaeger_ai.contract.modes import INTERACTION_TIERS, TIER_DESCRIPTIONS

        self._migrate_retired_interaction_tier()
        tier = self._current_tier()
        return web.json_response({
            "tier": tier,
            "options": list(INTERACTION_TIERS),
            "descriptions": dict(TIER_DESCRIPTIONS),
        })

    async def handle_set_tier(self, request: web.Request) -> web.Response:
        """POST /v1/runtime/tier ``{"tier": "agent"|"plan"}``: save work style.

        Legacy ``chat`` and ``jaeger`` values are accepted and stored as ``agent``.
        """
        from jaeger_ai.contract.modes import (
            INTERACTION_TIERS, RETIRED_INTERACTION_TIERS, TIER_DESCRIPTIONS,
            normalize_interaction_tier,
        )
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        raw = str((body or {}).get("tier") or "").strip().lower() if isinstance(body, dict) else ""
        if raw not in INTERACTION_TIERS and raw not in RETIRED_INTERACTION_TIERS:
            return web.json_response({"error": f"tier must be one of {list(INTERACTION_TIERS)}"}, status=400)
        tier = normalize_interaction_tier(raw)
        path = self._config_path()
        if path is None or not Path(path).is_file():
            return web.json_response({"error": "No instance config to save to"}, status=409)
        config = load_yaml(Path(path), Config)
        config.automation.interaction_tier = tier
        dump_yaml(Path(path), config)
        self.event_bus.publish("*", "runtime.tier.changed", {"tier": tier})
        return web.json_response({
            "tier": tier,
            "options": list(INTERACTION_TIERS),
            "descriptions": dict(TIER_DESCRIPTIONS),
        })

    async def handle_channels(self, request: web.Request) -> web.Response:
        from jaeger_ai.features.channels.status import snapshot
        return web.json_response(snapshot(self.store))

    async def handle_runtime_diagnostics(self, request: web.Request) -> web.Response:
        return web.json_response({**self.store.diagnostics_snapshot(), 'process_id': os.getpid(),
                                  'server_module_sha256': _server_attr('_GATEWAY_MODULE_SHA256'),
                                  'fingerprint_scope': 'server.py bytes captured at module import',
                                  'observed_at': time.time(), 'read_only': True})

    async def handle_runtime_tools(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.gateway.tool_inventory import collect
        query = str(request.query.get('q') or '').strip()
        if len(query) > 200:
            return web.json_response({'error': 'Tool query must be at most 200 characters'}, status=400)
        return web.json_response(collect(query))

    async def handle_runtime_skills(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/skills[?q=text] — the skills a client can offer, one row each.

        Read-only. Rows carry name, category, description and lifecycle, never the
        skill body or its path, so a client menu can list them safely.
        """
        from jaeger_agent.skill_registry.playbook_skills import discover_playbooks

        query = str(request.query.get("q") or "").strip().lower()
        rows = [
            {"name": s.name, "category": s.category, "description": s.description[:300],
             "lifecycle": s.lifecycle}
            for s in discover_playbooks()
            if not query or query in s.name.lower() or query in s.description.lower()
        ]
        return web.json_response({"skills": rows, "count": len(rows)})

    async def handle_runtime_skill_detail(self, request: web.Request) -> web.Response:
        """Inspect registry provenance/requirements only; never load toolsets or scripts."""
        from jaeger_agent.skill_registry.playbook_skills import discover_playbooks
        from jaeger_ai.core.redaction import redact_text
        name, category = request.query.get('name', ''), request.query.get('category', '')
        if not name or not category or len(name) > 200 or len(category) > 200:
            return web.json_response({'error': 'Exact skill name and category required'}, status=400)
        matches = [s for s in discover_playbooks() if s.name == name and s.category == category]
        if len(matches) != 1:
            return web.json_response({'error': 'Skill not found or registry identity ambiguous'}, status=404 if not matches else 409)
        skill = matches[0]
        clean = lambda values: [redact_text(str(value))[:300] for value in values[:100]]
        return web.json_response({'name': skill.name, 'category': skill.category,
            'description': redact_text(skill.description)[:2000], 'origin': skill.origin,
            'lifecycle': skill.lifecycle, 'skill_class': skill.skill_class,
            'platforms': clean(skill.platforms), 'requires_tools': clean(skill.requires_tools),
            'optional_tools': clean(skill.optional_tools), 'requires_toolsets': clean(skill.requires_toolsets),
            'requires_plugins': clean(skill.requires_plugins), 'aliases': clean(skill.aliases),
            'tags': clean(skill.tags), 'auto_activate': bool(skill.auto_activate), 'tier': skill.tier,
            'scope': 'discovered_registry_metadata', 'execution_authorized': False,
            'availability': 'not_probed', 'origin_verified': False})
