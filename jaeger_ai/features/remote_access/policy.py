"""Fail-closed network and bearer-token policy for remote Jaeger surfaces."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass

_TAILSCALE_NETWORKS = ("100.64.0.0/10", "fd7a:115c:a1e0::/48")


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    status: int
    reason: str


class RemoteAccessPolicy:
    """Authorize loopback directly and remote peers with two independent gates.

    A remote request must originate from a configured trusted network and must
    carry the configured bearer token. Forwarding headers are intentionally
    ignored: a reverse proxy must pass its actual trusted source address or be
    configured as an explicit network.
    """

    def __init__(
        self,
        *,
        token: str = "",
        trusted_networks: tuple[str, ...] = _TAILSCALE_NETWORKS,
        remote_enabled: bool = False,
    ) -> None:
        self._token = token
        self.remote_enabled = remote_enabled
        self.trusted_networks = tuple(
            ipaddress.ip_network(value, strict=True) for value in trusted_networks
        )

    @classmethod
    def from_environment(cls, *, remote_enabled: bool = False) -> RemoteAccessPolicy:
        raw = os.environ.get("JAEGER_REMOTE_TRUSTED_NETWORKS", "").strip()
        networks = tuple(item.strip() for item in raw.split(",") if item.strip())
        return cls(
            token=os.environ.get("JAEGER_REMOTE_ACCESS_TOKEN", "").strip(),
            trusted_networks=networks or _TAILSCALE_NETWORKS,
            remote_enabled=remote_enabled,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def authorize(self, client_ip: str, headers: Mapping[str, str]) -> AccessDecision:
        network = self.authorize_network(client_ip)
        if not network.allowed:
            return network
        if network.reason == "loopback":
            return network
        if self._valid_session(headers.get("Cookie", "")):
            return AccessDecision(True, 200, "authenticated remote session")
        authorization = headers.get("Authorization", "")
        scheme, separator, supplied = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer":
            return AccessDecision(False, 401, "bearer token or login session required")
        if not hmac.compare_digest(supplied.strip(), self._token):
            return AccessDecision(False, 401, "invalid bearer token")
        return AccessDecision(True, 200, "trusted remote peer")

    def authorize_network(self, client_ip: str) -> AccessDecision:
        """Check only the network boundary for authentication entry points."""
        try:
            address = ipaddress.ip_address(client_ip.split("%", 1)[0])
        except ValueError:
            return AccessDecision(False, 403, "invalid client address")
        if address.is_loopback:
            return AccessDecision(True, 200, "loopback")
        if not self.remote_enabled:
            return AccessDecision(False, 403, "remote access is disabled")
        if not any(address in network for network in self.trusted_networks):
            return AccessDecision(False, 403, "client is outside trusted networks")
        if not self._token:
            return AccessDecision(False, 503, "remote access token is not configured")
        return AccessDecision(True, 200, "trusted remote network")

    def issue_session(self, subject: str, *, lifetime_seconds: int = 28_800) -> str:
        """Issue an HMAC-signed, bounded browser session cookie value."""
        if not self._token:
            raise RuntimeError("remote access token is not configured")
        now = int(time.time())
        payload = json.dumps(
            {"sub": str(subject)[:256], "iat": now, "exp": now + lifetime_seconds},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
        signature = hmac.new(self._session_key(), encoded.encode(), hashlib.sha256).digest()
        return f"{encoded}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"

    def _valid_session(self, cookie_header: str) -> bool:
        value = next(
            (
                part.split("=", 1)[1].strip()
                for part in cookie_header.split(";")
                if part.strip().startswith("jaeger_session=")
            ),
            "",
        )
        encoded, separator, raw_signature = value.partition(".")
        if separator != "." or not encoded or not raw_signature or not self._token:
            return False
        try:
            signature = base64.urlsafe_b64decode(raw_signature + "=" * (-len(raw_signature) % 4))
            expected = hmac.new(self._session_key(), encoded.encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return False
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            payload = json.loads(raw)
            now = int(time.time())
            return (
                isinstance(payload, dict)
                and bool(payload.get("sub"))
                and int(payload.get("iat", 0)) <= now + 60
                and now < int(payload.get("exp", 0))
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            return False

    def _session_key(self) -> bytes:
        return hashlib.sha256(("jaeger-session-v1:" + self._token).encode()).digest()
