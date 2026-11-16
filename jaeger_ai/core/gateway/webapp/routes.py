"""The two helpers other web app modules still import from the old routes module."""
from __future__ import annotations
import json


def _jaeger_gateway_bases() -> list[str]:
    from api.jaeger_sessions import gateway_base
    return [gateway_base()]


def _handle_approval_respond(handler, body: dict) -> bool:
    from api.jaeger_sessions import _proxy
    from urllib.parse import quote
    choice = str(body.get("choice") or "once")
    payload = {"approved": choice != "deny", "decision": choice}
    return _proxy(handler, "POST", f"/v1/approvals/{quote(str(body.get('approval_id') or ''), safe='')}",
                  json.dumps(payload).encode("utf-8"))
