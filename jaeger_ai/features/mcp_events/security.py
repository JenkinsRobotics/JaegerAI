"""OAuth resource verification and pinned, public-only HTTPS delivery."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import aiohttp
import jwt

KEYCHAIN_SERVICE = "ai.jaeger.events"
MAX_BYTES = 262144


def secret_bytes(value):
    if not isinstance(value, str) or not value.startswith("whsec_"):
        raise ValueError("Invalid signing secret")
    try:
        raw = base64.b64decode(value[6:], validate=True)
    except (ValueError, TypeError):
        raise ValueError("Invalid signing secret") from None
    if not 24 <= len(raw) <= 64:
        raise ValueError("Invalid signing secret")
    return raw


def signed_headers(secret, subscription, event_id, body, now):
    if len(body) > MAX_BYTES:
        raise ValueError("Payload exceeds 256 KiB")
    stamp = str(int(now))
    signature = base64.b64encode(
        hmac.new(
            secret_bytes(secret),
            event_id.encode() + b"." + stamp.encode() + b"." + body,
            hashlib.sha256,
        ).digest()
    ).decode()
    return {
        "Content-Type": "application/json",
        "webhook-id": event_id,
        "webhook-timestamp": stamp,
        "webhook-signature": "v1," + signature,
        "X-MCP-Subscription-Id": subscription,
    }


def callback_url(value):
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
    ):
        raise ValueError("Invalid HTTPS callback")
    try:
        p = urlsplit(value)
        host = p.hostname or ""
        if (
            p.scheme != "https"
            or p.username is not None
            or p.password is not None
            or p.fragment
            or "\\" in value
            or p.port not in (None, 443)
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or "." not in host
            or host.endswith(".")
        ):
            raise ValueError
        # Literal IPs are unnecessary; reject ambiguous numeric DNS spellings too.
        if all(c in "0123456789." for c in host):
            raise ValueError
        return host
    except ValueError:
        raise ValueError("Invalid HTTPS callback") from None


def public_ip(address):
    if "%" in address:
        raise ValueError("Scoped addresses forbidden")
    ip = ipaddress.ip_address(address)
    # Explicit mapped/transition exclusions; never delegate embedded IPv4 policy.
    special = (
        ["192.0.0.0/24", "192.88.99.0/24"]
        if ip.version == 4
        else ["2001::/23", "3fff::/20"]
    )
    if (
        any(ip in ipaddress.ip_network(net) for net in special)
        or (ip.version == 6 and ip not in ipaddress.ip_network("2000::/3"))
        or not ip.is_global
        or ip.is_multicast
        or ip.is_reserved
        or (
            isinstance(ip, ipaddress.IPv6Address)
            and (ip.ipv4_mapped or ip.sixtofour or ip.teredo)
        )
    ):
        raise ValueError("Non-public destination")
    return str(ip)


class PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, host, records):
        self.host, self.records = host, records

    async def resolve(self, host, port=443, family=socket.AF_UNSPEC):
        if host != self.host or port != 443:
            raise ValueError("Destination changed")
        return [
            {
                "hostname": host,
                "host": ip,
                "port": port,
                "family": fam,
                "proto": socket.IPPROTO_TCP,
                "flags": 0,
            }
            for fam, ip in self.records
        ]

    async def close(self):
        pass


class PublicHTTPS:
    """Resolve afresh per POST; pin all answers. TLS uses the original URL host.

    No proxy environment, redirects, DNS cache, or pooled/reused connection.
    Test receivers inject a separate transport; this class has no local bypass.
    """

    async def post(self, url, body, headers):
        host = callback_url(url)
        async with asyncio.timeout(10):
            records = await asyncio.get_running_loop().getaddrinfo(
                host,
                443,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            addresses = sorted({(r[0], public_ip(r[4][0])) for r in records})
            if not addresses:
                raise ValueError("No public destination")
            connector = aiohttp.TCPConnector(
                resolver=PinnedResolver(host, addresses),
                use_dns_cache=False,
                force_close=True,
            )
            async with (
                aiohttp.ClientSession(
                    connector=connector,
                    trust_env=False,
                    auto_decompress=False,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as client,
                client.post(
                    url, data=body, headers=headers, allow_redirects=False
                ) as response,
            ):
                try:
                    raw = await response.content.readexactly(MAX_BYTES + 1)
                except asyncio.IncompleteReadError as exc:
                    raw = exc.partial
                if len(raw) > MAX_BYTES:
                    raise ValueError("Response too large")
                return response.status, raw


class KeychainSecrets:
    """Explicit native runtime adapter; tests replace its backend.

    Stores one JSON key bundle per subscription. Caller must separately approve
    production Keychain setup. Values are never included in exceptions/logs.
    """

    @staticmethod
    def backend():
        # Explicit maintained macOS backend, never plaintext/fallback keyrings.
        from keyring.backends.macOS import Keyring

        return Keyring()

    def get(self, account):
        value = self.backend().get_password(KEYCHAIN_SERVICE, account)
        if value is None:
            raise RuntimeError("Events secret unavailable")
        return json.loads(value)

    def put(self, account, value):
        self.backend().set_password(KEYCHAIN_SERVICE, account, json.dumps(value))

    def delete(self, account):
        from keyring.errors import PasswordDeleteError

        try:
            self.backend().delete_password(KEYCHAIN_SERVICE, account)
        except PasswordDeleteError:
            # Idempotent deletion only if the backend confirms absence.
            if self.backend().get_password(KEYCHAIN_SERVICE, account) is not None:
                raise RuntimeError("Events secret revocation failed") from None


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: frozenset[str]
    expires: float


class OAuthVerifier:
    """Real JWT resource-server verification using administrator-pinned RS256 key.

    Identity-provider authorization-code/PKCE and consent remain external. A key
    is pinned per deployment (no untrusted jku/x5u/JWKS URL fetching).
    """

    def __init__(self, issuer, audience, public_key, subject):
        for url in (issuer, audience):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or any(ord(c) <= 32 or c in '"\\' for c in url)
            ):
                raise ValueError("Canonical OAuth identifiers must use HTTPS")
        self.issuer, self.audience = issuer, audience
        self.public_key, self.subject = public_key, subject

    def check_metadata(self, metadata):
        if (
            metadata.get("issuer") != self.issuer
            or "S256" not in metadata.get("code_challenge_methods_supported", [])
            or not set(metadata.get("token_endpoint_auth_methods_supported", []))
            & {"none", "private_key_jwt", "client_secret_post", "client_secret_basic"}
        ):
            raise ValueError("OAuth 2.1/PKCE metadata required")
        for name in ("authorization_endpoint", "token_endpoint"):
            endpoint = urlsplit(metadata.get(name, ""))
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.fragment
            ):
                raise ValueError("Invalid OAuth endpoint metadata")

    def verify(self, header):
        if (
            not isinstance(header, str)
            or not header.startswith("Bearer ")
            or len(header) > 16384
        ):
            raise PermissionError("OAuth authorization required")
        try:
            claims = jwt.decode(
                header[7:],
                self.public_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            if claims["sub"] != self.subject or not isinstance(
                claims.get("scope"), str
            ):
                raise ValueError
            if (
                claims.get("token_use", "access") != "access"
                or "events" in claims
                or jwt.get_unverified_header(header[7:]).get("typ") == "logout+jwt"
            ):
                raise ValueError
            return Principal(
                claims["sub"], frozenset(claims["scope"].split()), claims["exp"]
            )
        except (jwt.PyJWTError, ValueError, TypeError):
            raise PermissionError("Invalid OAuth authorization") from None


class LogoutVerifier:
    """OpenID Connect Back-Channel Logout 1.0, account-wide single-owner profile.

    Separate client audience and explicit logout+jwt typing prevent confusing
    logout tokens with access tokens. Only sub-based account-wide logout is
    accepted: this facade does not maintain browser/session-ID mappings.
    """

    EVENT = "http://schemas.openid.net/event/backchannel-logout"

    def __init__(self, issuer, client_id, public_key, subject, *, max_age=120):
        if not isinstance(client_id, str) or not client_id or client_id == issuer:
            raise ValueError("Explicit logout client audience required")
        self.issuer, self.client_id = issuer, client_id
        self.public_key, self.subject, self.max_age = public_key, subject, max_age

    def verify(self, value):
        import time

        if not isinstance(value, str) or not value or len(value) > 16384:
            raise PermissionError("Invalid logout authorization")
        try:
            claims = jwt.decode(
                value,
                self.public_key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.client_id,
                options={
                    "require": ["iss", "aud", "iat", "exp", "jti", "sub", "events"]
                },
            )
            events = claims["events"]
            if (
                jwt.get_unverified_header(value).get("typ") != "logout+jwt"
                or claims["sub"] != self.subject
                or "nonce" in claims
                or "sid" in claims
                or not isinstance(claims["jti"], str)
                or not 1 <= len(claims["jti"]) <= 256
                or not isinstance(events, dict)
                or not isinstance(events.get(self.EVENT), dict)
                or type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or claims["exp"] <= claims["iat"]
                or time.time() - claims["iat"] > self.max_age
                or claims["exp"] - claims["iat"] > self.max_age
            ):
                raise ValueError
            receipt = hashlib.sha256(
                (self.issuer + "\0" + claims["jti"]).encode()
            ).hexdigest()
            return claims["sub"], receipt
        except (jwt.PyJWTError, ValueError, TypeError):
            raise PermissionError("Invalid logout authorization") from None
