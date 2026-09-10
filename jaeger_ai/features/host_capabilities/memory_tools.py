"""Memory tools backed natively by Honcho shared memory."""

from __future__ import annotations

from typing import Any

from jaeger_ai.features.shared_memory.honcho_client import HonchoClient
from .grants import _audit, _require, get_current_identity


def _client() -> HonchoClient:
    return HonchoClient()


def memory_status() -> dict[str, Any]:
    """Inspect Honcho shared memory server status and peer representation."""
    capability = "memory.context"
    _require(capability)
    client = _client()
    healthy = client.health()
    identity = get_current_identity()
    peer_card = client.get_peer_card(identity) if healthy else {}
    _audit(capability, outcome="allowed")
    return {
        "online": healthy,
        "base_url": client.base_url,
        "workspace": client.workspace,
        "peer_id": identity,
        "peer_card": peer_card,
    }


def memory_query(query: str, session_id: str = "") -> dict[str, Any]:
    """Query semantic recall and past session conclusions in Honcho."""
    capability = "memory.query"
    _require(capability)
    client = _client()
    results = client.search(query, session_id=session_id)
    conclusions = client.query_conclusions(query)
    _audit(capability, outcome="allowed")
    return {"query": query, "search_results": results, "conclusions": conclusions}


def memory_context(session_id: str = "") -> dict[str, Any]:
    """Retrieve active session context and dialectic summary from Honcho."""
    capability = "memory.context"
    _require(capability)
    client = _client()
    identity = get_current_identity()
    context = client.get_session_context(session_id) if session_id else client.get_peer_context(identity)
    _audit(capability, outcome="allowed")
    return {"session_id": session_id, "context": context}


def memory_add(session_id: str, content: str, peer_id: str = "") -> dict[str, Any]:
    """Add a message or factual observation into Honcho shared memory."""
    capability = "memory.context"
    _require(capability)
    client = _client()
    caller_peer = peer_id or get_current_identity()
    result = client.add_message(session_id, caller_peer, content)
    _audit(capability, outcome="allowed")
    return {"added": True, "session_id": session_id, "result": result}
