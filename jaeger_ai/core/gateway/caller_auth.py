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

ALL_SCOPES = frozenset({"read", "turn", "delegate", "approve", "ide", "stop", "admin", "handoff", "search"})
_OWNER = frozenset({"read", "turn", "delegate", "approve", "stop", "admin", "search"})


@dataclass(frozen=True)
class CallerSpec:
    name: str
    actor: str
    scopes: frozenset[str]
    session_prefix: str | None = None
    description: str = ""
    display_name: str | None = None
    peer_kind: str | None = None
    transport: str | None = None
    framework_id: str | None = None


#: Local agent apps that reach Jaeger over loopback MCP (127.0.0.1:8792/mcp),
#: one dedicated credential each so messages, goals and receipts are attributed
#: per app. Same ceiling as ``ares``/``grokbot``: read + turn (agent-bridge
#: messages and goals, which run through PolicyKernel and owner approvals) and
#: the ``handoff`` label. Never approve, delegate, stop or admin.
APP_CALLERS: Mapping[str, str] = {
    "claude": "Claude Code", "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini",
    "vscode": "VS Code / Copilot", "opencode": "OpenCode", "continue": "Continue",
    "cline": "Cline", "openclaw": "OpenClaw", "cagent": "cagent", "muse": "Muse",
    "geminidesktop": "Gemini desktop app",
}
APP_CALLER_SCOPES = frozenset({"read", "turn", "handoff", "search"})

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
                   description="jaegerd's own tools calling back into the Gateway",
                   display_name="Jaeger", peer_kind="resident", transport="gateway",
                   framework_id="jaeger"),
        CallerSpec("mcp", "mcp", frozenset({"read", "turn", "stop"}), session_prefix="mcp:",
                   description="Jaeger MCP server (agentgateway, OpenClaw, Hermes, other AIs)"),
        CallerSpec("ares", "mcp:ares", frozenset({"read", "turn", "search"}), session_prefix="ares:",
                   description="ARES agent bridge client; dedicated credential required",
                   display_name="ARES", peer_kind="agent_service", transport="agent_bridge",
                   framework_id="ares"),
        CallerSpec("grokbot", "mcp:grokbot", frozenset({"read", "turn", "search"}), session_prefix="grokbot:",
                   description="GrokBot local bridge client; dedicated credential required",
                   display_name="Grok Bot", peer_kind="external_agent", transport="agent_bridge",
                   framework_id="grok"),
        CallerSpec("hermes", "mcp:hermes", frozenset({"read", "turn"}), session_prefix="hermes:",
                   description="Hermes headless hub worker",
                   display_name="Hermes", peer_kind="external_agent", transport="message_hub",
                   framework_id="hermes"),
        CallerSpec("rackpc", "mcp:rackpc", frozenset({"read", "turn"}), session_prefix="rackpc:",
                   description="Rack PC Ollama worker (claims hub tasks, posts results only)",
                   display_name="Rack PC", peer_kind="worker", transport="message_hub"),
        CallerSpec("a2a", "a2a", frozenset({"read", "turn", "stop"}), session_prefix="a2a:",
                   description="Jaeger A2A server"),
        *(CallerSpec(name, f"mcp:{name}", APP_CALLER_SCOPES, session_prefix=f"{name}:",
                     description=f"{label} (local MCP client, dedicated credential)",
                     display_name=label, peer_kind="agent_app", transport="mcp",
                     framework_id=name)
          for name, label in APP_CALLERS.items()),
    )
}

#: The MCP HTTP server (:8792) and A2A server (:8796) accept the ``mcp`` /
#: ``a2a`` caller tokens inbound (agentgateway presents them via backendAuth)
#: and relay the same identity to the Gateway, so there is one credential per
#: outside caller end to end.

PUBLIC_ROUTES = frozenset({("GET", "/health"), ("GET", "/version"), ("HEAD", "/health")})

#: Route prefixes that are public (no auth) — used for static assets like
#: character card images that the browser loads directly in <img> tags.
PUBLIC_ROUTE_PREFIXES = frozenset({
    "/v1/characters/",  # Character cards, avatars — public images for UI
})

#: Non-GET routes an outside caller's turn needs (canonical aiohttp paths).
TURN_ROUTES = frozenset({
    ("POST", "/v1/agent-messages"),
    ("POST", "/v1/agent-goals"),
    ("POST", "/v1/agent-goals/{goal_id}/cancel"),
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
    ("POST", "/v1/sessions/{id}/attachments/upload"),
    ("POST", "/v1/sessions/{id}/feedback"),
    ("POST", "/v1/sessions/{id}/branch"),
    ("POST", "/v1/sessions/{id}/retry"),
    # AppControl proposals only queue a needs-confirmation approval; nothing is applied.
    ("POST", "/v1/apps/{app}/proposals"),
})
#: Owner decisions. Answering a clarify form is owner input, never an agent self-answer (GB-033).
APPROVE_ROUTES = frozenset({("POST", "/v1/approvals/{id}"), ("POST", "/v1/approvals/{id}/decision"),
                            ("POST", "/v1/approvals/{id}/decide"), ("POST", "/v1/approvals/batch"), ("POST", "/v1/approvals/{id}/viewed"),
                            ("POST", "/v1/tasks/{id}/approve"),
                            # AppControl: the handler further limits these to the webui/menubar callers.
                            ("POST", "/v1/apps/proposals/{pid}/decision"), ("POST", "/v1/apps/proposals/{pid}/rollback"),
                            ("POST", "/v1/sessions/{id}/clarify/{clarify_id}")})
