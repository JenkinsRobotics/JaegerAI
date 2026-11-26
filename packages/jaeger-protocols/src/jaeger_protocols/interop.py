"""AG-UI, A2UI, and ACP protocol translators (adapted from AG2 & Hermes specs)."""

from __future__ import annotations

import time
import uuid
from typing import Any, Mapping


def to_agui_event(jaeger_event: str, payload: Mapping[str, Any], *, run_id: str = "") -> dict[str, Any]:
    """Translate a Jaeger Gateway SSE event into an AG-UI standard protocol frame."""
    mapping = {
        "run.started": "RUN_STARTED",
        "text.delta": "TEXT_MESSAGE_CONTENT",
        "thinking.delta": "THINKING_TEXT_MESSAGE_CONTENT",
        "tool.started": "TOOL_CALL_START",
        "tool.completed": "TOOL_CALL_RESULT",
        "run.completed": "RUN_FINISHED",
        "run.failed": "RUN_ERROR",
    }
    return {
        "protocol": "ag-ui/1",
        "type": mapping.get(jaeger_event, "CUSTOM"),
        "name": jaeger_event,
        "runId": run_id or str(payload.get("request_id") or ""),
        "timestamp": int(time.time() * 1000),
        "payload": dict(payload),
    }


def build_a2ui_surface(surface_id: str, title: str, components: list[dict[str, Any]]) -> dict[str, Any]:
    """Emit a declarative A2UI v0.8 component surface envelope for rich agent-rendered cards."""
    return {
        "protocol": "a2ui/0.8",
        "surfaceId": surface_id or f"surf_{uuid.uuid4().hex[:8]}",
        "title": title,
        "components": list(components),
    }


def to_acp_jsonrpc(method: str, params: Mapping[str, Any], *, req_id: str | int | None = None) -> dict[str, Any]:
    """Encode an Agent Client Protocol (ACP) JSON-RPC 2.0 frame for Zed / JetBrains / IDEs."""
    frame: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": dict(params)}
    if req_id is not None:
        frame["id"] = req_id
    return frame


__all__ = ["build_a2ui_surface", "to_acp_jsonrpc", "to_agui_event"]
