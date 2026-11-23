"""Extracted Gateway health & readiness probes (Strangler-Fig Phase 5/6).

Runs all backend readiness checks concurrently in a single bounded
``asyncio.gather`` so ``GET /health`` never blocks the aiohttp event loop
and always responds within ~2s even while a long model turn is running or
cancelling.
"""
from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any, Callable

from aiohttp import web


async def safe_thread_probe(
    fn: Callable[..., Any],
    *args: Any,
    timeout_s: float = 1.5,
    default: Any = None,
) -> Any:
    """Run a synchronous probe off the event loop with a hard ceiling."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001 — health must never crash or hang
        return default(exc) if callable(default) else default


async def build_health_response(
    app: Any,
    *,
    locked_ollama_url: str,
    locked_webui_url: str,
    default_gateway_host: str,
    default_gateway_port: int,
    jaeger_version: str,
    probe_timeout_s: float = 1.5,
) -> web.Response:
    """Assemble the canonical ``GET /health`` JSON response in one parallel wave."""
    def _read_external_configured() -> bool:
        try:
            from jaeger_ai.core.instance.instance import resolve_instance_dir
            from jaeger_ai.core.instance.schemas import Config, load_yaml

            cfg_path = resolve_instance_dir() / "config.yaml"
            if cfg_path.exists():
                cfg = load_yaml(cfg_path, Config)
                ext = getattr(cfg, "external_model", None)
                return bool(ext and getattr(ext, "enabled", False))
        except Exception:  # noqa: BLE001
            return False
        return False

    def _read_active_model() -> str:
        try:
            from jaeger_ai.core.runtime.truth import _active_model

            return (_active_model(app._instance_root()) or {}).get("model") or "unknown"
        except Exception:  # noqa: BLE001
            return "unknown"

    def _collect_store_diag() -> dict[str, Any]:
        return {
            "schema_version": app.store.schema_version(),
            "process_lease": app.store.process_lease(),
            **app._entity_diagnostics(),
        }

    async def _bounded_async(coro: Any, fallback: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(coro, timeout=probe_timeout_s)
        except Exception as exc:  # noqa: BLE001
            return {**fallback, "error": type(exc).__name__}

    # All 8 probes execute concurrently in ONE gather — total latency is bounded
    # by max(probe_timeout_s), never sum(probe_timeout_s).
    (
        owner,
        bridge,
        ollama,
        webui_chat,
        native_mcp,
        external_model_configured,
        active_model,
        diag_extra,
    ) = await asyncio.gather(
        safe_thread_probe(
            app._probe_owner_runtime,
            timeout_s=probe_timeout_s,
            default=lambda exc: {"ok": False, "error": type(exc).__name__, "execution_verified": False},
        ),
        _bounded_async(app._probe_bridge(), {"ok": False, "transport": "unix-socket"}),
        _bounded_async(app._probe_http(f"{locked_ollama_url}/api/tags"), {"ok": False, "status_code": 0, "url": f"{locked_ollama_url}/api/tags"}),
        _bounded_async(app._probe_http(locked_webui_url), {"ok": False, "status_code": 0, "url": locked_webui_url}),
        _bounded_async(app._probe_native_mcp(), {"ok": False}),
        safe_thread_probe(_read_external_configured, timeout_s=probe_timeout_s, default=False),
        safe_thread_probe(_read_active_model, timeout_s=probe_timeout_s, default="unknown"),
        safe_thread_probe(_collect_store_diag, timeout_s=probe_timeout_s, default={}),
    )

    ollama_required = not bool(external_model_configured)
    checks = {
        "gateway": {"ok": True, "url": f"http://{default_gateway_host}:{default_gateway_port}"},
        "bridge": {**bridge, "required": False},
        "ollama": {**ollama, "required": ollama_required},
        "webui": {**webui_chat, "required": False, "chat_execution_verified": False},
        "native_mcp": dict(native_mcp),
        "owner_runtime": owner,
    }
    checks["native_mcp"]["required"] = not owner.get("ok")
    required_ok = (
        (bool(ollama.get("ok")) or not ollama_required)
        and (bool(owner.get("ok")) or bool(native_mcp.get("ok")))
    )
    all_green = required_ok
    status = "ok" if all_green else "unhealthy"
    payload = {
        "status": status,
        "service": "jaeger-gateway",
        "host": socket.gethostname(),
        "version": jaeger_version,
        "commit": app.source_revision_at_start,
        "model": active_model or "unknown",
        "architecture": "single-engine",
        "persistence_spine": True,
        "agents_api": "/v1/agents",
        "fundamentals_fee_gated": False,
        "fail_closed": True,
        "health_scope": "backend_transport_readiness",
        "all_green": all_green,
        "checks": checks,
        "diagnostics": {
            "source_file": str(Path(__file__).resolve()),
            "background_delivery": app._background_status,
            "session_store": str(app.store.path.resolve()),
            "instance_root": str(app._instance_root()),
            **(diag_extra or {}),
        },
        "capabilities": {
            "native_agent": bool(owner.get("ok")) or bool(native_mcp.get("ok")),
            "transport_ready": bool(native_mcp.get("transport_ready") or native_mcp.get("chat_tool_available")),
            "agent_ready": bool(owner.get("ok")) or bool(native_mcp.get("agent_ready")),
            "execution_verified": bool(native_mcp.get("execution_verified")),
            "end_to_end_chat_verified": False,
        },
        "locked_endpoints": {
            "ollama": locked_ollama_url,
            "webui": locked_webui_url,
            "gateway": f"http://{default_gateway_host}:{default_gateway_port}",
        },
    }
    return web.json_response(payload, status=200 if all_green else 503)
