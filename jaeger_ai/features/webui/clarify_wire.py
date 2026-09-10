"""Wire mid-turn clarify to the vendored Hermes WebUI clarify API.

Prefer this module over a new ``features/clarify/`` folder: the HTTP/SSE
surface already lives in ``vendor/hermes-webui/api/clarify.py`` and is
mounted by the chat face on :8790. Agent-side Hermes tools
(``clarify_tool.py`` / ``clarify_gateway.py``) are donors for a later
loop integration; this file only documents and re-exports the product
entry points Jaeger should call.
"""

from __future__ import annotations

from typing import Any

# Public routes already served by vendor hermes-webui (chat UI :8790):
CLARIFY_PENDING_PATH = "/api/clarify/pending"
CLARIFY_RESPOND_PATH = "/api/clarify/respond"
CLARIFY_STREAM_PATH = "/api/clarify/stream"

DEFAULT_TIMEOUT_SECONDS = 120


def vendor_clarify_module() -> str:
    """Import path of the authoritative clarify state module."""
    return "api.clarify"  # resolved inside vendor/hermes-webui runtime


def describe_wire() -> dict[str, Any]:
    """Machine-readable note for adapters / docs / tests."""
    return {
        "mode": "wire",
        "authority": "vendor/hermes-webui/api/clarify.py",
        "chat_port": 8790,
        "routes": {
            "pending": CLARIFY_PENDING_PATH,
            "respond": CLARIFY_RESPOND_PATH,
            "stream": CLARIFY_STREAM_PATH,
        },
        "donor_tools": [
            "hermes-agent/tools/clarify_tool.py",
            "hermes-agent/tools/clarify_gateway.py",
        ],
        "todo": "Bind jaeger-agent loop ask-user path to WebUI clarify submit/resolve",
    }
