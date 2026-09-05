#!/usr/bin/env python3
"""Jaeger-owned runtime launcher for the ARES donor host capability MCP server.

DOCTRINE: Upstream ARES is donor code and remains completely clean and untouched.
This launcher sets up the runtime environment, imports donor tools from ARES,
and applies runtime patches for Honcho body serialization and Ollama network discovery.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARES_CONTROLLER = Path("/Users/matthewjenkins/GitHub/ARES/services/controller")

if ARES_CONTROLLER.exists() and str(ARES_CONTROLLER) not in sys.path:
    sys.path.insert(0, str(ARES_CONTROLLER))

# 1. Runtime patch for Honcho client serialization (prevents FastAPI 422 on empty dict payload)
try:
    from core.knowledge.memory.honcho_client import HonchoClient

    _original_request = HonchoClient._request

    def _patched_request(self, method: str, path: str, data: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        # Ensure empty dict {} is serialized as b"{}" instead of being dropped to None
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"error": str(exc)}

    HonchoClient._request = _patched_request
except Exception as e:
    sys.stderr.write(f"[host-capability-launcher] Note: honcho_client patch skipped: {e}\n")

# 2. Import the donor capability MCP server
import host_capability_mcp_server

# 3. Wrap service_status to probe configured network Ollama and report clean errors
try:
    _original_service_status = host_capability_mcp_server.service_status

    def _patched_service_status() -> dict:
        capability = "service.status"
        host_capability_mcp_server._require(capability)
        endpoints = {
            "ares": "http://127.0.0.1:8788/health",
            "jaeger": "http://127.0.0.1:8791/health",
            "n8n": "http://127.0.0.1:5678/healthz",
        }
        result: dict = {}
        for name, url in endpoints.items():
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    response.read(4096)
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

        # Ollama may run on LAN or Tailscale host (Arch PC) rather than localhost loopback
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
                with urllib.request.urlopen(tags_url, timeout=3) as response:
                    response.read(4096)
                    result["ollama"] = {"online": True, "http_status": response.status, "endpoint": candidate}
                    ollama_found = True
                    break
            except Exception:
                continue
        if not ollama_found:
            result["ollama"] = {"online": False, "error": "URLError"}

        host_capability_mcp_server._audit(capability, outcome="allowed")
        return result

    # Replace the tool function implementation
    host_capability_mcp_server.service_status = _patched_service_status
    if hasattr(host_capability_mcp_server, "mcp") and hasattr(host_capability_mcp_server.mcp, "_tool_manager"):
        tm = host_capability_mcp_server.mcp._tool_manager
        if hasattr(tm, "_tools") and "service_status" in tm._tools:
            tm._tools["service_status"].fn = _patched_service_status
except Exception as e:
    sys.stderr.write(f"[host-capability-launcher] Note: service_status patch skipped: {e}\n")


def main() -> None:
    host_capability_mcp_server.mcp.run()


if __name__ == "__main__":
    main()
