"""Minimal Gateway client for the relay (``channels`` caller credential)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

BASE = os.environ.get("JAEGER_GATEWAY_URL", "http://127.0.0.1:33418").rstrip("/")


class GatewayError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status


def _headers() -> dict[str, str]:
    from jaeger_ai.core.gateway.caller_auth import client_headers
    return {"Content-Type": "application/json", **client_headers("channels")}


def call(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 30) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read().decode("utf-8")).get("error") or exc.reason
        except Exception:  # noqa: BLE001
            msg = str(exc.reason)
        raise GatewayError(exc.code, str(msg)) from None
    return json.loads(raw) if raw else {}


def q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def home_session(agent_id: str) -> str:
    return str(call("GET", f"/v1/agents/{q(agent_id)}/home").get("session_id") or "agent-native:jaeger")
