"""Per-caller authentication for the Jaeger Gateway (jaegerd).

One bearer token per *caller* (menu-bar app, CLI, WebUI server, IDE, the
bridge, MCP, A2A, jaegerd's own tools). Token values live in the macOS login
Keychain (generic passwords, service ``ai.jaeger.gateway.caller``, account =
caller name) and are never printed or logged. The Gateway compares a presented
token against every caller's token with :func:`hmac.compare_digest` and binds
the matching caller's identity and scopes to the request.

Scopes are fixed in code here, not in config, so no client, model output,
webpage, MCP or A2A message can widen them:

* ``read``    GET routes
* ``turn``    session-scoped turn routes (create/patch session, send/queue/
              cancel/steer a turn, attachments, feedback)
* ``approve`` resolve approval cards
* ``ide``     post IDE tool results
* ``stop``    engage Global Stop
* ``admin``   everything else that changes state: autonomy, tier, agents,
              tasks, orchestration, handoffs, deleting sessions, undo, and
              releasing Global Stop

Callers with a ``session_prefix`` (MCP, A2A) are outside callers: they may only
touch sessions whose id starts with that prefix, and their turns reach
PolicyKernel as untrusted actors (``mcp`` / ``a2a``), which cannot run
privileged tools.

Limit (single-owner local system): any process running as the owner's macOS
user can read these Keychain items through ``/usr/bin/security``. The tokens
stop other machines, other users, browsers and DNS-rebinding pages, and they
attribute every request to a caller; they are not a sandbox between the
owner's own local processes.

Tests and throwaway instances set ``JAEGER_CALLER_TOKEN_DIR`` to a directory of
``<caller>.token`` files (mode 0600 enforced) instead of the Keychain.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import stat
import subprocess
from typing import Iterable, Mapping

KEYCHAIN_SERVICE = "ai.jaeger.gateway.caller"
TOKEN_DIR_ENV = "JAEGER_CALLER_TOKEN_DIR"
SECURITY_BIN = "/usr/bin/security"

ALL_SCOPES = frozenset({"read", "turn", "delegate", "approve", "ide", "stop", "admin"})
_OWNER = frozenset({"read", "turn", "delegate", "approve", "stop", "admin"})


@dataclass(frozen=True)
class CallerSpec:
    name: str
    actor: str
    scopes: frozenset[str]
    session_prefix: str | None = None
    description: str = ""


#: The closed set of Gateway callers. Adding a caller is a code change.
CALLERS: Mapping[str, CallerSpec] = {
    spec.name: spec
    for spec in (
        CallerSpec("menubar", "owner:menubar", _OWNER, description="Mac menu-bar app"),
        CallerSpec("cli", "owner:cli", _OWNER, description="jaeger CLI, TUI, voice, dev scripts"),
        CallerSpec("webui", "owner:webui", _OWNER, description="WebUI server-side proxy (:8790)"),
        CallerSpec("ide", "owner:ide", _OWNER | {"ide"}, description="VS Code / Cursor extension"),
        CallerSpec("bridge", "owner:bridge", frozenset({"read", "turn", "approve", "stop"}),
                   description="bridge socket (Swift chat, TUI attach)"),
        CallerSpec("jaegerd", "agent:jaeger", frozenset({"read", "turn", "delegate"}),
                   description="jaegerd's own tools calling back into the Gateway"),
        CallerSpec("mcp", "mcp", frozenset({"read", "turn", "stop"}), session_prefix="mcp:",
                   description="Jaeger MCP server (agentgateway, OpenClaw, Hermes, other AIs)"),
        CallerSpec("a2a", "a2a", frozenset({"read", "turn", "stop"}), session_prefix="a2a:",
                   description="Jaeger A2A server"),
    )
}

#: The MCP HTTP server (:8792) and A2A server (:8796) accept the ``mcp`` /
#: ``a2a`` caller tokens inbound (agentgateway presents them via backendAuth)
#: and relay the same identity to the Gateway, so there is one credential per
#: outside caller end to end.

PUBLIC_ROUTES = frozenset({("GET", "/health"), ("GET", "/version"), ("HEAD", "/health")})

#: Non-GET routes an outside caller's turn needs (canonical aiohttp paths).
TURN_ROUTES = frozenset({
    ("POST", "/v1/sessions"),
    ("PATCH", "/v1/sessions/{id}"),
    ("POST", "/v1/sessions/{id}/turns"),
    ("POST", "/v1/sessions/{id}/queue"),
    ("POST", "/v1/sessions/{id}/queue/reorder"),
    ("PATCH", "/v1/sessions/{id}/queue/{request_id}"),
    ("DELETE", "/v1/sessions/{id}/queue/{request_id}"),
    ("POST", "/v1/sessions/{id}/cancel"),
    ("POST", "/v1/sessions/{id}/requests/{request_id}/steer"),
    ("POST", "/v1/sessions/{id}/reconcile"),
    ("POST", "/v1/sessions/{id}/attachments"),
    ("POST", "/v1/sessions/{id}/feedback"),
    ("POST", "/v1/sessions/{id}/branch"),
    ("POST", "/v1/sessions/{id}/retry"),
})
APPROVE_ROUTES = frozenset({("POST", "/v1/approvals/{id}"), ("POST", "/v1/tasks/{id}/approve")})
IDE_ROUTES = frozenset({("POST", "/v1/sessions/{id}/ide/{ide_request_id}")})
STOP_ROUTES = frozenset({("POST", "/v1/stop")})
#: Lead → specialist handoff (``call_agent``): owners and jaegerd, never outside callers.
DELEGATE_ROUTES = frozenset({("POST", "/v1/agents/{id}/handoff")})
#: GET routes an outside (prefixed) caller may use; all are session-scoped.
PREFIXED_READ_ROUTES = frozenset({
    "/v1/sessions/{id}", "/v1/sessions/{id}/stream", "/v1/sessions/{id}/events",
    "/v1/sessions/{id}/requests/{request_id}", "/v1/sessions/{id}/queue",
    "/v1/sessions/{id}/attachments", "/v1/sessions/{id}/activity", "/v1/stop",
})


def required_scope(method: str, route: str | None) -> str | None:
    """Scope a request needs; ``None`` means public. Unknown routes need admin."""
    method = (method or "").upper()
    if (method, route or "") in PUBLIC_ROUTES:
        return None
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    key = (method, route or "")
    if key in TURN_ROUTES:
        return "turn"
    if key in APPROVE_ROUTES:
        return "approve"
    if key in IDE_ROUTES:
        return "ide"
    if key in STOP_ROUTES:
        return "stop"
    if key in DELEGATE_ROUTES:
        return "delegate"
    return "admin"


def prefixed_route_allowed(method: str, route: str | None) -> bool:
    """Routes an outside caller may use at all (session id checked separately)."""
    method = (method or "").upper()
    route = route or ""
    if method in {"GET", "HEAD"}:
        return route in PREFIXED_READ_ROUTES
    return (method, route) in TURN_ROUTES or (method, route) in STOP_ROUTES


# ── token storage ──────────────────────────────────────────────────────


class TokenStoreError(RuntimeError):
    """The token store could not be read or written (value never included)."""


def _token_dir() -> Path | None:
    raw = os.environ.get(TOKEN_DIR_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def _known(name: str) -> None:
    if name not in CALLERS:
        raise TokenStoreError(f"unknown caller {name!r}")


def read_token(name: str) -> str | None:
    """The stored token for ``name`` or ``None`` if absent. Never logs it."""
    _known(name)
    directory = _token_dir()
    if directory is not None:
        path = directory / f"{name}.token"
        try:
            st = path.stat()
        except FileNotFoundError:
            return None
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise TokenStoreError(f"{path} must be mode 0600")
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    try:
        proc = subprocess.run(
            [SECURITY_BIN, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TokenStoreError(f"Keychain unavailable: {type(exc).__name__}") from None
    if proc.returncode == 44:  # errSecItemNotFound
        return None
    if proc.returncode != 0:
        raise TokenStoreError(f"Keychain read failed for {name!r} (security exit {proc.returncode})")
    value = proc.stdout.strip()
    return value or None


def _write_token(name: str, value: str) -> None:
    directory = _token_dir()
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.token"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
        os.chmod(path, 0o600)
        return
    # ``security -i`` reads the command from stdin, so the value never
    # appears in argv (ps) or in this process's logs.
    command = (f'add-generic-password -U -s {KEYCHAIN_SERVICE} -a {name} '
               f'-l "Jaeger Gateway caller: {name}" -w {value}\n')
    try:
        proc = subprocess.run([SECURITY_BIN, "-i"], input=command, capture_output=True,
                              text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TokenStoreError(f"Keychain unavailable: {type(exc).__name__}") from None
    if proc.returncode != 0 or "error" in (proc.stderr or "").lower():
        raise TokenStoreError(f"Keychain write failed for {name!r}")


def ensure_tokens(names: Iterable[str] | None = None) -> dict[str, str]:
    """Create any missing token; returns ``{name: "existing"|"created"}``."""
    result: dict[str, str] = {}
    for name in (list(names) if names is not None else list(CALLERS)):
        if read_token(name):
            result[name] = "existing"
            continue
        # URL-safe alphabet only: no quoting issues in ``security -i``.
        _write_token(name, secrets.token_urlsafe(32))
        if not read_token(name):
            raise TokenStoreError(f"token for {name!r} did not persist")
        result[name] = "created"
    return result


_CLIENT_CACHE: dict[tuple[str, str], tuple[float, str | None]] = {}
_CLIENT_CACHE_TTL_S = 30.0


def client_token(caller: str) -> str | None:
    """This process's token for ``caller`` (cached briefly; ``None`` if absent)."""
    import time

    key = (os.environ.get(TOKEN_DIR_ENV, ""), caller)
    hit = _CLIENT_CACHE.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < _CLIENT_CACHE_TTL_S:
        return hit[1]
    try:
        token = read_token(caller)
    except TokenStoreError:
        token = None
    _CLIENT_CACHE[key] = (now, token)
    return token


