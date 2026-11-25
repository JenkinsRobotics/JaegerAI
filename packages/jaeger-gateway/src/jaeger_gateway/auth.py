"""Fail-closed HTTP & WebSocket authentication and Origin verification."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    actor: str = "anonymous"
    reason: str = ""
    scopes: frozenset[str] = frozenset()


@dataclass
class GatewayAuthPolicy:
    """Fail-closed token + WebSocket Origin guard.

    - If ``tokens`` is configured (mapping token -> actor or scopes), requests
      MUST carry a matching ``Authorization: Bearer <token>`` or
      ``X-Jaeger-Token: <token>`` verified via constant-time ``hmac.compare_digest``.
    - If ``tokens`` is empty and ``allow_loopback_unauthenticated`` is False
      (the fail-closed default), ALL requests are denied.
    - WebSocket upgrades additionally enforce Origin allowlisting to prevent
      cross-site WebSocket hijacking (CSWSH).
    """

    tokens: Mapping[str, str] = field(default_factory=dict)
    allow_loopback_unauthenticated: bool = False
    allowed_origins: frozenset[str] = frozenset({
        "http://127.0.0.1",
        "http://localhost",
        "https://127.0.0.1",
        "https://localhost",
        "tauri://localhost",
        "vscode-webview://",
    })
    ws_enabled: bool = True

    def verify_http(
        self,
        headers: Mapping[str, str],
        *,
        remote_addr: str = "",
    ) -> AuthDecision:
        token = self._extract_token(headers)
        if token:
            for secret, actor in self.tokens.items():
                if hmac.compare_digest(token, secret):
                    return AuthDecision(allowed=True, actor=actor, scopes=frozenset({"*"}))
            return AuthDecision(allowed=False, reason="invalid bearer token")

        if self.allow_loopback_unauthenticated and self._is_loopback(remote_addr):
            return AuthDecision(allowed=True, actor="owner:loopback", scopes=frozenset({"*"}))
        return AuthDecision(allowed=False, reason="missing credentials (fail-closed)")

    def verify_websocket(
        self,
        headers: Mapping[str, str],
        *,
        remote_addr: str = "",
    ) -> AuthDecision:
        if not self.ws_enabled:
            return AuthDecision(allowed=False, reason="websocket transport is disabled")
        origin = self._header(headers, "origin")
        if origin and not self._origin_allowed(origin):
            return AuthDecision(allowed=False, reason=f"disallowed websocket origin: {origin!r}")
        return self.verify_http(headers, remote_addr=remote_addr)

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str:
        low = name.lower()
        for k, v in headers.items():
            if k.lower() == low:
                return str(v or "").strip()
        return ""

    def _extract_token(self, headers: Mapping[str, str]) -> str:
        auth = self._header(headers, "authorization")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return self._header(headers, "x-jaeger-token")

    @staticmethod
    def _is_loopback(remote_addr: str) -> bool:
        host = (remote_addr or "").strip().lower()
        return host in _LOOPBACK_HOSTS

    def _origin_allowed(self, origin: str) -> bool:
        raw = origin.strip().lower()
        if any(raw.startswith(prefix) for prefix in self.allowed_origins):
            return True
        parsed = urlparse(raw)
        base = f"{parsed.scheme}://{parsed.hostname}" if parsed.scheme and parsed.hostname else ""
        return base in self.allowed_origins


__all__ = ["AuthDecision", "GatewayAuthPolicy"]
