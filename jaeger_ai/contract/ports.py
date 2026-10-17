"""Every port JaegerAI binds, named once.

Ports are the classic value typed twice. There were 149 bare literals across
this repo when this module was written, and a dead earlier copy of this file
defined ``ANIMATION_BRIDGE_DEFAULT_PORT = 9999`` while the live definition in
:mod:`jaeger_os.contract.ports` said ``8765`` — the same constant name, two
files, two answers. Anyone grepping the name found both.

These are **defaults**. Almost every service takes an override (a CLI flag, an
env var, an instance setting); this module says what the number is when nobody
overrode it, so a reader has one place to look instead of a grep that returns
twenty-six hits for a bare port number.

Animation-bridge and JP01 hardware ports are NOT here. They belong to the
engine, not the app, and live in :mod:`jaeger_os.contract.ports` — importing
them from there is correct, and re-declaring them here is what created the
9999-vs-8765 split in the first place.
"""
from __future__ import annotations

import os
import socket
from typing import Callable, Final, Mapping
from urllib.parse import urlsplit

LOOPBACK: Final = "127.0.0.1"
"""Bind address for everything that must not leave the machine."""

CONTAINER_HOST: Final = os.environ.get("JAEGER_CONTAINER_HOST", "192.168.64.1")
"""Mac host address visible from Apple Container guests."""

# ── the chat spine ───────────────────────────────────────────────────────

GATEWAY_PORT: Final = int(os.environ.get("JAEGER_GATEWAY_PORT") or 33418)
"""Jaeger Gateway — sessions, SSE events, approvals. Started by
``jaeger gateway daemon``. The one every client connects to.
Serves ``/health``, *not* ``/v1/health``. ``JAEGER_GATEWAY_PORT`` overrides it
(``JAEGER_GATEWAY_PORT=8810`` is the emergency way back to the old port)."""

GATEWAY_URL: Final = f"http://{LOOPBACK}:{GATEWAY_PORT}"
"""Where clients look for the Gateway first. Loopback only."""

LEGACY_GATEWAY_PORT: Final = 8810
"""The Gateway's port before 2026-10-17. The ONLY place this number lives in
code. Clients fall back to it while installed services (launchd plists,
agentgateway, older extensions) still run the Gateway there; set
``JAEGER_GATEWAY_LEGACY_FALLBACK=0`` to turn the fallback off. Remove once
everything has moved to :data:`GATEWAY_PORT`."""

LEGACY_GATEWAY_URL: Final = f"http://{LOOPBACK}:{LEGACY_GATEWAY_PORT}"
"""The legacy Gateway URL clients try when :data:`GATEWAY_URL` is unreachable."""

WEBUI_PORT: Final = 8790
"""The first-party Jaeger WebUI. What a person opens."""

WEBUI_ADAPTER_PORT: Final = 8791
"""Loopback runner the WebUI calls to execute a turn. Not browser-facing."""

# ── external protocol surfaces ───────────────────────────────────────────

MCP_GATEWAY_PORT: Final = 8811
"""Agentgateway's MCP surface — the third-party binary, not the Jaeger
Gateway above. See ``jaeger_ai/features/agentgateway/``."""

MCP_GATEWAY_URL: Final = os.environ.get(
    "JAEGERS_MCP_URL", f"http://{LOOPBACK}:{MCP_GATEWAY_PORT}/mcp"
).rstrip("/")
"""MCP chat endpoint. Environment overrides are resolved at process start."""

MCP_HTTP_PORT: Final = 8792
"""Jaeger's own loopback MCP backend; Agentgateway proxies to it."""

MCP_HTTP_PATH: Final = "/mcp"
"""Canonical streamable-HTTP MCP route."""

MCP_HTTP_URL: Final = os.environ.get(
    "JAEGER_LOCAL_MCP_URL", f"http://{LOOPBACK}:{MCP_HTTP_PORT}{MCP_HTTP_PATH}"
).rstrip("/")
"""Jaeger's native local MCP server. Local frameworks connect here directly."""

MCP_CONTAINER_GATEWAY_URL: Final = (
    f"http://{CONTAINER_HOST}:{MCP_GATEWAY_PORT}/mcp"
)
"""The same MCP gateway as seen from an Apple Container guest."""

OLLAMA_PORT: Final = 11434
"""Ollama's native HTTP port."""

_OLLAMA_CONFIGURED = (
    os.environ.get("JAEGER_OLLAMA_URL") or os.environ.get("OLLAMA_BASE_URL")
    or f"http://{LOOPBACK}:{OLLAMA_PORT}"
).rstrip("/")
OLLAMA_URL: Final = _OLLAMA_CONFIGURED.removesuffix("/v1")
"""Canonical Ollama native API root with a portable loopback default."""

