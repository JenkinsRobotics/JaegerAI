"""Native background results enter the same durable conversation as chat."""
from __future__ import annotations

import uuid
from typing import Any

from jaeger_ai.core.runtime.heartbeat import is_silent_ok
from jaeger_ai.core.sessions import get_store


def record_result(layout: Any, result: dict[str, Any], *, source: str,
                  source_session: str, display_name: str,
                  delivery_id: str | None = None) -> dict[str, Any] | None:
    failed = bool(result.get("error") or result.get("halt_reason")
                  or result.get("cancelled") or result.get("execution_unknown"))
    text = str(result.get("text") or "").strip()
    if not failed and (not text or (source == "heartbeat" and is_silent_ok(text))):
        return None
    status = ("execution_unknown" if result.get("execution_unknown") else
              "cancelled" if result.get("cancelled") or result.get("halt_reason") == "interrupted" else
              "failed" if failed else "completed")
    if failed:
        reason = str(result.get("error") or result.get("halt_reason") or status)
        text = f"Background {source} {status}: {reason}" + (f"\n\nPartial output:\n{text}" if text else "")
    store = get_store(layout)
    if store is None:
        raise RuntimeError("Background conversation storage unavailable")
    instance = layout.root.name
    return store.record_background(delivery_id or uuid.uuid4().hex, {
        "session_id": "dispatcher", "profile": instance,
        "agent_id": f"native:{instance}", "display_name": display_name,
        "source": source, "source_session": source_session,
        "status": status, "text": text,
    })
