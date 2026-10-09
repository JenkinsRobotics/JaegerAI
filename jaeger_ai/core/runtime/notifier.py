"""jaegerd-owned outbound channels for speak-first messages to the owner.

The Gateway already delivers into the owner's conversation (SSE + the
durable /v1/notifications feed). This adds optional push adapters. Only
channels that reach Matthew himself live here; messaging anyone else stays
an owner-approved external effect.

ntfy (self-hosted, over Tailscale): set ``JAEGER_NTFY_URL`` to a topic URL
such as ``https://matthews-mac-studio.tail80f206.ts.net:8443/ntfy/jaeger``.
Unset means off. The URL must be loopback, a ``*.ts.net`` name or a
Tailscale 100.64.0.0/10 address, so message bodies never leave the tailnet.
An optional token comes from ``JAEGER_NTFY_TOKEN`` and is never logged.
"""
from __future__ import annotations

import ipaddress

import os
import urllib.request
from typing import Any
from urllib.parse import urlparse

_TAILNET = ipaddress.ip_network("100.64.0.0/10")


def tailnet_only(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(host) in _TAILNET
    except ValueError:
        return False


def _ntfy(payload: dict[str, Any]) -> dict[str, Any] | None:
    url = (os.environ.get("JAEGER_NTFY_URL") or "").strip()
    if not url:
        return None
    if not tailnet_only(url):
        return {"channel": "ntfy", "sent": False, "error": "refused: not a loopback/tailnet URL"}
    body = str(payload.get("body") or "").encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Title", str(payload.get("title") or "Jaeger"))
    req.add_header("Priority", "high" if payload.get("salience") == "immediate" else "default")
    req.add_header("Tags", "robot")
    token = (os.environ.get("JAEGER_NTFY_TOKEN") or "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return {"channel": "ntfy", "sent": 200 <= int(resp.status) < 300}
    except Exception as exc:  # noqa: BLE001
        return {"channel": "ntfy", "sent": False, "error": type(exc).__name__}


def fan_out(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort push to every configured owner channel. Never raises."""
    results = []
    for adapter in (_ntfy,):
        try:
            res = adapter(payload)
        except Exception as exc:  # noqa: BLE001
            res = {"channel": adapter.__name__.strip("_"), "sent": False, "error": type(exc).__name__}
        if res is not None:
            results.append(res)
    return results


__all__ = ["fan_out", "tailnet_only"]