OLLAMA_OPENAI_URL: Final = OLLAMA_URL + "/v1"
"""The same Ollama endpoint using its OpenAI-compatible API root."""

A2A_GATEWAY_PORT: Final = 8812
"""Agentgateway's agent-to-agent surface; proxies to :data:`A2A_PORT`."""

A2A_PORT: Final = 8796
"""Jaeger's own A2A JSON-RPC server, loopback only. :data:`A2A_GATEWAY_PORT`
is the public door to it."""

A2A_GATEWAY_URL: Final = f"http://{LOOPBACK}:{A2A_GATEWAY_PORT}"
"""Canonical host-side A2A endpoint advertised to local frameworks."""

A2A_CONTAINER_GATEWAY_URL: Final = f"http://{CONTAINER_HOST}:{A2A_GATEWAY_PORT}"
"""Canonical A2A endpoint as seen from an Apple Container guest."""

A2A_URL: Final = f"http://{LOOPBACK}:{A2A_PORT}"
"""Jaeger's native local A2A server. Local frameworks connect here directly."""

# ── framework sidecars ───────────────────────────────────────────────────

HERMES_NATIVE_API_PORT: Final = 8645
"""Hermes' native API inside its container."""

DISPATCHER_SIDECAR_PORT: Final = 8646
"""Token-authenticated loopback proxy the Dispatcher board talks to."""


# ── Gateway discovery (current port first, legacy fallback) ────────────────

_FALSEY = {"0", "false", "no", "off"}


def gateway_legacy_fallback_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether clients may fall back to :data:`LEGACY_GATEWAY_URL`."""
    env = os.environ if environ is None else environ
    return str(env.get("JAEGER_GATEWAY_LEGACY_FALLBACK", "1")).strip().lower() not in _FALSEY


def gateway_candidate_urls(environ: Mapping[str, str] | None = None) -> list[str]:
    """Gateway base URLs a client should try, in order.

    An explicit ``JAEGER_GATEWAY_URL`` is the only candidate: a URL somebody
    typed is never second-guessed. Otherwise the current loopback URL (honouring
    ``JAEGER_GATEWAY_PORT``) comes first and the legacy URL second.
    """
    env = os.environ if environ is None else environ
    explicit = str(env.get("JAEGER_GATEWAY_URL") or "").strip().rstrip("/")
    if explicit:
        return [explicit]
    port = int(env.get("JAEGER_GATEWAY_PORT") or GATEWAY_PORT)
    urls = [f"http://{LOOPBACK}:{port}"]
    if gateway_legacy_fallback_enabled(env) and port != LEGACY_GATEWAY_PORT:
        urls.append(LEGACY_GATEWAY_URL)
    return urls


def _tcp_reachable(url: str, timeout: float) -> bool:
    parts = urlsplit(url)
    host = parts.hostname or LOOPBACK
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_gateway_url(
    environ: Mapping[str, str] | None = None,
    *,
    timeout: float = 0.25,
    reachable: Callable[[str, float], bool] | None = None,
) -> str:
    """The Gateway base URL to use right now.

    The first candidate from :func:`gateway_candidate_urls` that accepts a TCP
    connection wins. If none does, the current URL is returned so error
    messages name where the Gateway is supposed to be.
    """
    candidates = gateway_candidate_urls(environ)
    if len(candidates) == 1:
        return candidates[0]
    probe = reachable or _tcp_reachable
    for url in candidates:
        if probe(url, timeout):
            return url
    return candidates[0]


def is_gateway_port(port: int | None) -> bool:
    """True for the current or the legacy Gateway port."""
    return port is not None and int(port) in {GATEWAY_PORT, LEGACY_GATEWAY_PORT}


__all__ = [
    "A2A_GATEWAY_PORT",
    "A2A_GATEWAY_URL",
    "A2A_CONTAINER_GATEWAY_URL",
    "A2A_URL",
    "A2A_PORT",
    "CONTAINER_HOST",
    "DISPATCHER_SIDECAR_PORT",
    "GATEWAY_PORT",
    "GATEWAY_URL",
    "HERMES_NATIVE_API_PORT",
    "LEGACY_GATEWAY_PORT",
    "LEGACY_GATEWAY_URL",
    "LOOPBACK",
    "MCP_GATEWAY_PORT",
    "MCP_GATEWAY_URL",
    "MCP_CONTAINER_GATEWAY_URL",
    "MCP_HTTP_PATH",
    "MCP_HTTP_PORT",
    "MCP_HTTP_URL",
    "OLLAMA_OPENAI_URL",
    "OLLAMA_PORT",
    "OLLAMA_URL",
    "WEBUI_ADAPTER_PORT",
    "WEBUI_PORT",
    "gateway_candidate_urls",
    "gateway_legacy_fallback_enabled",
    "is_gateway_port",
    "resolve_gateway_url",
]
