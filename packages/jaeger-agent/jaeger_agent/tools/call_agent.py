"""Agents-as-tools stub — lead calls a standing specialist via Gateway handoff.

Honest stub: records handoff + optional approval on Gateway :8810. Does not
claim a live multi-agent turn until that is proven end-to-end. Approvals reuse
the existing Gateway ``/v1/approvals/{id}`` path (not a second local tier gate).
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jaeger_os.core.tools.tool_registry import register_tool_from_function


def _gateway_base() -> str:
    return (os.environ.get("JAEGER_GATEWAY_URL") or "http://127.0.0.1:8810").rstrip("/")


def _post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    url = f"{_gateway_base()}{path}"
    raw = json.dumps(body).encode("utf-8")
    req = Request(url, data=raw, method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            return {"error": json.loads(detail), "http_status": int(exc.code)}
        except json.JSONDecodeError:
            return {"error": detail or exc.reason, "http_status": int(exc.code)}
    except (OSError, URLError) as exc:
        return {"error": f"gateway unreachable: {exc}", "http_status": 503}


@register_tool_from_function(name="call_agent", side_effect="read")
def call_agent(
    agent_id: str,
    task: str,
    *,
    require_approval: bool = True,
    from_agent_id: str = "native:jaeger",
) -> dict[str, Any]:
    """Hand a task to a standing specialist (Surfaces / Gateway / Everyday).

    Uses Gateway ``POST /v1/agents/{id}/handoff``. When ``require_approval`` is
    true, Gateway emits ``approval.request`` and waits on
    ``POST /v1/approvals/{id}`` — same pull-in path as other gated ops.

    This is a **stub**: it records the handoff for product wiring; it does not
    yet run a live specialist turn.
    """
    target = (agent_id or "").strip()
    work = (task or "").strip()
    if not target:
        return {"ok": False, "error": "agent_id is required"}
    if not work:
        return {"ok": False, "error": "task is required"}

    try:
        from jaeger_ai.core.agent_registry import get_default_registry

        record = get_default_registry().get_agent(target)
        if record is None:
            return {
                "ok": False,
                "error": f"unknown agent: {target}",
                "hint": "Use native:surfaces, native:gateway, or native:everyday",
            }
        target = record.id
    except Exception:
        pass

    payload = _post_json(
        f"/v1/agents/{target}/handoff",
        {
            "task": work,
            "from_agent_id": from_agent_id or "native:jaeger",
            "require_approval": bool(require_approval),
        },
    )
    if "error" in payload and "id" not in payload:
        return {"ok": False, **payload}
    return {
        "ok": True,
        "stub": True,
        "note": (
            "Handoff recorded; live multi-agent turn not claimed until "
            "product acceptance P6 is proven green."
        ),
        "handoff": payload,
    }