IDE_ROUTES = frozenset({("POST", "/v1/sessions/{id}/ide/{ide_request_id}")})
STOP_ROUTES = frozenset({("POST", "/v1/stop")})
#: Shared web search (local SearXNG) and safe page fetch: the ``search`` grant.
SEARCH_ROUTES = frozenset({("POST", "/v1/search"), ("POST", "/v1/fetch"),
                           # OSS stack (features.oss_stack): model router, shared MCP tools, Documents RAG
                           ("POST", "/v1/models/route"), ("POST", "/v1/models/generate"),
                           ("POST", "/v1/tools/list"), ("POST", "/v1/tools/call"), ("POST", "/v1/docs/search"),
                           # Backlog (features.backlog): read/add/update/assign; approve + import are owner-only in the handler
                           ("POST", "/v1/backlog"), ("POST", "/v1/backlog/{id}"), ("POST", "/v1/backlog/{id}/assign"),
                           ("POST", "/v1/backlog/import")})
#: Lead → specialist handoff (``call_agent``): owners and jaegerd, never outside callers.
DELEGATE_ROUTES = frozenset({("POST", "/v1/agents/{id}/handoff")})
#: GET routes an outside (prefixed) caller may use; all are session-scoped.
PREFIXED_READ_ROUTES = frozenset({
    "/v1/agent-messages", "/v1/agent-threads/{thread}",
    "/v1/agent-goals/{goal_id}",
    "/v1/sessions/{id}", "/v1/sessions/{id}/stream", "/v1/sessions/{id}/events",
    "/v1/sessions/{id}/requests/{request_id}", "/v1/sessions/{id}/requests/{request_id}/steer", "/v1/sessions/{id}/queue",
    "/v1/sessions/{id}/attachments", "/v1/sessions/{id}/activity", "/v1/stop",
    "/v1/sessions/{id}/messages",
    # Status of one approval; the handler limits it to the caller's sessions.
    "/v1/approvals/{id}",
    # Hub collaboration: the agent roster and pending-approval totals carry no
    # session content, so outside callers may read them.
    "/v1/agents",
    "/v1/agent-peers",
    "/v1/approvals/counts",
    # AppControl reads: status and redacted config only.
    "/v1/apps", "/v1/apps/proposals", "/v1/apps/proposals/{pid}", "/v1/apps/{app}", "/v1/apps/{app}/config",
})


def agent_peer_catalog() -> list[dict[str, object]]:
    """Stable agent identities that can participate through the Gateway.

    Caller authentication remains the authority for identity, scopes, and
    session namespaces.  This is its public read model for clients and agent
    bridges; it deliberately does not create a second editable registry.
    """
    return [
        {
            "id": spec.name,
            "display_name": spec.display_name or spec.name,
            "kind": spec.peer_kind,
            "actor": spec.actor,
            "transport": spec.transport,
            "framework_id": spec.framework_id,
            "session_prefix": spec.session_prefix,
            "scopes": sorted(spec.scopes),
        }
        for spec in CALLERS.values()
        if spec.peer_kind is not None
    ]


#: OpenAI-compatible surface (core/gateway/openai_compat.py). It runs a turn,
#: so it needs ``turn``; it is deliberately absent from TURN_ROUTES so callers
#: confined to a session prefix (mcp, a2a) cannot use it to open unprefixed
#: sessions.
OPENAI_COMPAT_ROUTES = frozenset({
    ("POST", "/v1/chat/completions"),
})


def required_scope(method: str, route: str | None) -> str | None:
    """Scope a request needs; ``None`` means public. Unknown routes need admin."""
    method = (method or "").upper()
    route = route or ""
    if (method, route) in PUBLIC_ROUTES:
        return None
    # Public route prefixes (e.g., character card images for <img> tags)
    if method in {"GET", "HEAD", "OPTIONS"}:
        for prefix in PUBLIC_ROUTE_PREFIXES:
            if route.startswith(prefix):
                return None
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    key = (method, route or "")
    if key in SEARCH_ROUTES:
        return "search"
    if key in TURN_ROUTES or key in OPENAI_COMPAT_ROUTES:
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


#: Extra read-only GET routes for one named outside caller (not every prefixed caller).
#: grokbot reads the Agents-tab activity feed (handoff.sent / handoff.result rows).
CALLER_READ_ROUTES: Mapping[str, frozenset[str]] = {
    "grokbot": frozenset({"/v1/activity", "/v1/backlog", "/v1/backlog/sweep"}),
    "ares": frozenset({"/v1/backlog", "/v1/backlog/sweep"}),
    "muse": frozenset({"/v1/backlog", "/v1/backlog/sweep"}),
}


