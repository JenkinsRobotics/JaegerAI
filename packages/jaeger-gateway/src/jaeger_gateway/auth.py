"""Fail-closed HTTP & WebSocket authentication and Origin verification."""

from __future__ import annotations

import hmac
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_RFC1123_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

_PRIVATE_OR_TAILSCALE_V4 = (
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("100.64.0.0/10"),
)

_PRIVATE_OR_TAILSCALE_V6 = (
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
    ipaddress.IPv6Network("fe80::/10"),
    ipaddress.IPv6Network("fd7a:115c:a1e0::/48"),
)


def _is_valid_domain(host: str, *, suffix: str, min_labels: int) -> bool:
    raw = (host or "").strip().lower()
    if not raw or len(raw) > 253:
        return False
    if raw.startswith(".") or raw.endswith(".") or ".." in raw:
        return False
    if not raw.endswith(suffix):
        return False
    labels = raw.split(".")
    if len(labels) < min_labels:
        return False
    return all(_RFC1123_LABEL_RE.fullmatch(label) is not None for label in labels)


def _is_valid_ts_net_host(host: str) -> bool:
    """Return True iff host is a valid Tailscale MagicDNS hostname (*.ts.net)."""
    return _is_valid_domain(host, suffix=".ts.net", min_labels=3)


def _is_valid_local_host(host: str) -> bool:
    """Return True iff host is a valid mDNS .local hostname."""
    return _is_valid_domain(host, suffix=".local", min_labels=2)


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
    - When ``allow_private_network_unauthenticated`` is True, RFC1918 LAN,
      link-local, loopback, and Tailscale CGNAT/ULA remote addresses are allowed
      while public internet IPs remain strictly denied.
    - WebSocket upgrades additionally enforce Origin allowlisting to prevent
      cross-site WebSocket hijacking (CSWSH).
    """

    tokens: Mapping[str, str] = field(default_factory=dict)
    allow_loopback_unauthenticated: bool = False
    allow_private_network_unauthenticated: bool = False
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
            ts_login = self._header(headers, "tailscale-user-login")
            if ts_login:
                safe_login = re.sub(r"[\r\n\s]+", "", ts_login)[:128]
                actor = f"owner:tailscale:{safe_login}" if safe_login else "owner:loopback"
            else:
                actor = "owner:loopback"
            return AuthDecision(allowed=True, actor=actor, scopes=frozenset({"*"}))

        if self.allow_private_network_unauthenticated and self._is_private_or_tailscale(remote_addr):
            return AuthDecision(allowed=True, actor="owner:lan", scopes=frozenset({"*"}))

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
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if host in _LOOPBACK_HOSTS:
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return ip.is_loopback

    @staticmethod
    def _is_private_or_tailscale(remote_addr: str) -> bool:
        raw = (remote_addr or "").strip().lower()
        if not raw:
            return False
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1]
        if raw == "localhost":
            return True
        if "%" in raw and ":" in raw:
            raw = raw.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if isinstance(ip, ipaddress.IPv4Address):
            return any(ip in net for net in _PRIVATE_OR_TAILSCALE_V4)
        return any(ip in net for net in _PRIVATE_OR_TAILSCALE_V6)

    def _origin_allowed(self, origin: str) -> bool:
        raw = origin.strip().lower()
        if not raw:
            return False
        if raw in self.allowed_origins:
            return True
        if any(raw.startswith(prefix) for prefix in self.allowed_origins if prefix.endswith("://")):
            return True
        parsed = urlparse(raw)
        if not parsed.scheme or not parsed.hostname:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
            return False
        try:
            _ = parsed.port
        except ValueError:
            return False
        hostname = parsed.hostname.lower()
        base = f"{parsed.scheme}://{hostname}"
        if base in self.allowed_origins:
            return True
        if parsed.scheme == "https" and _is_valid_ts_net_host(hostname):
            return True
        if self.allow_private_network_unauthenticated and parsed.scheme in ("http", "https"):
            if _is_valid_local_host(hostname) or self._is_private_or_tailscale(hostname):
                return True
        return False


__all__ = ["AuthDecision", "GatewayAuthPolicy"]
