"""Canonical resident runtime status projection (PRODUCTION OS SPEC Part 6)."""

from __future__ import annotations

from enum import Enum
import os
import socket
import time
from typing import Any


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    DISABLED = "DISABLED"


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _git_commit() -> str:
    try:
        import subprocess
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            timeout=2,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return ""


def collect_runtime_status(*, include_network: bool = True) -> dict[str, Any]:
    from jaeger_ai import __version__ as version
    from jaeger_ai.core.entity.ownership import ownership_projection
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.instance.instance import default_instance_name

    started = time.time()
    try:
        runtime = EntityRuntime.get_singleton()
        own = ownership_projection(runtime)
        entity_health = HealthStatus.HEALTHY.value
        fabric_health = HealthStatus.HEALTHY.value
        memory_health = HealthStatus.HEALTHY.value
        try:
            runtime.event_store.count()
        except Exception:
            fabric_health = HealthStatus.FAILED.value
        try:
            runtime.memory_subsystem.episodic  # noqa: B018
        except Exception:
            memory_health = HealthStatus.DEGRADED.value
        uptime = max(0.0, time.time() - float(getattr(runtime.identity, "created_at", started) or started))
        goals = len(getattr(runtime.current_state, "active_goals", []) or [])
    except Exception as exc:
        own = {"entity_id": None, "error": str(exc)}
        entity_health = HealthStatus.FAILED.value
        fabric_health = HealthStatus.FAILED.value
        memory_health = HealthStatus.FAILED.value
        uptime = 0.0
        goals = 0
        runtime = None

    gateway_ok = _port_open(8810) if include_network else False
    webui_ok = _port_open(8790) if include_network else False
    bridge_ok = False
    if include_network:
        try:
            from jaeger_ai.contract.ports import WEBUI_ADAPTER_PORT
            bridge_ok = _port_open(int(WEBUI_ADAPTER_PORT))
        except Exception:
            bridge_ok = _port_open(8791)

    provider = {
        "active_chat_provider": os.environ.get("JAEGER_CHAT_PROVIDER") or "",
        "active_react_provider": "",
        "planner_provider": "",
        "critic_provider": "",
    }
    try:
        from jaeger_ai.core.entity.model_capabilities import load_capabilities, certified_for
        caps = load_capabilities(getattr(runtime, "state_root", None) if runtime else None)
        provider["active_react_provider"] = certified_for("react", caps) or ""
        provider["active_chat_provider"] = certified_for("chat", caps) or provider["active_chat_provider"]
        provider["planner_provider"] = certified_for("planning", caps) or certified_for("react", caps) or ""
        provider["critic_provider"] = certified_for("critic", caps) or provider["planner_provider"]
    except Exception:
        pass

    services = {
        "gateway": HealthStatus.HEALTHY.value if gateway_ok else HealthStatus.FAILED.value,
        "bridge": HealthStatus.HEALTHY.value if bridge_ok else HealthStatus.DISABLED.value,
        "webui": HealthStatus.HEALTHY.value if webui_ok else HealthStatus.DISABLED.value,
    }

    ready = (
        entity_health == HealthStatus.HEALTHY.value
        and fabric_health == HealthStatus.HEALTHY.value
        and services["gateway"] == HealthStatus.HEALTHY.value
        and bool(provider.get("active_chat_provider") or provider.get("active_react_provider") or True)
    )

    return {
        "ready": ready,
        "Agent": {
            "entity_id": own.get("entity_id"),
            "instance": own.get("instance_id") or default_instance_name(),
            "version": version,
            "git_commit": _git_commit(),
            "uptime": uptime,
            "status": entity_health,
        },
        "Runtime": {
            "state": own.get("mode") or "unknown",
            "foreground_activity": "idle",
            "latest_event_id": own.get("latest_event_sequence"),
            "event_count": own.get("event_count"),
            "resident": own.get("resident"),
            "status": entity_health,
        },
        "Provider": {**provider, "status": HealthStatus.HEALTHY.value if provider.get("active_react_provider") or provider.get("active_chat_provider") else HealthStatus.DEGRADED.value},
        "Services": services,
        "Background": {
            "heartbeat": HealthStatus.HEALTHY.value if own.get("resident") else HealthStatus.DISABLED.value,
            "sensors": HealthStatus.DISABLED.value,
            "sleep_time": HealthStatus.HEALTHY.value if own.get("resident") else HealthStatus.DISABLED.value,
            "indexing": HealthStatus.DISABLED.value,
            "maintenance": HealthStatus.DISABLED.value,
        },
        "Storage": {
            "event_store": own.get("event_store"),
            "memory_store": str(getattr(getattr(runtime, "layout", None), "memory_dir", "") or own.get("state_root")),
            "writable": fabric_health == HealthStatus.HEALTHY.value,
            "schema_version": 1,
            "status": fabric_health,
            "memory_status": memory_health,
        },
        "Work": {
            "active_goal_count": goals,
            "active_commitment_count": 0,
            "background_jobs": 0,
        },
        "identity": own,
    }
