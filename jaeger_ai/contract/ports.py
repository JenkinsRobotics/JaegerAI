"""Every port JaegerAI binds, named once.

Ports are the classic value typed twice. There were 149 bare literals across
this repo when this module was written, and a dead earlier copy of this file
defined ``ANIMATION_BRIDGE_DEFAULT_PORT = 9999`` while the live definition in
:mod:`jaeger_os.contract.ports` said ``8765`` — the same constant name, two
files, two answers. Anyone grepping the name found both.

These are **defaults**. Almost every service takes an override (a CLI flag, an
env var, an instance setting); this module says what the number is when nobody
overrode it, so a reader has one place to look instead of a grep that returns
twenty-six hits for ``8810``.

Animation-bridge and JP01 hardware ports are NOT here. They belong to the
engine, not the app, and live in :mod:`jaeger_os.contract.ports` — importing
them from there is correct, and re-declaring them here is what created the
9999-vs-8765 split in the first place.
"""
from __future__ import annotations

import os
from typing import Final

LOOPBACK: Final = "127.0.0.1"
"""Bind address for everything that must not leave the machine."""

CONTAINER_HOST: Final = os.environ.get("JAEGER_CONTAINER_HOST", "192.168.64.1")
"""Mac host address visible from Apple Container guests."""

# ── the chat spine ───────────────────────────────────────────────────────

GATEWAY_PORT: Final = 8810
"""Jaeger Gateway — sessions, SSE events, approvals. Started by
``jaeger gateway daemon``. The one every client connects to.
Serves ``/health``, *not* ``/v1/health``."""

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

# ── framework sidecars ───────────────────────────────────────────────────

HERMES_NATIVE_API_PORT: Final = 8645
"""Hermes' native API inside its container."""

DISPATCHER_SIDECAR_PORT: Final = 8646
"""Token-authenticated loopback proxy the Dispatcher board talks to."""

OLLAMA_PORT: Final = 11434
"""Default local Ollama HTTP API."""

__all__ = [
    "A2A_GATEWAY_PORT",
    "A2A_PORT",
    "CONTAINER_HOST",
    "DISPATCHER_SIDECAR_PORT",
    "GATEWAY_PORT",
    "HERMES_NATIVE_API_PORT",
    "LOOPBACK",
    "OLLAMA_PORT",
    "MCP_GATEWAY_PORT",
    "MCP_GATEWAY_URL",
    "OLLAMA_OPENAI_URL",
    "OLLAMA_PORT",
    "OLLAMA_URL",
    "WEBUI_ADAPTER_PORT",
    "WEBUI_PORT",
]
