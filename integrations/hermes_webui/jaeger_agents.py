"""Proxy WebUI /api/agents* to Jaeger Gateway :8810 /v1/agents*.

Browser clients on :8790 cannot reliably reach loopback :8810; the WebUI
process proxies server-side. Chat spine is Gateway — not ARES :8813.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def gateway_base() -> str:
    return (
        os.environ.get("JAEGER_GATEWAY_URL")
        or os.environ.get("HERMES_WEBUI_GATEWAY_URL")
        or "http://127.0.0.1:8810"
    ).rstrip("/")


def _proxy(handler, method: str, path: str, body: bytes | None = None) -> bool:
    from api.helpers import bad, j

    url = f"{gateway_base()}{path}"
    data = body if method.upper() in {"POST", "PUT", "PATCH"} else None
    req = Request(url, data=data, method=method.upper())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=8) as resp:
            payload = resp.read()
            try:
                parsed = json.loads(payload.decode("utf-8") or "null")
            except json.JSONDecodeError:
                return bad(handler, "gateway returned non-JSON", 502)
            return j(handler, parsed, status=int(getattr(resp, "status", 200) or 200))
    except HTTPError as exc:
        raw = exc.read() or b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            parsed = {"error": exc.reason}
        return j(handler, parsed, status=int(exc.code))
    except (OSError, URLError) as exc:
        return bad(handler, f"gateway unreachable: {exc}", 503)


def route(handler, parsed, method: str) -> bool:
    """Return True if this request was handled (success or error response)."""
    path = parsed.path or ""
    method = (method or "GET").upper()

    if method == "GET" and path in {"/api/agents", "/v1/agents"}:
        qs = ("?" + parsed.query) if parsed.query else ""
        return _proxy(handler, "GET", f"/v1/agents{qs}")

    if method == "GET" and (
        path.startswith("/api/agents/") or path.startswith("/v1/agents/")
    ):
        suffix = path.split("/agents/", 1)[-1]
        if suffix and "/activate" not in suffix:
            return _proxy(handler, "GET", f"/v1/agents/{suffix}")
        return False

    if method == "POST" and path in {"/api/agents", "/v1/agents"}:
        raw = getattr(handler, "_json_body_bytes", None)
        if raw is None:
            from api.helpers import read_body

            raw = json.dumps(read_body(handler) or {}).encode("utf-8")
        return _proxy(handler, "POST", "/v1/agents", raw)

    if method == "POST" and path.endswith("/activate") and (
        path.startswith("/api/agents/") or path.startswith("/v1/agents/")
    ):
        suffix = path.split("/agents/", 1)[-1]
        return _proxy(handler, "POST", f"/v1/agents/{suffix}")

    if method == "POST" and path.endswith("/handoff") and (
        path.startswith("/api/agents/") or path.startswith("/v1/agents/")
    ):
        suffix = path.split("/agents/", 1)[-1]
        raw = getattr(handler, "_json_body_bytes", None)
        if raw is None:
            from api.helpers import read_body

            raw = json.dumps(read_body(handler) or {}).encode("utf-8")
        return _proxy(handler, "POST", f"/v1/agents/{suffix}", raw)

    if method == "GET" and path in {"/api/handoffs", "/v1/handoffs"}:
        return _proxy(handler, "GET", "/v1/handoffs")

    return False