#: Callers confined to an exact route allow-list (both reads and writes).
#: rackpc is a job worker: it reads its inbox/threads and posts results, nothing else.
CALLER_ONLY_ROUTES: Mapping[str, frozenset[tuple[str, str]]] = {
    "muse": frozenset({
        ("GET", "/v1/agent-messages"), ("GET", "/v1/agent-threads/{thread}"),
        ("POST", "/v1/agent-messages"),
        ("GET", "/v1/agents"), ("GET", "/v1/approvals/counts"),
        ("GET", "/v1/agent-goals/{goal_id}"),
        ("GET", "/v1/backlog"), ("GET", "/v1/backlog/sweep"),
        ("POST", "/v1/backlog"), ("POST", "/v1/backlog/{id}"),
        ("POST", "/v1/backlog/{id}/assign"),
    }),
    "hermes": frozenset({
        ("GET", "/v1/agent-messages"), ("GET", "/v1/agent-threads/{thread}"),
        ("POST", "/v1/agent-messages"),
    }),
    "rackpc": frozenset({
        ("GET", "/v1/agent-messages"), ("GET", "/v1/agent-threads/{thread}"),
        ("POST", "/v1/agent-messages"),
    }),
}


def prefixed_route_allowed(method: str, route: str | None, caller: str | None = None) -> bool:
    """Routes an outside caller may use at all (session id checked separately)."""
    method = (method or "").upper()
    route = route or ""
    only = CALLER_ONLY_ROUTES.get(caller or "")
    if only is not None:
        return ("GET" if method == "HEAD" else method, route) in only
    if method in {"GET", "HEAD"}:
        return route in PREFIXED_READ_ROUTES or route in CALLER_READ_ROUTES.get(caller or "", ())
    return (method, route) in TURN_ROUTES or (method, route) in STOP_ROUTES or (method, route) in SEARCH_ROUTES


# ── token storage ──────────────────────────────────────────────────────


class TokenStoreError(RuntimeError):
    """The token store could not be read or written (value never included)."""


def _explicit_token_dir() -> Path | None:
    raw = os.environ.get(TOKEN_DIR_ENV, "").strip()
    return Path(raw).expanduser() if raw else None


def _state_token_dir() -> Path | None:
    try:
        from jaeger_ai.core.instance.instance import operator_state_root
        return operator_state_root() / "caller_tokens"
    except Exception:
        return None


def _token_dir() -> Path | None:
    return _explicit_token_dir() or _state_token_dir()


def _known(name: str) -> None:
    if name not in CALLERS:
        raise TokenStoreError(f"unknown caller {name!r}")


def read_token(name: str) -> str | None:
    """The stored token for ``name`` or ``None`` if absent. Never logs it."""
    _known(name)
    explicit = _explicit_token_dir()
    if explicit is not None:
        path = explicit / f"{name}.token"
        try:
            st = path.stat()
        except FileNotFoundError:
            return None
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise TokenStoreError(f"{path} must be mode 0600")
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    state_dir = _state_token_dir()
    if state_dir is not None:
        path = state_dir / f"{name}.token"
        if path.exists():
            try:
                st = path.stat()
                if stat.S_IMODE(st.st_mode) & 0o077:
                    raise TokenStoreError(f"{path} must be mode 0600")
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
            except FileNotFoundError:
                pass

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
    explicit = _explicit_token_dir()
    if explicit is not None:
        explicit.mkdir(parents=True, exist_ok=True)
        path = explicit / f"{name}.token"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
        os.chmod(path, 0o600)
        return

    state_dir = _state_token_dir()
    if state_dir is not None:
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            path = state_dir / f"{name}.token"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(value)
            os.chmod(path, 0o600)
        except Exception:
            pass

    if Path(SECURITY_BIN).exists():
        command = (f'add-generic-password -U -s {KEYCHAIN_SERVICE} -a {name} '
                   f'-l "Jaeger Gateway caller: {name}" -w {value}\n')
        try:
            proc = subprocess.run([SECURITY_BIN, "-i"], input=command, capture_output=True,
                                  text=True, timeout=15, check=False)
            if proc.returncode != 0 or "error" in (proc.stderr or "").lower():
                if state_dir is None:
                    raise TokenStoreError(f"Keychain write failed for {name!r}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            if state_dir is None:
                raise TokenStoreError(f"Keychain unavailable: {type(exc).__name__}") from None


def ensure_tokens(names: Iterable[str] | None = None) -> dict[str, str]:
    """Create any missing token; returns ``{name: "existing"|"created"}``."""
    result: dict[str, str] = {}
    for name in (list(names) if names is not None else list(CALLERS)):
        existing = read_token(name)
        if existing:
            # Sync to state dir if present in Keychain but not yet on disk
            if _explicit_token_dir() is None:
                state_dir = _state_token_dir()
                if state_dir is not None and not (state_dir / f"{name}.token").exists():
                    _write_token(name, existing)
            result[name] = "existing"
            continue
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
    "agent_peer_catalog", "default_caller", "ensure_tokens", "prefixed_route_allowed", "read_token",
    "required_scope", "session_allowed",
]
