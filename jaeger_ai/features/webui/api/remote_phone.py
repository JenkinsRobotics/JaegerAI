"""Phone/PWA remote-access endpoints overlaid on the WebUI."""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs

from api.helpers import j


def route(handler, parsed, method: str) -> bool:
    path = parsed.path or ""
    method = (method or "GET").upper()
    if not path.startswith("/api/remote/"):
        return False

    if method == "POST" and path == "/api/remote/pair":
        return _pair(handler)
    if method == "GET" and path == "/api/remote/phone-status":
        return _phone_status(handler)
    if method == "GET" and path == "/api/remote/devices":
        return _devices(handler)
    if method == "POST" and path == "/api/remote/devices/revoke":
        return _revoke(handler)
    if method == "POST" and path == "/api/remote/devices/revoke-all":
        return _revoke_all(handler)
    return False


def _read_json(handler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        length = 0
    raw = handler.rfile.read(max(0, min(length, 64_000))) if length else b"{}"
    try:
        from api.helpers import mark_request_body_consumed
        mark_request_body_consumed(handler)
    except Exception:
        pass
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _pair(handler):
    from jaeger_ai.features.remote_access.service import consume_pairing_token
    from api.auth import create_session, csrf_token_for_session

    body = _read_json(handler)
    qs = parse_qs(parsed_query(handler) or "")
    token = str(body.get("token") or (qs.get("pair") or [""])[0] or "").strip()
    if not token or not consume_pairing_token(token):
        return j(handler, {"ok": False, "error": "invalid or expired pairing token"}, status=401)
    ua = handler.headers.get("User-Agent") or ""
    device = "iPhone" if "iPhone" in ua else ("iPad" if "iPad" in ua else "Phone")
    cookie = create_session(auth_type="pair", username="operator", remote=True, device=device, user_agent=ua)
    from api.auth import _auth_cookie_header, _queue_pending_cookie
    _queue_pending_cookie(handler, _auth_cookie_header(cookie, handler))
    return j(handler, {
        "ok": True,
        "device": device,
        "csrf": csrf_token_for_session(cookie),
        "authenticated": True,
    })


def parsed_query(handler) -> str:
    try:
        return handler.path.split("?", 1)[1]
    except Exception:
        return ""


def _phone_status(handler):
    compact = {
        "online": True,
        "current": "Idle",
        "background": 0,
        "last_activity": "",
        "needs_attention": "none",
        "entity_id": "",
        "instance": "",
        "resident": False,
        "gateway": "unknown",
    }
    try:
        from api.jaeger_sessions import gateway_base
        from urllib.request import Request, urlopen
        req = Request(gateway_base() + "/v1/runtime/status", headers={"Accept": "application/json"})
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        agent = data.get("Agent") or {}
        compact["entity_id"] = str(agent.get("entity_id") or "")
        compact["resident"] = bool(data.get("resident") or (data.get("ownership") or {}).get("resident"))
        compact["gateway"] = "READY" if data.get("ready") else "DOWN"
        compact["instance"] = str(data.get("instance") or data.get("instance_name") or "")
        activity = str(data.get("activity") or data.get("state") or "")
        compact["current"] = activity or ("Idle" if data.get("ready") else "Unreachable")
    except Exception:
        compact["online"] = False
        compact["current"] = "Unreachable"
        compact["gateway"] = "UNREACHABLE"
    return j(handler, compact)


def _devices(handler):
    from api.auth import list_sessions
    sessions = list_sessions()
    return j(handler, {"ok": True, "devices": sessions})


def _revoke(handler):
    from api.auth import revoke_session_prefix
    body = _read_json(handler)
    prefix = str(body.get("id") or body.get("prefix") or "")
    n = revoke_session_prefix(prefix)
    return j(handler, {"ok": n > 0, "revoked": n})


def _revoke_all(handler):
    from api.auth import revoke_remote_sessions
    n = revoke_remote_sessions()
    return j(handler, {"ok": True, "revoked": n})
