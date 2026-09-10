"""System diagnostic and status tools for host capabilities."""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from typing import Any

from .grants import _audit, _grant, _require, _roots, get_current_identity


def capabilities_inspect() -> dict[str, Any]:
    """Show this caller's identity, approved roots, and granted capabilities."""
    grant = _grant()
    identity = get_current_identity()
    roots = [str(r) for r in _roots(grant)]
    capabilities = list(grant.get("capabilities") or [])
    _audit("capabilities.inspect", outcome="allowed")
    return {
        "identity": identity,
        "roots": roots,
        "capabilities": capabilities,
        "count": len(capabilities),
    }


def host_environment() -> dict[str, Any]:
    """Read live Mac identity, canonical repo mapping, and caller workspace grants."""
    _require("capabilities.inspect")
    identity = get_current_identity()
    grant = _grant()
    roots = [str(r) for r in _roots(grant)]
    try:
        from jaeger_ai.core.runtime.host_environment import snapshot
        result = snapshot(roots)
    except Exception:
        result = {"identity": identity, "roots": roots}
    _audit("capabilities.inspect", outcome="allowed")
    return result


def service_status() -> dict[str, Any]:
    """Probe public health endpoints on host, LAN, and Tailscale."""
    capability = "service.status"
    _require(capability)
    endpoints = {
        "ares": "http://127.0.0.1:8788/health",
        "jaeger": "http://127.0.0.1:8791/health",
        "n8n": "http://127.0.0.1:5678/healthz",
    }
    result: dict[str, Any] = {}
    for name, url in endpoints.items():
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                response.read(1024)
                result[name] = {"online": True, "http_status": response.status}
        except urllib.error.HTTPError as exc:
            result[name] = {"online": True, "http_status": exc.code}
        except Exception as exc:
            reason = getattr(exc, "reason", None)
            detail = (
                "Connection refused (service stopped)"
                if isinstance(reason, ConnectionRefusedError)
                else str(reason or type(exc).__name__)
            )
            result[name] = {"online": False, "error": detail}

    # Ollama may run on LAN (10.15.0.239:11434) or Tailscale host
    ollama_candidates = [
        os.environ.get("OLLAMA_BASE_URL", "").rstrip("/"),
        "http://10.15.0.239:11434",
        "http://100.78.245.49:11434",
        "http://127.0.0.1:11434",
    ]
    ollama_found = False
    for candidate in [c for c in ollama_candidates if c]:
        tags_url = f"{candidate}/api/tags" if not candidate.endswith("/api/tags") else candidate
        try:
            with urllib.request.urlopen(tags_url, timeout=2) as response:
                response.read(1024)
                result["ollama"] = {"online": True, "http_status": response.status, "endpoint": candidate}
                ollama_found = True
                break
        except Exception:
            continue
    if not ollama_found:
        result["ollama"] = {"online": False, "error": "Connection refused (service stopped)"}

    _audit(capability, outcome="allowed")
    return result


_RESTARTABLE_SERVICES = {
    "jaeger": ("com.jenkinsrobotics.jaeger-bridge", "http://127.0.0.1:8791/health"),
    "n8n": ("com.jenkinsrobotics.n8n", "http://127.0.0.1:5678/healthz"),
    "ollama": ("com.jenkinsrobotics.ares-ollama", "http://127.0.0.1:11434/api/tags"),
}


def service_restart(service: str) -> dict[str, Any]:
    """Restart one allowlisted host service via launchctl and verify recovery."""
    import subprocess
    import time

    capability = "service.restart"
    _require(capability)
    name = str(service or "").strip().lower()
    if name not in _RESTARTABLE_SERVICES:
        _audit(capability, outcome="denied", requested_service=name)
        return {"restarted": False, "error": f"Service '{name}' is not restartable; allowed: {sorted(_RESTARTABLE_SERVICES)}"}

    label, health_url = _RESTARTABLE_SERVICES[name]
    domain = f"gui/{os.getuid()}"
    try:
        kick = subprocess.run(
            ["/bin/launchctl", "kickstart", "-k", f"{domain}/{label}"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if kick.returncode != 0:
            _audit(capability, outcome="failed", service=name, exit_code=kick.returncode)
            return {"restarted": False, "service": name, "error": kick.stderr.strip() or f"exit {kick.returncode}"}
    except Exception as exc:
        _audit(capability, outcome="error", service=name, error=str(exc))
        return {"restarted": False, "service": name, "error": str(exc)}

    # Wait for service health check
    healthy = False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                if resp.status == 200:
                    healthy = True
                    break
        except Exception:
            pass
        time.sleep(1)

    _audit(capability, outcome="allowed" if healthy else "degraded", service=name, healthy=healthy)
    return {"restarted": True, "service": name, "healthy": healthy}