def bearer(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def client_headers(caller: str) -> dict[str, str]:
    """``Authorization`` header for ``caller``; empty when it has no token
    (the Gateway then answers 401, which is the honest failure)."""
    return bearer(client_token(caller))


def default_caller(fallback: str = "cli") -> str:
    """Caller name for this process (``JAEGER_GATEWAY_CALLER``), else fallback."""
    name = os.environ.get("JAEGER_GATEWAY_CALLER", "").strip() or fallback
    return name if name in CALLERS else fallback


# ── verification (Gateway side) ────────────────────────────────────────


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class CallerAuthenticator:
    """Maps a presented bearer token to a :class:`CallerSpec`.

    Only SHA-256 digests are kept in memory. Every known digest is compared
    (constant time each) so timing does not reveal which caller nearly matched.
    A miss triggers one reload, so a token rotated in the Keychain works
    without restarting jaegerd.
    """

    def __init__(self) -> None:
        self._digests: dict[str, bytes] = {}
        self.load_errors: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        digests: dict[str, bytes] = {}
        errors: dict[str, str] = {}
        for name in CALLERS:
            try:
                value = read_token(name)
            except TokenStoreError as exc:
                errors[name] = str(exc)
                continue
            if value:
                digests[name] = _digest(value)
        self._digests = digests
        self.load_errors = errors

    @property
    def configured_callers(self) -> list[str]:
        return sorted(self._digests)

    def _match(self, presented: str) -> CallerSpec | None:
        got = _digest(presented)
        found: str | None = None
        for name, expected in self._digests.items():
            if hmac.compare_digest(got, expected) and found is None:
                found = name
        return CALLERS[found] if found else None

    def authenticate(self, authorization: str | None) -> CallerSpec | None:
        value = (authorization or "").strip()
        if not value.lower().startswith("bearer "):
            return None
        presented = value[7:].strip()
        if not presented:
            return None
        spec = self._match(presented)
        if spec is None:
            self.reload()
            spec = self._match(presented)
        return spec


def session_allowed(spec: CallerSpec, session_id: str | None) -> bool:
    if spec.session_prefix is None:
        return True
    return bool(session_id) and str(session_id).startswith(spec.session_prefix)


__all__ = [
    "ALL_SCOPES", "CALLERS", "CallerAuthenticator", "CallerSpec",
    "KEYCHAIN_SERVICE", "TOKEN_DIR_ENV", "TokenStoreError", "bearer", "client_headers", "client_token",
    "default_caller", "ensure_tokens", "prefixed_route_allowed", "read_token",
    "required_scope", "session_allowed",
]
