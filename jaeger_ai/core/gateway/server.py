"""Jaeger Unified Gateway Daemon.

Decouples the Agent Engine from any UI window. Runs as a persistent background
service. Multi-client: allows Mac App, Web UI, and CLI to connect simultaneously,
share sessions, and stream live events without process teardown.
"""

from __future__ import annotations

import asyncio
import time
import json
import math
import logging
import ipaddress
import os
import re
import threading
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

from aiohttp import ClientSession, ClientTimeout, web

from jaeger_ai import __version__ as JAEGER_VERSION
from jaeger_ai.contract.frameworks import DEFAULT_AGENT_MODEL
from jaeger_ai.contract.legacy_paths import legacy_paths_enabled
from jaeger_ai.contract.model_ids import provider_model_name, split_routed_model_id
from jaeger_ai.contract.ports import (
    GATEWAY_PORT,
    LOOPBACK,
    OLLAMA_URL as LOCKED_OLLAMA_URL,
    WEBUI_ADAPTER_PORT,
    WEBUI_PORT,
)
from jaeger_ai.contract.sessions import normalise_surface

from . import caller_auth
from .event_bus import GatewayEventBus, ReplayGap
from jaeger_ai.core.runtime.cancellation import CancellationRegistry
from jaeger_ai.core.runtime.salience import SalienceLevel

from .session_store import EXECUTION_INPUT_KEYS, GatewaySessionStore, RequestBusy, RequestConflict

logger = logging.getLogger("jaeger.gateway")

# GATEWAY_PORT already honours JAEGER_GATEWAY_PORT (contract/ports.py).
DEFAULT_GATEWAY_PORT = GATEWAY_PORT
# Loopback by default. JAEGER_GATEWAY_HOST is the explicit opt-out for anyone
# who really needs a wider bind; publish to a tailnet rather than widening it.
DEFAULT_GATEWAY_HOST = os.environ.get("JAEGER_GATEWAY_HOST") or LOOPBACK

# Locked spine endpoints (docs/spine-acceptance.md M10). Chat does not use :8813.
LOCKED_BRIDGE_HEALTH_URL = os.environ.get(
    "JAEGER_BRIDGE_HEALTH_URL", f"http://{LOOPBACK}:{WEBUI_ADAPTER_PORT}/health"
).rstrip("/")
LOCKED_WEBUI_URL = os.environ.get(
    "JAEGER_WEBUI_URL", f"http://{LOOPBACK}:{WEBUI_PORT}"
).rstrip("/")
DEFAULT_OLLAMA_MODEL = os.environ.get("JAEGER_GATEWAY_OLLAMA_MODEL", "kimi-k2.7-code:cloud")


NO_TOOLS_LANE_NOTE = (
    "[No tools in this conversation]\n"
    "This turn runs without tools: you cannot run commands, read or write files, "
    "or change memory here. Do not write tool calls, JSON tool arguments, or "
    "commands as if you were running them, and never claim an action happened. "
    "Answer from what you already know, or say plainly that the task needs Agent "
    "mode (tools enabled)."
)


def no_tools_lane_system_prompt(system_prompt: str | None) -> str:
    """System prompt for the tool-less model-only lane (Chat tier, specialists).

    The base prompt still describes Jaeger's tools. With ``interaction_tier: chat``
    the SOTA run (2026-10-16) sent every request down this lane, and the model
    wrote its tool calls out as text (```json {"command": ...}``` and
    ``recall(key=...)``) that nothing executed. Stating the lane's limits keeps
    the answer honest instead of looking like work that was done.
    """
    base = (system_prompt or "").rstrip()
    if NO_TOOLS_LANE_NOTE in base:
        return base
    return f"{base}\n\n{NO_TOOLS_LANE_NOTE}" if base else NO_TOOLS_LANE_NOTE


def _model_has_vision(model: str) -> bool:
    """True when this model has a VISION certification (or an explicit override)."""
    try:
        from jaeger_ai.core.entity.model_capabilities import capabilities_for
        return str(capabilities_for(model).get("vision") or "").lower() == "pass"
    except Exception:
        pass
    return False
# Agent turns require native MCP. Reduced text mode must be explicitly selected.
NATIVE_LEAD_MCP_TIMEOUT_S = float(os.environ.get("JAEGER_GATEWAY_MCP_TIMEOUT_S", "300"))


# ``native_session`` marker for a request bound to the Entity's own run
# (owner-react), as opposed to a run on the native MCP server.
OWNER_RUN_SESSION_PREFIX = "owner:"

# How long a tool call waits for the operator before it is refused.
APPROVAL_WAIT_S = 300.0

# Arguments that name what a tool call will touch, in the order a human
# reading an approval on a phone needs them.
_APPROVAL_TARGET_KEYS = (
    "path", "src", "dst", "command", "url", "to", "recipient", "package",
    "script", "code", "target", "name", "query",
)


def _approval_target(request: Any) -> str:
    """What this call will touch, for the approval prompt."""
    arguments = getattr(request, "arguments", None) or {}
    parts = []
    for key in _APPROVAL_TARGET_KEYS:
        value = arguments.get(key)
        if value not in (None, ""):
            text = str(value)
            parts.append(f"{key}={text[:200]}{'…' if len(text) > 200 else ''}")
    return "; ".join(parts)


# Opening words of a request that only asks about what an image shows.
_IMAGE_QUESTION_OPENERS = frozenset({
    "what", "which", "who", "where", "when", "why", "how", "is", "are", "does",
    "do", "can", "read", "describe", "look", "tell", "identify", "count",
})


#: Streamed answer text is batched into durable ``turn.delta`` events at
#: whichever comes first: this many characters or this many seconds.
TURN_DELTA_BATCH_CHARS = 96
TURN_DELTA_BATCH_S = 0.1
#: Reasoning batches flush on time (TURN_DELTA_BATCH_S) or at this size.
TURN_REASONING_BATCH_CHARS = 2048
TOOL_EVENT_NAME_MAX = 80
TOOL_EVENT_DURATION_MAX_S = 86_400.0


#: Shell-like tools whose command and output the operator sees inline, as in any IDE
#: agent. Everything else (file contents, credentials, arbitrary results) stays
#: unpublished. ``write_stdin`` is excluded on purpose: what is typed into a live
#: process can be a password.
_INLINE_INPUT_KEY = {"terminal": "command", "run_shell": "command", "exec_command": "cmd", "execute_code": "code"}
_INLINE_OUTPUT_KEYS = ("output", "stdout", "stderr", "result")
_INLINE_INPUT_MAX = 600
_INLINE_OUTPUT_MAX = 1500
_SECRET_TEXT = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|passwd|password|authorization|bearer)\s*[=:]\s*['\"]?|\bsk-)[A-Za-z0-9_\-./+=]{8,}"
)


def _inline_text(text: Any, limit: int) -> str:
    """Bounded, secret-redacted text for an inline tool block (best effort)."""
    value = _SECRET_TEXT.sub(lambda m: m.group(1) + "***", str(text or "")).strip()
    if len(value) <= limit:
        return value
    half = limit // 2
    return f"{value[:half]}\n…\n{value[-half:]}"


def _tool_input_text(name: str, args: Any) -> str:
    key = _INLINE_INPUT_KEY.get(name)
    return _inline_text(args.get(key), _INLINE_INPUT_MAX) if key and isinstance(args, dict) else ""


#: Helper-framework tools whose answer IS the work product. Their result is
#: already redacted and fenced as untrusted data by ``frameworks.delegate``;
#: the session record keeps a bounded copy plus the saved-file paths, so the
#: answer survives a stalled turn without digging through another
#: framework's private rollout files (Oct 9 manager run).
_HELPER_OUTPUT_TOOLS = frozenset({"framework_delegate", "framework_apply_diff"})
_HELPER_OUTPUT_MAX = 12_000


def _helper_output_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    head = [f"{k}: {result[k]}" for k in ("framework", "exit_code", "answer_file", "patch_file",
                                          "workspace", "files", "error")
            if result.get(k) not in (None, "", [])]
    body = result.get("content") or result.get("status") or ""
    return _inline_text("\n".join(head + ([str(body)] if body else [])), _HELPER_OUTPUT_MAX)


def _tool_output_text(name: str, result: Any) -> str:
    if name in _HELPER_OUTPUT_TOOLS:
        return _helper_output_text(result)
    if name not in _INLINE_INPUT_KEY or not isinstance(result, dict):
        return ""
    parts = [str(result[k]) for k in _INLINE_OUTPUT_KEYS if isinstance(result.get(k), (str, int, float)) and str(result[k]).strip()]
    return _inline_text("\n".join(parts), _INLINE_OUTPUT_MAX)


_ARG_VALUE_MAX = 240
_ARGS_TOTAL_MAX = 2048
_SECRET_ARG_KEY = re.compile(r"(?i)(pass(word|phrase)?|secret|token|api[_-]?key|auth|credential|cookie|private[_-]?key)")
#: Payload bodies (file contents, edits, prompts, stdin) never cross; only their size does.
_BODY_ARG_KEY = re.compile(r"(?i)^(content|contents|text|body|data|new_string|old_string|new_str|old_str|"
                           r"patch|diff|input|stdin|prompt|message|messages|code|source|replacement)$")


def _tool_event_args(args: Any) -> dict[str, Any]:
    """A bounded, redacted copy of a tool call's arguments for the event stream.

    Observers (the bridge, run drivers, evaluators) need to see WHAT a tool was
    asked to do. Credentials never cross: values under credential-like keys are
    withheld, payload bodies (file contents, edits, prompts) are replaced by
    their size, known secret shapes are masked, long strings are clipped, and
    the whole payload is size-bounded.
    """
    if not isinstance(args, dict):
        return {}
    from jaeger_os.core.safety.redact import redact_text

    def clip(value: Any, depth: int = 0) -> Any:
        if isinstance(value, str):
            value = redact_text(value)
            return value if len(value) <= _ARG_VALUE_MAX else value[:_ARG_VALUE_MAX] + f"…(+{len(value) - _ARG_VALUE_MAX} chars)"
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if depth >= 2:
            return f"<{type(value).__name__}>"
        if isinstance(value, dict):
            return {str(k)[:64]: ("<withheld>" if _SECRET_ARG_KEY.search(str(k))
                                  else f"<{len(v) if isinstance(v, (str, list, dict)) else '?'} {type(v).__name__}>"
                                  if _BODY_ARG_KEY.match(str(k)) else clip(v, depth + 1))
                    for k, v in list(value.items())[:24]}
        if isinstance(value, (list, tuple)):
            return [clip(v, depth + 1) for v in list(value)[:24]]
        return f"<{type(value).__name__}>"

    shown = clip(args)
    if len(json.dumps(shown, default=str)) > _ARGS_TOTAL_MAX:
        shown = {k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:80])
                 for k, v in list(shown.items())[:12]}
    return shown


def _safe_tool_event_name(value: Any) -> str:
    """Return a bounded identifier, never arbitrary tool-supplied text.

    Tool names normally come from the registered catalog, but this callback is
    an observability boundary.  If a malformed provider invents a name, do not
    copy it into the durable client stream where it could contain prompts,
    arguments, terminal control characters, or secrets.
    """
    name = str(value or "")
    if (
        not name
        or len(name) > TOOL_EVENT_NAME_MAX
        or any(
            not (char.isascii() and (char.isalnum() or char in "_.:-"))
            for char in name
        )
    ):
        return "tool"
    return name


def _safe_tool_duration(value: Any) -> float:
    """Normalize the sole tool-result datum allowed onto the public stream."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not 0.0 <= seconds <= TOOL_EVENT_DURATION_MAX_S:
        return 0.0
    return round(seconds, 3)


def _admitted_execution(request_row: dict[str, Any]) -> dict[str, Any] | None:
    """The frozen execution snapshot of an admitted request, or ``None`` for a
    digest-v1 receipt admitted before snapshots existed."""
    if int(request_row.get("digest_version") or 1) < 2:
        return None
    execution = request_row.get("execution")
    return execution if isinstance(execution, dict) else None


def _normalize_salience(value: str | int | None) -> str:
    """One wire spelling for proactive salience; invalid is a quiet digest."""
    try:
        if isinstance(value, int):
            return SalienceLevel(value).name.lower()
        return SalienceLevel[str(value or "digest").strip().upper()].name.lower()
    except (KeyError, ValueError):
        return "digest"


def _asks_about_the_image(request: str) -> bool:
    """True for a question about an image; anything else goes to the Entity.

    The direct vision lane has no tools. Defaulting to it made "save the
    phrase to a file" in an image session a tool-less reply recorded as
    completed, and ``is_actionable_request`` does not recognise that
    sentence as work. So the tool-less lane is opt-in by shape of request:
    a question, or a read/describe-style ask. A heuristic, deliberately
    narrow — a misread costs a slower turn, not a lost action.
    """
    words = request.strip().lower().split()
    return bool(words) and (request.strip().endswith("?") or words[0].strip(",.:") in _IMAGE_QUESTION_OPENERS)


_LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})
_TAILSCALE_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


def _is_allowed_gateway_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip().lower()
    if host in _LOOPBACK_HOSTNAMES or host == "0.0.0.0":
        return True
    if host.endswith(".ts.net") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        if ip in _TAILSCALE_CGNAT_NET or ip.is_private or ip.is_loopback:
            return True
    except ValueError:
        pass
    extra_hosts = os.environ.get("JAEGER_GATEWAY_ALLOW_HOSTS", "").split(",")
    for extra in extra_hosts:
        extra = extra.strip().lower()
        if extra and (extra == "*" or extra == host):
            return True
    return False


@web.middleware
async def _reject_browser_cross_site(request: web.Request, handler: Any) -> web.StreamResponse:
    """Refuse requests a web page could forge.

    The Gateway has no credentials of its own; loopback/tailnet is its boundary.
    That boundary stops public web pages and DNS rebinding attacks while allowing
    legitimate loopback, LAN, and Tailscale callers.
    """
    if not _is_allowed_gateway_host(request.url.host):
        return web.json_response({"error": "Gateway accepts loopback Host only"}, status=421)
    origin = request.headers.get("Origin")
    if origin is not None:
        try:
            from yarl import URL
            source = URL(origin)
        except ValueError:
            source = None
        if source is None or not _is_allowed_gateway_host(source.host) or source.port != request.url.port:
            return web.json_response({"error": "Cross-origin requests are refused"}, status=403)
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return web.json_response({"error": "Cross-site requests are refused"}, status=403)
    return await handler(request)


#: aiohttp app key: ``{"auth": CallerAuthenticator | None}``, built lazily on first use.
CALLER_AUTH_KEY = "jaeger.caller_auth"
#: (caller name, actor) of the authenticated HTTP request being handled.
_REQUEST_CALLER: ContextVar[tuple[str, str] | None] = ContextVar("gateway_request_caller", default=None)
#: Actors jaegerd's own tools may act for when calling back in (X-Jaeger-Actor).
_DELEGABLE_ACTORS = frozenset({spec.actor for spec in caller_auth.CALLERS.values()})


_BOUND_GATEWAY_PORT: int | None = None
"""The port :func:`run_gateway_forever` actually bound, once it has."""


def _register_tool_gateway_auth() -> None:
    """Give jaeger-agent's ``call_agent`` jaegerd's Gateway credential."""
    import importlib

    try:  # the module, not the same-named tool function re-exported by the package
        module = importlib.import_module("jaeger_agent.tools.call_agent")
    except ImportError:
        return
    module.set_gateway_auth(lambda: caller_auth.client_headers("jaegerd"))
    if hasattr(module, "set_gateway_base"):
        # The tool runs inside this process; it reaches the port we bound.
        module.set_gateway_base(
            lambda: os.environ.get("JAEGER_GATEWAY_URL")
            or f"http://{LOOPBACK}:{_BOUND_GATEWAY_PORT or DEFAULT_GATEWAY_PORT}"
        )


def current_request_actor() -> str | None:
    """Actor of the authenticated request in this context (``None`` = internal)."""
    bound = _REQUEST_CALLER.get()
    return bound[1] if bound else None


def _route_template(request: web.Request) -> str | None:
    resource = getattr(getattr(request.match_info, "route", None), "resource", None)
    return getattr(resource, "canonical", None) if resource is not None else None


def _control_plane_block() -> str | None:
    """In-process producers bypass HTTP middleware. They still honor Stop and the lease."""
    from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError
    from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease
    try:
        if GlobalStop.load().engaged():
            return "global stop"
    except GlobalStopError:
        return "global stop"
    except Exception:
        return "global stop unavailable"
    try:
        decision = LifecycleLease.load().decide()
    except Exception:
        return "lifecycle lease unavailable"
    if not decision.privileged_work_allowed:
        return decision.reason
    return None


@web.middleware
async def _authenticate_caller(request: web.Request, handler: Any) -> web.StreamResponse:
    """Every non-public route needs a per-caller bearer token (fail closed).

    The token picks a caller from ``caller_auth.CALLERS``; its fixed scopes
    decide the route, outside callers (MCP, A2A) are held to their own
    session prefix, and the caller's actor is bound for the handler so an
    admitted turn carries it into PolicyKernel. No header, body field, model
    output or tool result can name a different caller.
    """
    route = _route_template(request)
    scope = caller_auth.required_scope(request.method, route)
    if scope is None:
        return await handler(request)
    holder = request.app.get(CALLER_AUTH_KEY)
    if not isinstance(holder, dict):
        return web.json_response({"error": "Caller authentication unavailable"}, status=503)
    auth = holder.get("auth")
    if auth is None:
        try:
            auth = caller_auth.CallerAuthenticator()
        except Exception as exc:  # noqa: BLE001 - fail closed, never echo values
            logger.error("Caller authentication unavailable: %s", type(exc).__name__)
            return web.json_response({"error": "Caller authentication unavailable"}, status=503)
        holder["auth"] = auth
    spec = auth.authenticate(request.headers.get("Authorization"))
    if spec is None:
        return web.json_response(
            {"error": "Unauthorized: a Jaeger caller token is required"}, status=401,
            headers={"WWW-Authenticate": 'Bearer realm="jaeger-gateway"'},
        )
    if scope not in spec.scopes:
        return web.json_response({"error": f"Caller {spec.name!r} lacks scope {scope!r}"}, status=403)
    if spec.session_prefix is not None:
        if not caller_auth.prefixed_route_allowed(request.method, route):
            return web.json_response({"error": f"Caller {spec.name!r} may not use this route"}, status=403)
        if (route or "").startswith("/v1/sessions/{id}") and not caller_auth.session_allowed(
                spec, request.match_info.get("id")):
            return web.json_response(
                {"error": f"Caller {spec.name!r} may only use sessions starting {spec.session_prefix!r}"},
                status=403,
            )
    from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError, allowed_while_stopped
    from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease
    try:
        stopped = GlobalStop.load().engaged()
    except GlobalStopError:
        stopped = True
    except Exception:
        logger.error("Global stop path unavailable", exc_info=True)
        return web.json_response({"error": "global stop unavailable"}, status=503)
    if stopped and not allowed_while_stopped(request.method, route, spec):
        return web.json_response({"error": "global stop", "state": "stopped"}, status=423)
    try:
        decision = LifecycleLease.load().decide()
    except Exception:
        logger.error("Lifecycle lease path unavailable", exc_info=True)
        return web.json_response({"error": "lifecycle lease unavailable"}, status=503)
    if not decision.privileged_work_allowed and not allowed_while_stopped(
            request.method, route, spec):
        return web.json_response({"error": decision.reason, "state": "offline"}, status=423)
    actor = spec.actor
    if spec.name == "jaegerd":
        claimed = (request.headers.get("X-Jaeger-Actor") or "").strip()
        if claimed:
            if claimed not in _DELEGABLE_ACTORS:
                return web.json_response({"error": "Unknown delegated actor"}, status=403)
            actor = claimed
    request["caller"] = spec
    request["caller_actor"] = actor
    bound = _REQUEST_CALLER.set((spec.name, actor))
    try:
        return await handler(request)
    finally:
        _REQUEST_CALLER.reset(bound)


class _GatewayToolConfirmationProvider:
    """Park WRITE_LOCAL (and similar) confirms on the Gateway approval bus.

    Phone/WebUI resolve them with POST /v1/approvals/{id}. Standing
    commissioning filesystem.write grants still auto-allow.
    """

    def __init__(self, app: "JaegerGatewayApp", session_id: str, request_id: str) -> None:
        self.app = app
        self.session_id = session_id
        self.request_id = request_id

    #: Asks a human for this call when ``force_prompt`` is set (no standing
    #: grant, autonomy shortcut or remembered answer). Required by
    #: PolicyKernel REQUIRE_APPROVAL (tool_executor._owner_approves).
    fresh_approval = True

    def _grants(self) -> Any:
        """The instance's persistent per-skill grants — the same
        ``<instance>/permissions.json`` the bridge and console read, so an
        "always" answered on any client applies on every client."""
        from jaeger_ai.core.entity.runtime import EntityRuntime
        from jaeger_os.core.safety.permissions import PermissionGrants

        layout = getattr(EntityRuntime.get_singleton(), "layout", None)
        return PermissionGrants.load(layout.root if layout is not None else None)

    def confirm(self, request: Any) -> bool:
        from jaeger_os.core.safety.permissions import PermissionTier
        skill_name = str(getattr(request, "skill", "") or "")
        # PolicyKernel REQUIRE_APPROVAL: only an explicit owner decision on an
        # approval card answers it; grants and autonomy shortcuts do not.
        if getattr(request, "force_prompt", False) is True:
            return self._decided(self._prompt(request))
        if skill_name and skill_name in self._session_grants():
            return True
        if self._write_or_exec(request) and not self._autonomy_auto():
            # Gateway-turn policy: writes and code/shell execution get a card
            # unless a project grant covers the target or the owner granted
            # this session (above). Persistent per-skill "always" grants and
            # the commissioning filesystem.write default do NOT apply here.
            try:
                if self.app._project_grant_allows(self.session_id, request):
                    return True
            except Exception:  # noqa: BLE001 — a grant check that fails means "ask"
                logger.debug("project grant check failed", exc_info=True)
            return self._decided(self._prompt(request))
        try:
            if self._grants().is_granted(skill_name):
                return True
        except Exception:  # noqa: BLE001 — unreadable grants mean "ask", never "allow"
            pass
        try:
            # Autonomy "auto" means no approval prompts for tiers 1-4. It is
            # honored only when the instance config explicitly says so; the
            # code default is "scoped" and an unreadable config reads as
            # "ask" (core/runtime/autonomy.py). Hardline-blocked commands never
            # reach here (the guard sits outside the tiers), and every action
            # stays audited.
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.runtime.autonomy import effective_autonomy
            layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            if effective_autonomy(getattr(layout, "config_path", None)) == "auto":
                return True
        except Exception:  # noqa: BLE001 — unreadable settings mean "ask", never "allow"
            pass
        try:
            from jaeger_ai.core.instance.commissioning import load_authority_policy
            from jaeger_ai.core.entity.runtime import EntityRuntime
            rt = EntityRuntime.get_singleton()
            policy = load_authority_policy(rt.layout.root) if getattr(rt, "layout", None) else {}
            tier = getattr(request, "tier", None)
            if tier == PermissionTier.READ_ONLY:
                return True
            if tier == PermissionTier.WRITE_LOCAL and bool((policy.get("filesystem") or {}).get("write")):
                return True
        except Exception:
            pass
        try:
            if self.app._project_grant_allows(self.session_id, request):
                return True
        except Exception:  # noqa: BLE001 — a grant check that fails means "ask"
            logger.debug("project grant check failed", exc_info=True)
        return self._decided(self._prompt(request))

    _DELETE_TOOLS = frozenset({"delete_file", "remove_file", "delete_path", "delete", "rm"})
    _EXEC_TOOLS = frozenset({"execute_code", "run_code", "python_exec"})

    def _write_or_exec(self, request: Any) -> bool:
        names = {str(getattr(request, "operation", "") or "")}
        app_cls = type(self.app)
        return bool(names & (app_cls._PROJECT_WRITE_TOOLS | app_cls._PROJECT_SHELL_TOOLS
                             | self._DELETE_TOOLS | self._EXEC_TOOLS))

    @staticmethod
    def _autonomy_auto() -> bool:
        """Owner explicitly saved autonomy "auto" (never the default)."""
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.runtime.autonomy import effective_autonomy
            layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            return effective_autonomy(getattr(layout, "config_path", None)) == "auto"
        except Exception:  # noqa: BLE001
            return False

    def _session_grants(self) -> set[str]:
        """Skills the owner allowed "for this session" (session metadata)."""
        try:
            meta = (self.app.store.get_session(self.session_id) or {}).get("metadata") or {}
            return {str(s) for s in meta.get("session_grants") or []}
        except Exception:  # noqa: BLE001 — unreadable means "ask", never "allow"
            return set()

    def _grant_for_session(self, skill: str) -> None:
        grants = sorted(self._session_grants() | {skill})
        self.app.store.update_metadata(self.session_id, {"session_grants": grants})

    def _decided(self, approved: bool) -> bool:
        if not approved and self.request_id not in self.app._owner_unanswered:
            self.app._owner_declined.add(self.request_id)
        return approved

    def _prompt(self, request: Any) -> bool:
        """Park an approval card and wait for the owner's decision."""
        loop = getattr(self.app, "_loop", None)
        if loop is None or not loop.is_running():
            return False
        skill = str(getattr(request, "skill", "") or "")
        op = str(getattr(request, "operation", "") or "")
        summary = str(getattr(request, "summary", "") or "")
        target = _approval_target(request) or summary
        tier_name = getattr(getattr(request, "tier", None), "name", str(getattr(request, "tier", "")))
        aid = f"approval_{uuid.uuid4().hex[:12]}"
        box: dict[str, Any] = {"done": threading.Event(), "approved": False}
        origin = self.app._approval_origin(self.session_id)

        def _arm() -> None:
            fut = loop.create_future()
            self.app.pending_approvals[aid] = fut
            self.app.store.create_approval(
                kind="tool_confirm",
                prompt=f"Allow {skill}.{op}? {target}".strip(),
                options=APPROVAL_OPTIONS,
                session_id=self.session_id,
                request_id=self.request_id,
                approval_id=aid,
                metadata={
                    "tool": f"{skill}.{op}" if skill else op,
                    "target": target,
                    "summary": summary,
                    "reason": tier_name,
                    **({"origin": origin} if origin else {}),
                },
            )
            self.app._publish_approval_request(self.session_id, origin, {
                "approval_id": aid,
                # Same card shape as handoff approvals (see handle_stream_events).
                "kind": "tool",
                "prompt": f"Allow {skill}.{op}? {target}".strip(),
                "tool": f"{skill}.{op}" if skill else op,
                "target": target,
                "reason": tier_name,
                "options": APPROVAL_OPTIONS,
                "session_id": self.session_id,
                "request_id": self.request_id,
            })

            def _done(f: asyncio.Future) -> None:
                try:
                    box["approved"] = bool(f.result())
                except Exception:
                    box["approved"] = False
                box["done"].set()

            fut.add_done_callback(_done)

        loop.call_soon_threadsafe(_arm)
        scope = self.app._cancellations.get(self.request_id)
        deadline = time.monotonic() + APPROVAL_WAIT_S
        while not box["done"].wait(timeout=0.05):
            if scope is not None and scope.cancelled:
                # Cancelled while parked: close the approval (first writer
                # wins) and refuse, whatever a racing decision says.
                self.app.pending_approvals.pop(aid, None)
                self.app.store.resolve_approval(aid, approved=False, decision="cancelled")
                return False
            if time.monotonic() >= deadline:
                break
        else:
            approved = bool(box["approved"]) and not (scope is not None and scope.cancelled)
            decision = (self.app.store.get_approval(aid) or {}).get("decision")
            # "always" also covers this session: under the write/exec policy the
            # persistent grant alone no longer skips the card in other sessions.
            if (approved and skill and decision in {"session", "always"}
                    and not getattr(request, "force_prompt", False)):
                try:
                    self._grant_for_session(skill)
                except Exception:  # noqa: BLE001 — the call itself stays approved
                    logger.warning("could not record session grant for %s", skill, exc_info=True)
            if (approved and not getattr(request, "force_prompt", False)
                    and decision == "always"):
                try:
                    self._grants().grant_persistent(skill)
                except Exception:  # noqa: BLE001 — the call itself stays approved
                    logger.warning("could not persist grant for %s", skill, exc_info=True)
            return approved
        # The tool call is about to be refused. Close the row so the phone
        # does not keep offering an approval that can no longer take effect;
        # if the operator's answer won the race, honour it instead.
        self.app.pending_approvals.pop(aid, None)
        if self.app.store.resolve_approval(aid, approved=False, decision="expired") is not None:
            self.app._owner_unanswered.add(self.request_id)     # nobody answered: needs the owner
            return False
        row = self.app.store.get_approval(aid) or {}
        return row.get("decision") not in {None, "deny", "expired"}


#: Tool-confirm card choices. ``session`` = "Allow for this session": recorded
#: in the session's metadata (``session_grants``), never for force_prompt calls.
APPROVAL_OPTIONS = ["once", "session", "deny"]


def _proactive_notification_payload(
    session_id: str, request_id: str, status: str, result: dict[str, Any],
) -> dict[str, Any] | None:
    """Build one Tier 3 wire payload, or None for quiet/proactive-unaware turns."""
    raw = result.get("proactive_salience")
    try:
        level = (
            SalienceLevel(int(raw)) if isinstance(raw, int)
            else SalienceLevel[str(raw).upper()]
        )
    except (KeyError, TypeError, ValueError):
        return None
    if level not in {SalienceLevel.IMMEDIATE, SalienceLevel.DIGEST}:
        return None
    if status not in {"completed", "failed", "cancelled", "execution_unknown"}:
        return None
    if status == "completed":
        title = "Jaeger proactive update"
        body = str(result.get("output") or "").strip() or "Proactive task completed."
        audio_cue = "chime"
    else:
        title = "Jaeger proactive task failed"
        body = f"Proactive task {status}: {str(result.get('error') or status)}"
        audio_cue = "alert"
    return {
        "title": title,
        "body": body,
        "session_id": session_id,
        "salience": level.name.lower(),
        "speak": level is SalienceLevel.IMMEDIATE,
        "audio_cue": audio_cue,
        "request_id": request_id,
        "source": result.get("proactive_source") or "sensor",
    }


# Fingerprint is scoped to this module's bytes at import, not the entire backend.
import hashlib as _source_hashlib
_GATEWAY_MODULE_SHA256 = _source_hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class JaegerGatewayApp:
    def __init__(
        self,
        store: GatewaySessionStore | None = None,
        event_bus: GatewayEventBus | None = None,
        background_client: Any = None,
        orchestration: Any | None = None,
    ) -> None:
        # Explicit stores are used by embedded/test gateways and never attach
        # to the operator's running bridge unless a client is supplied.
        if background_client is None and store is None:
            from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
            background_client = jaeger_bridge()
        self._background_client = background_client
        self._background_task: asyncio.Task | None = None
        self._background_status: dict[str, Any] = {"enabled": background_client is not None}
        self.store = store or GatewaySessionStore()
        from .file_changes import FileChanges
        self.file_changes = FileChanges(self.store.path.parent / "turn-file-changes")
        from jaeger_ai.core.agent_registry.projects import ProjectStore
        self.projects = ProjectStore(self.store.path.parent / "projects.json")
        self._summarizing: dict[str, asyncio.Task] = {}
        self.event_bus = event_bus or GatewayEventBus(store=self.store)
        if getattr(self.event_bus, "store", None) is None:
            self.event_bus.attach_store(self.store)
        self.pending_approvals: dict[str, asyncio.Future[bool]] = {}
        # Requests the agent has sent to the operator's editor, awaiting its answer.
        self._ide_pending: dict[str, tuple[str, Any]] = {}
        from jaeger_agent import task_port
        task_port.install_ide_requester(self._ide_request)
        self._running_tasks: dict[str | tuple[str, str], asyncio.Future[Any]] = {}
        # Requests whose owner declined an approval. A turn-owned card ends there (blocked).
        self._owner_declined: set[str] = set()
        # Tool names each live request has run, in order (for the owner's check step).
        self._request_tools: dict[str, list[str]] = {}
        # Requests whose approval the owner never answered. That is needs_owner, not blocked.
        self._owner_unanswered: set[str] = set()
        # Request-scoped live ReAct agents. The Gateway does not own the agent;
        # EntityRuntime supplies it while an admitted request is executing so
        # steering can be forwarded to the active JaegerAgent.
        self._active_agents: dict[str, Any] = {}
        # Request-scoped cancellation (R03): registered at admission, bound
        # to the executing agent, released when the worker returns.
        self._cancellations = CancellationRegistry()
        self._mcp_transport_lock = threading.RLock()
        self._mcp_transport_signature: tuple[Any, ...] | None = None
        self._mcp_transport: Any = None
        self._mcp_tool_names: frozenset[str] = frozenset()
        self._owns_store = False
        self._owner_task: asyncio.Task | None = None
        self._pending_recovery_report = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lifecycle_shutdown = asyncio.Event()
        self._background_producers: Any = None
        self._last_human_at = time.monotonic()
        self._last_human_session = "desktop-app"
        if orchestration is not None:
            self.orchestration = orchestration
        else:
            try:
                from jaeger_ai.features.ide_orchestration.service import create_default_orchestration_service
                self.orchestration = create_default_orchestration_service()
            except Exception as exc:
                logger.debug("Failed to initialize default ide_orchestration: %s", exc)
                self.orchestration = None
        if self.orchestration is not None and hasattr(self.orchestration, "bind_store"):
            self.orchestration.bind_store(self.store.path)
        from jaeger_ai.core.tasks.owner import GatewayTaskOwner
        self.task_owner = GatewayTaskOwner(self)
        self.app = web.Application(middlewares=[_reject_browser_cross_site, _authenticate_caller])
        self.app[CALLER_AUTH_KEY] = {"auth": None}
        _register_tool_gateway_auth()
        self.app.on_startup.append(self._recover_interrupted)
        self.app.on_startup.append(self._prewarm_gateway_mcp)
        self.app.on_cleanup.append(self._bounded_shutdown)
        self._setup_routes()
        from jaeger_ai.features.agent_bridge.outbox import attach as attach_agent_outbox
        attach_agent_outbox(self)

    async def _recover_interrupted(self, app: web.Application) -> None:
        self._loop = asyncio.get_running_loop()
        lease = self.store.claim_process(source_file=str(Path(__file__).resolve()))
        if not lease.get("ok"):
            raise RuntimeError(f"Gateway store is owned by live pid {lease.get('owner_pid')}")
        self._owns_store = True
        self.store.recover_interrupted_sessions()
        expired = self.store.expire_orphaned_tool_confirms()
        if expired:
            logger.info("Expired %d tool approvals orphaned by the previous process", expired)
        runtime_for_producers = None
        try:
            from jaeger_ai.core.entity.ownership import EntityRuntimeMode
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.entity.sensors.supervisor import SensorSupervisor
            try:
                from jaeger_agent.memory import sqlite_store
                from jaeger_agent.core.workspace import bind as bind_workspace
                from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
                inst = os.environ.get("JAEGER_INSTANCE_DIR")
                layout = InstanceLayout(root=Path(inst) if inst else resolve_instance_dir())
                sqlite_store.bind(layout)
                bind_workspace(layout)
            except Exception as exc:
                logger.debug("sqlite_store/workspace bind skipped: %s", exc)
            rt = EntityRuntime.get_singleton(mode=EntityRuntimeMode.OWNER)
            runtime_for_producers = rt
            if not getattr(rt, "_gateway_cognition_handler_registered", False):
                def _on_cognition_wake(ev: Any, state: Any) -> None:
                    from jaeger_ai.core.entity.events import EventType, JaegerEvent

                    # Human turns already execute through Gateway turn admission / execute_turn.
                    # Non-turn salient events (perceptions, observations, heartbeats) record an
                    # executive decision when they wake cognition on the resident owner.
                    if str(getattr(ev, "event_type", "")) in {
                        EventType.HUMAN_MESSAGE.value,
                        EventType.AGENT_RESPONSE.value,
                        EventType.EXECUTIVE_DECISION.value,
                    }:
                        return
                    dec = rt.executive_selector.select_strategy(ev, state)
                    rt.event_store.append(
                        JaegerEvent.executive_decision(
                            dec.strategy.value,
                            dec.reason,
                            parent_event_id=ev.event_id,
                            session_id=getattr(ev, "session_id", "system") or "system",
                        )
                    )

                rt.register_cognition_handler(_on_cognition_wake)
                rt._gateway_cognition_handler_registered = True
            logger.info(
                "Gateway attached EntityRuntime %s resident=%s",
                rt.identity.entity_id,
                getattr(rt, "is_resident", False),
            )
            try:
                from jaeger_ai.core.entity.recovery import RecoveryManager
                rt._recovery_report = RecoveryManager().scan_resumable_runs()
            except Exception as exc:
                logger.debug("Recovery rescan skipped: %s", exc)
            try:
                from jaeger_ai.core.instance.commissioning import install_commissioning_permissions
                install_commissioning_permissions(getattr(rt, "layout", None))
            except Exception as exc:
                logger.debug("commissioning permissions install skipped: %s", exc)
            if getattr(rt, "is_resident", False):
                try:
                    from jaeger_ai.core.instance.schemas import Config, load_yaml
                    layout = getattr(rt, "layout", None)
                    if layout is not None:
                        cfg = load_yaml(layout.config_path, Config)
                        desktop = getattr(getattr(cfg, "sensors", None), "desktop", None)
                        if desktop is not None and getattr(desktop, "enabled", False):
                            sup = SensorSupervisor(
                                runtime=rt,
                                enabled=True,
                                interval_s=float(desktop.interval_seconds),
                            )
                            sup.start()
                            rt._sensor_supervisor = sup
                except Exception as exc:
                    logger.debug("Gateway sensor supervisor skipped: %s", exc)
                self._owner_task = asyncio.create_task(self._owner_maintenance_loop(rt))
                self._pending_recovery_report = True
        except Exception as exc:
            logger.debug("Gateway EntityRuntime attach skipped: %s", exc)
        if runtime_for_producers is not None and getattr(runtime_for_producers, "layout", None) is not None:
            try:
                self.task_owner.migrate_legacy(runtime_for_producers.layout)
            except Exception:
                logger.exception("Legacy task import failed; original queue retained")
        self.task_owner.start()
        self._drain_all_queues()
        resume_workers = getattr(self.orchestration, 'resume_pending', None)
        if callable(resume_workers):
            resume_workers()
        if self._background_producers is None:
            self._start_background_producers(runtime_for_producers)
        if self._background_client is not None:
            self._background_task = asyncio.create_task(self._background_loop())

    async def _bounded_shutdown(self, app: web.Application) -> None:
        if not self._owns_store:
            return
        await self.task_owner.stop()
        if self._background_task is not None:
            self._background_task.cancel()
            await asyncio.gather(self._background_task, return_exceptions=True)
            self._background_task = None
        if self._owner_task is not None:
            self._owner_task.cancel()
            await asyncio.gather(self._owner_task, return_exceptions=True)
            self._owner_task = None
        if self._background_producers is not None:
            try:
                self._background_producers.stop()
            except Exception:
                logger.debug("background producer shutdown skipped", exc_info=True)
            self._background_producers = None
        cancel_all = getattr(self.orchestration, "cancel_all", None)
        if callable(cancel_all):
            try:
                unresolved = await cancel_all(timeout_seconds=1.5)
                if unresolved:
                    logger.warning(
                        "IDE worker cancellation unconfirmed during shutdown: %s",
                        ", ".join(unresolved),
                    )
            except Exception:
                logger.exception("IDE orchestration shutdown failed")
        tasks = list(self._running_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=2.0)
        self.store.recover_interrupted_sessions()
        self.store.release_process()
        self._owns_store = False

    async def _collect_background(self) -> int:
        client = self._background_client
        rows = await asyncio.to_thread(client.query, "background_messages", {"limit": 50}, timeout_s=5)
        if not isinstance(rows, list):
            raise ValueError("Native background outbox returned an invalid response")
        for row in rows:
            receipt = self.store.receive_background(row)
            if not receipt["replayed"]:
                self.event_bus.fanout(receipt["event"])
                try:
                    from jaeger_ai.core.entity.runtime import EntityRuntime
                    EntityRuntime.get_singleton().record_background_completed(
                        str(row.get("id") or row.get("delivery_id") or ""),
                        row,
                        session_id=str(row.get("session_id") or "dispatcher"),
                    )
                except Exception:
                    pass
            # Receipt + transcript + event are committed before native ACK.
            # Failed/lost ACK retries delivery, never the model or its tools.
            await asyncio.to_thread(client.command, "acknowledge_background", {"delivery_id": row["delivery_id"]})
        return len(rows)

    async def _owner_maintenance_loop(self, runtime: Any) -> None:
        """Heartbeat, sleep-time, and indexing owned by the resident Gateway.

        The owner tick stays on its existing cadence. The lifecycle lease is
        polled faster so a missed menu-bar heartbeat shuts the stack down
        soon after the grace period, not a full tick later.
        """
        interval = float(os.environ.get("JAEGER_HEARTBEAT_INTERVAL_S") or 0) or 30.0
        lease_every = float(os.environ.get("JAEGER_LIFECYCLE_POLL_S") or 2.0)
        elapsed = 0.0
        while not self._lifecycle_shutdown.is_set():
            if elapsed <= 0:
                try:
                    await asyncio.to_thread(self._owner_tick, runtime)
                except Exception as exc:
                    logger.warning("Owner maintenance tick failed: %s", exc)
                elapsed = interval
            self._note_lifecycle()
            step = max(0.5, min(lease_every, elapsed))
            try:
                await asyncio.wait_for(self._lifecycle_shutdown.wait(), timeout=step)
            except asyncio.TimeoutError:
                elapsed -= step

    def _owner_tick(self, runtime: Any) -> None:
        """Sleep-time consolidation. Heartbeat/board/cron live on the producer lease."""
        sleep_due = os.environ.get("JAEGER_SLEEP_DUE", "").strip() in {"1", "true", "yes"}
        force_hb = os.environ.get("JAEGER_HEARTBEAT_DUE", "").strip() in {"1", "true", "yes"}
        if not (sleep_due or force_hb):
            return
        try:
            runtime.sleep_time_processor.run_sleep_cycle(reason="gateway_idle")
        except Exception as exc:
            logger.debug("Sleep-time cycle skipped: %s", exc)

    def _start_background_producers(self, runtime: Any) -> None:
        from jaeger_ai.core.runtime.background_producers import BackgroundProducers

        layout = getattr(runtime, "layout", None)
        if layout is None:
            try:
                from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
                inst = os.environ.get("JAEGER_INSTANCE_DIR")
                layout = InstanceLayout(root=Path(inst) if inst else resolve_instance_dir())
            except Exception as exc:
                logger.debug("Gateway background producer layout unavailable: %s", exc)
                return
        name = ""
        try:
            name = str(getattr(runtime.identity, "display_name", "") or "")
        except Exception:
            name = ""
        producers = BackgroundProducers(layout, self._background_sink(), display_name=name)
        if producers.try_start():
            self._background_producers = producers
            logger.info("Gateway owns instance background producers")
        else:
            logger.info("Gateway skipped background producers; another process holds the lease")

    def _background_sink(self) -> Any:
        app = self

        class _Sink:
            def current_tier(self) -> str:
                return app._current_tier()

            def is_busy(self) -> bool:
                return bool(app._running_tasks)

            def last_user_quiet_s(self) -> float:
                return time.monotonic() - app._last_human_at

            def last_user_session(self) -> str:
                return app._last_human_session or "desktop-app"

            def submit_turn(
                self, prompt: str, *, session: str, request_id: str, source: str,
                salience: str | None = None, allowed_tools: list[str] | None = None,
            ) -> dict[str, Any]:
                return app.submit_background_turn(
                    prompt, session_id=session, request_id=request_id, source=source,
                    salience=salience, allowed_tools=allowed_tools,
                )

            def deliver_proactive(self, text: str, *, initiative: Any, request_id: str) -> dict[str, Any]:
                return app.deliver_proactive(text, initiative=initiative, request_id=request_id)

        return _Sink()

    def deliver_proactive(self, text: str, *, initiative: Any, request_id: str) -> dict[str, Any]:
        """Speak first: put one composed initiative into the owner's conversation.

        Thread-safe (called from the producer thread). The message lands as
        an assistant message in the owner's last session plus one
        ``notification.proactive`` SSE event there, which the Mac app and
        WebUI surface (and speak). Global Stop silences delivery.
        """
        body = str(text or "").strip()
        if not body:
            return {"delivered": False, "reason": "empty"}
        blocked = _control_plane_block()
        if blocked:
            return {"delivered": False, "reason": "stopped"}
        session_id = self._last_human_session or "desktop-app"
        level = getattr(getattr(initiative, "level", None), "name", "DIGEST").lower()
        payload = {
            "title": "Jaeger",
            "body": body,
            "session_id": session_id,
            "salience": level,
            "speak": True,
            "audio_cue": "chime" if level != "immediate" else "alert",
            "request_id": request_id,
            "proactive": True,
            "proactive_source": str(getattr(initiative, "source", "") or "initiative"),
            "kind": str(getattr(initiative, "kind", "") or ""),
            "created_at": time.time(),
        }

        def _write() -> None:
            self.store.ensure_session(session_id)
            self.store.append_message(session_id, "assistant", body)
            self.event_bus.publish(session_id, "notification.proactive", payload)

        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                _write()
            else:
                async def _on_loop() -> None:
                    _write()
                asyncio.run_coroutine_threadsafe(_on_loop(), loop).result(timeout=30)
        else:
            _write()
        try:
            from jaeger_ai.core.runtime.notifier import fan_out
            payload["channels"] = fan_out(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("proactive fan-out failed: %s", exc)
        return {"delivered": True, "session_id": session_id, **payload}

    def submit_background_turn(
        self,
        prompt: str,
        *,
        session_id: str,
        request_id: str,
        source: str,
        salience: str | int | None = None,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Admit and run a background turn on the Gateway event loop.

        Safe to call from a producer thread. Identical request_id replays;
        a busy session is skipped rather than crashing the producer.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            return {"text": "", "error": "gateway loop is not running", "halt_reason": "error"}
        blocked = _control_plane_block()
        if blocked:
            return {"text": "", "error": blocked, "halt_reason": "stopped", "skipped": True, "replayed": False}
        future = asyncio.run_coroutine_threadsafe(
            self._run_background_turn(
                prompt, session_id=session_id, request_id=request_id, source=source,
                salience=salience, allowed_tools=allowed_tools,
            ),
            loop,
        )
        return future.result(timeout=float(os.environ.get("JAEGER_BACKGROUND_TURN_WAIT_S") or 3600))

    async def _run_background_turn(
        self,
        prompt: str,
        *,
        session_id: str,
        request_id: str,
        source: str,
        salience: str | int | None = None,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        tier = self._current_tier()
        if tier != "jaeger":
            return {
                "text": "",
                "error": f"Proactive background turns are disabled in '{tier}' mode (requires 'jaeger' mode)",
                "status": "disabled",
                "replayed": False,
                "skipped": True,
                "halt_reason": "tier_disabled",
            }
        options = {"source": source, "background": True}
        if salience is not None:
            options["proactive_salience"] = _normalize_salience(salience)
        requested: dict[str, Any] = {"options": options}
        if allowed_tools is not None:
            # [] = a compose-only turn: the agent is built with no tools.
            requested["allowed_tools"] = list(allowed_tools)
        try:
            admitted = self.store.admit_request(
                session_id, prompt, request_id=request_id, requested=requested,
            )
        except RequestConflict as exc:
            # Same request_id with different text or choices is a conflict.
            # Returning the old output would hide the changed input.
            return {
                "text": "",
                "error": str(exc),
                "status": "conflict",
                "replayed": False,
                "halt_reason": "conflict",
            }
        except RequestBusy:
            return {"text": "", "error": "Turn already in progress", "halt_reason": "busy", "skipped": True}
        except ValueError as exc:
            return {"text": "", "error": str(exc), "halt_reason": "error"}

        self._start_admitted_turn(admitted, session_id, prompt)
        rid = admitted["request_id"]
        task = self._running_tasks.get(rid)
        if task is not None:
            await task
        row = self.store.get_request(rid) or {}
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        return {
            "text": str(result.get("output") or ""),
            "error": result.get("error"),
            "status": row.get("status"),
            "replayed": bool(admitted.get("replayed")),
            "halt_reason": "interrupted" if row.get("status") == "cancelled" else None,
            "execution_unknown": row.get("status") == "execution_unknown",
        }

    def _drain_session_queue(self, session_id: str) -> None:
        """Promote exactly one queued item after a definite terminal outcome."""
        promoted = self.store.promote_next_queue_item(session_id)
        if promoted is None:
            return
        items = self.store.list_queue(session_id)
        self.event_bus.publish(session_id, "queue.updated", {"items": items})
        self._start_admitted_turn(
            promoted, session_id, str(promoted.get("input_text") or ""),
        )

    def _drain_all_queues(self) -> None:
        """Restart-safe drain: one queued item per idle session."""
        for session_id in self.store.sessions_with_queue():
            self._drain_session_queue(session_id)

    def _start_admitted_turn(
        self, admitted: dict[str, Any], session_id: str, text: str,
    ) -> None:
        turn_id = admitted["turn_id"]
        rid = admitted["request_id"]
        if admitted.get("event"):
            self.event_bus.fanout(admitted["event"])
        elif not admitted.get("replayed"):
            self.event_bus.publish(session_id, "turn.start", {
                "turn_id": turn_id, "request_id": rid, "text": text,
            })
        if admitted.get("accepted") and rid not in self._running_tasks:
            self._cancellations.register(rid)
            self._running_tasks[rid] = asyncio.create_task(
                self._execute_turn(
                    session_id, turn_id, text, request_id=rid,
                    execution=_admitted_execution(admitted),
                )
            )

    def _preserve_unknown_requests(self) -> None:
        """Startup observes uncertain outcomes; it never redispatches their input.

        A recoverable native checkpoint or an empty pending-effect list does
        not establish whether the original request already caused an effect.
        Keep the original request/session/history for explicit reconciliation.
        """
        unknown = self.store.list_requests(status="execution_unknown")
        if unknown:
            logger.warning("Preserving %d execution_unknown requests without replay", len(unknown))

    async def _background_loop(self) -> None:
        while True:
            try:
                count = await self._collect_background()
                self._background_status = {"enabled": True, "ok": True, "last_poll": time.time(), "received": count}
            except Exception as exc:
                self._background_status = {"enabled": True, "ok": False, "error": str(exc)}
                logger.warning("Background delivery pending: %s", exc)
            await asyncio.sleep(2)

    def _setup_routes(self) -> None:
        from jaeger_ai.features.knowledge_library.routes import register as register_library
        register_library(self)
        from jaeger_ai.features.workflows.routes import register as register_workflows
        register_workflows(self)
        from jaeger_ai.plugins.mcp.routes import register as register_mcp_controls
        register_mcp_controls(self)
        from jaeger_ai.plugins.control_routes import register as register_plugin_controls
        register_plugin_controls(self)
        from jaeger_ai.features.notifications.routes import register as register_notifications
        register_notifications(self)
        from jaeger_ai.features.channels.controls import register as register_channel_controls
        register_channel_controls(self)
        from .agent_memory import register as register_agent_memory
        register_agent_memory(self)
        from .native_controls import register as register_native_controls
        register_native_controls(self)
        from jaeger_ai.features.agent_bridge.routes import register
        register(self)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/v1/stop", self.handle_stop_status)
        self.app.router.add_post("/v1/stop", self.handle_engage_stop)
        self.app.router.add_post("/v1/stop/release", self.handle_release_stop)
        self.app.router.add_get("/v1/runtime/status", self.handle_runtime_status)
        self.app.router.add_get("/version", self.handle_version)
        # Agent catalog — persistence spine for Mac app + WebUI clients.
        self.app.router.add_get("/v1/agents", self.handle_list_agents)
        self.app.router.add_get("/v1/frameworks", self.handle_list_frameworks)
        self.app.router.add_post("/v1/frameworks/{id}/grants", self.handle_framework_grant)
        self.app.router.add_post("/v1/agents", self.handle_create_agent)
        self.app.router.add_get("/v1/agent-templates", self.handle_agent_templates)
        self.app.router.add_get("/v1/agents/{id}/knowledge", self.handle_agent_knowledge)
        self.app.router.add_patch("/v1/agents/{id}/knowledge", self.handle_agent_knowledge)
        self.app.router.add_get("/v1/agents/{id}/configuration", self.handle_agent_configuration)
        self.app.router.add_patch("/v1/agents/{id}/configuration", self.handle_agent_configuration)
        self.app.router.add_get("/v1/sections", self.handle_agent_sections)
        self.app.router.add_post("/v1/sections", self.handle_agent_sections)
        self.app.router.add_post("/v1/agents/pins", self.handle_agent_pins)
        self.app.router.add_get("/v1/agents/primary", self.handle_agent_primary)
        self.app.router.add_post("/v1/agents/primary", self.handle_agent_primary)
        self.app.router.add_patch("/v1/agents/{id}", self.handle_agent_presentation)
        self.app.router.add_get("/v1/agents/summary", self.handle_agents_summary)
        self.app.router.add_get("/v1/agents/{id}", self.handle_get_agent)
        self.app.router.add_get("/v1/agents/{id}/home", self.handle_agent_home)
        self.app.router.add_get("/v1/agents/{id}/messages/search", self.handle_agent_message_search)
        self.app.router.add_post("/v1/agents/{id}/activate", self.handle_activate_agent)
        self.app.router.add_post("/v1/agents/{id}/seen", self.handle_agent_seen)
        self.app.router.add_post("/v1/agents/{id}/handoff", self.handle_handoff_agent)
        self.app.router.add_get("/v1/handoffs", self.handle_list_handoffs)
        self.app.router.add_get("/v1/projects", self.handle_list_projects)
        self.app.router.add_post("/v1/projects", self.handle_create_project)
        self.app.router.add_get("/v1/projects/{id}", self.handle_get_project)
        self.app.router.add_post("/v1/projects/{id}/check", self.handle_project_check)
        self.app.router.add_get("/v1/sessions", self.handle_list_sessions)
        self.app.router.add_post("/v1/sessions", self.handle_create_session)
        self.app.router.add_get("/v1/sessions/{id}", self.handle_get_session)
        self.app.router.add_delete("/v1/sessions/{id}", self.handle_delete_session)
        self.app.router.add_patch("/v1/sessions/{id}", self.handle_patch_session)
        self.app.router.add_post("/v1/sessions/{id}/branch", self.handle_branch_session)
        self.app.router.add_post("/v1/sessions/{id}/feedback", self.handle_message_feedback)
        self.app.router.add_get("/v1/sessions/{id}/feedback", self.handle_message_feedback)
        self.app.router.add_post("/v1/sessions/{id}/retry", self.handle_retry_session)
        self.app.router.add_post("/v1/sessions/{id}/turns", self.handle_send_turn)
        self.app.router.add_get("/v1/sessions/{id}/queue", self.handle_get_queue)
        self.app.router.add_post("/v1/sessions/{id}/queue", self.handle_add_queue)
        self.app.router.add_post("/v1/sessions/{id}/queue/reorder", self.handle_reorder_queue)
        self.app.router.add_patch("/v1/sessions/{id}/queue/{request_id}", self.handle_update_queue)
        self.app.router.add_delete("/v1/sessions/{id}/queue/{request_id}", self.handle_delete_queue)
        self.app.router.add_post("/v1/sessions/{id}/cancel", self.handle_cancel_turn)
        self.app.router.add_post("/v1/sessions/{id}/requests/{request_id}/steer", self.handle_steer_request)
        self.app.router.add_post("/v1/sessions/{id}/reconcile", self.handle_reconcile)
        self.app.router.add_get("/v1/sessions/{id}/requests/{request_id}", self.handle_get_request)
        self.app.router.add_get("/v1/sessions/{id}/requests/{request_id}/changes", self.handle_file_changes)
        self.app.router.add_post("/v1/sessions/{id}/requests/{request_id}/changes/undo", self.handle_file_changes)
        self.app.router.add_post("/v1/sessions/{id}/handoff", self.handle_session_handoff)
        self.app.router.add_get("/v1/sessions/{id}/stream", self.handle_stream_events)
        self.app.router.add_get("/v1/sessions/{id}/messages", self.handle_list_messages)
        self.app.router.add_get("/v1/events/stream", self.handle_global_stream)
        self.app.router.add_get("/v1/connect-apps", self.handle_connect_apps)
        self.app.router.add_get("/v1/connect-apps/{id}/state", self.handle_connect_app_state)
        self.app.router.add_post("/v1/connect-apps/{id}/install", self.handle_connect_app_install)
        self.app.router.add_get("/v1/sessions/{id}/events", self.handle_session_events_json)
        self.app.router.add_get("/v1/notifications", self.handle_list_notifications)
        self.app.router.add_get("/v1/presence", self.handle_presence)
        self.app.router.add_get("/v1/requests/{request_id}", self.handle_get_request_any_session)
        self.app.router.add_get("/v1/sessions/{id}/activity", self.handle_activity_history)
        self.app.router.add_get("/v1/handoffs/{id}", self.handle_get_handoff)
        self.app.router.add_get("/v1/handoffs/{id}/messages", self.handle_handoff_messages)
        self.app.router.add_post("/v1/handoffs/{id}/reply", self.handle_handoff_reply)
        self.app.router.add_post("/v1/approvals/{id}", self.handle_resolve_approval)
        self.app.router.add_post("/v1/approvals/{id}/decision", self.handle_resolve_approval)
        self.app.router.add_get("/v1/approvals", self.handle_list_approvals)
        self.app.router.add_get("/v1/approvals/{id}", self.handle_get_approval)
        self.app.router.add_get("/v1/runtime/frameworks", self.handle_runtime_frameworks)
        self.app.router.add_get("/v1/runtime/models", self.handle_runtime_models)
        self.app.router.add_get("/v1/runtime/capabilities", self.handle_runtime_capabilities)
        self.app.router.add_get("/v1/runtime/skills", self.handle_runtime_skills)
        self.app.router.add_get("/v1/runtime/skills/detail", self.handle_runtime_skill_detail)
        self.app.router.add_get("/v1/runtime/tools", self.handle_runtime_tools)
        self.app.router.add_get("/v1/channels", self.handle_channels)
        self.app.router.add_get("/v1/task-submissions/{request_id}", self.handle_task_submission)
        self.app.router.add_get("/v1/runtime/diagnostics", self.handle_runtime_diagnostics)
        self.app.router.add_post("/v1/sessions/{id}/ide/{ide_request_id}", self.handle_ide_result)
        self.app.router.add_get("/v1/runtime/autonomy", self.handle_get_autonomy)
        self.app.router.add_post("/v1/runtime/autonomy", self.handle_set_autonomy)
        self.app.router.add_get("/v1/runtime/tier", self.handle_get_tier)
        self.app.router.add_post("/v1/runtime/tier", self.handle_set_tier)
        self.app.router.add_get("/v1/sessions/{id}/attachments", self.handle_list_attachments)
        self.app.router.add_get("/v1/sessions/{id}/files", self.handle_session_files)
        self.app.router.add_get("/v1/sessions/{id}/files/{attachment_id}", self.handle_session_file)
        self.app.router.add_post("/v1/sessions/{id}/attachments", self.handle_add_attachment)
        self.app.router.add_post("/v1/sessions/{id}/attachments/upload", self.handle_upload_attachment)
        self.app.router.add_get("/v1/tasks", self.handle_tasks)
        self.app.router.add_post("/v1/tasks", self.handle_tasks)
        self.app.router.add_get("/v1/tasks/{id}", self.handle_task)
        self.app.router.add_patch("/v1/tasks/{id}", self.handle_task_edit)
        self.app.router.add_post("/v1/tasks/{id}/cancel", self.handle_task_cancel)
        self.app.router.add_post("/v1/tasks/{id}/approve", self.handle_task_approve)
        self.app.router.add_get("/v1/orchestration/workers", self.handle_list_orchestration_workers)
        self.app.router.add_post("/v1/orchestration/tasks", self.handle_create_orchestration_task)
        self.app.router.add_get("/v1/orchestration/tasks/{id}", self.handle_get_orchestration_task)
        self.app.router.add_post("/v1/orchestration/tasks/{id}/follow-up", self.handle_follow_up_orchestration_task)
        self.app.router.add_post("/v1/orchestration/tasks/{id}/cancel", self.handle_cancel_orchestration_task)
        # OpenAI-compatible surface for the IDE (GET /v1/models, POST /v1/chat/completions).
        from jaeger_ai.core.gateway import openai_compat
        openai_compat.register(self.app)

    async def handle_version(self, request: web.Request) -> web.Response:
        """Stable, read-only identity for clients and deployment checks."""
        return web.json_response({
            "component": "jaeger-gateway",
            "version": JAEGER_VERSION,
            "protocol_version": "1",
        })

    async def _probe_http(self, url: str, *, timeout_s: float = 2.0) -> dict[str, Any]:
        """Probe a dependency; never raises — fail-closed callers inspect ok=False.

        HTTP 2xx alone is not enough: bridge may answer 200 with ``{"ok": false}``.
        """
        try:
            timeout = ClientTimeout(total=timeout_s)
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    body = await resp.text()
                    payload_ok: bool | None = None
                    try:
                        parsed = json.loads(body)
                        if isinstance(parsed, dict) and "ok" in parsed:
                            payload_ok = bool(parsed.get("ok"))
                        elif isinstance(parsed, dict) and "status" in parsed:
                            payload_ok = str(parsed.get("status")).lower() in {
                                "ok", "healthy", "up", "ready",
                            }
                    except Exception:  # noqa: BLE001
                        payload_ok = None
                    http_ok = 200 <= resp.status < 300
                    ok = http_ok if payload_ok is None else (http_ok and payload_ok)
                    return {
                        "ok": ok,
                        "status_code": resp.status,
                        "url": url,
                        "payload_ok": payload_ok,
                        "body_excerpt": body[:200],
                    }
        except Exception as exc:  # noqa: BLE001 — health must never crash
            return {"ok": False, "status_code": 0, "url": url, "error": str(exc)}

    async def _probe_webui_legacy_chat(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Probe locked WebUI legacy ``/api/chat``. HTTP 500 ⇒ fail-closed (M8).

        Non-500 responses (including 400/404 validation) mean the route is alive.
        Connection errors also fail closed — chat surface unreachable.
        """
        url = f"{LOCKED_WEBUI_URL}/api/chat"
        try:
            timeout = ClientTimeout(total=timeout_s)
            async with ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    json={"session_id": "__jaeger_health_probe__", "message": "ping"},
                ) as resp:
                    body = await resp.text()
                    # CoS: must not claim all_green while legacy /api/chat returns 500.
                    # Validation errors establish reachability only, not readiness.
                    ok = 200 <= resp.status < 300
                    return {
                        "ok": ok,
                        "status_code": resp.status,
                        "url": url,
                        "required": True,
                        "body_excerpt": body[:200],
                        "note": (
                            "legacy /api/chat returned 500"
                            if resp.status == 500
                            else "legacy chat readiness is not verified by a validation response"
                        ),
                    }
        except Exception as exc:  # noqa: BLE001 — health must never crash
            return {
                "ok": False,
                "status_code": 0,
                "url": url,
                "required": True,
                "error": str(exc),
                "note": "legacy /api/chat unreachable",
            }

    async def _probe_native_mcp(self, *, timeout_s: float = 3.0) -> dict[str, Any]:
        """Read-only MCP and native-agent readiness; never executes chat."""
        from jaeger_ai.core.gateway.native_mcp import (
            MCP_URL, MCP_HOST_HEADER, mcp_api_key,
        )
        headers = {"Accept": "application/json, text/event-stream", "Host": MCP_HOST_HEADER}

        async def terminate_session() -> None:
            """Release the stdio backend allocated by the MCP handshake."""
            if "Mcp-Session-Id" not in headers:
                return
            try:
                timeout = ClientTimeout(total=min(1.0, timeout_s))
                async with ClientSession(timeout=timeout) as client:
                    async with client.delete(MCP_URL, headers=headers) as response:
                        # Session termination is best-effort health-check cleanup. A
                        # proxy may answer 404 after already reaping the session.
                        if response.status not in {200, 202, 204, 404}:
                            response.raise_for_status()
            except Exception:  # noqa: BLE001 — cleanup must not hide probe health
                pass

        async def rpc(client, method, params, identity):
            async with client.post(MCP_URL, headers=headers, json={
                "jsonrpc": "2.0", "id": identity, "method": method, "params": params,
            }) as response:
                response.raise_for_status()
                if response.headers.get("Mcp-Session-Id"):
                    headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                # A server may keep SSE open after the response; consume only
                # the matching RPC result, with a bounded total body and timeout.
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    size = 0
                    async for line in response.content:
                        size += len(line)
                        if size > 1_000_000:
                            raise ValueError("MCP catalog response too large")
                        if line.startswith(b"data:"):
                            value = json.loads(line[5:])
                            if value.get("id") == identity:
                                break
                    else:
                        raise ValueError("MCP returned no matching result")
                else:
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > 1_000_000:
                            raise ValueError("MCP catalog response too large")
                    value = json.loads(raw)
                if value.get("error") or value.get("id") != identity:
                    raise ValueError("MCP rejected readiness probe")
                return value.get("result", {})

        try:
            key = mcp_api_key()
            if key:
                headers["Authorization"] = f"Bearer {key}"
            async with asyncio.timeout(timeout_s):
                async with ClientSession(timeout=ClientTimeout(total=timeout_s)) as client:
                    await rpc(client, "initialize", {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "jaeger-health", "version": "1"},
                    }, 1)
                    async with client.post(MCP_URL, headers=headers, json={
                        "jsonrpc": "2.0", "method": "notifications/initialized",
                    }) as response:
                        response.raise_for_status()
                    catalog = await rpc(client, "tools/list", {}, 2)
                    names = {t.get("name") for t in catalog.get("tools", [])}
                    chat_available = bool(names & {"chat", "jaeger_chat"})
                    health_tool = next((n for n in ("jaeger_bridge_health", "bridge_health") if n in names), None)
                    agent_ready = False
                    if chat_available and health_tool:
                        health_result = await rpc(client, "tools/call", {"name": health_tool, "arguments": {}}, 3)
                        if not health_result.get("isError"):
                            health = health_result.get("structuredContent")
                            if not isinstance(health, dict):
                                health = json.loads(self._mcp_chat_text(health_result))
                            agent_ready = bool(health.get("ok")) and health.get("ready", {}).get("agent") == "ready"
                    transport_ready = chat_available
                    ok = chat_available and agent_ready
                    return {
                        "ok": ok, "required": True, "url": MCP_URL,
                        "transport_ready": transport_ready,
                        "chat_tool_available": chat_available,
                        "agent_ready": agent_ready,
                        "execution_verified": False,
                        "note": "Native bridge readiness; model execution not probed",
                    }
        except Exception as exc:
            return {
                "ok": False, "required": True, "url": MCP_URL,
                "error": type(exc).__name__,
                "transport_ready": False,
                "chat_tool_available": False,
                "agent_ready": False,
                "execution_verified": False,
            }
        finally:
            await terminate_session()

    def _note_lifecycle(self) -> None:
        """Suspend is immediate. Once the grace inside the lease has elapsed, shut down."""
        from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease
        try:
            decision = LifecycleLease.load().decide()
        except Exception:
            logger.error("Lifecycle lease unreadable; shutting down", exc_info=True)
            self._lifecycle_shutdown.set()
            return
        if decision.shutdown:
            logger.warning("Lifecycle owner disappeared; controlled shutdown (%s)", decision.reason)
            self._lifecycle_shutdown.set()

    async def _halt_for_stop(self) -> list[str]:
        """Cancel in-flight helpers. Names that do not confirm are returned."""
        from jaeger_ai.core.devices.registry import block_device_commands
        block_device_commands()
        unconfirmed: list[str] = []
        scopes = getattr(self._cancellations, "_scopes", {})
        for request_id in list(scopes):
            try:
                self._cancellations.cancel(str(request_id))
            except Exception:
                unconfirmed.append(str(request_id))
        cancel_all = getattr(self.orchestration, "cancel_all", None)
        if callable(cancel_all):
            try:
                pending = cancel_all(timeout_seconds=1.5)
                if asyncio.iscoroutine(pending):
                    pending = await pending
                if pending:
                    unconfirmed.extend(str(item) for item in pending)
            except Exception:
                unconfirmed.append("orchestration")
        cancelled_tasks = []
        for key, task in list(self._running_tasks.items()):
            if not task.done():
                task.cancel()
                cancelled_tasks.append((key, task))
        # Commands the owner's workers started are not stopped by cancelling the task that
        # awaits them: terminate them, and report anything that survives.
        unconfirmed.extend(await asyncio.to_thread(self._stop_owned_processes))
        if cancelled_tasks:
            _done, still = await asyncio.wait([t for _, t in cancelled_tasks], timeout=2.0)
            unconfirmed.extend(str(k) for k, t in cancelled_tasks if t in still)
        return unconfirmed

    @staticmethod
    def _stop_owned_processes() -> list[str]:
        """Terminate command sessions and background processes this owner started."""
        survivors: list[str] = []
        try:
            from jaeger_agent.tools.pty_exec import kill_all_sessions
            survivors += [f"command-session:{pid}" for pid in kill_all_sessions()["survivors"]]
        except Exception:
            logger.warning("could not stop command sessions", exc_info=True)
            survivors.append("command-sessions")
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            if layout is not None:
                from jaeger_agent.background.processes import stop_all_background
                survivors += [f"background:{pid}" for pid in stop_all_background(layout)["survivors"]]
        except Exception:
            logger.warning("could not stop background processes", exc_info=True)
            survivors.append("background-processes")
        return survivors

    async def handle_stop_status(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError
        latch = GlobalStop.load()
        try:
            state = latch.read()
        except GlobalStopError:
            return web.json_response({
                "engaged": True, "reason": "unreadable latch", "engaged_by": "", "unconfirmed": [],
            })
        return web.json_response({
            "engaged": state.engaged,
            "reason": state.reason,
            "engaged_by": state.engaged_by,
            "unconfirmed": list(state.unconfirmed),
            "cancellation_confirmed": not state.unconfirmed,
        })

    async def handle_engage_stop(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.gateway.global_stop import GlobalStop
        spec = request["caller"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        reason = str(body.get("reason") or "stop")
        state = GlobalStop.load().engage(
            spec.name, reason=reason, unconfirmed=await self._halt_for_stop(),
        )
        return web.json_response({
            "engaged": state.engaged,
            "reason": state.reason,
            "engaged_by": state.engaged_by,
            "unconfirmed": list(state.unconfirmed),
            "cancellation_confirmed": not state.unconfirmed,
        })

    async def handle_release_stop(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.devices.registry import allow_device_commands
        from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError
        spec = request["caller"]
        try:
            state = GlobalStop.load().release(spec)
        except GlobalStopError as exc:
            return web.json_response({"error": str(exc)}, status=403)
        allow_device_commands()
        return web.json_response({"engaged": state.engaged, "released_by": spec.name})

    async def handle_health(self, request: web.Request) -> web.Response:
        """Backend readiness is independent of optional HTTP adapters and UIs."""
        owner = self._probe_owner_runtime()
        bridge, ollama, webui_chat, native_mcp = await asyncio.gather(
            self._probe_http(LOCKED_BRIDGE_HEALTH_URL),
            self._probe_http(f"{LOCKED_OLLAMA_URL}/api/tags"),
            self._probe_http(LOCKED_WEBUI_URL),
            self._probe_native_mcp(),
        )
        # Read-only surface availability. Never create fake chat requests from
        # health checks, and never mistake a 404 for a working conversation.
        external_model_configured = False
        try:
            from jaeger_ai.core.instance.instance import resolve_instance_dir
            from jaeger_ai.core.instance.schemas import Config, load_yaml
            cfg_path = resolve_instance_dir() / "config.yaml"
            if cfg_path.exists():
                cfg = load_yaml(cfg_path, Config)
                ext = getattr(cfg, "external_model", None)
                if ext and getattr(ext, "enabled", False):
                    external_model_configured = True
        except Exception:
            pass

        ollama_required = not external_model_configured
        checks = {
            "gateway": {"ok": True, "url": f"http://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}"},
            "bridge": {**bridge, "required": False},
            "ollama": {**ollama, "required": ollama_required},
            "webui": {**webui_chat, "required": False, "chat_execution_verified": False},
            "native_mcp": native_mcp,
            "owner_runtime": owner,
        }
        native_mcp["required"] = not owner["ok"]
        required_ok = (
            (bool(ollama.get("ok")) or not ollama_required)
            and (owner["ok"] or bool(native_mcp.get("ok")))
        )
        all_green = required_ok
        status = "ok" if all_green else "unhealthy"
        git_commit = "unknown"
        try:
            import subprocess
            git_commit = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                text=True,
                timeout=2,
            ).strip()
        except Exception:
            pass

        active_model = "unknown"
        try:
            from jaeger_ai.core.runtime.truth import _active_model
            active_model = _active_model(self._instance_root()).get("model") or "unknown"
        except Exception:
            pass

        payload = {
            "status": status,
            "service": "jaeger-gateway",
            "version": JAEGER_VERSION,
            "commit": git_commit,
            "model": active_model,
            "architecture": "openclaw-parity",
            "persistence_spine": True,
            "agents_api": "/v1/agents",
            "fundamentals_fee_gated": False,
            "fail_closed": True,
            "health_scope": "backend_transport_readiness",
            "all_green": all_green,
            "checks": checks,
            "diagnostics": {"source_file": str(Path(__file__).resolve()),
                            "background_delivery": self._background_status,
                            "session_store": str(self.store.path.resolve()),
                            "instance_root": str(self._instance_root()),
                            "schema_version": self.store.schema_version(),
                            "process_lease": self.store.process_lease(),
                            **self._entity_diagnostics()},
            "capabilities": {
                "native_agent": owner["ok"] or bool(native_mcp.get("ok")),
                "transport_ready": bool(native_mcp.get("transport_ready") or native_mcp.get("chat_tool_available")),
                "agent_ready": owner["ok"] or bool(native_mcp.get("agent_ready")),
                "execution_verified": bool(native_mcp.get("execution_verified")),
                "end_to_end_chat_verified": False,
            },
            "locked_endpoints": {
                "ollama": LOCKED_OLLAMA_URL,
                "webui": LOCKED_WEBUI_URL,
                "gateway": f"http://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}",
            },
        }
        return web.json_response(payload, status=200 if all_green else 503)

    @staticmethod
    def _probe_owner_runtime() -> dict[str, Any]:
        """Check the same resident OWNER used by turn execution, without a turn."""
        from jaeger_ai.core.entity.ownership import EntityRuntimeMode
        from jaeger_ai.core.entity.runtime import EntityRuntime

        try:
            runtime = EntityRuntime.get_singleton()
            resident = bool(getattr(runtime, "is_resident", False))
            owner = runtime.mode == EntityRuntimeMode.OWNER
            runtime.event_store.count()
            return {"ok": owner and resident, "resident": resident, "owner": owner,
                    "execution_verified": False}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "execution_verified": False}

    async def handle_runtime_status(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.entity.runtime_status import collect_runtime_status
        payload = collect_runtime_status(include_network=True)
        payload["interaction_tier"] = self._current_tier()
        return web.json_response(payload, status=200 if payload.get("ready") else 503)

    def _entity_diagnostics(self) -> dict[str, Any]:
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            rt = EntityRuntime.get_singleton()
            return {
                "entity_id": rt.identity.entity_id,
                "entity_resident": bool(getattr(rt, "is_resident", False)),
                "event_count": int(rt.current_state.total_events_processed),
            }
        except Exception as exc:
            return {"entity_id": None, "entity_error": str(exc)}

    def _registry(self):
        from jaeger_ai.core.agent_registry import AgentRegistry

        return AgentRegistry()

    _frameworks_cache: tuple[float, list] | None = None

    async def handle_list_frameworks(self, request: web.Request) -> web.Response:
        """Detected agent frameworks (presence and counts only) with the owner's grants."""
        from jaeger_ai.core.frameworks.discovery import detect
        from jaeger_ai.core.frameworks.grants import CAPABILITIES, FrameworkGrants

        now = time.monotonic()
        cached = JaegerGatewayApp._frameworks_cache
        if cached is None or now - cached[0] > 30 or request.query.get("refresh"):
            JaegerGatewayApp._frameworks_cache = (now, await asyncio.to_thread(detect))
        grants = FrameworkGrants().all()
        out = []
        for fw in JaegerGatewayApp._frameworks_cache[1]:
            g = grants.get(fw["id"]) or {}
            out.append({**fw, "grants": {c: bool((g.get(c) or {}).get("granted")) for c in CAPABILITIES}})
        return web.json_response({"frameworks": out, "capabilities": list(CAPABILITIES)})

    async def handle_framework_grant(self, request: web.Request) -> web.Response:
        """Owner grants or revokes one capability for one framework (admin scope)."""
        from jaeger_ai.core.frameworks.discovery import by_id
        from jaeger_ai.core.frameworks.grants import CAPABILITIES, FrameworkGrants

        fid = request.match_info["id"]
        fw = by_id(fid)
        if fw is None:
            return web.json_response({"error": "Unknown framework"}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        cap = str((body or {}).get("capability") or "")
        granted = (body or {}).get("granted")
        if cap not in CAPABILITIES or not isinstance(granted, bool):
            return web.json_response({"error": "capability and boolean granted are required"}, status=400)
        if granted and cap != "delegate" and not fw.readable:
            return web.json_response({"error": f"{fw.name} has no read connector"}, status=400)
        caller = _REQUEST_CALLER.get()
        by = caller[1] if caller else "owner"
        state = FrameworkGrants().set(fid, cap, granted, by=by)
        return web.json_response({"framework": fid, "grants": {c: bool((state.get(c) or {}).get("granted")) for c in CAPABILITIES}})

    async def handle_list_agents(self, request: web.Request) -> web.Response:
        """List JaegerNativeAgent + ThirdPartyAgent for Mac app / WebUI.

        Query: ``?kind=`` and/or ``?role=lead|specialist|runtime``.
        Unfiltered response is the full catalog including ``lead``.
        """
        kind = request.query.get("kind")
        role = request.query.get("role")
        registry = self._registry()
        if kind or role:
            from jaeger_ai.core.agent_registry.registry import with_roster_flags
            agents = [
                with_roster_flags(a)
                for a in registry.list_agents(kind=kind or None, role=role or None)
            ]
            payload: dict[str, Any] = {"agents": self._with_skills(agents)}
            if kind:
                payload["kind"] = kind
            if role:
                payload["role"] = role
            return web.json_response(payload)
        return web.json_response(self._with_skills(registry.to_catalog()))

    async def handle_agent_primary(self, request: web.Request) -> web.Response:
        """Operator presentation default only: never activate or rewrite an agent."""
        from jaeger_ai.core.gateway.agent_presentation import primary_eligible, PresentationConflict
        if request.method == 'GET':
            return web.json_response({'agent_id': self.store.primary_agent_id()})
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'agent_id', 'expected_agent_id'} or any(not isinstance(v, str) or not v for v in body.values()):
                raise ValueError('Canonical agent_id and expected_agent_id are required')
            record = self._registry().get_agent(body['agent_id'])
            if record is None or record.id != body['agent_id']:
                return web.json_response({'error': 'Agent not found'}, status=404)
            from jaeger_ai.core.gateway.agent_presentation import project
            row = project(record.to_dict(), self.store.agent_presentation(), primary_id=self.store.primary_agent_id())
            if not primary_eligible(row):
                return web.json_response({'error': 'Agent is not an exposed native lead/specialist'}, status=409)
            self.store.set_primary_agent(record.id, body['expected_agent_id'])
        except PresentationConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'primary_agent_id': record.id})
        return web.json_response({'agent_id': record.id})

    async def handle_agent_sections(self, request: web.Request) -> web.Response:
        if request.method == 'GET':
            return web.json_response({'sections': self.store.agent_sections()})
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'name'}:
                raise ValueError('Only section name accepted')
            section = self.store.create_agent_section(body['name'])
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'section_id': section['id']})
        return web.json_response(section, status=201)

    async def handle_agent_presentation(self, request: web.Request) -> web.Response:
        """Admin-scoped cosmetic update; never rewrites registry definitions or sessions."""
        from jaeger_ai.core.gateway.agent_presentation import validate_patch, protected, can_rename
        agent_id = request.match_info['id']
        record = self._registry().get_agent(agent_id)
        if record is None or record.id != agent_id:
            return web.json_response({'error': 'Agent not found'}, status=404)
        try:
            patch = validate_patch(await request.json())
            if {'display_name', 'icon_preset'} & patch.keys() and not can_rename(record.to_dict()):
                return web.json_response({'error': 'protected_agent'}, status=409)
            if protected(record.to_dict()) and (patch.get('archived') is True or patch.get('pinned') is True or patch.get('deleted') is True or 'section_id' in patch):
                return web.json_response({'error': 'protected_agent'}, status=409)
            prefs = self.store.patch_agent_presentation(record.id, patch)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'agent_id': record.id, 'presentation': prefs})
        return web.json_response(self._with_skills(record.to_dict()))

    async def handle_agent_pins(self, request: web.Request) -> web.Response:
        """Admin-scoped ordered pins for the existing single local operator."""
        from jaeger_ai.core.gateway.agent_presentation import MAX_AGENT_PINS, protected, PresentationConflict
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {'agent_ids', 'expected_agent_ids'}:
                raise ValueError('agent_ids and expected_agent_ids are required; owner/profile is not client-selectable')
            ids = body['agent_ids']
            if not isinstance(ids, list) or len(ids) > MAX_AGENT_PINS or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
                raise ValueError(f'agent_ids must be a unique list of at most {MAX_AGENT_PINS} agent IDs')
            for agent_id in ids:
                record = self._registry().get_agent(agent_id)
                if record is None or record.id != agent_id:
                    return web.json_response({'error': 'Agent not found'}, status=404)
                if protected(record.to_dict()):
                    return web.json_response({'error': 'protected_agent'}, status=409)
            self.store.set_agent_pins(ids, body['expected_agent_ids'])
        except PresentationConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        self.event_bus.publish('*', 'agent.updated', {'pins': ids})
        return web.json_response({'agent_ids': ids})

    async def handle_agent_message_search(self, request: web.Request) -> web.Response:
        agent_id = request.match_info['id']
        record = self._registry().get_agent(agent_id)
        if record is None or record.id != agent_id:
            return web.json_response({'error': 'Agent not found'}, status=404)
        query = str(request.query.get('q') or '').strip()
        try:
            if not 1 <= len(query) <= 200:
                raise ValueError('Search text must be 1–200 characters')
            before = int(request.query['before']) if request.query.get('before') else None
            if before is not None and before < 1:
                raise ValueError('before must be a positive message ID')
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        return web.json_response(self.store.search_agent_messages(agent_id, query, before=before))

    async def handle_agent_templates(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.configuration import TEMPLATES
        return web.json_response({"templates": [dict(t, tools_granted=False) for t in TEMPLATES]})

    async def handle_agent_knowledge(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.configuration import editable, settings
        from jaeger_ai.features.knowledge_library.agent_context import pin_documents
        from jaeger_ai.contract.knowledge import MAX_KNOWLEDGE_DOCUMENTS, MAX_KNOWLEDGE_CONTEXT_CHARS
        from jaeger_ai.features.knowledge_library.tools import _library
        registry = self._registry()
        record = registry.get_agent(request.match_info['id'])
        if record is None or record.id != request.match_info['id']:
            return web.json_response({'error': 'Agent not found'}, status=404)
        if request.method == 'PATCH' and not editable(record):
            return web.json_response({'error': 'Protected specialist definition'}, status=403)
        try:
            library = _library()
            try:
                if request.method == 'PATCH':
                    body = await request.json()
                    if not isinstance(body, dict) or set(body) != {'expected_revision', 'document_ids'}:
                        raise ValueError('expected_revision and document_ids are required')
                    refs = pin_documents(library, body['document_ids'])
                    record = registry.assign_knowledge(record.id, refs, body['expected_revision'])
                catalog = library.managed_documents(include_archived=True)
            finally:
                library.close()
        except KeyError:
            return web.json_response({'error': 'Managed document not found'}, status=404)
        except PermissionError as exc:
            return web.json_response({'error': str(exc)}, status=403)
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=400)
        except RuntimeError as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except OSError:
            return web.json_response({'error': 'Instance knowledge library unavailable'}, status=503)
        if request.method == 'PATCH':
            self.event_bus.publish('*', 'agent.updated', {'agent_id': record.id, 'configuration_revision': settings(record)['revision']})
        caller = request.get('caller')
        return web.json_response({'agent_id': record.id, 'revision': settings(record)['revision'],
                                  'editable': editable(record) and bool(caller and 'admin' in caller.scopes),
                                  'documents': record.metadata.get('knowledge_documents') or [], 'available': catalog,
                                  'limits': {'max_documents': MAX_KNOWLEDGE_DOCUMENTS, 'context_chars': MAX_KNOWLEDGE_CONTEXT_CHARS}})

    async def handle_agent_configuration(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.agent_registry.configuration import editable, settings
        registry = self._registry()
        record = registry.get_agent(request.match_info['id'])
        if record is None or record.id != request.match_info['id']:
            return web.json_response({'error': 'Agent not found'}, status=404)
        if request.method == 'PATCH':
            try:
                body = await request.json()
                if not isinstance(body, dict) or set(body) != {'expected_revision', 'settings'}:
                    raise ValueError('expected_revision and settings are required')
                record = registry.configure_specialist(record.id, body['settings'], body['expected_revision'])
            except PermissionError as exc:
                return web.json_response({'error': str(exc)}, status=403)
            except RuntimeError as exc:
                return web.json_response({'error': str(exc)}, status=409)
            except (ValueError, TypeError) as exc:
                return web.json_response({'error': str(exc)}, status=400)
            self.event_bus.publish('*', 'agent.updated', {'agent_id': record.id, 'configuration_revision': settings(record)['revision']})
        caller = request.get('caller')
        return web.json_response({**settings(record), 'editable': editable(record) and bool(caller and 'admin' in caller.scopes)})

    async def handle_create_agent(self, request: web.Request) -> web.Response:
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Body must be an object"}, status=400)
        operation_id = body.get("operation_id")
        if operation_id is not None:
            if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 128:
                return web.json_response({"error": "Invalid operation_id"}, status=400)
            payload = {"action": "agent.create", "body": {k: v for k, v in body.items() if k != "operation_id"}}
            try:
                fresh = self.store.reserve_control_operation(operation_id, payload)
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=409)
            if not fresh:
                saved = self.store.control_operation(operation_id) or {}
                receipt = saved.get("receipt")
                if receipt:
                    return web.json_response(receipt.get("agent") if receipt.get("ok") else {"error": receipt.get("error")}, status=receipt.get("http_status", 200))
                return web.json_response({"error": "Agent creation outcome unknown; reconcile the saved operation without retry", "operation_id": operation_id}, status=409)
        def failure(message: str, status: int = 400):
            if operation_id:
                self.store.finish_control_operation(operation_id, {"ok": False, "operation_id": operation_id, "error": message, "http_status": status})
            return web.json_response({"error": message}, status=status)
        name = str(body.get("name") or "").strip()
        if not name:
            return failure("name is required")
        kind = str(body.get("kind") or "jaeger_native").strip()
        # Explicit creation commands cannot silently rename/reconfigure an existing
        # discovered, built-in or registered identity. Legacy registration callers
        # retain their existing contract when no operation identity is supplied.
        candidate = f"native:{name}" if kind == "jaeger_native" else f"tp:{body.get('adapter') or name}"
        if operation_id and self._registry().get_agent(candidate) is not None:
            return failure("Agent identity already exists; choose another name", 409)
        metadata = body.get("metadata") or {}
        if not isinstance(metadata, dict):
            return failure("metadata must be an object")
        if body.get('template_id') is not None:
            from jaeger_ai.core.agent_registry.configuration import TEMPLATES
            template = next((t for t in TEMPLATES if t['id'] == body['template_id'] and type(body.get('template_version')) is int and t['version'] == body['template_version']), None)
            if template is None:
                return failure("Unknown template/version")
            if (kind != 'jaeger_native' or body.get('role', 'specialist') != 'specialist'
                    or set(body) - {'name', 'display_name', 'kind', 'role', 'metadata', 'operation_id', 'template_id', 'template_version'}
                    or set(metadata) - {'specialty'} or not isinstance(metadata.get('specialty', ''), str)):
                return failure("Templates create specialists without inherited grants or execution configuration")
            from jaeger_ai.core.agent_registry.configuration import validate_settings
            try:
                validate_settings({'specialty': metadata.get('specialty') or template['specialty'], 'summary': template['summary'], 'instructions': template['instructions']})
            except ValueError as exc:
                return failure(str(exc))
            metadata = {'specialty': metadata.get('specialty') or template['specialty'], 'summary': template['summary'],
                        'operator_instructions': template['instructions'], 'configuration_revision': 0,
                        'template': {'id': template['id'], 'version': template['version']}, 'allowed_tools': []}
        try:
            record = self._registry().create_agent(
                name,
                kind=kind,
                role=(str(body["role"]) if body.get("role") else None),
                display_name=(str(body["display_name"]) if body.get("display_name") else None),
                adapter=(str(body["adapter"]) if body.get("adapter") else None),
                profile_id=(str(body["profile_id"]) if body.get("profile_id") else None),
                endpoint=(str(body["endpoint"]) if body.get("endpoint") else None),
                port=(int(body["port"]) if body.get("port") is not None else None),
                metadata=metadata,
                make_active=bool(body.get("make_active", False)),
            )
        except (ValueError, TypeError) as exc:
            return failure(str(exc))
        if operation_id:
            self.store.finish_control_operation(operation_id, {"ok": True, "operation_id": operation_id, "agent": record.to_dict(), "http_status": 201})
        self.event_bus.publish("*", "agent.created", {"agent": record.to_dict()})
        return web.json_response(record.to_dict(), status=201)

    async def handle_agents_summary(self, request: web.Request) -> web.Response:
        """GET /v1/agents/summary — per-agent status for the sidebar and Tasks board.

        Computed, never stored: from durable tasks (agent_id/eta/runner),
        handoffs and the agent's direct-chat sessions. No agent_status table.
        """
        from jaeger_ai.core.gateway.agent_summary import summarize_agents
        from jaeger_ai.core.gateway.agent_presentation import project
        registry = self._registry()
        agents = [a for a in registry.list_agents() if a.role.value in {"lead", "specialist"}]
        tasks = [t.to_dict() for t in self.task_owner.store.list_tasks()] if self.task_owner else []
        presentation = self.store.agent_presentation()
        primary_id = self.store.primary_agent_id()
        return web.json_response(summarize_agents(
            [project(a.to_dict(), presentation, primary_id=primary_id) for a in agents],
            tasks=tasks,
            handoffs=self.store.list_handoffs(limit=500),
            sessions=self.store.list_sessions(),
            last_message=self._last_message_preview,
            seen=self.store.agents_seen(),
            requests=[r for status in ("admitted", "queued", "running", "awaiting_approval", "cancelling")
                      for r in self.store.list_requests(status=status)],
        ))

    async def handle_agent_seen(self, request: web.Request) -> web.Response:
        """POST /v1/agents/{id}/seen — mark an agent's activity read (summary ``unseen``).

        Body: optional seen_at/event_id and boolean unread. Explicit unread persists until open/read clears it.
        """
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None or record.id != agent_id:
            return web.json_response({"error": "Agent not found"}, status=404)
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        body = body if isinstance(body, dict) else {}
        try:
            seen_at = float(body["seen_at"]) if body.get("seen_at") is not None else time.time()
            event_id = int(body["event_id"]) if body.get("event_id") is not None else None
        except (TypeError, ValueError):
            return web.json_response({"error": "seen_at must be a number and event_id an integer"}, status=400)
        if set(body) - {'seen_at', 'event_id', 'unread'} or not isinstance(body.get('unread', False), bool) or not math.isfinite(seen_at):
            return web.json_response({'error': 'Only finite seen_at, event_id and boolean unread are accepted'}, status=400)
        value = self.store.mark_agent_seen(agent_id, seen_at=seen_at, event_id=event_id, unread=body.get('unread', False))
        self.event_bus.publish('*', 'agent.updated', {'agent_id': agent_id, 'read_marker': value})
        return web.json_response(value)

    def _last_message_preview(self, session_id: str) -> str:
        session = self.store.get_session(session_id) or {}
        messages = session.get("messages") or []
        return str(messages[-1].get("content") or "") if messages else ""

    async def handle_get_agent(self, request: web.Request) -> web.Response:
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        return web.json_response(self._with_skills(record.to_dict()))

    async def handle_activate_agent(self, request: web.Request) -> web.Response:
        """Switch active agent — never fee-gated (fundamentals stay open)."""
        agent_id = request.match_info["id"]
        try:
            record = self._registry().set_active(agent_id)
        except KeyError:
            return web.json_response({"error": "Agent not found"}, status=404)
        self.event_bus.publish("*", "agent.activated", {"agent": record.to_dict()})
        return web.json_response(record.to_dict())

    async def handle_handoff_agent(self, request: web.Request) -> web.Response:
        """Lead → specialist handoff using a real isolated child run."""
        to_agent_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        task = str(body.get("task") or "").strip()
        if not task:
            return web.json_response({"error": "task is required"}, status=400)
        registry = self._registry()
        target = registry.get_agent(to_agent_id)
        if target is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        from_id = str(body.get("from_agent_id") or "native:jaeger").strip()
        require_approval = bool(body.get("require_approval", True))
        caller = request.get("caller")
        if not require_approval and getattr(caller, "name", None) == "jaegerd":
            # The agent asks through jaegerd's credential and cannot waive the
            # owner's approval itself; only the owner's autonomy=auto does.
            from jaeger_ai.core.runtime.autonomy import effective_autonomy
            require_approval = effective_autonomy(self._config_path()) != "auto"
        reply_parent = None
        if body.get("reply_to_handoff_id"):
            if not isinstance(body["reply_to_handoff_id"], str):
                return web.json_response({"error": "reply_to_handoff_id must be text"}, status=400)
            from jaeger_ai.core.gateway.handoff_reply import reply_context, ReplyConflict
            try:
                reply_parent = reply_context(self.store, body["reply_to_handoff_id"], source=from_id, target=target.id, session=body.get("session_id"))
            except ReplyConflict as exc:
                return web.json_response({"error": str(exc)}, status=409)
            require_approval = True
        request_id = str(body.get("request_id") or uuid.uuid4().hex)
        parent_run_id = body.get("parent_run_id") or body.get("parent_request_id")
        parent_chain = list(body.get("parent_chain") or [])
        depth = int(body.get("delegation_depth") or len(parent_chain))
        permitted_context = str(body.get("permitted_context") or "")
        timeout_s = int(body.get("timeout_seconds") or 120)
        allowed_tools = body.get("allowed_tools") or []
        if not isinstance(allowed_tools, list) or any(not isinstance(x, str) or not x.strip() for x in allowed_tools):
            return web.json_response({"error": "allowed_tools must be a list of tool names"}, status=400)
        if "dispatcher" in permitted_context.lower() and "dispatcher transcript" in permitted_context.lower():
            return web.json_response({"error": "dispatcher transcript is not permitted specialist context"}, status=403)
        # Project: shared root, team membership, limits and the owner's
        # handoff grant. Without a project_id the origin chat's project is used.
        from jaeger_ai.core.agent_registry.projects import default_limits
        project_id = str(body.get("project_id") or "").strip() or None
        hint_session = str(body.get("session_id") or "").strip() or None
        if project_id is None and hint_session:
            project_id = ((self.store.get_session(hint_session) or {}).get("metadata") or {}).get("project_id") or None
        project = self.projects.get(project_id) if project_id else None
        if project_id and project is None:
            return web.json_response({"error": f"Project not found: {project_id}"}, status=404)
        if project and project.get("team") and target.id not in project["team"]:
            return web.json_response({"error": f"{target.id} is not on project {project['name']}'s team"}, status=403)
        workspace = project["root"] if project else (str(body.get("workspace") or "").strip() or None)
        if workspace and not os.path.isabs(workspace):
            return web.json_response({"error": "workspace must be an absolute path"}, status=400)
        limits = dict(project["limits"]) if project else default_limits()
        timeout_s = max(1, min(timeout_s, int(limits["child_timeout_s"])))
        approved_by = None
        if require_approval and not reply_parent and project and (project.get("grants") or {}).get("handoffs"):
            # The owner approved this team when creating the project.
            require_approval = False
            approved_by = "project_grant"

        # Preserve the authenticated actor and a durable bridge root across
        # approval/restart; a child must not become an internal owner turn.
        from jaeger_ai.features.agent_bridge.delegation import prepare_handoff
        from jaeger_ai.features.agent_bridge.service import BridgeError
        actor = current_request_actor()
        try:
            bridge_origin, allowed_tools = prepare_handoff(
                self, actor, body, workspace, allowed_tools,
            )
        except (BridgeError, PermissionError) as exc:
            return web.json_response({"error": str(exc)}, status=403)
        if bridge_origin is not None:
            require_approval = True
            approved_by = None
            parent_session = self.store.get_session(str(body.get("session_id") or "")) or {}
            parent_meta = parent_session.get("metadata") or {}
            parent_handoff = (self.store.get_handoff(parent_meta["handoff_id"])
                              if parent_meta.get("handoff_id") else None)
            # Root goals cannot forge a chain through editable session metadata.
            is_root = parent_run_id == bridge_origin["request_id"]
            parent_chain = ([] if is_root else list(
                ((parent_handoff or {}).get("metadata") or {}).get("parent_chain") or []
            ))
            depth = len(parent_chain)
            from_id = "native:jaeger" if is_root else str(parent_meta.get("agent_id") or "")

        existing = self.store.get_handoff_by_request(request_id)
        if existing:
            prior = existing.get("metadata") or {}
            if (existing["task"] != task or existing["to_agent_id"] != target.id
                or existing["from_agent_id"] != from_id
                or existing.get("parent_run_id") != parent_run_id
                or existing["require_approval"] != require_approval
                or prior.get("permitted_context", "") != permitted_context
                or ("caller_actor" in prior and prior["caller_actor"] != actor)
                or prior.get("bridge_origin") != bridge_origin
                or (bridge_origin is not None and prior.get("workspace") != workspace)
                or sorted(prior.get("allowed_tools") or []) != sorted(allowed_tools)
                or prior.get("timeout_seconds", 120) != timeout_s
                or prior.get("reply_to_handoff_id") != (reply_parent["id"] if reply_parent else None)):
                return web.json_response(
                    {"error": "Request identity was already used for different input"},
                    status=409,
                )
            return web.json_response(existing, status=200)

        from jaeger_ai.core.agent_registry.specialist_runtime import check_delegation_limits
        limit_error = check_delegation_limits(
            from_agent_id=from_id,
            to_agent_id=target.id,
            parent_chain=parent_chain,
            depth=depth,
            active_children=self.store.count_active_handoffs(parent_run_id=str(parent_run_id) if parent_run_id else None),
            max_depth=int(limits["max_depth"]),
            max_fanout=int(limits["max_fanout"]),
        )
        if limit_error:
            return web.json_response({"error": limit_error, "ok": False, "status": "rejected"}, status=409)

        approval_id = f"approval_{uuid.uuid4().hex[:12]}" if require_approval else None
        handoff_id = f"handoff_{uuid.uuid4().hex[:12]}"
        origin_session = str(body.get("session_id") or "").strip() or None
        if origin_session is None and parent_run_id:
            parent_row = (self.store.get_request(str(parent_run_id))
                          or self.store.get_request_by_turn(str(parent_run_id)))
            origin_session = (parent_row or {}).get("session_id")
        record = {
            "id": handoff_id,
            "session_id": origin_session,
            "request_id": request_id,
            "from_agent_id": from_id,
            "to_agent_id": target.id,
            "parent_run_id": parent_run_id,
            "child_run_id": None,
            "task": task,
            "status": "pending_approval" if require_approval else "admitted",
            "require_approval": require_approval,
            "approval_id": approval_id,
            "result": {},
            "metadata": {
                "reply_to_handoff_id": reply_parent["id"] if reply_parent else None,
                "thread_handoff_id": ((reply_parent.get("metadata") or {}).get("thread_handoff_id") or reply_parent["id"]) if reply_parent else handoff_id,
                "caller_actor": actor,
                "bridge_origin": bridge_origin,
                "target_display": target.display_name,
                "target_role": (target.metadata or {}).get("role"),
                "specialty": (target.metadata or {}).get("specialty"),
                "permitted_context": permitted_context,
                "allowed_tools": list(allowed_tools),
                "timeout_seconds": timeout_s,
                "parent_chain": [*parent_chain, from_id],
                "delegation_depth": depth + 1,
                "project_id": project["id"] if project else None,
                "project_name": project["name"] if project else None,
                "workspace": workspace,
                "max_child_timeout_s": int(limits["child_timeout_s"]),
                "approved_by": approved_by,
                "wake_lead": bool(body.get("wake_lead", project is not None)),
            },
        }
        saved = self.store.save_handoff(record)
        if require_approval and approval_id:
            self.store.create_approval(
                approval_id=approval_id,
                kind="handoff",
                session_id=origin_session,
                prompt=f"Allow handoff to {target.display_name}?",
                options=["once", "deny"],
                request_id=request_id,
                metadata={"handoff_id": handoff_id, "to_agent_id": target.id},
            )
            loop = asyncio.get_running_loop()
            self.pending_approvals[approval_id] = loop.create_future()
            request_payload = {
                "approval_id": approval_id,
                "handoff_id": handoff_id,
                "kind": "handoff",
                "from_agent_id": from_id,
                "to_agent_id": target.id,
                "task": task,
                "options": ["once", "deny"],
                "prompt": f"Allow handoff to {target.display_name}?",
            }
            self.event_bus.publish("*", "approval.request", request_payload)
            origin = self._origin_turn(saved)
            if origin:
                # The approval card shows in the chat that asked for the handoff.
                self.event_bus.publish(origin[0], "approval.request", {
                    **request_payload, "title": f"Hand off to {target.display_name}?",
                    "prompt": task, "request_id": origin[1],
                })
        else:
            self._running_tasks[request_id] = asyncio.create_task(self._execute_handoff(handoff_id))
        self._publish_handoff("agent.handoff", saved)
        return web.json_response(saved, status=202 if require_approval else 200)

    def _origin_turn(self, record: dict[str, Any]) -> tuple[str, str] | None:
        """(session_id, request_id) of the chat turn that started a handoff."""
        session_id = record.get("session_id")
        parent = str(record.get("parent_run_id") or "")
        if not session_id or not parent:
            return None
        row = self.store.get_request(parent) or self.store.get_request_by_turn(parent)
        if not row or row.get("session_id") != session_id:
            return None
        return session_id, row["request_id"]

    def _publish_handoff(self, event: str, record: dict[str, Any]) -> None:
        """Publish a handoff globally and on the chat whose turn started it.

        The copy on the origin session carries that turn's ``request_id``, so
        the chat streams it with the turn and turn_parts persists it as a
        ``handoff`` part when the turn completes.
        """
        self.event_bus.publish("*", event, {"handoff": record})
        origin = self._origin_turn(record)
        if origin:
            self.event_bus.publish(origin[0], event, {"handoff": record, "request_id": origin[1]})
        if event == "agent.handoff.finished":
            self._post_handoff_result(record)

    # ── Sessions contract: home chats, typed messages, rolling summary ──

    @staticmethod
    def _agent_home_id(agent_id: str) -> str:
        # Same id the WebUI agents panel already uses for an agent's home chat.
        return f"agent-{agent_id}"

    def _ensure_agent_home(self, agent_id: str, display: str | None = None) -> tuple[str, bool]:
        """Get-or-create the one persistent home chat of an agent. Never archived."""
        try:  # one agent, one home: the registry's canonical id ("jaeger" -> "native:jaeger")
            record = self._registry().get_agent(agent_id)
            agent_id = str(getattr(record, "id", None) or agent_id)
        except Exception:  # noqa: BLE001
            pass
        sid = self._agent_home_id(agent_id)
        existing = self.store.get_session(sid)
        meta = {"agent_id": agent_id, "home": True, "agent_pinned": True, "route_checked": True}
        if existing is None:
            self.store.ensure_session(sid, title=display or agent_id, profile="jaeger", metadata=meta)
            return sid, True
        emeta = existing.get("metadata") or {}
        if not emeta.get("home") or emeta.get("agent_id") != agent_id:
            self.store.update_metadata(sid, meta)
        if emeta.get("archived"):
            try:
                self.store.set_session_archived(sid, False)
            except Exception:  # noqa: BLE001
                logger.warning("could not unarchive home session %s", sid, exc_info=True)
        return sid, False

    async def handle_agent_home(self, request: web.Request) -> web.Response:
        """GET /v1/agents/{id}/home — idempotent get-or-create of the agent's home chat."""
        agent_id = request.match_info["id"]
        record = self._registry().get_agent(agent_id)
        if record is None:
            return web.json_response({"error": "Agent not found"}, status=404)
        canonical = str(getattr(record, "id", None) or agent_id)
        sid, created = self._ensure_agent_home(canonical, getattr(record, "display_name", None))
        return web.json_response({"session_id": sid, "agent_id": canonical, "created": created})

    async def handle_list_messages(self, request: web.Request) -> web.Response:
        """GET /v1/sessions/{id}/messages?before=<message_id>&limit=50 — newest first."""
        session_id = request.match_info["id"]
        try:
            before = int(request.query["before"]) if request.query.get("before") else None
            limit = int(request.query.get("limit") or 50)
        except ValueError:
            return web.json_response({"error": "before and limit must be integers"}, status=400)
        if not 1 <= limit <= 200:
            return web.json_response({"error": "limit must be between 1 and 200"}, status=400)
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        return web.json_response(self.store.list_messages(session_id, before=before, limit=limit))

    def _post_handoff_request(self, record: dict[str, Any]) -> None:
        """The task, as a message in the specialist's home chat."""
        try:
            target = self._registry().get_agent(record["to_agent_id"])
            home, _ = self._ensure_agent_home(record["to_agent_id"], getattr(target, "display_name", None))
            message_id = self.store.append_handoff_post_once(
                home, "user", str(record.get("task") or ""), kind="handoff_request",
                sender_agent_id=record.get("from_agent_id"),
                links={"handoff_id": record["id"], "origin_session_id": record.get("session_id"), "thread_handoff_id": (record.get("metadata") or {}).get("thread_handoff_id") or record["id"], "reply_to_handoff_id": (record.get("metadata") or {}).get("reply_to_handoff_id")}, meta={"status": record.get("status")})
            # Delivery means the target home transcript durably accepted this
            # message, not merely that admission or approval was requested.
            self._publish_handoff("agent.handoff", {
                **record, "metadata": {**(record.get("metadata") or {}),
                                       "delivery_message_id": message_id}})
        except Exception:  # noqa: BLE001 — a transcript copy never fails the handoff
            logger.warning("handoff_request message not posted for %s", record.get("id"), exc_info=True)

    def _post_handoff_result(self, record: dict[str, Any]) -> None:
        """The specialist's result, as an assistant message from that specialist in
        the chat that asked for it and in the specialist's home chat."""
        result = record.get("result") or {}
        status = str(record.get("status") or result.get("status") or "")
        text = str(result.get("summary") or "").strip() or f"Handoff {status or 'finished'}."
        agent_id = record.get("to_agent_id")
        links = {"handoff_id": record.get("id"), "child_session_id": result.get("worker_session_id"), "origin_session_id": record.get("session_id"), "thread_handoff_id": (record.get("metadata") or {}).get("thread_handoff_id") or record["id"], "reply_to_handoff_id": (record.get("metadata") or {}).get("reply_to_handoff_id")}
        part = {"type": "handoff", "direction": "from", "handoff_id": record.get("id"),
                "agent_id": agent_id, "status": status}
        targets = []
        if record.get("session_id") and self.store.get_session(record["session_id"]) is not None:
            targets.append(record["session_id"])
        try:
            home, _ = self._ensure_agent_home(agent_id)
            if home not in targets:
                targets.append(home)
        except Exception:  # noqa: BLE001
            logger.warning("no home session for %s", agent_id, exc_info=True)
        for sid in targets:
            try:
                self.store.append_handoff_post_once(sid, "assistant", text, kind="handoff_result",
                                          sender_agent_id=agent_id, links=links, parts=[part],
                                          meta={"status": status})
            except Exception:  # noqa: BLE001
                logger.warning("handoff_result message not posted to %s", sid, exc_info=True)

    SUMMARY_TRIGGER = int(os.environ.get("JAEGER_SUMMARY_TRIGGER", "24") or 24)
    SUMMARY_KEEP = int(os.environ.get("JAEGER_SUMMARY_KEEP", "12") or 12)
    _SUMMARY_SYSTEM = (
        "You maintain the running summary of one conversation so it can continue after "
        "older messages leave the context window. Merge the previous summary (if any) with "
        "the new messages. Keep: the user's first request and goals in their own words, "
        "names, numbers, codes, file paths, decisions, results, open tasks and preferences. "
        "Drop small talk. Plain text, at most 350 words, no preamble."
    )

    def _schedule_summary(self, session_id: str) -> None:
        if not session_id or session_id in self._summarizing:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._maybe_summarize(session_id))
        except RuntimeError:
            return
        self._summarizing[session_id] = task
        task.add_done_callback(lambda _t, sid=session_id: self._summarizing.pop(sid, None))

    async def _summary_text(self, prompt: str) -> tuple[str, str]:
        models = [m for m in (os.environ.get("JAEGER_SUMMARY_MODEL") or DEFAULT_OLLAMA_MODEL,
                              os.environ.get("JAEGER_SUMMARY_FALLBACK_MODEL")) if m]
        last: Exception | None = None
        for model in models:
            try:
                text = await self._ollama_chat(prompt, model=model, system_prompt=self._SUMMARY_SYSTEM)
                if text and text.strip():
                    return text.strip(), model
            except Exception as exc:  # noqa: BLE001 — try the fallback model
                last = exc
                logger.warning("summary model %s failed: %s", model, exc)
        raise RuntimeError(f"no summary model answered: {last}")

    async def _maybe_summarize(self, session_id: str, *, force: bool = False) -> dict[str, Any] | None:
        """Fold older messages into one cumulative summary message instead of
        dropping them. Originals stay in the table and stay pageable."""
        try:
            session = self.store.get_session(session_id)
            if session is None:
                return None
            meta = session.get("metadata") or {}
            upto = int(meta.get("summary_upto_message_id") or 0)
            rows = [m for m in self.store.messages_after(session_id, upto)
                    if m.get("kind") != "summary" and m.get("role") in {"user", "assistant"}]
            if len(rows) <= self.SUMMARY_TRIGGER and not force:
                return None
            block = rows[:-self.SUMMARY_KEEP] if len(rows) > self.SUMMARY_KEEP else ([] if not force else rows)
            if not block:
                return None
            lines, used = [], 0
            for m in block:
                who = m.get("sender_agent_id") or m.get("role")
                line = f"[#{m['id']} {who}] {str(m.get('content') or '')[:1500]}"
                used += len(line)
                if used > 40_000:
                    break
                lines.append(line)
            prev = str(meta.get("summary_text") or "").strip()
            prompt = ((f"Previous summary:\n{prev}\n\n" if prev else "")
                      + "New messages to fold in:\n" + "\n".join(lines))
            text, model = await self._summary_text(prompt)
            covers_from = int(meta.get("summary_covers_from") or block[0]["id"])
            covers_to = int(block[-1]["id"])
            count = int(meta.get("summary_message_count") or 0) + len(block)
            summary = {"covers_from": covers_from, "covers_to": covers_to, "message_count": count}
            mid = self.store.append_message(session_id, "system", text, kind="summary",
                                            meta={"summary": summary, "model": model})
            self.store.update_metadata(session_id, {
                "summary_upto_message_id": covers_to, "summary_covers_from": covers_from,
                "summary_message_count": count, "summary_message_id": mid, "summary_text": text})
            payload = {"session_id": session_id, "summary_message_id": mid, "covers_to": covers_to}
            self.event_bus.publish(session_id, "session.summarized", payload)
            self.event_bus.publish("*", "session.summarized", payload)
            logger.info("session %s summarized through #%s (%s msgs) with %s", session_id, covers_to, count, model)
            return {**payload, "summary": summary, "model": model}
        except Exception:  # noqa: BLE001 — summary is best effort; history is never dropped
            logger.warning("summary failed for %s", session_id, exc_info=True)
            return None

    UPLOAD_MAX_BYTES = 25 * 1024 * 1024

    def _staged_upload_dir(self, session_id: str) -> Path:
        """This session's staged-upload folder (one per session, hashed id)."""
        import hashlib
        return self.store.path.parent / "attachments" / hashlib.sha256(session_id.encode()).hexdigest()[:24]

    @staticmethod
    def _upload_view(row: dict[str, Any]) -> dict[str, Any]:
        return {"attachment_id": row["attachment_id"], "name": row.get("original_filename"),
                "mime": row.get("mime_type"), "size": row.get("size_bytes"), "sha256": row.get("sha256")}

    async def handle_upload_attachment(self, request: web.Request) -> web.Response:
        """POST /v1/sessions/{id}/attachments/upload — stage bytes gateway-side.

        multipart ``file`` (+ ``name``) or JSON ``{name, mime, data_base64}``.
        25 MB per file (413 over). ``Idempotency-Key`` replays the same attachment.
        Staged uploads join a turn only when its ``attachment_ids`` names them."""
        import base64
        import hashlib
        import mimetypes

        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        idem = (request.headers.get("Idempotency-Key") or "").strip()[:200]
        if idem:
            for row in self.store.list_attachments(session_id):
                if (row.get("metadata") or {}).get("idempotency_key") == idem:
                    return web.json_response({**self._upload_view(row), "replayed": True}, status=201)
        limit = self.UPLOAD_MAX_BYTES
        too_big = web.json_response({"error": f"attachment exceeds {limit // (1024 * 1024)} MB"}, status=413)
        att_id = f"att_{uuid.uuid4().hex[:16]}"
        stage = self._staged_upload_dir(session_id) / att_id
        stage.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = stage / ".upload"
        digest, size = hashlib.sha256(), 0
        name, mime = "", ""
        ctype = request.content_type or ""
        try:
            if ctype.startswith("multipart/"):
                if request.content_length and request.content_length > limit + 1024 * 1024:
                    return too_big
                reader = await request.multipart()
                got_file = False
                while True:
                    part = await reader.next()
                    if part is None:
                        break
                    if part.name == "file" and not got_file:
                        got_file = True
                        name = name or (part.filename or "")
                        mime = part.headers.get("Content-Type", "") or mime
                        with tmp.open("wb") as out:
                            while True:
                                chunk = await part.read_chunk(1024 * 1024)
                                if not chunk:
                                    break
                                size += len(chunk)
                                if size > limit:
                                    return too_big
                                digest.update(chunk)
                                out.write(chunk)
                    elif part.name == "name":
                        name = (await part.text()).strip() or name
                    elif part.name == "mime":
                        mime = (await part.text()).strip() or mime
                if not got_file:
                    return web.json_response({"error": "multipart field 'file' is required"}, status=400)
            elif ctype in {"application/json", ""}:
                cap = limit * 4 // 3 + 64 * 1024
                if request.content_length and request.content_length > cap:
                    return too_big
                raw = await request.content.read(cap + 1)
                if len(raw) > cap:
                    return too_big
                try:
                    body = json.loads(raw or b"{}")
                    data = base64.b64decode(str(body.get("data_base64") or ""), validate=True)
                except (ValueError, TypeError) as exc:
                    return web.json_response({"error": f"invalid JSON upload: {exc}"}, status=400)
                if not data:
                    return web.json_response({"error": "data_base64 is required"}, status=400)
                if len(data) > limit:
                    return too_big
                name, mime = str(body.get("name") or ""), str(body.get("mime") or "")
                size = len(data)
                digest.update(data)
                tmp.write_bytes(data)
            else:
                return web.json_response({"error": "use multipart/form-data or application/json"}, status=415)
            safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name or "upload.bin").name).strip(" .")[:200] or "upload.bin"
            mime = mime or mimetypes.guess_type(safe)[0] or "application/octet-stream"
            final = stage / safe
            tmp.replace(final)
            os.chmod(final, 0o600)
        finally:
            if tmp.exists():
                tmp.unlink()
                try:
                    stage.rmdir()
                except OSError:
                    pass
        row = self.store.add_attachment(session_id, {
            "attachment_id": att_id, "original_filename": safe, "stored_filename": safe,
            "safe_path": str(final), "mime_type": mime, "size_bytes": size,
            "sha256": digest.hexdigest(), "provenance": "upload_staged",
            "metadata": {"staged": True, **({"idempotency_key": idem} if idem else {})},
        })
        self.event_bus.publish(session_id, "attachment.added", {"attachment": row})
        return web.json_response(self._upload_view(row), status=201)

    async def handle_list_handoffs(self, request: web.Request) -> web.Response:
        """GET /v1/handoffs[?agent_id=&session_id=&since=&limit=] — newest first."""
        query = request.query
        try:
            since = float(query["since"]) if query.get("since") else None
            limit = int(query["limit"]) if query.get("limit") else None
        except ValueError:
            return web.json_response({"error": "since must be epoch seconds and limit an integer"}, status=400)
        if limit is not None and not 1 <= limit <= 500:
            return web.json_response({"error": "limit must be between 1 and 500"}, status=400)
        records = self.store.list_handoffs(
            agent_id=query.get("agent_id") or None,
            session_id=query.get("session_id") or None,
            since=since,
            limit=limit,
        )
        return web.json_response({"handoffs": records, "count": len(records)})

    async def handle_handoff_reply(self, request: web.Request) -> web.Response:
        """Explicit owner follow-up, always through existing handoff approval/admission."""
        from jaeger_ai.core.gateway.handoff_reply import reply_payload, ReplyConflict
        try:
            target, payload = reply_payload(self.store, request.match_info["id"], await request.json())
        except ReplyConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        class FollowupRequest(dict):
            can_read_body = True
            match_info = {"id": target}
            async def json(self):
                return payload
        return await self.handle_handoff_agent(FollowupRequest(request))

    async def handle_handoff_messages(self, request: web.Request) -> web.Response:
        """GET /v1/handoffs/{id}/messages — the specialist's side of one exchange.

        Hides the ``specialist:<agent>:<request>`` worker-session naming from
        clients; the exchange panel reads task + messages + summary in one call.
        """
        record = self.store.get_handoff(request.match_info["id"])
        if record is None:
            return web.json_response({"error": "Handoff not found"}, status=404)
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
        result = record.get("result") or {}
        worker = str(result.get("worker_session_id") or "") or specialist_session(
            record["to_agent_id"], record.get("request_id") or record["id"])
        session = self.store.get_session(worker) or {}
        messages = [
            {key: m.get(key) for key in ("id", "role", "content", "timestamp")}
            for m in session.get("messages") or []
        ]
        return web.json_response({
            "handoff_id": record["id"],
            "thread_handoff_id": (record.get("metadata") or {}).get("thread_handoff_id") or record["id"],
            "reply_to_handoff_id": (record.get("metadata") or {}).get("reply_to_handoff_id"),
            "from_agent_id": record["from_agent_id"],
            "request_id": record.get("request_id"),
            "session_id": record.get("session_id"),
            "to_agent_id": record["to_agent_id"],
            "status": record["status"],
            "task": record["task"],
            "worker_session_id": worker,
            "messages": messages,
            "summary": result.get("summary") or "",
        })

    async def handle_get_handoff(self, request: web.Request) -> web.Response:
        record = self.store.get_handoff(request.match_info["id"])
        if record is None:
            return web.json_response({"error": "Handoff not found"}, status=404)
        if record["status"] == "execution_unknown":
            import hashlib
            from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
            rid = record.get("request_id") or record["id"]
            native_id = hashlib.sha256(("handoff:" + rid).encode()).hexdigest()
            session = specialist_session(record["to_agent_id"], rid)
            receipt = self._native_receipt(native_id, session)
            if receipt and not receipt.get("execution_unknown") and receipt.get("status") in {"completed", "failed", "cancelled"}:
                reply = receipt.get("reply") or {}
                record = self.store.save_handoff({**record, "status": receipt["status"],
                    "result": {"ok": receipt["status"] == "completed", "status": receipt["status"],
                               "summary": reply.get("text") or reply.get("error") or reply.get("halt_reason") or "",
                               "worker_session_id": session, "metadata": {"native_receipt": receipt}}})
                self._publish_handoff("agent.handoff.finished", record)
        return web.json_response(record)

    async def handle_list_sessions(self, request: web.Request) -> web.Response:
        profile = request.query.get("profile")
        sessions = self.store.list_sessions(profile=profile, query=request.query.get("q"),
                                            agent_id=(request.query.get("agent_id") or "").strip() or None)
        return web.json_response({"sessions": sessions})

    @staticmethod
    def _validate_workspace_folder(raw: Any) -> tuple[str, str | None]:
        """(realpath, None) or ("", error): absolute, existing directory, not / or $HOME."""
        value = str(raw or "").strip()
        if not value:
            return "", "workspace_folder must be a non-empty absolute path"
        if not os.path.isabs(value):
            return "", f"workspace_folder must be absolute: {value!r}"
        real = os.path.realpath(value)
        if not os.path.isdir(real):
            return "", f"workspace_folder does not exist or is not a directory: {value!r}"
        if real == os.path.sep or real == os.path.realpath(os.path.expanduser("~")):
            return "", f"workspace_folder may not be / or your home folder itself: {value!r}"
        return real, None

    async def handle_create_session(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        # The Gateway owns the session namespace, but an explicitly supplied
        # id is honored: durable contracts (task replay, cross-client
        # continuation, restart recovery) address the SAME session row after
        # a Gateway restart, and `ensure_session` is idempotent, so a stable
        # client-supplied id is one row, never a second store.
        session_id = str(body.get("session_id") or "").strip() or uuid.uuid4().hex
        caller = request.get("caller")
        prefix = getattr(caller, "session_prefix", None)
        if prefix and not body.get("session_id"):
            session_id = prefix + session_id
        if prefix and not session_id.startswith(prefix):
            return web.json_response(
                {"error": f"Caller {caller.name!r} may only create sessions starting {prefix!r}"}, status=403,
            )
        title = str(body.get("title") or "New Conversation")
        workspace = str(body.get("workspace") or "")
        metadata = dict(body.get("metadata") or {})
        if body.get("workspace_folder") is not None:
            # The client's open folder (IDE / Mac app) becomes the session's
            # existing ``workspace``: the turn's project_root for file and
            # shell tools and the ide_context fallback. Same field, validated.
            folder, error = self._validate_workspace_folder(body.get("workspace_folder"))
            if error:
                return web.json_response({"error": error, "field": "workspace_folder"}, status=400)
            workspace = folder
            metadata = {**metadata, "workspace_folder": folder}
        # Profile binding is enforced HERE, gateway-side. The client may name a
        # profile; the gateway validates it against the framework registry and
        # stamps it — the id no longer carries the profile, so a client cannot
        # mint a "hermes" session by shaping its id.
        profile = str(body.get("profile") or "").strip()
        if not profile:
            profile = "jaeger"
        from jaeger_ai.contract.frameworks import canonical_runtime, UnknownFramework
        try:
            profile = canonical_runtime(profile)
        except UnknownFramework:
            return web.json_response({"error": f"Unknown profile: {profile}"}, status=400)
        # Record where it was started so the sidebar can split browser from
        # terminal conversations for each framework.
        surface = normalise_surface(body.get("source") or metadata.get("source"))
        if surface and "source" not in metadata:
            metadata = {**metadata, "source": surface}

        existed = self.store.get_session(session_id) is not None
        session = self.store.ensure_session(
            session_id,
            title=title,
            profile=profile,
            workspace=workspace,
            metadata=metadata,
        )
        if not existed:
            from jaeger_ai.core.gateway.session_hygiene import archive_on_create
            session = archive_on_create(self.store, session)
        self.event_bus.publish(session_id, "session.created", {"session": session})
        return web.json_response(session, status=201)

    async def handle_get_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        conversation = request.query.get("view") == "conversation"
        session = self.store.get_session(session_id, conversation=True) if conversation else self.store.get_session(session_id)
        if not session:
            return web.json_response({"error": "Session not found"}, status=404)
        # Surfaces chrome polls GET without SSE — stamp role/display_name
        # after handoff so the UI can render the active agent identity.
        payload = self._enrich_session_agent(session)
        if conversation:
            return web.json_response(payload)
        # Recovery clients need a scoped control identity even when they did
        # not submit this turn. Do not expose input/output through this field.
        latest = self.store.latest_request(session_id)
        payload["latest_request"] = ({
            key: latest.get(key) for key in (
                "session_id", "request_id", "turn_id", "status", "updated_at", "finished_at",
            )
        } if latest else None)
        if request.query.get("view") == "control":
            return web.json_response({key: payload.get(key) for key in (
                "session_id", "status", "latest_request",
            )})
        if request.query.get("view") == "settings":
            metadata = payload.get("metadata") or {}
            return web.json_response({"session_id": session_id, "model": metadata.get("model"), "provider": metadata.get("provider")})
        return web.json_response(payload)

    async def handle_branch_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        keep_count = body.get("keep_count")
        if keep_count is None and body.get("message_id") is not None:
            source = self.store.get_session(session_id)
            try:
                wanted = int(body["message_id"])
                match = next((i for i, row in enumerate(source.get("messages", []))
                              if int(row.get("id", -1)) == wanted), None) if source else None
                if match is not None:
                    keep_count = match + 1
            except (TypeError, ValueError):
                return web.json_response({"error": "message_id must be an integer"}, status=400)
        if keep_count is not None:
            try:
                keep_count = int(keep_count)
            except (TypeError, ValueError):
                return web.json_response({"error": "keep_count must be an integer"}, status=400)
            if keep_count < 0:
                return web.json_response({"error": "keep_count must be non-negative"}, status=400)
        branch = self.store.branch_session(
            session_id,
            title=str(body.get("title") or "").strip() or None,
            keep_count=keep_count,
        )
        if branch is None:
            return web.json_response({"error": "Session not found"}, status=404)
        self.event_bus.publish(session_id, "session.branched", {
            "session_id": branch["session_id"], "parent_session_id": session_id,
        })
        return web.json_response(branch, status=201)

    async def handle_message_feedback(self, request: web.Request) -> web.Response:
        from jaeger_ai.contract.message_feedback import REACTION_EMOJIS
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        if request.method == "GET":
            return web.json_response({"feedback": self.store.message_feedback(session_id), **self.store.message_reactions(session_id), 'allowed_emojis': REACTION_EMOJIS})
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            return web.json_response({'error': 'JSON object required'}, status=400)
        if not isinstance(body, dict):
            return web.json_response({'error': 'JSON object required'}, status=400)
        if isinstance(body, dict) and 'emoji' in body:
            if set(body) != {'request_id', 'role', 'emoji', 'active'} or body['emoji'] not in REACTION_EMOJIS or not isinstance(body['role'], str) or body['role'] not in {'user', 'assistant'} or type(body['active']) is not bool or not isinstance(body['request_id'], str):
                return web.json_response({'error': 'Valid request_id, role, emoji and boolean active required'}, status=400)
            target = self.store.get_request(body['request_id'])
            if target is None or target['session_id'] != session_id:
                return web.json_response({'error': 'Request not found in this conversation'}, status=404)
            snapshot = self.store.set_message_reaction(session_id, target['request_id'], body['role'], body['emoji'], body['active'])
            event = snapshot.pop('_event', None)
            if event:
                self.event_bus.fanout(event)
            return web.json_response({**snapshot, 'allowed_emojis': REACTION_EMOJIS})
        rating = str(body.get("rating") or "").strip().lower()
        if rating not in {"positive", "negative"}:
            return web.json_response({"error": "rating must be positive or negative"}, status=400)
        message_id = body.get("message_id")
        event = self.store.append_event(session_id, "message.feedback", {
            "message_id": message_id, "rating": rating,
            "comment": str(body.get("comment") or "")[:1000],
        })
        self.event_bus.publish(session_id, "message.feedback", event)
        return web.json_response({"ok": True, "feedback": event})

    async def handle_retry_session(self, request: web.Request) -> web.Response:
        """Replay the last completed request with a new durable identity."""
        session_id = request.match_info["id"]
        previous = self.store.latest_request(session_id)
        if previous is None:
            return web.json_response({"error": "No previous request to retry"}, status=404)
        if previous.get("status") in {"running", "admitted", "cancelling"}:
            return web.json_response({"error": "The previous request is still running"}, status=409)
        body = {
            "text": previous.get("input_text") or "",
            "request_id": uuid.uuid4().hex,
        }
        execution = previous.get("execution") or {}
        for key in ("model", "provider", "workspace", "options", "allowed_tools",
                    "interaction_tier"):
            if key in execution:
                body[key] = execution[key]
        attachments = execution.get("attachments") or []
        if isinstance(attachments, list):
            body["attachment_ids"] = [item.get("attachment_id") for item in attachments
                                       if isinstance(item, dict) and item.get("attachment_id")]
        # Reuse the normal admission and execution path so retry has the same
        # receipts, locking, approvals, and SSE behavior as a new turn.
        # Invoke the shared admission path through a tiny internal dispatch
        # payload instead of duplicating the normal turn handler.
        return await self._admit_and_start_retry(session_id, body)

    async def _admit_and_start_retry(self, session_id: str, body: dict[str, Any]) -> web.Response:
        text = str(body.get("text") or "").strip()
        requested = self._requested_from_body(body)
        try:
            admitted = self.store.admit_request(
                session_id, text, request_id=body["request_id"], requested=requested,
            )
        except (RequestConflict, RequestBusy, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=409 if isinstance(exc, RequestBusy) else 400)
        self._start_admitted_turn(admitted, session_id, text)
        return web.json_response({
            "session_id": session_id, "turn_id": admitted["turn_id"],
            "request_id": admitted["request_id"], "status": "running",
            "replayed": False,
            "start_event_id": (admitted.get("event") or {}).get("event_id"),
        }, status=202)

    async def handle_activity_history(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if not self.store.get_session(session_id):
            return web.json_response({"error": "Session not found"}, status=404)
        try:
            after = max(0, int(request.query.get("after", "0")))
        except ValueError:
            return web.json_response({"error": "Invalid cursor"}, status=400)
        return web.json_response(self.store.activity_history(session_id, after))

    def _session_model_choice(self, model_id: str) -> dict[str, Any] | None:
        """``{model, provider}`` if ``model_id`` is a reachable /v1/runtime/models entry.

        Accepts a bare model name or a routed ``@provider:model`` id."""
        from jaeger_ai.contract.model_ids import split_routed_model_id
        from jaeger_ai.core.runtime.truth import provider_model_inventory

        lane, name = split_routed_model_id(model_id)
        for provider in provider_model_inventory().get("providers") or []:
            if not provider.get("reachable") or (lane and provider.get("id") != lane):
                continue
            if any(str(m.get("id")) == name for m in provider.get("models") or []):
                return {"model": name, "provider": provider.get("id")}
        return None

    async def handle_patch_session(self, request: web.Request) -> web.Response:
        """PATCH /v1/sessions/{id} — the one place title, archive state and the
        session's default ``model`` change. ``model`` must be a reachable
        /v1/runtime/models entry (or null to clear); turns use it unless the
        turn names its own model."""
        session_id = request.match_info["id"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict) or not body:
            return web.json_response({"error": "Nothing to update"}, status=400)

        title = body.get("title")
        if "title" in body and (not isinstance(title, str) or not title.strip()):
            return web.json_response({"error": "title must be a non-empty string"}, status=400)
        archived = body.get("archived")
        if "archived" in body and not isinstance(archived, bool):
            return web.json_response({"error": "archived must be a boolean"}, status=400)
        model = body.get("model")
        if "model" in body and model is not None and (not isinstance(model, str) or not model.strip()):
            return web.json_response({"error": "model must be a non-empty string or null"}, status=400)

        session = self.store.get_session(session_id)
        if session is None:
            return web.json_response({"error": "Session not found"}, status=404)
        if "model" in body:
            if model is None:
                choice = {"model": None, "provider": None}
            else:
                choice = await asyncio.to_thread(self._session_model_choice, model.strip())
                if choice is None:
                    return web.json_response(
                        {"error": f"Unknown or unreachable model {model.strip()!r} (see /v1/runtime/models)"},
                        status=400)
            session = self.store.update_metadata(session_id, choice) or session
        if "title" in body:
            session = self.store.rename_session(session_id, title.strip()[:200])
        if "archived" in body:
            session = self.store.set_session_archived(session_id, archived)
        self.event_bus.publish(session_id, "session.updated", {"session": session})
        return web.json_response(session)

    async def handle_delete_session(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        deleted = self.store.delete_session(session_id)
        if not deleted:
            return web.json_response({"error": "Session not found"}, status=404)
        self.event_bus.publish(session_id, "session.deleted", {"session_id": session_id})
        return web.json_response({"deleted": True})

    async def handle_session_handoff(self, request: web.Request) -> web.Response:
        """Transfer a session to another agent (P6) — never fee-gated.

        Body: ``{to_agent_id, reason?, keep_history?: true}``.
        Updates session ``agent_id`` metadata; optionally clears transcript.
        """
        session_id = request.match_info["id"]
        session = self.store.get_session(session_id)
        if not session:
            return web.json_response({"error": "Session not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        to_agent_id = str(body.get("to_agent_id") or "").strip()
        if not to_agent_id:
            return web.json_response({"error": "to_agent_id is required"}, status=400)
        keep_history = bool(body.get("keep_history", True))
        reason = str(body.get("reason") or "").strip() or None

        registry = self._registry()
        target = registry.get_agent(to_agent_id)
        if target is None:
            # Surfaces: missing agent must be a clean 404 (not 500 / empty body).
            return web.json_response({"error": "Agent not found"}, status=404)
        # Lead ↔ specialist (and runtime) handoffs are all allowed; role is not gated.

        previous_agent_id = session.get("agent_id") or (session.get("metadata") or {}).get(
            "agent_id"
        )
        if not keep_history:
            self.store.clear_messages(session_id)

        patch = {
            "agent_id": target.id,
            "previous_agent_id": previous_agent_id,
            "handoff_reason": reason,
            "handed_off_at": time.time(),
            # An explicit handoff is the owner's choice: auto-routing never overrides it.
            "agent_pinned": True,
            "routed_by": "owner",
        }
        updated = self.store.update_metadata(session_id, patch)
        if updated is None:
            return web.json_response({"error": "Session not found"}, status=404)

        agent = target.to_dict()
        self.event_bus.publish(
            session_id,
            "session.handoff",
            {
                "session_id": session_id,
                "from_agent_id": previous_agent_id,
                "to_agent_id": target.id,
                "agent": agent,
                "reason": reason,
                "keep_history": keep_history,
            },
        )
        # The same handoff, globally: the sidebar learns an agent now has a
        # direct chat without subscribing to every session (D4).
        self.event_bus.publish("*", "agent.direct_chat", {
            "session_id": session_id,
            "agent_id": target.id,
            "from_agent_id": previous_agent_id,
            "title": updated.get("title"),
            "reason": reason,
        })
        return web.json_response(
            {
                "session_id": session_id,
                "agent_id": target.id,
                "previous_agent_id": previous_agent_id,
                "agent": agent,
                "session": updated,
                "keep_history": keep_history,
                "reason": reason,
            }
        )

    def _requested_from_body(self, body: dict[str, Any]) -> dict[str, Any]:
        """One place normalizes client execution choices before admission."""
        requested = {key: body.get(key) for key in EXECUTION_INPUT_KEYS if body.get(key) is not None}
        options = requested.get("options")
        if isinstance(options, dict) and "ide" in options:
            from jaeger_ai.core.entity.ide_context import clean as clean_ide_context
            options = {**options}
            cleaned = clean_ide_context(options.pop("ide"))
            if cleaned:
                options["ide"] = cleaned
            if options:
                requested["options"] = options
            else:
                requested.pop("options")
        if requested.get("model") and not requested.get("provider"):
            lane, _ = split_routed_model_id(str(requested["model"]))
            if lane:
                requested["provider"] = lane
        if "interaction_tier" not in requested:
            requested["interaction_tier"] = self._current_tier()
        # The acting caller is assigned here from the authenticated request,
        # never taken from the body.
        requested.pop("caller", None)
        actor = current_request_actor()
        if actor:
            requested["caller"] = actor
        return requested

    async def handle_send_turn(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        text = str(body.get("text") or body.get("input") or "").strip()
        if not text:
            return web.json_response({"error": "Missing turn text"}, status=400)
        # Profile binding is enforced gateway-side: a turn may not switch the
        # profile a session was created with. Cross-client continuation
        # (start on the phone, finish in the IDE) works because both clients
        # address the same gateway-owned session id.
        requested_profile = str(body.get("profile") or "").strip()
        if requested_profile:
            session = self.store.get_session(session_id)
            if session is None:
                return web.json_response({"error": "Session not found"}, status=404)
            bound = str(session.get("profile") or "").strip().lower()
            if bound and bound != requested_profile.strip().lower():
                return web.json_response(
                    {"error": f"This conversation belongs to {bound}; start a new chat to talk to {requested_profile}"},
                    status=409,
                )
        request_id = body.get("request_id")
        if request_id is not None:
            request_id = str(request_id).strip() or None

        requested = self._requested_from_body(body)
        try:
            admitted = self.store.admit_request(
                session_id, text, request_id=request_id, requested=requested,
            )
        except RequestConflict as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except RequestBusy as exc:
            session = self.store.get_session(session_id) or {}
            return web.json_response(
                {
                    "error": str(exc),
                    "session_id": session_id,
                    "status": session.get("status"),
                    "agent_id": self._session_agent_id(session),
                },
                status=409,
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        turn_id = admitted["turn_id"]
        rid = admitted["request_id"]
        options = (admitted.get("execution") or {}).get("options") or {}
        if not options.get("background"):
            self._last_human_at = time.monotonic()
            self._last_human_session = session_id
        self._start_admitted_turn(admitted, session_id, text)

        result = admitted.get("result") or {}
        payload = {
            "session_id": session_id,
            "turn_id": turn_id,
            "request_id": rid,
            "status": admitted["status"] if admitted.get("replayed") else "running",
            "replayed": bool(admitted.get("replayed")),
        }
        if result.get("output") is not None:
            payload["output"] = result.get("output")
        if admitted.get("event"):
            # Durable cursor of this turn's turn.start: a client streams
            # ``?last_event_id=<start_event_id - 1>`` to follow just this turn.
            payload["start_event_id"] = admitted["event"]["event_id"]
        return web.json_response(payload)

    def _queue_updated(self, session_id: str) -> dict[str, Any]:
        items = self.store.list_queue(session_id)
        payload = {"session_id": session_id, "items": items}
        self.event_bus.publish(session_id, "queue.updated", payload)
        return payload

    async def handle_get_queue(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        items = self.store.list_queue(session_id)
        return web.json_response({"session_id": session_id, "items": items})

    async def handle_add_queue(self, request: web.Request) -> web.Response:
        """Add Gateway-owned follow-up work for a session."""
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "Missing queue text"}, status=400)
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        requested_profile = str(body.get("profile") or "").strip()
        if requested_profile:
            session = self.store.get_session(session_id) or {}
            bound = str(session.get("profile") or "").strip().lower()
            if bound and bound != requested_profile.strip().lower():
                return web.json_response(
                    {"error": f"This conversation belongs to {bound}; start a new chat to talk to {requested_profile}"},
                    status=409,
                )
        request_id = body.get("request_id")
        if request_id is not None:
            request_id = str(request_id).strip() or None
        requested = self._requested_from_body(body)
        try:
            item = self.store.enqueue_request(
                session_id, text, request_id=request_id, requested=requested,
            )
        except RequestConflict as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except RequestBusy as exc:
            return web.json_response({"error": str(exc), "session_id": session_id}, status=409)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        promoted = self.store.promote_next_queue_item(session_id)
        self._queue_updated(session_id)
        if promoted is not None:
            self._start_admitted_turn(
                promoted, session_id, str(promoted.get("input_text") or ""),
            )
        current_item = self.store.get_request(item['request_id']) or item
        own_promotion = promoted is not None and promoted['request_id'] == item['request_id']
        payload = {
            "session_id": session_id,
            "request_id": item["request_id"],
            "turn_id": current_item.get("turn_id"),
            "status": current_item["status"],
            "queued": current_item['status'] in {'queued', 'paused'},
            "replayed": bool(item.get("replayed")),
        }
        if own_promotion and promoted.get("event"):
            payload["start_event_id"] = promoted["event"]["event_id"]
        return web.json_response(payload, status=202)

    async def handle_update_queue(self, request: web.Request) -> web.Response:
        """Edit text, position, or pause/resume a still-queued item."""
        session_id = request.match_info["id"]
        request_id = request.match_info["request_id"]
        body = await request.json() if request.can_read_body else {}
        fields = {key: body.get(key) for key in ("text", "status", "position") if key in body}
        if not fields:
            return web.json_response({"error": "Nothing to update"}, status=400)
        try:
            updated = self.store.update_queue_item(
                session_id,
                request_id,
                text=fields.get("text"),
                status=fields.get("status"),
                position=fields.get("position"),
                expected_updated_at=body.get('expected_updated_at'),
            )
        except RequestConflict as exc:
            return web.json_response({'error': str(exc)}, status=409)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if updated is None:
            return web.json_response({"error": "Queued request not found"}, status=404)
        promoted = None
        if fields.get("status") == "queued":
            promoted = self.store.promote_next_queue_item(session_id)
        self._queue_updated(session_id)
        if promoted is not None:
            self._start_admitted_turn(
                promoted, session_id, str(promoted.get("input_text") or ""),
            )
        return web.json_response({
            "session_id": session_id,
            "item": promoted or updated,
            "promoted": promoted is not None,
        })

    async def handle_reorder_queue(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        order = body.get("order")
        if not isinstance(order, list) or not all(isinstance(v, str) for v in order):
            return web.json_response({"error": "order must be a list of request ids"}, status=400)
        try:
            items = self.store.reorder_queue(session_id, order)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        self._queue_updated(session_id)
        return web.json_response({"session_id": session_id, "items": items})

    async def handle_delete_queue(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        request_id = request.match_info["request_id"]
        if not self.store.delete_queue_item(session_id, request_id):
            return web.json_response({"error": "Queued request not found"}, status=404)
        self._queue_updated(session_id)
        return web.json_response({"session_id": session_id, "deleted": True})

    def _session_agent_id(self, session: dict[str, Any] | None) -> str | None:
        """Resolve session agent_id from top-level or metadata (handoff patch)."""
        if not session:
            return None
        aid = session.get("agent_id")
        if aid:
            return str(aid)
        meta = session.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("agent_id"):
            return str(meta["agent_id"])
        return None

    def _enrich_session_agent(self, session: dict[str, Any]) -> dict[str, Any]:
        """Attach agent_id / role / display_name for chrome GET without SSE."""
        out = dict(session)
        agent_id = self._session_agent_id(session)
        if not agent_id:
            return out
        out["agent_id"] = agent_id
        try:
            agent = self._registry().get_agent(agent_id)
        except Exception:  # noqa: BLE001 — GET must stay readable
            logger.exception("Failed to enrich session agent %s", agent_id)
            agent = None
        if agent is None:
            out.setdefault("role", None)
            out.setdefault("display_name", None)
            return out
        role = getattr(agent, "role", None)
        out["role"] = role.value if hasattr(role, "value") else (str(role) if role else None)
        out["display_name"] = agent.display_name
        return out

    @staticmethod
    def _read_roots(runtime: Any, selection: dict[str, Any], staged_dir: Any = None) -> list[str]:
        """Where a Gateway turn's read/list/search tools may look: the session
        workspace folder, else the instance workspace; plus the instance skills
        dir so an agent can read its own SKILL.md references, and the
        instance ``logs/tool_results`` dir where oversized tool results are
        spilled (the model is told that path and must be able to read it back)."""
        layout = getattr(runtime, "layout", None)
        workspace = str(selection.get("workspace") or "")
        if not workspace:
            try:
                from jaeger_agent.core.workspace import get_effective_workspace_dir
                workspace = str(get_effective_workspace_dir() or "")
            except Exception:  # noqa: BLE001
                workspace = ""
            workspace = workspace or str(getattr(layout, "workspace_dir", "") or "")
        roots = [workspace] if workspace else []
        skills = getattr(layout, "skills_dir", None)
        if isinstance(skills, (str, Path)):
            roots.append(str(skills))
        logs = getattr(layout, "logs_dir", None)
        if isinstance(logs, (str, Path)):
            roots.append(str(Path(logs) / "tool_results"))
        if staged_dir:
            # Only THIS session's staged uploads; other sessions' stay refused.
            roots.append(str(staged_dir))
        return roots

    def _load_gateway_mcp(self) -> dict[str, Any]:
        """Start mcp.json servers marked ``gateway: true`` (once per process)."""
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.mcp.service import load_gateway_servers
            layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            if layout is None:
                from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
                layout = InstanceLayout(root=resolve_instance_dir())
            result = load_gateway_servers(layout)
            logger.info("gateway MCP: servers=%s tools=%s errors=%s", result.get("servers"),
                        result.get("tool_count"), list((result.get("errors") or {}).keys()))
            return result
        except Exception:  # noqa: BLE001
            logger.warning("gateway MCP load failed", exc_info=True)
            return {}

    async def _prewarm_gateway_mcp(self, app: web.Application) -> None:
        """Opt-in (JAEGER_GATEWAY_MCP_PREWARM=1): connect Gateway MCP servers in
        the background at startup so the first turn does not wait on npx."""
        if os.environ.get("JAEGER_GATEWAY_MCP_PREWARM") != "1":
            return
        asyncio.get_running_loop().run_in_executor(None, self._load_gateway_mcp)

    def _specialist_scope(self, agent: Any, execution: dict[str, Any] | None) -> dict[str, Any] | None:
        """The specialist's tool grant and notes dir for this turn, or None (model-only)."""
        if execution is None:
            return None
        from jaeger_ai.core.agent_registry.specialists import (
            expand_tool_patterns, scoped_skill_names, specialist_tools,
        )

        tools = specialist_tools(agent)
        if not tools:
            return None
        if any(str(t).startswith("mcp__") and "*" in str(t) for t in tools):
            self._load_gateway_mcp()  # globs expand against the started servers
        try:
            from jaeger_os.core.tools.tool_registry import get_tools
            available = {t.name for t in get_tools()}
        except Exception:  # noqa: BLE001 — no registry: globs expand to nothing
            available = set()
        tools = expand_tool_patterns(tools, available)
        grant = execution.get("allowed_tools")
        scoped = list(tools) if grant is None else [t for t in tools if t in set(grant)]
        return {
            "execution": {**execution, "allowed_tools": scoped},
            "notes_dir": self.agent_memory_dir(agent),
            "skills": scoped_skill_names(agent) or [],
        }

    @staticmethod
    def _skill_roots() -> list[Path]:
        roots = [JaegerGatewayApp._instance_root() / "skills"]
        try:
            from jaeger_agent.skill_registry import playbook_skills as _pb
            roots.append(Path(_pb._SKILLS_DIR))
        except Exception:  # noqa: BLE001
            pass
        return roots

    @staticmethod
    def _agent_skill_cards(agent: Any) -> list[dict[str, Any]]:
        from jaeger_ai.core.agent_registry.specialists import agent_skill_names, resolve_skill_cards
        try:
            return resolve_skill_cards(agent_skill_names(agent), JaegerGatewayApp._skill_roots())
        except Exception:  # noqa: BLE001 — a listing must stay readable
            logger.debug("skill cards unavailable for %s", getattr(agent, "id", agent), exc_info=True)
            return []

    def _with_skills(self, payload: Any) -> Any:
        """Add ``skills: [{id, name, description, source_path}]`` to agent dicts."""
        from jaeger_ai.core.agent_registry.types import AgentRecord

        from jaeger_ai.core.gateway.agent_presentation import project
        presentation = self.store.agent_presentation()
        primary_id = self.store.primary_agent_id()
        from jaeger_ai.core.gateway.caller_auth import CALLERS
        caller = _REQUEST_CALLER.get()
        spec = CALLERS.get(caller[0]) if caller else None
        writable = bool(spec and 'admin' in spec.scopes)

        def one(row: Any) -> Any:
            if not isinstance(row, dict) or not row.get("id"):
                return row
            view = project(row, presentation, writable=writable, primary_id=primary_id)
            try:
                return {**view, "skills": self._agent_skill_cards(AgentRecord.from_dict(row))}
            except Exception:  # noqa: BLE001
                return view

        if isinstance(payload, list):
            return [one(r) for r in payload]
        if isinstance(payload, dict) and "id" in payload and "kind" in payload:
            return one(payload)
        if isinstance(payload, dict):
            out = dict(payload)
            for key in ("agents", "jaeger_native", "third_party", "specialists"):
                if isinstance(out.get(key), list):
                    out[key] = [one(r) for r in out[key]]
            for key in ("active", "lead"):
                if isinstance(out.get(key), dict):
                    out[key] = one(out[key])
            return out
        return payload

    def _auto_route(self, session: dict[str, Any] | None, text: str) -> bool:
        """Lead triage, once per conversation, before the first turn runs.

        A chat still on Jaeger by default moves to the one specialist whose
        domain clearly matches; the move is a normal session handoff with a
        visible notice and one-click undo. Home sessions and chats the owner
        assigned (``agent_pinned``) are never moved. True when it handed off."""
        meta = (session or {}).get("metadata") or {}
        if not session or meta.get("route_checked") or meta.get("home") or meta.get("agent_pinned"):
            return False
        from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID

        current = self._session_agent_id(session)
        if current not in (None, LEAD_AGENT_ID):
            return False
        sid = session["session_id"]
        try:
            from jaeger_ai.core.agent_registry.router import suggest_specialist

            target = suggest_specialist(text)
            if not target or self._registry().get_agent(target) is None:
                self.store.update_metadata(sid, {"route_checked": True})
                return False
            self.store.update_metadata(sid, {
                "route_checked": True, "agent_id": target, "previous_agent_id": current or LEAD_AGENT_ID,
                "routed_by": "auto", "handoff_reason": "matched specialty", "handed_off_at": time.time(),
            })
            self.event_bus.publish(sid, "session.handoff", {
                "session_id": sid, "from_agent_id": current or LEAD_AGENT_ID, "to_agent_id": target,
                "reason": "auto-routed", "routed_by": "auto", "keep_history": True,
            })
            return True
        except Exception:  # noqa: BLE001 — triage must never fail a turn
            logger.debug("auto-route failed", exc_info=True)
            return False

    def _resolve_session_agent(self, session_id: str):
        """Look up the session's AgentRecord via AgentRegistry (or None)."""
        session = self.store.get_session(session_id)
        agent_id = self._session_agent_id(session)
        if not agent_id:
            return None
        try:
            return self._registry().get_agent(agent_id)
        except Exception:  # noqa: BLE001 — chat must not fail closed on registry
            logger.exception("Failed to resolve session agent %s", agent_id)
            return None

    @staticmethod
    def _instance_root() -> Path:
        """Resolve the active Jaeger instance root (SI character + memory home)."""
        try:
            from jaeger_ai.core.instance.instance import resolve_instance_dir

            return resolve_instance_dir()
        except Exception:  # noqa: BLE001 — gateway must still answer without instance
            home = Path(os.environ.get("JAEGER_HOME", str(Path.home() / ".jaeger")))
            return home / "instances" / "jaeger"

    @staticmethod
    def _si_character_prompt() -> str | None:
        """Load the live SI brief from personality/Character.character_block()."""
        try:
            from jaeger_ai.features.personality.character import active_character

            character = active_character(JaegerGatewayApp._instance_root())
            if character is None:
                return None
            block = (character.character_block() or "").strip()
            return block or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("SI character prompt unavailable: %s", exc)
            return None

    @staticmethod
    def _si_soul_prompt() -> str | None:
        """Load SOUL.md via load_soul(InstanceLayout) — same root as character.

        Returns None on an error or empty document. Used only for the
        explicitly selected lead/default text-mode system prompt.
        """
        try:
            from jaeger_ai.core.instance.instance import InstanceLayout
            from jaeger_ai.core.prompt_documents import load_soul

            layout = InstanceLayout(root=JaegerGatewayApp._instance_root())
            soul = (load_soul(layout) or "").strip()
            return soul or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("SI SOUL prompt unavailable: %s", exc)
            return None


    @staticmethod
    def _skills_block(agent: Any) -> str:
        """``[Your skills]`` for a specialist prompt: exactly the skills it may load."""
        from jaeger_ai.core.agent_registry.specialists import resolve_skill_cards, scoped_skill_names
        names = scoped_skill_names(agent) or []
        if not names:
            return ""
        try:
            cards = resolve_skill_cards(names, JaegerGatewayApp._skill_roots())
        except Exception:  # noqa: BLE001
            cards = [{"name": n, "description": "", "missing": True} for n in names]
        lines = ["[Your skills]",
                 "These are the only skills loaded for you. Load one with use_skill(name=...) "
                 "and follow it before acting; skill(action=\"list\") shows the same set."]
        for card in cards:
            note = " (not installed)" if card.get("missing") else ""
            lines.append(f"- {card['name']}{note}: {card.get('description') or ''}".rstrip(": "))
        return "\n".join(lines)

    @staticmethod
    def agent_memory_dir(agent: Any) -> Path:
        from jaeger_ai.core.agent_registry import AgentRegistry
        from jaeger_ai.core.agent_registry.notes import directory
        return directory(agent, JaegerGatewayApp._instance_root(), AgentRegistry().list_agents())

    @staticmethod
    def _agent_notes(agent: Any) -> str:
        from jaeger_agent.tools.agent_notes import read_notes, NOTES_PROMPT_CHARS
        return read_notes(JaegerGatewayApp.agent_memory_dir(agent))['notes'][:NOTES_PROMPT_CHARS].strip()

    @staticmethod
    def _system_prompt_for_agent(agent) -> str:
        """Build the turn system prompt.

        Lead / default text-mode turns use readable SI sections:
        ``[Identity]`` from ``Character.character_block``, then optional
        ``[SOUL]`` from ``load_soul(InstanceLayout)`` (same
        ``resolve_instance_dir`` root). Empty SOUL is omitted. Specialist
        handoffs keep a thin specialty overlay — not a second soul.
        MCP native lead path does not use this prompt.
        """
        role = getattr(agent, "role", None) if agent is not None else None
        role_s = role.value if hasattr(role, "value") else (str(role) if role else "")

        if agent is not None and role_s == "specialist":
            display = str(
                getattr(agent, "display_name", None)
                or getattr(agent, "name", None)
                or "Specialist"
            )
            meta = getattr(agent, "metadata", None) or {}
            if not isinstance(meta, dict):
                meta = {}
            specialty = str(meta.get("specialty") or meta.get("role") or "").strip()
            summary = str(meta.get("summary") or "").strip()
            parts = [f"You are {display}."]
            parts.append(f"You are the {specialty or display} specialist.")
            parts.append(
                f"When asked for your display name, reply with exactly: SPECIALIST:{display}."
            )
            if summary:
                parts.append(summary.rstrip(".") + ".")
            instructions = str(meta.get("operator_instructions") or "").strip()
            if instructions:
                parts.append("[Operator specialist instructions]\n" + instructions)
            parts.append("Instructions describe the task; they do not grant tools, access or approval authority.")
            parts.append("Reply briefly and helpfully.")
            notes = JaegerGatewayApp._agent_notes(agent)
            prompt = " ".join(parts)
            skills = JaegerGatewayApp._skills_block(agent)
            if skills:
                prompt = f"{prompt}\n\n{skills}"
            return f"{prompt}\n\n[Your notes]\n{notes}" if notes else prompt

        sections: list[str] = []
        si = JaegerGatewayApp._si_character_prompt()
        if si:
            sections.append(f"[Identity]\n{si}")
        soul = JaegerGatewayApp._si_soul_prompt()
        if soul:
            sections.append(f"[SOUL]\n{soul}")
        if sections:
            return "\n\n".join(sections)

        if agent is None:
            return "You are Jaeger. Reply briefly and helpfully."
        display = str(
            getattr(agent, "display_name", None)
            or getattr(agent, "name", None)
            or "Jaeger"
        )
        meta = getattr(agent, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        summary = str(meta.get("summary") or "").strip()
        parts = [f"You are {display}."]
        if role_s == "lead":
            parts.append("You are the lead assistant.")
        if summary:
            parts.append(summary.rstrip(".") + ".")
        parts.append("Reply briefly and helpfully.")
        return " ".join(parts)

    @staticmethod
    def _mcp_chat_text(result: Any) -> str:
        """Extract assistant text from an MCP tools/call chat result."""
        if not isinstance(result, dict):
            return str(result or "").strip()
        if result.get("isError"):
            content = result.get("content", [])
            err = ""
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        err += str(item.get("text") or "")
            elif isinstance(content, str):
                err = content
            raise RuntimeError(err or "MCP tool error")
        content = result.get("content", [])
        text = ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text += str(item.get("text") or "")
        elif isinstance(content, str):
            text = content
        else:
            # Some adapters nest reply under structuredContent / text.
            nested = result.get("structuredContent") or result.get("text")
            if isinstance(nested, str):
                text = nested
            elif isinstance(nested, dict):
                text = str(nested.get("text") or nested.get("reply") or "")
        return text.strip()

    async def _native_lead_turn(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str | None = None,
        mcp_session: str | None = None,
        allowed_tools: list[str] | None = None,
        is_subordinate: bool = True,
    ) -> tuple[str, str] | None:
        """Lead turn via the Jaeger-owned native MCP server on loopback.

        Returns ``(response_text, backend_label)`` on success, or ``None`` when
        no result was confirmed. An uncertain execution must not be retried here.
        Does not invent a parallel agent runtime — reuses hermes adapters.

        Shared MCP chat session: literal ``dispatcher`` — same key Mac Chat /
        WebUI / Hermes adapter bind via DispatcherStore (see
        core.frameworks/jaeger.py rewrite to session_id='dispatcher',
        features/webui/service/session_unify.py, features/dispatcher/store.py
        DISPATCHER). Gateway /v1/sessions UUID stays separate for SSE/store;
        only the MCP chat session_id is shared so one self / one transcript.
        Specialist child runs pass an isolated ``mcp_session``.
        """
        native_session = mcp_session or "dispatcher"

        def _blocking_chat() -> tuple[str, str]:
            import urllib.error
            from urllib.parse import urlparse

            from jaeger_ai.core.gateway.native_mcp import (
                MCPClient,
                MCP_URL,
                MCP_HOST_HEADER,
                mcp_api_key,
            )

            # Reuse the framework MCP client against Jaeger's native HTTP server.
            args: dict[str, Any] = {"message": text, "session_id": native_session}
            if request_id:
                args["request_id"] = request_id
            if allowed_tools is not None:
                args["allowed_tools"] = allowed_tools
            if is_subordinate:
                args["is_subordinate"] = True
            logger.info(
                "native MCP chat session_id=%s request_id=%s",
                native_session,
                request_id,
            )
            key = mcp_api_key()
            signature = (MCPClient, MCP_URL, key, MCP_HOST_HEADER)
            with self._mcp_transport_lock:
                if signature != self._mcp_transport_signature:
                    client = MCPClient(MCP_URL, key, MCP_HOST_HEADER)
                    client.initialize()
                    names = frozenset(tool.get("name") for tool in client.list_tools())
                    self._mcp_transport = client
                    self._mcp_tool_names = names
                    self._mcp_transport_signature = signature
                client = self._mcp_transport
                tool_name = next(
                    (name for name in ("jaeger_chat", "chat") if name in self._mcp_tool_names), None)
                if tool_name is None:
                    raise RuntimeError("MCP chat tool unavailable")
                if request_id and self.store.get_request(request_id) is not None:
                    self.store.bind_native(
                        request_id,
                        native_run_id=request_id,
                        native_session=native_session,
                        status="running",
                    )
                try:
                    result = client._execute_call(tool_name, args)
                except urllib.error.HTTPError as exc:
                    if exc.code != 404:
                        raise
                    # MCP HTTP restarted and forgot this transport's session;
                    # a 404 means the call never ran, so reconnect and send once.
                    client = MCPClient(MCP_URL, key, MCP_HOST_HEADER)
                    client.initialize()
                    self._mcp_transport = client
                    result = client._execute_call(tool_name, args)
            response_text = JaegerGatewayApp._mcp_chat_text(result)
            if not response_text:
                raise RuntimeError("MCP chat returned empty content")
            label = "mcp"
            host = (urlparse(MCP_URL).netloc or "").strip()
            if host:
                label = f"mcp:{host}"
            return response_text, label

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_blocking_chat),
                timeout=NATIVE_LEAD_MCP_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — caller records the unconfirmed turn
            logger.warning(
                "native MCP turn has no confirmed result: %s",
                exc,
            )
            if "MCP credential missing" in str(exc):
                raise
            if getattr(exc, "code", None) in {401, 403}:
                raise RuntimeError(f"MCP credential rejected (HTTP {exc.code})") from exc
            return None

    @staticmethod
    def _history_before_admitted_user(
        session: dict[str, Any] | None,
        request_row: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Return history before this request's separately supplied prompt.

        Admission persists the current user message and request row with the
        same timestamp. Model callsites then pass the current prompt as a
        separate argument. Remove only that exact final admitted row; never
        value-deduplicate, because an earlier identical user message is valid
        conversation history. Callers without a durable admission row retain
        their history unchanged.
        """
        messages = list((session or {}).get("messages") or [])
        if not messages or not request_row:
            return messages
        tail = messages[-1]
        if (
            isinstance(tail, dict)
            and tail.get("role") == "user"
            and tail.get("timestamp") == request_row.get("created_at")
        ):
            return messages[:-1]
        return messages

    async def _ollama_chat(
        self,
        text: str,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        """Live text turn via locked Ollama — never routes through :8813."""
        target_model = model or DEFAULT_OLLAMA_MODEL
        if not target_model:
            raise RuntimeError(
                "Explicit text-only mode requires JAEGER_GATEWAY_OLLAMA_MODEL"
            )
        sys_content = system_prompt or "You are Jaeger. Reply briefly and helpfully."

        # Capability inventory injection when user asks about capabilities or tools
        if any(w in text.lower() for w in ("capabilities", "tools available", "what can you do", "what tools")):
            try:
                from jaeger_ai.interfaces.mcp_server import capability_inventory
                inv = capability_inventory()
                tool_list = []
                for grp, gdata in (inv.get("groups") or {}).items():
                    tool_list.extend(gdata.get("agent_tools") or [])
                if tool_list:
                    tools_str = ", ".join(sorted(set(tool_list)))
                    sys_content += f"\n\n[Live Capabilities Inventory]\nAvailable tools: {tools_str}"
            except Exception:
                pass

        messages = [
            {"role": item.get("role"), "content": item.get("content")}
            for item in (history or [])
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        if not messages or messages[-1] != {"role": "user", "content": text}:
            messages.append({"role": "user", "content": text})

        # Multimodal / Vision extraction: find uploaded image references in attachments, history, or text
        import base64
        import re
        from pathlib import Path

        image_b64s: list[str] = []
        all_text_blobs = [text] + [str(item.get("content") or "") for item in (history or [])]
        seen_paths: set[str] = set()

        for att in (attachments or []):
            safe_path = att.get("safe_path")
            mime = att.get("mime_type") or ""
            if safe_path and (mime.startswith("image/") or Path(safe_path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}):
                p = Path(safe_path)
                if p.is_file() and str(p) not in seen_paths:
                    seen_paths.add(str(p))
                    try:
                        image_b64s.append(base64.b64encode(p.read_bytes()).decode("utf-8"))
                    except Exception:
                        pass
        for blob in all_text_blobs:
            for match in re.finditer(r"stored at\s+([^\s]+\.(?:png|jpg|jpeg|webp|gif))", blob, re.IGNORECASE):
                img_path = match.group(1).strip()
                if img_path not in seen_paths:
                    seen_paths.add(img_path)
                    p = Path(img_path)
                    if p.is_file():
                        try:
                            image_b64s.append(base64.b64encode(p.read_bytes()).decode("utf-8"))
                        except Exception:
                            pass
            for match in re.finditer(r"(?:image attachment|attached image|file):\s*(?:[^\s]+\s+at\s+)?([^\s)]+\.(?:png|jpg|jpeg|webp|gif))", blob, re.IGNORECASE):
                img_path = match.group(1).strip()
                if img_path not in seen_paths:
                    seen_paths.add(img_path)
                    p = Path(img_path)
                    if p.is_file():
                        try:
                            image_b64s.append(base64.b64encode(p.read_bytes()).decode("utf-8"))
                        except Exception:
                            pass

        if image_b64s and messages:
            messages[-1]["images"] = image_b64s
            # Respect a model the operator or certification says has VISION.
            # Fall back only when the selected model is not vision-certified.
            if not _model_has_vision(target_model):
                target_model = DEFAULT_OLLAMA_MODEL

        payload = {
            "model": target_model,
            "messages": [
                {
                    "role": "system",
                    "content": sys_content,
                },
                *messages,
            ],
            "stream": False,
        }
        # Ollama Cloud models (":cloud" suffix, e.g. kimi-k2.7-code:cloud)
        # require Authorization: Bearer <key>. This call never attached one,
        # unlike every other model path in the codebase (see
        # external_model.py:556) — confirmed root cause of real 401s
        # ("Ollama chat HTTP 401: {\"error\":\"Unauthorized\"}\n") on the
        # vision-test / non-image-doc-test sessions in
        # gateway_sessions.sqlite3. Local Ollama needs no key, so an absent
        # one is fine (matches external_model.py's `if key else {}`).
        ollama_headers: dict[str, str] = {}
        ollama_key = (
            os.environ.get("OLLAMA_API_KEY")
            or os.environ.get("OLLAMA_CLOUD_API_KEY")
            or os.environ.get("OLLAMA_KEY")
        )
        if not ollama_key:
            try:
                from jaeger_ai.core.entity.runtime import EntityRuntime
                from jaeger_agent import credentials as creds
                layout = getattr(EntityRuntime.get_singleton(), "layout", None)
                if layout is not None:
                    ollama_key = creds.get_credential(layout, "ollama_cloud_api_key") or None
            except Exception:
                ollama_key = None
        if ollama_key:
            ollama_headers["Authorization"] = f"Bearer {ollama_key}"

        timeout = ClientTimeout(total=90)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{LOCKED_OLLAMA_URL}/api/chat", json=payload, headers=ollama_headers
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(
                        f"Ollama chat HTTP {resp.status}: {body[:500]}"
                    )
                data = json.loads(body)
        message = (data.get("message") or {})
        content = str(message.get("content") or "").strip()
        if not content:
            raise RuntimeError(f"Ollama returned empty content: {body[:500]}")
        return content

    def _turn_attachments(
        self, session_id: str, execution: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Attachments this turn may use: exactly those frozen at admission.

        An upload after admission belongs to a later turn. A snapshotted
        attachment whose content no longer matches its admitted sha256 is
        withheld rather than silently substituted.
        """
        rows = self.store.list_attachments(session_id)
        if execution is None:
            return rows
        by_id = {row.get("attachment_id"): row for row in rows}
        chosen = []
        for ref in execution.get("attachments") or []:
            row = by_id.get(ref.get("attachment_id"))
            if row is None:
                continue
            if ref.get("sha256") and row.get("sha256") and ref["sha256"] != row["sha256"]:
                logger.warning("Attachment %s changed after admission; withheld", ref.get("attachment_id"))
                continue
            chosen.append(row)
        return chosen

    def _turn_stream_callbacks(self, session_id: str, request_id: str) -> tuple[Any, Callable[[], None]]:
        """Agent callbacks that stream this turn to clients as durable events.

        ``turn.delta`` carries answer text (what Swift's voice loop and the
        bridge speak/render incrementally); ``turn.reasoning`` carries model
        deliberation, never part of the answer. Tool lifecycle events contain
        a catalog-shaped name, phase, outcome, bounded duration and, on start,
        redacted and bounded arguments (``_tool_event_args``: no credentials,
        no payload bodies). Results and errors never enter the client stream.
        Deltas are batched — each publish is a durable row — and are flushed
        before reasoning/tool boundaries and the terminal event so replay
        reproduces the exact observed order.
        """
        from jaeger_agent.loop.callbacks import AgentCallbacks

        row = self.store.get_request(request_id) or {}
        ids = {"turn_id": row.get("turn_id") or request_id, "request_id": request_id}
        lock = threading.Lock()
        pending: list[str] = []
        last = [time.monotonic()]
        # ``AgentCallbacks`` predates call ids.  Starts and finishes are serial
        # at the loop boundary (including parallel read batches), so a FIFO per
        # raw catalog name pairs them without publishing either the args or the
        # raw name. UUIDs remain stable because the event payload is durable.
        active_tools: dict[str, list[str]] = {}
        file_snapshots: dict[str, list[dict]] = {}

        def flush() -> None:
            with lock:
                text = "".join(pending)
                pending.clear()
                last[0] = time.monotonic()
            if text:
                self.event_bus.publish(session_id, "turn.delta", {**ids, "delta": text, "channel": "provisional"})

        reasoning_started: list[float | None] = [None]
        # Reasoning arrives a few characters at a time; like text deltas it is
        # coalesced (~TURN_DELTA_BATCH_S) and always flushed before any other
        # event, so ordering is unchanged.
        reasoning_pending: list[str] = []
        reasoning_last = [time.monotonic()]

        def flush_reasoning() -> None:
            with lock:
                text = "".join(reasoning_pending)
                reasoning_pending.clear()
                reasoning_last[0] = time.monotonic()
            if text:
                self.event_bus.publish(session_id, "turn.reasoning", {**ids, "text": text})

        def end_reasoning() -> None:
            # One ``turn.reasoning.done`` per reasoning run, when the answer,
            # a tool, or the end of the turn follows it (chat "Thought for Ns").
            flush_reasoning()
            with lock:
                started, reasoning_started[0] = reasoning_started[0], None
            if started is not None:
                self.event_bus.publish(session_id, "turn.reasoning.done", {
                    **ids, "started_at": started,
                    "duration_ms": max(0, int((time.time() - started) * 1000))})

        def on_delta(piece: str) -> None:
            end_reasoning()
            with lock:
                pending.append(str(piece))
                due = sum(map(len, pending)) >= TURN_DELTA_BATCH_CHARS or (
                    time.monotonic() - last[0] >= TURN_DELTA_BATCH_S)
            if due:
                flush()

        def on_reasoning(text: str) -> None:
            flush()
            if text:
                with lock:
                    if reasoning_started[0] is None:
                        reasoning_started[0] = time.time()
                    reasoning_pending.append(str(text))
                    due = sum(map(len, reasoning_pending)) >= TURN_REASONING_BATCH_CHARS or (
                        time.monotonic() - reasoning_last[0] >= TURN_DELTA_BATCH_S)
                if due:
                    flush_reasoning()

        def on_tool_progress(name: str, phase: str, data: Any) -> None:
            # ``done`` is followed immediately by the richer ``tool_done``
            # callback, which knows success/failure. Publishing here would
            # create two terminal rows for one call.
            if phase != "start":
                return
            flush()
            end_reasoning()
            raw_name = str(name or "")
            self.event_bus.publish(session_id, "turn.progress", {**ids, "channel": "progress"})
            activity_id = f"tool_{uuid.uuid4().hex}"
            with lock:
                active_tools.setdefault(raw_name, []).append(activity_id)
            if raw_name in {"write_file", "append_file", "patch", "delete_file", "move_file", "copy_file"} and isinstance(data, dict):
                try:
                    from jaeger_agent.core.workspace import _resolve_write
                    keys = ["src", "dst"] if raw_name == "move_file" else ["dst"] if raw_name == "copy_file" else ["path"]
                    file_snapshots[activity_id] = [self.file_changes.begin(_resolve_write(str(data[key]))) for key in keys]
                except Exception:
                    logger.debug("File change checkpoint unavailable for %s", raw_name)
            self.event_bus.publish(session_id, "tool.started", {
                **ids,
                "session_id": session_id,
                "activity_id": activity_id,
                "call_id": activity_id,
                "tool": _safe_tool_event_name(name),
                "phase": "started",
                "success": None,
                "ok": None,
                "text": "Started",
                **({"input": shown} if (shown := _tool_input_text(raw_name, data)) else {}),
                "args": _tool_event_args(data),
            })

        def on_tool_done(
            name: str,
            args: dict[str, Any],
            result: Any,
            ok: bool,
            error: str | None,
            elapsed_s: float,
        ) -> None:
            # Arguments, result and error are intentionally not published. They
            # can contain credentials, file contents, prompts, or command output.
            # The one exception is ``update_plan``: its result is the plan the
            # model chose to show the operator, and only that validated payload
            # (steps, statuses, an optional note) leaves this callback.
            self._request_tools.setdefault(request_id, []).append(str(name or ""))
            output_text = _tool_output_text(str(name or ""), result)
            plan_payload = None
            if str(name or "") == "update_plan" and ok and isinstance(result, dict) and result.get("ok"):
                plan_payload = {
                    "plan": [
                        {"step": str(item.get("step", ""))[:500], "status": str(item.get("status", ""))}
                        for item in (result.get("plan") or []) if isinstance(item, dict)
                    ][:50],
                    "summary": dict(result.get("summary") or {}),
                }
                if isinstance(result.get("explanation"), str):
                    plan_payload["explanation"] = result["explanation"][:500]
            from jaeger_ai.contract.tool_outcomes import tool_outcome
            outcome = tool_outcome(bool(ok), result)
            del args, result, error
            flush()
            end_reasoning()
            raw_name = str(name or "")
            with lock:
                queued = active_tools.get(raw_name)
                activity_id = queued.pop(0) if queued else f"tool_{uuid.uuid4().hex}"
                if queued == []:
                    active_tools.pop(raw_name, None)
            succeeded = bool(ok)
            snapshots = file_snapshots.pop(activity_id, [])
            if snapshots:
                try:
                    for snapshot in snapshots:
                        self.file_changes.finish(session_id, request_id, snapshot)
                    self.event_bus.publish(session_id, "files.changed", {
                        **ids, **self.file_changes.describe(session_id, request_id)})
                except (OSError, ValueError, UnicodeError):
                    logger.warning("File change checkpoint could not settle for %s", raw_name)
            duration = _safe_tool_duration(elapsed_s)
            phase = "completed" if succeeded else "failed"
            detail = (
                f"Completed in {duration:.3f}s"
                if succeeded
                else f"Failed after {duration:.3f}s"
            )
            self.event_bus.publish(session_id, f"tool.{phase}", {
                **ids,
                "session_id": session_id,
                "activity_id": activity_id,
                "call_id": activity_id,
                "tool": _safe_tool_event_name(name),
                "phase": phase,
                "outcome": outcome,
                "success": succeeded,
                "ok": succeeded,
                "elapsed_s": duration,
                "text": detail,
                **({"output": output_text} if output_text else {}),
            })
            if plan_payload is not None:
                self.event_bus.publish(session_id, "turn.plan", {**ids, **plan_payload})

        def finish() -> None:
            flush()
            end_reasoning()

        return AgentCallbacks(
            stream_delta=on_delta,
            reasoning=on_reasoning,
            tool_progress=on_tool_progress,
            tool_done=on_tool_done,
        ), finish

    def _owner_react_turn(
        self, prompt: str, *, session_key: str, request_id: str,
        on_model: Callable[[str], None] | None = None,
        execution: dict[str, Any] | None = None,
        continuation_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one inner ReAct step in the EntityRuntime OWNER process."""
        from jaeger_ai.core.entity.runtime import EntityRuntime

        runtime = EntityRuntime.get_singleton()
        native = None
        try:
            row = self.store.get_request(request_id)
            native = str((row or {}).get("native_run_id") or "") or None
        except Exception:
            pass
        if execution is not None:
            # Admitted request: execute exactly what was frozen at admission.
            selection = execution
            lane, selected_model = split_routed_model_id(str(execution.get("model") or ""))
        else:
            # Pre-snapshot (digest v1) request recovered after upgrade.
            session = self.store.get_session(session_key) or {}
            selection = session.get("metadata") or {}
            lane, selected_model = split_routed_model_id(str(selection.get("model") or session.get("model") or ""))
        callbacks, flush = self._turn_stream_callbacks(session_key, request_id)
        from jaeger_agent.tool_executor import tool_allowlist
        from jaeger_agent.core.workspace import read_confinement

        grant = execution.get("allowed_tools") if execution is not None else None
        try:
            # The admitted tool grant scopes the agent built for this turn
            # ([] = no tools; absent = the owner's normal catalog).
            from jaeger_agent.task_port import task_scope
            request_row = self.store.get_request(request_id) or {}
            options = selection.get("options") or {}
            source = "background" if options.get("background") else "user"
            with task_scope(self.task_owner, session_id=session_key, request_id=request_id,
                            execution=selection, user_text=request_row.get("input_text", prompt), source=source), \
                    tool_allowlist(list(grant) if grant is not None else None), \
                    read_confinement(self._read_roots(runtime, selection, self._staged_upload_dir(session_key))):
                return runtime.run_subordinate_react(
                    prompt,
                    session_key=session_key,
                    request_id=request_id,
                    callbacks=callbacks,
                    continuation_state=continuation_state,
                    project_root=str(selection.get("workspace") or "") or None,
                    confirmation_provider=_GatewayToolConfirmationProvider(self, session_key, request_id),
                    native_run_id=native,
                    model=selected_model or None,
                    provider=str(selection.get("provider") or lane or "") or None,
                    on_model=on_model,
                    on_agent=lambda agent: self._active_agents.__setitem__(request_id, agent),
                    cancellation=self._cancellations.get(request_id),
                    on_run=lambda run_id: self.store.bind_native(
                        request_id,
                        native_run_id=run_id,
                        native_session=f"{OWNER_RUN_SESSION_PREFIX}{session_key}",
                    ),
                )
        finally:
            flush()

    def _continued_owner_react(
        self, prompt: str, *, session_key: str, request_id: str,
        on_model: Callable[[str], None] | None = None,
        execution: dict[str, Any] | None = None,
        objective: str = "",
    ) -> dict[str, Any]:
        """One admitted request: inner ReAct plus owner-side continuation."""
        from jaeger_ai.core.runtime.autonomous_runner import run_continued_turn

        continuation_state: dict[str, Any] = {}

        def step(inner_prompt: str) -> dict[str, Any]:
            before = len(self._request_tools.get(request_id, []))
            out = self._owner_react_turn(
                inner_prompt, session_key=session_key, request_id=request_id,
                on_model=on_model, execution=execution,
                continuation_state=continuation_state,
            )
            return {
                **out,
                "text": out.get("text") or "",
                "halt_reason": out.get("halt_reason"),
                "status": "completed",
                "tools_used": list(self._request_tools.get(request_id, [])[before:]),
            }

        from jaeger_ai.core.runtime.work_ledger import ledger_scope, last_completion
        _options = ((execution or {}).get("options") or {})
        # A turn-owned card runs in the chat's own session, so it must start from a
        # fresh ledger: resuming would hand it an earlier request's completion.
        turn_owned = bool(_options.get("turn_owned"))

        def stop_requested() -> bool:
            if self._cancellations.is_cancelled(request_id):
                return True
            # An owner decline is an answer, and an unanswered approval needs the owner:
            # neither is a stall to push the model through.
            return turn_owned and (request_id in self._owner_declined or request_id in self._owner_unanswered)

        with ledger_scope(session_key, resume_completed=bool(_options.get("task_id")) and not bool(_options.get("verification_error")) and not turn_owned):
            try:
                result = run_continued_turn(
                    step, prompt, objective=objective or prompt,
                    durable=bool(_options.get("task_id")),
                    interactive=turn_owned,
                    max_steps=(4 if turn_owned else 8) if _options.get("task_id") else None,
                    is_cancelled=stop_requested,
                    on_checkpoint=lambda checkpoint: self.event_bus.publish(
                        session_key, "turn.checkpoint", {**checkpoint, "request_id": request_id}),
                )
                if turn_owned and request_id in self._owner_unanswered and not self._cancellations.is_cancelled(request_id):
                    result = {**result, "halt_reason": "needs_owner", "error": None,
                              "evidence": {"approval_unanswered": True}}
                elif turn_owned and request_id in self._owner_declined and not self._cancellations.is_cancelled(request_id):
                    result = {**result, "halt_reason": "blocked", "error": None,
                              "evidence": {"declined_by_owner": True}}
                elif turn_owned and not result.get("error") and not stop_requested():
                    # One bounded correction, as a durable task gets: a completion with no
                    # file receipt is not something the owner can verify.
                    from jaeger_ai.core.runtime.autonomous_runner import missing_named_paths
                    from jaeger_ai.core.tasks.owner import EVIDENCE_CONTRACT, has_file_receipt
                    # Only when the worker claimed completion without a file receipt, or
                    # the request names files that still do not exist. An answer-only
                    # request has no file to receipt; asking for one invites the model
                    # to invent an artifact.
                    completion = last_completion()
                    if not has_file_receipt(completion) and (
                            completion is not None or missing_named_paths(objective or prompt)):
                        fix = step(
                            "Owner verification requires correction: your completion carried no receipt for a "
                            "file the owner can check. Finish the work if it is not done, then " + EVIDENCE_CONTRACT)
                        result = {**result, **fix, "text": fix.get("text") or result.get("text")}
                return {**result, "task_completion": last_completion()}
            finally:
                self._active_agents.pop(request_id, None)
                self._request_tools.pop(request_id, None)

    async def _execute_turn(
        self,
        session_id: str,
        turn_id: str,
        text: str,
        *,
        request_id: str | None = None,
        execution: dict[str, Any] | None = None,
    ) -> None:
        """Run an admitted turn as the caller that admitted it.

        The actor frozen in the execution snapshot at admission (from the
        authenticated request) is bound for every tool call, so PolicyKernel
        judges an MCP/A2A turn as that outside caller. Turns jaegerd starts
        itself (tasks, background work, pre-auth requests) carry no caller and
        run as the entity, ``agent:jaeger``.
        """
        from jaeger_agent.tool_executor import caller_identity

        from jaeger_ai.features.agent_bridge.tool_scope import goal_scope

        actor = (execution or {}).get("caller")
        try:
            with caller_identity(actor if isinstance(actor, str) and actor.strip() else None), \
                    goal_scope(self, session_id, request_id, execution):
                await self._execute_turn_inner(
                    session_id, turn_id, text, request_id=request_id, execution=execution,
                )
        finally:
            self._schedule_summary(session_id)

    async def _execute_turn_inner(
        self,
        session_id: str,
        turn_id: str,
        text: str,
        *,
        request_id: str | None = None,
        execution: dict[str, Any] | None = None,
    ) -> None:
        """Background turn executor: lead via native MCP, specialist via Ollama.

        ``execution`` is the snapshot frozen at admission (model, provider,
        attachment revisions). ``None`` only for a pre-snapshot request
        recovered after upgrade, which keeps the historical session reads.

        Final assistant text is persisted before turn.finish is published.
        Cancellation is explicit; a dropped SSE client does not stop work.
        """
        session = self.store.get_session(session_id)
        if self._auto_route(session, text):
            session = self.store.get_session(session_id)
        session_agent_id = self._session_agent_id(session)
        agent = self._resolve_session_agent(session_id)
        system_prompt = self._system_prompt_for_agent(agent)
        agent_fields: dict[str, Any] = {}
        if session_agent_id:
            agent_fields["agent_id"] = session_agent_id
            agent_fields["role"] = None
            agent_fields["display_name"] = None
        if agent is not None:
            role = getattr(agent, "role", None)
            agent_fields = {
                "agent_id": agent.id,
                "role": role.value if hasattr(role, "value") else str(role),
                "display_name": agent.display_name,
            }
        role_s = str(agent_fields.get("role") or "")
        # A specialist runs on the same agent loop as Jaeger with its own
        # allowed tools (intersected with any admitted grant) and its own notes
        # (Claude Code subagent pattern). Without a scoped set it stays model-only.
        specialist_scope = self._specialist_scope(agent, execution) if role_s == "specialist" else None
        if specialist_scope is not None:
            execution = specialist_scope["execution"]
            # This turn runs in its own asyncio task, so the skill scope set
            # here covers its prepare/run threads (to_thread copies context)
            # and ends with the task: the specialist sees only its own skills.
            from jaeger_agent.skill_registry.playbook_skills import bind_skill_scope
            bind_skill_scope(specialist_scope["skills"])
            logger.info("specialist run agent=%s session=%s skills=%s tools=%d",
                        getattr(agent, "id", None), session_id, specialist_scope["skills"],
                        len(execution.get("allowed_tools") or []))
            self.event_bus.publish(session_id, "agent.skills", {
                "session_id": session_id, "request_id": request_id or turn_id,
                "agent_id": getattr(agent, "id", None), "skills": specialist_scope["skills"],
                "allowed_tools": list(execution.get("allowed_tools") or []),
            })
        rid = request_id or turn_id
        admitted_request = self.store.get_request(rid)
        # One Goal/TaskCard per operational turn (see _open_turn_card). None for conversation.
        card_task_id: str | None = None
        self._present(session_id, "listening", intent="turn")
        # What the operator wrote, before attachment notes are inlined. Lane
        # decisions read this: an inlined "inspect it with the vision_analyze
        # tool" note made a plain question about an image look actionable.
        request_text = text

        try:
            atts = self._turn_attachments(session_id, execution)
        except Exception:
            atts = []
        if atts:
            try:
                from jaeger_ai.core.frameworks.run_input import inline_webui_text_attachments
                mapped = [
                    {
                        "path": a.get("safe_path"),
                        "name": a.get("original_filename") or a.get("stored_filename"),
                        "mime": a.get("mime_type"),
                        "is_image": str(a.get("mime_type") or "").startswith("image/"),
                    }
                    for a in atts
                ]
                text = inline_webui_text_attachments(text, mapped)
            except Exception:
                logger.debug("attachment materialize failed", exc_info=True)

        try:
            if self._cancellations.is_cancelled(rid):
                self._finish_cancelled(session_id, turn_id, rid, agent_fields, "cancelled before native dispatch")
                return

            if agent is not None and (getattr(agent, 'metadata', None) or {}).get('knowledge_documents'):
                from jaeger_ai.features.knowledge_library.agent_context import materialize
                knowledge = materialize(agent, actor=(execution or {}).get('caller'))
                system_prompt += "\n\n" + knowledge['text']
                self.event_bus.publish(session_id, 'agent.knowledge', {'request_id': rid, 'turn_id': turn_id, 'agent_id': agent.id, 'documents': knowledge['documents']})
            backend = LOCKED_OLLAMA_URL
            model = DEFAULT_OLLAMA_MODEL
            response_text: str | None = None

            text_only = (session or {}).get("metadata", {}).get("execution_mode") == "text_only"
            from jaeger_ai.core.runtime.autonomous_runner import is_actionable_request
            actionable = bool(
                (session or {}).get("metadata", {}).get("actionable")
                or is_actionable_request(request_text)
            )

            loop = asyncio.get_running_loop()

            async def _run_native_coro(prompt: str) -> tuple[str, str] | None:
                if self._cancellations.is_cancelled(rid):
                    raise RuntimeError("cancelled before native dispatch")
                return await self._native_lead_turn(session_id, prompt, request_id=rid, is_subordinate=True)

            def _sync_react(prompt: str, session_key: str = session_id) -> dict[str, Any]:
                nonlocal backend, model
                session_atts = self._turn_attachments(session_id, execution)
                has_image = any(str(a.get("mime_type") or "").startswith("image/") for a in session_atts)
                if not has_image:
                    # The operator's request, not ``prompt``: the Entity
                    # prefixes recalled history, and an image filename from
                    # another session's turn sent an unrelated WebUI question
                    # down the tool-less vision lane.
                    import re as _re
                    has_image = bool(_re.search(r"\.(?:png|jpg|jpeg|webp)\b", request_text, _re.IGNORECASE))
                # A question about an image goes straight to a vision model.
                # Anything that asks for work goes through the Entity with its
                # tools and Authority: in an image session, "save this to a
                # file" used to be answered "I'll create the file" by a model
                # with no tools, and recorded as completed.
                if has_image and not actionable and _asks_about_the_image(request_text):
                    backend = LOCKED_OLLAMA_URL
                    model = self._lane_model(request_text, None)
                    current = self.store.get_session(session_id) or {}
                    chat_fut = asyncio.run_coroutine_threadsafe(
                        self._ollama_chat(
                            # request_text, not prompt: prompt has been
                            # rewritten by inline_webui_text_attachments to
                            # say "inspect it with the vision_analyze tool",
                            # a tool this bare _ollama_chat call never
                            # attaches. The model spent its whole output
                            # budget narrating a tool call it couldn't make
                            # and returned empty content (verified against
                            # real failures: session da59748d.../97afa8d5...,
                            # "Ollama returned empty content", thinking cut
                            # off mid-"I'll use visi[on_analyze]"). This path
                            # already sends the image directly as base64 via
                            # attachments=session_atts below, so it needs the
                            # operator's actual question, not a tool note.
                            request_text,
                            model=model,
                            system_prompt=system_prompt,
                            history=self._history_before_admitted_user(
                                current, admitted_request,
                            ),
                            attachments=session_atts,
                        ),
                        loop,
                    )
                    txt = chat_fut.result()
                    return {"text": txt, "status": "completed"}

                owner_first = os.environ.get("JAEGER_OWNER_REACT", "").strip() in {"1", "true", "yes"}
                try:
                    from jaeger_ai.core.entity.ownership import EntityRuntimeMode
                    from jaeger_ai.core.entity.runtime import EntityRuntime
                    rt = EntityRuntime.get_singleton()
                    if rt.mode == EntityRuntimeMode.OWNER and getattr(rt, "is_resident", False):
                        owner_first = True
                except Exception:
                    pass
                # The native-MCP-first lead turn is an isolated second path: the
                # resident Entity is the one executor. It runs only when the
                # operator re-enabled legacy paths, never as a silent fallback.
                if not owner_first and legacy_paths_enabled():
                    try:
                        native_res = asyncio.run_coroutine_threadsafe(_run_native_coro(prompt), loop).result()
                        if native_res is not None:
                            txt, b_end = native_res
                            backend = b_end
                            model = "jaeger-mcp"
                            return {"text": txt, "status": "completed"}
                    except Exception as ex:
                        logger.warning("Native MCP unavailable; OWNER in-process ReAct: %s", ex)
                def selected_model(name: str) -> None:
                    nonlocal model
                    model = name

                backend = "owner-react"
                return self._continued_owner_react(
                    prompt, session_key=session_key, request_id=rid,
                    on_model=selected_model,
                    execution=execution if session_key == session_id else None,
                    objective=request_text,
                )

            session_meta = (session.get("metadata") or {}) if isinstance(session, dict) and isinstance(session.get("metadata"), dict) else {}
            if execution is not None:
                req_model = provider_model_name(execution.get("model") or "")
            else:
                req_model = provider_model_name(session_meta.get("model") or (session or {}).get("model") or "")
            active_model = req_model or DEFAULT_OLLAMA_MODEL

            def _model_only_lane(prompt: str) -> dict[str, Any]:
                """A plain model answer with no tools: text-only chats and specialist agents.

                These are session-level choices made by the operator (a text-only
                conversation, an agent registered as a specialist), so they are an
                explicit lane at the Gateway boundary, next to the image lane. They
                do not pass through the agent loop and therefore never call tools.
                """
                nonlocal backend, model
                backend = LOCKED_OLLAMA_URL
                model = self._lane_model(request_text, active_model)
                current = self.store.get_session(session_id) or {}
                chat_fut = asyncio.run_coroutine_threadsafe(
                    self._ollama_chat(
                        prompt,
                        model=model,
                        system_prompt=no_tools_lane_system_prompt(system_prompt),
                        history=self._history_before_admitted_user(current, admitted_request),
                        attachments=self._turn_attachments(session_id, execution),
                    ),
                    loop,
                )
                return {"text": chat_fut.result(), "status": "completed"}

            from jaeger_ai.core.entity.runtime import EntityRuntime
            runtime = EntityRuntime.get_singleton()

            tier = (execution or {}).get("interaction_tier") or self._current_tier()
            turn_meta = {
                "execution_mode": "text_only" if (text_only or tier == "chat") else "agent",
                "interaction_tier": tier,
                "actionable": False if tier == "chat" else actionable,
                "role": role_s,
                "agent_id": agent_fields.get("agent_id"),
                "specialist": agent_fields.get("agent_id") if role_s == "specialist" else None,
            }

            # One turn shape. The main loop is the agent loop: build the request with
            # its fenced memory, run it, record the answer. Chat turns and durable
            # child tasks take exactly this path; nothing gates it.
            try:
                prepared = await asyncio.to_thread(
                    runtime.prepare_turn,
                    text,
                    session_id=session_id,
                    source="gateway",
                    request_id=rid,
                    gateway_session=session,
                    metadata=turn_meta,
                    ide_context=((execution or {}).get("options") or {}).get("ide"),
                )
                prompt = prepared.prompt
            except Exception:
                # Memory is an enrichment: if reading it fails the operator's
                # request must still reach the agent, unadorned.
                logger.warning("turn context unavailable for %s; running the bare request", rid, exc_info=True)
                prepared, prompt = None, text
            self._present(session_id, "thinking", intent="turn")
            card_task_id, execution = self._open_turn_card(
                runtime, prepared, session=session, session_id=session_id, rid=rid,
                request_text=request_text, actionable=actionable, tier=tier, role_s=role_s,
                execution=execution,
            )
            if card_task_id:
                # The worker must know how the owner will check its result.
                from jaeger_ai.core.tasks.owner import TURN_CARD_GUIDANCE
                prompt = f"{TURN_CARD_GUIDANCE}\n\n" + prompt
            if tier == "chat":
                model_only = True
            else:
                model_only = (text_only and not actionable) or (
                    role_s == "specialist" and specialist_scope is None)
            if specialist_scope is not None and not model_only:
                prompt = (f"[Agent]\n{system_prompt}\nYour own notes: use the agent_notes tool "
                          "(read/append/replace) to keep what matters for your specialty.\n\n") + prompt
                from jaeger_agent.tools.agent_notes import bound_notes_dir
                with bound_notes_dir(specialist_scope["notes_dir"]):
                    turn_result = await asyncio.to_thread(_sync_react, prompt)
            else:
                turn_result = await asyncio.to_thread(_model_only_lane if model_only else _sync_react, prompt)
            if prepared is not None and not turn_result.get("error"):
                try:
                    await asyncio.to_thread(runtime.finish_turn, prepared, str(turn_result.get("text") or ""))
                except Exception:
                    logger.warning("could not record the answer for %s", rid, exc_info=True)

            if self._cancellations.is_cancelled(rid):
                self._close_turn_card(card_task_id, {"error": "cancelled"}, "cancelled", session_id=session_id)
                if self._settle_cancelled(session_id, turn_id, rid, agent_fields):
                    return
                raise RuntimeError(
                    "Cancellation requested after native acceptance; "
                    "outcome is unconfirmed until reconcile"
                )

            if turn_result.get("error"):
                raise RuntimeError(str(turn_result["error"]))

            response_text = str(turn_result.get("text") or "")
            card_fields = self._close_turn_card(
                card_task_id, turn_result, "completed", session_id=session_id,
                models=(model, backend),
            )
            if not card_task_id:
                self._present(session_id, "done", intent="conversation", status="completed")

            self.event_bus.publish(session_id, "turn.delta", {
                "turn_id": turn_id,
                "request_id": rid,
                "delta": "",
                "model": model,
                "backend": backend,
                **agent_fields,
            })

            agent_lane = str(backend).startswith("mcp") or backend == "owner-react"
            options = ((execution or {}).get("options") or {})
            proactive_fields = {}
            if str(options.get("source") or "") == "sensor" and options.get("proactive_salience"):
                proactive_fields = {
                    "proactive": True,
                    "proactive_source": "sensor",
                    "proactive_salience": _normalize_salience(options["proactive_salience"]),
                }
            result = {
                "output": response_text,
                "status": "completed",
                "backend": backend,
                "model": model,
                "turn_id": turn_id,
                "execution_mode": "agent" if agent_lane else "text_only",
                "capabilities": {
                    "native_tools": agent_lane,
                    "native_memory": agent_lane,
                },
                "verification": turn_result.get("verification"),
                "task_completion": turn_result.get("task_completion"),
                "halt_reason": turn_result.get("halt_reason"),
                "trace_id": turn_result.get("trace_id"),
                **card_fields,
                **agent_fields,
                **proactive_fields,
            }
            self._persist_terminal(rid, session_id, "completed", result, assistant_text=response_text, record_entity_event=False)
        except asyncio.CancelledError:
            # Global Stop cancels this task. Persist how the request ended (cancelled, or
            # execution_unknown when an effect is pending) so it is never left 'running'.
            try:
                self._close_turn_card(card_task_id, {"error": "cancelled"}, "cancelled", session_id=session_id)
                if not self._settle_cancelled(session_id, turn_id, rid, agent_fields):
                    self._finish_cancelled(session_id, turn_id, rid, agent_fields, "cancelled by Global Stop")
            except Exception:
                logger.exception("could not persist the cancelled outcome of %s", rid)
            raise
        except Exception as exc:
            if self._cancellations.is_cancelled(rid) and self._settle_cancelled(
                session_id, turn_id, rid, agent_fields,
            ):
                return
            logger.exception("Turn execution failed: %s", exc)
            bound = self.store.get_request(rid) or {}
            after_native = bool(bound.get("native_run_id"))
            owner_run = str(bound.get("native_session") or "").startswith(OWNER_RUN_SESSION_PREFIX)
            if after_native and owner_run:
                # The Entity's own run: its effect ledger, not the MCP
                # receipt store, says whether anything was left half-done.
                from jaeger_ai.core.entity.runtime import EntityRuntime
                after_native = EntityRuntime.run_has_indeterminate_effects(str(bound["native_run_id"]))
            status = "execution_unknown" if after_native else "failed"
            receipt = (
                self._native_receipt(bound.get("native_run_id"), bound.get("native_session"))
                if after_native and not owner_run else None
            )
            reply = (receipt or {}).get("reply") if isinstance(receipt, dict) else None
            reply = reply if isinstance(reply, dict) else {}
            if receipt and receipt.get("execution_unknown") is False and receipt.get("status") in {"completed", "failed", "cancelled"}:
                status = receipt["status"]
            options = (((execution or {}).get("options") or {}) if execution is not None else {})
            proactive_fields = {}
            if str(options.get("source") or "") == "sensor" and options.get("proactive_salience"):
                proactive_fields = {
                    "proactive": True,
                    "proactive_source": "sensor",
                    "proactive_salience": _normalize_salience(options["proactive_salience"]),
                }
            result = {"error": str(exc), "turn_id": turn_id, "status": status, **agent_fields, **proactive_fields}
            if status == "completed":
                result = {
                    "output": str(reply.get("text") or ""),
                    "status": "completed",
                    "turn_id": turn_id,
                    "backend": "native_receipt",
                    **agent_fields,
                    **proactive_fields,
                }
            if receipt:
                result["native_receipt"] = receipt
            result.update(self._close_turn_card(card_task_id, result, status, session_id=session_id))
            if not card_task_id:
                self._present(session_id, "stopped" if status == "cancelled" else "failed", status=status)
            self._persist_terminal(
                rid,
                session_id,
                status,
                result,
                assistant_text=str(reply.get("text") or "") or None if status == "completed" else None,
            )
        finally:
            # Global Stop cancels this asyncio task (CancelledError skips the except
            # above). A card still open here is settled, never left running.
            self._close_turn_card(
                card_task_id, {"error": "the turn ended before the task was settled"},
                "cancelled", session_id=session_id,
            )
            self._owner_declined.discard(rid)
            self._owner_unanswered.discard(rid)
            self._running_tasks.pop(rid, None)
            self._cancellations.release(rid)

    @staticmethod
    def _lane_model(request_text: str, requested: str | None) -> str:
        """The Gateway's one routing decision for a direct model lane.

        It is the existing router's sensitivity decision (``core/models/router.py``):
        private text stays on the local model, public text uses the requested one.
        Judged on what the operator wrote, not on the prompt with recalled memory.
        """
        from jaeger_ai.core.models.router import apply_sensitivity_routing

        model, _provider, _decision = apply_sensitivity_routing(request_text, model=requested or None)
        return provider_model_name(model or requested or DEFAULT_OLLAMA_MODEL)

    def _present(self, session_id: str, state: str, **fields: Any) -> None:
        """Publish ``jaeger.state``. Presence reports a turn; it never decides whether one runs."""
        try:
            self.event_bus.publish_state(session_id, state, **fields)
        except Exception:
            logger.debug("presence publish skipped", exc_info=True)

    def _open_turn_card(
        self, runtime: Any, prepared: Any, *, session: Any, session_id: str, rid: str,
        request_text: str, actionable: bool, tier: str, role_s: str,
        execution: dict[str, Any] | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Conversation stays a conversation. Work becomes one Goal/TaskCard on GatewayTaskOwner.

        The existing ExecutiveStrategySelector judges the prepared turn; the existing
        owner ReAct is the worker, run in durable mode so it must return evidence.
        """
        if prepared is None or execution is None or not actionable or tier == "chat" or role_s == "specialist":
            return None, execution
        from jaeger_ai.core.entity.executive import CognitiveStrategy

        try:
            decision = runtime.executive_selector.select_strategy(prepared.event, runtime.current_state)
        except Exception:
            logger.debug("executive strategy unavailable for %s", rid, exc_info=True)
            decision = None
        strategy = decision.strategy if decision is not None else CognitiveStrategy.REACT_LOOP
        if strategy in {
            CognitiveStrategy.DIRECT_RESPONSE, CognitiveStrategy.PASSIVE_OBSERVE,
            CognitiveStrategy.SLEEP_TIME_CONSOLIDATION,
        }:
            return None, execution
        workspace = str(
            execution.get("workspace") or (session or {}).get("workspace")
            or getattr(getattr(runtime, "layout", None), "workspace_dir", "") or ""
        )
        try:
            task = self.task_owner.open_turn(
                session_id=session_id, request_id=rid, text=request_text, strategy=strategy.value,
                owner=str(execution.get("caller") or "owner"), workspace=workspace,
            )
        except Exception:
            logger.warning("could not open a task card for %s; running as a plain turn", rid, exc_info=True)
            return None, execution
        self._present(
            session_id, "planning", task_id=task.task_id, intent="work", status=strategy.value,
            strategy=strategy.value,
            complexity=float(getattr(decision, "complexity_score", 0.0) or 0.0),
            requires_work_ledger=bool(getattr(decision, "requires_work_ledger", False)),
        )
        options = {**(execution.get("options") or {}), "task_id": task.task_id, "turn_owned": True}
        self._world_claim(runtime, task.task_id, "planned_strategy", strategy.value, "planned")
        self._present(session_id, "working", task_id=task.task_id, intent="work", worker="owner-react")
        return task.task_id, {**execution, "options": options}

    def _settle_dispatch(self, orchestration_id: str, done: Any) -> None:
        """Settle the owner's card for a worker dispatch once the worker has returned."""
        card_id = f"orch:{orchestration_id}"
        try:
            from jaeger_ai.contract.presence import ACTIVITY_FOR_TASK_STATE
            from jaeger_ai.core.entity.runtime import EntityRuntime

            record = self.orchestration.get_task(orchestration_id) if self.orchestration else None
            task, receipt = self.task_owner.close_dispatch(
                card_id, record, cancelled=bool(done.cancelled()),
                identity=EntityRuntime.get_singleton().identity,
            )
            session = task.notification_policy.recipient_session_id or "orchestration"
            self._present(
                session, ACTIVITY_FOR_TASK_STATE.get(task.state.value, "failed"), task_id=task.task_id,
                intent="work", status=task.state.value, worker=str((record or {}).get("worker") or ""),
                receipt_id=receipt.receipt_id,
            )
        except Exception:
            logger.exception("could not settle the card for orchestration task %s", orchestration_id)

    @staticmethod
    def _world_claim(runtime: Any, subject: str, predicate: str, value: str, provenance: str) -> None:
        """Ask the resident Entity to record a world claim. A claim never gates a turn."""
        record = getattr(runtime, "record_world_claim", None)
        if record is None:
            return
        try:
            record(subject, predicate, value, provenance=provenance, source_id="gateway")
        except Exception:
            logger.debug("world claim skipped: %s %s", subject, predicate, exc_info=True)

    def _close_turn_card(
        self, card_task_id: str | None, turn_result: dict[str, Any], status: str, *,
        session_id: str, models: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Verify and settle a turn's card through the task owner, then report it. Idempotent."""
        if not card_task_id:
            return {}
        try:
            existing = self.task_owner.store.get_task(card_task_id)
            if existing is not None and existing.is_terminal:
                return {}  # already settled and reported once
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.contract.presence import ACTIVITY_FOR_TASK_STATE

            if status == "completed" and not turn_result.get("error"):
                self._present(session_id, "verifying", task_id=card_task_id, intent="work")
            task, receipt = self.task_owner.close_turn(
                card_task_id, turn_result, status=status,
                identity=EntityRuntime.get_singleton().identity, models=models,
            )
            runtime = EntityRuntime.get_singleton()
            if task.state.value == "completed_verified":
                self._world_claim(runtime, task.task_id, "worker_evidence", str(receipt.evidence)[:300], "observed")
                self._world_claim(runtime, task.task_id, "completed_verified", task.goal, "verified")
            self._present(
                session_id, ACTIVITY_FOR_TASK_STATE.get(task.state.value, "failed"), task_id=task.task_id,
                intent="work", status=task.state.value, receipt_id=receipt.receipt_id,
            )
            return {"task_id": task.task_id, "task_state": task.state.value, "receipt": receipt.to_dict()}
        except Exception:
            logger.exception("could not settle turn card %s", card_task_id)
            return {}

    def _settle_cancelled(
        self,
        session_id: str,
        turn_id: str,
        request_id: str,
        agent_fields: dict[str, Any],
    ) -> bool:
        """Persist the single authoritative outcome of a cancelled request.

        The effect ledger decides: no run bound yet → ``cancelled``; the
        Entity's own run with every claimed effect resolved → ``cancelled``
        (completed effects stay recorded); a pending effect →
        ``execution_unknown`` until reconciled. Returns False for a legacy
        MCP-dispatched run, whose outcome only its native receipt can settle.
        """
        bound = self.store.get_request(request_id) or {}
        run_id = str(bound.get("native_run_id") or "")
        if not run_id:
            self._finish_cancelled(session_id, turn_id, request_id, agent_fields,
                                   "cancelled before native acceptance")
            return True
        if not str(bound.get("native_session") or "").startswith(OWNER_RUN_SESSION_PREFIX):
            return False
        from jaeger_ai.core.entity.runtime import EntityRuntime
        if EntityRuntime.run_has_indeterminate_effects(run_id):
            self._persist_terminal(request_id, session_id, "execution_unknown", {
                "status": "execution_unknown", "turn_id": turn_id, "output": None,
                "error": "cancelled with an external effect whose outcome is unknown; reconcile",
                **agent_fields,
            })
            return True
        self._finish_cancelled(session_id, turn_id, request_id, agent_fields,
                               "cancelled during execution")
        return True

    def _persist_terminal(
        self,
        request_id: str,
        session_id: str,
        status: str,
        result: dict[str, Any],
        *,
        assistant_text: str | None = None,
        record_entity_event: bool = True,
    ) -> None:
        session_status = "idle" if status in {"completed", "cancelled"} else status
        if assistant_text is None and status != "completed":
            notification = _proactive_notification_payload(session_id, request_id, status, result)
            if notification is not None:
                assistant_text = notification["body"]
        if assistant_text and status == "completed" and record_entity_event:
            try:
                from jaeger_ai.core.entity.runtime import EntityRuntime
                EntityRuntime.get_singleton().record_agent_response(
                    assistant_text,
                    session_id=session_id,
                    model=str(result.get("model") or ""),
                    metadata=result,
                )
            except Exception:
                pass
        persisted = None
        try:
            persisted = self.store.complete_request(
                request_id,
                status=status,
                result=result,
                assistant_text=assistant_text,
                session_status=session_status,
            )
            try:
                from jaeger_ai.features.agent_bridge.responses import deliver_responses
                deliver_responses(self, request_id=request_id)
            except Exception:
                logger.exception("Peer response delivery deferred to inbox/goal read recovery")
            if persisted.get("event"):
                self.event_bus.fanout(persisted["event"])
            if not persisted.get("replayed"):
                self._publish_proactive_notification(
                    request_id, session_id, status, result,
                )
            if status in {"completed", "failed", "cancelled"}:
                self._drain_session_queue(session_id)
            if status == "completed" and not persisted.get("replayed"):
                try:
                    from jaeger_ai.core.entity.runtime import EntityRuntime
                    artifacts = []
                    if isinstance(result, dict):
                        for key in ("artifact", "path", "output_path"):
                            if result.get(key):
                                artifacts.append(str(result.get(key)))
                    EntityRuntime.get_singleton().record_background_completed(
                        request_id,
                        {
                            "summary": (assistant_text or str((result or {}).get("output") or ""))[:500],
                            "originating_event_id": str((result or {}).get("turn_id") or request_id),
                            "artifact_refs": artifacts,
                        },
                        session_id=session_id,
                    )
                except Exception:
                    pass
        except KeyError:
            if assistant_text is not None:
                self.store.append_message(session_id, "assistant", assistant_text)
            self.store.update_status(session_id, session_status)
            self.event_bus.publish(session_id, {
                "completed": "turn.finish", "failed": "turn.failed",
                "cancelled": "turn.cancelled", "execution_unknown": "turn.unknown",
            }[status], {**result, "request_id": request_id})

    def _publish_proactive_notification(
        self,
        request_id: str,
        session_id: str,
        status: str,
        result: dict[str, Any],
    ) -> bool:
        """Emit one SSE notification for a completed Tier 3 proactive result."""
        payload = _proactive_notification_payload(session_id, request_id, status, result)
        if payload is None:
            return False
        self.event_bus.publish(session_id, "notification.proactive", payload)
        return True

    def _finish_cancelled(
        self,
        session_id: str,
        turn_id: str,
        request_id: str,
        agent_fields: dict[str, Any],
        reason: str,
    ) -> None:
        result = {
            "status": "cancelled",
            "turn_id": turn_id,
            "output": None,
            "error": reason,
            **agent_fields,
        }
        self._persist_terminal(request_id, session_id, "cancelled", result)

    async def handle_file_changes(self, request: web.Request) -> web.Response:
        sid, rid = request.match_info["id"], request.match_info["request_id"]
        row = self.store.get_request(rid)
        if not row or row.get("session_id") != sid:
            return web.json_response({"error": "Request not found"}, status=404)
        if request.method == "POST" and row.get("status") not in {"completed", "failed", "cancelled"}:
            return web.json_response({"error": "Wait for the turn to settle before undoing"}, status=409)
        if request.method == "POST" and any(not task.done() for task in self._running_tasks.values()):
            return web.json_response({"error": "Wait for active Gateway turns to finish before undoing"}, status=409)
        try:
            if request.method == "POST":
                data = await asyncio.to_thread(self.file_changes.undo, sid, rid)
                self.event_bus.publish(sid, "files.changed", {"request_id": rid, **data})
            else:
                data = await asyncio.to_thread(self.file_changes.describe, sid, rid,
                                               contents=request.query.get("contents") == "1")
            return web.json_response(data)
        except (ValueError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    async def handle_get_request(self, request: web.Request) -> web.Response:
        row = self.store.get_request(request.match_info["request_id"])
        if row is None or row["session_id"] != request.match_info["id"]:
            return web.json_response({"error": "Request not found"}, status=404)
        return web.json_response(row)

    async def handle_get_request_any_session(self, request: web.Request) -> web.Response:
        """GET /v1/requests/{request_id} — request lookup without knowing the session.

        The WebUI shim holds only the request_id a turn admission returned;
        the session id is the Gateway's business. Resolves by request_id
        first, then by turn_id (the same fallback handle_cancel_turn uses).
        """
        rid = request.match_info["request_id"]
        row = self.store.get_request(rid) or self.store.get_request_by_turn(rid)
        if row is None:
            return web.json_response({"error": "Request not found"}, status=404)
        return web.json_response(row)

    async def handle_list_notifications(self, request: web.Request) -> web.Response:
        """GET /v1/notifications?since_event_id=N - Jaeger's speak-first messages.

        One cross-session feed of durable ``notification.proactive`` events so
        any surface (WebUI, menu bar, phone bridge) can show and speak what
        Jaeger said first, without knowing which session it landed in.
        """
        try:
            since = int(request.query.get("since_event_id") or 0)
            limit = int(request.query.get("limit") or 20)
        except ValueError:
            return web.json_response({"error": "Invalid since_event_id or limit"}, status=400)
        items = self.store.proactive_notifications(since, limit)
        cursor = items[-1]["event_id"] if items else since
        return web.json_response({"notifications": items, "cursor": cursor})

    async def handle_presence(self, request: web.Request) -> web.Response:
        """GET /v1/presence - what Jaeger is doing now, for avatars to animate.

        A read of the newest ``jaeger.state`` event (contract/presence.py). It
        reports; it never decides anything.
        """
        from jaeger_ai.contract.presence import ACTIVITY_STATES, DISPLAY
        from jaeger_ai.core.gateway.event_bus import latest_presence
        latest = latest_presence(self.store) or {}
        state = latest.get("state")
        if state not in ACTIVITY_STATES:
            state = "idle"
        try:
            from jaeger_ai.core.gateway.server import _control_plane_block
            if _control_plane_block():
                state = "stopped"
        except Exception:
            pass
        return web.json_response({
            "state": state, "display": DISPLAY[state],
            "session_id": latest.get("session_id"), "event_id": latest.get("event_id"),
            "owner_needed": state == "needs_owner" or bool(latest.get("approval_required")),
        })

    async def handle_session_events_json(self, request: web.Request) -> web.Response:
        """GET /v1/sessions/{id}/events?since_event_id=N — the replay window as JSON.

        The SSE stream is for live subscribers; polling clients (the WebUI
        shim's run feed) need the same durable events as one JSON document.
        Same store, same schema, same cursor semantics as the stream.
        """
        session_id = request.match_info["id"]
        if not self.store.get_session(session_id):
            return web.json_response({"error": "Session not found"}, status=404)
        try:
            since = int(request.query.get("since_event_id") or 0)
        except ValueError:
            return web.json_response({"error": "Invalid since_event_id"}, status=400)
        window = self.event_bus.replay_window(session_id, since)
        return web.json_response(window)

    async def handle_cancel_turn(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        request_id = str(body.get("request_id") or body.get("turn_id") or "").strip()
        if not request_id:
            return web.json_response({"error": "request_id is required"}, status=400)
        row = self.store.get_request(request_id) or self.store.get_request_by_turn(request_id)
        if row is None or row["session_id"] != session_id:
            return web.json_response({"error": "Request not found"}, status=404)
        if row["status"] in {"completed", "failed", "cancelled"}:
            return web.json_response({**row, "cancel_requested": False, "already_terminal": True})
        scope = self._cancellations.cancel(row["request_id"])
        updated = self.store.mark_request_status(row["request_id"], "cancelling") or row
        native_requested = False
        owner_run = str(updated.get("native_session") or "").startswith(OWNER_RUN_SESSION_PREFIX)
        if updated.get("native_run_id") and not owner_run:
            # Legacy MCP-dispatched run: only the native side can stop it.
            native_requested = await self._request_native_cancel(
                updated["native_run_id"], updated.get("native_session") or "dispatcher"
            )
        self._close_pending_approvals(row["request_id"])
        self.event_bus.publish(session_id, "turn.cancel", {
            "request_id": updated["request_id"],
            "turn_id": updated["turn_id"],
            "native_cancel_requested": native_requested,
            "native_cancel_confirmed": False,
            "interrupt_delivered": scope.interrupt_delivered,
        })
        return web.json_response({
            **updated,
            "cancel_requested": True,
            "native_cancel_requested": native_requested,
            "interrupt_delivered": scope.interrupt_delivered,
            "cancellation_confirmed": False,
        })

    def _close_pending_approvals(self, request_id: str) -> None:
        """Deny every approval still pending for a cancelled request.

        First writer wins in the store, so an operator decision that landed
        first is kept on record — but the confirm wait also sees the
        cancellation and refuses the action either way.
        """
        for approval in self.store.list_pending_approvals():
            if approval.get("request_id") != request_id:
                continue
            aid = approval["approval_id"]
            self.store.resolve_approval(aid, approved=False, decision="cancelled")
            future = self.pending_approvals.pop(aid, None)
            if future is not None and not future.done():
                future.set_result(False)

    async def _request_native_cancel(self, native_run_id: str, native_session: str) -> bool:
        try:
            from jaeger_ai.core.gateway.native_mcp import (
                MCPClient, MCP_URL, MCP_HOST_HEADER, mcp_api_key,
            )
            def _call() -> bool:
                client = MCPClient(MCP_URL, mcp_api_key(), MCP_HOST_HEADER)
                client.initialize()
                names = {tool.get("name") for tool in client.list_tools()}
                tool = next((n for n in ("cancel_turn", "jaeger_cancel_turn") if n in names), None)
                if tool is None:
                    return False
                result = client._execute_call(tool, {
                    "session_id": native_session,
                    "request_id": native_run_id,
                })
                return not result.get("isError")
            return await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001 — cancel request is best-effort
            logger.warning("native cancel request failed: %s", exc)
            return False

    async def handle_steer_request(self, request: web.Request) -> web.Response:
        """Inject guidance into the active admitted ReAct request.

        This is live steering, not a second turn. The agent owns a per-turn
        queue and drains it before its next model step. If no ReAct agent is
        active (for example a text-only lane), the Gateway returns an honest
        409 so the client can decide whether to queue a follow-up turn.
        """
        session_id = request.match_info["id"]
        request_id = request.match_info["request_id"]
        body = await request.json() if request.can_read_body else {}
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "Steering text is required"}, status=400)
        row = self.store.get_request(request_id)
        if row is None or row.get("session_id") != session_id:
            return web.json_response({"error": "Request not found"}, status=404)
        if row.get("status") in {"completed", "failed", "cancelled", "execution_unknown"}:
            return web.json_response(
                {"error": "Request is already terminal", "request_id": request_id},
                status=409,
            )
        agent = self._active_agents.get(request_id)
        if agent is None:
            return web.json_response(
                {
                    "error": "This request has no active ReAct agent to steer",
                    "request_id": request_id,
                    "status": row.get("status"),
                },
                status=409,
            )
        accepted = bool(agent.steer(text))
        if not accepted:
            return web.json_response(
                {"error": "Agent did not accept steering", "request_id": request_id},
                status=409,
            )
        self.event_bus.publish(session_id, "turn.steer", {
            "request_id": request_id,
            "text": text,
            "queued": True,
        })
        return web.json_response({
            "request_id": request_id,
            "steered": True,
            "queued": True,
        })

    async def handle_reconcile(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        request_id = str(body.get("request_id") or "").strip()
        if not request_id:
            if self.store.get_session(session_id) is None:
                return web.json_response({"error": "Session not found"}, status=404)
            return web.json_response({"error": "request_id is required"}, status=400)
        row = self.store.get_request(request_id)
        if row is None or row["session_id"] != session_id:
            return web.json_response({"error": "Request not found"}, status=404)
        if row["status"] in {"completed", "failed", "cancelled"}:
            return web.json_response({**row, "reconciled": False, "already_terminal": True})
        receipt = self._native_receipt(row.get("native_run_id"), row.get("native_session"))
        if receipt is None or receipt.get("execution_unknown") is not False:
            return web.json_response({
                **row,
                "reconciled": False,
                "execution_unknown": True,
                "error": "Native execution remains unknown; not replaying",
                "receipt": receipt,
            }, status=409)
        status = receipt.get("status")
        if status not in {"completed", "failed", "cancelled"}:
            return web.json_response({
                **row,
                "reconciled": False,
                "execution_unknown": True,
                "error": "Native receipt is not terminal; not replaying",
                "receipt": receipt,
            }, status=409)
        output = ""
        reply = receipt.get("reply") or {}
        if isinstance(reply, dict):
            output = str(reply.get("text") or "")
        result = {
            "output": output,
            "status": status,
            "backend": "native_receipt",
            "turn_id": row["turn_id"],
            "reconciliation": receipt,
        }
        persisted = self.store.complete_request(
            request_id,
            status=status,
            result=result,
            assistant_text=output or None,
            session_status="idle" if status in {"completed", "cancelled"} else "failed",
            event_name="turn.reconciled",
        )
        if persisted.get("event"):
            self.event_bus.fanout(persisted["event"])
        return web.json_response({**persisted, "reconciled": True, "receipt": receipt})

    def _native_receipt(self, native_run_id: str | None, native_session: str | None) -> dict[str, Any] | None:
        if not native_run_id or not native_session:
            return None
        try:
            from jaeger_ai.core.runtime.native_turns import NativeTurns
            root = self._instance_root() / "run"
            result = NativeTurns(root, read_only=True).get(native_run_id, native_session)
            return result if result is not None else {"execution_unknown": True, "error": "run_not_found"}
        except Exception as exc:  # noqa: BLE001 — reconciliation must not crash
            logger.warning("native receipt lookup failed: %s", exc)
            return {"execution_unknown": True, "error": type(exc).__name__}

    async def handle_stream_events(self, request: web.Request) -> web.StreamResponse:
        """SSE for session + global (``*``) events.

        Surfaces P8 — approval request payload on the stream::

            event: approval.request
            data: {
              "approval_id": "approval_…",
              "kind": "handoff" | "tool" | str,
              "prompt": "Allow …?",
              "options": ["once", "deny"],
              "session_id": "…" | null,
              "handoff_id": "…" | null,
              "from_agent_id": "…" | null,
              "to_agent_id": "…" | null,
              "task": "…" | null
            }

        Resolve with ``POST /v1/approvals/{approval_id}`` body
        ``{"approved": true|false}`` → emits ``approval.resolved``.
        """
        return await self._sse_stream(request, request.match_info["id"])

    def _connect_apps(self):
        if getattr(self, "_connect_apps_service", None) is None:
            from jaeger_ai.core.gateway.connect_apps import ConnectApps
            self._connect_apps_service = ConnectApps()
        return self._connect_apps_service

    async def handle_connect_apps(self, request: web.Request) -> web.Response:
        """GET /v1/connect-apps — registry + live (30 s cached, read-only) state."""
        return web.json_response(await asyncio.to_thread(self._connect_apps().listing))

    async def handle_connect_app_state(self, request: web.Request) -> web.Response:
        app_id = request.match_info["id"]
        refresh = request.query.get("refresh") in {"1", "true"}
        state = await asyncio.to_thread(self._connect_apps().state, app_id, refresh=refresh)
        if state is None:
            return web.json_response({"error": "Unknown app"}, status=404)
        return web.json_response({"id": app_id, "state": state})

    async def handle_connect_app_install(self, request: web.Request) -> web.Response:
        """POST /v1/connect-apps/{id}/install ``{"confirm": true}`` — owner callers only.

        202 then ``connect_app.updated`` {id, state, audit} on the global stream
        (the durable event row is the audit record). Fixed argv, shell=False.
        """
        from jaeger_ai.core.gateway.connect_apps import OWNER_INSTALL_CALLERS
        caller = request.get("caller")
        if getattr(caller, "name", None) not in OWNER_INSTALL_CALLERS:
            return web.json_response({"error": "Only the owner's apps may install"}, status=403)
        try:
            body = await request.json() if request.can_read_body else {}
        except Exception:
            body = {}
        if not isinstance(body, dict) or body.get("confirm") is not True:
            return web.json_response({"error": "confirm: true is required"}, status=400)
        app_id = request.match_info["id"]
        service = self._connect_apps()
        status, payload, plan = await asyncio.to_thread(service.begin_install, app_id)
        if plan is None:
            return web.json_response(payload, status=status)
        self.event_bus.publish("*", "connect_app.updated", {
            "id": app_id, "state": {"value": "installing", "checked_at": time.time()}})

        async def _run() -> None:
            result = await asyncio.to_thread(service.run_install, app_id, plan, caller=caller.name)
            logger.info("connect-apps install audit: %s", result["audit"])
            self.event_bus.publish("*", "connect_app.updated", {"id": app_id, **result})

        task = asyncio.create_task(_run())
        self._connect_install_task = task
        return web.json_response(payload, status=202)

    async def handle_global_stream(self, request: web.Request) -> web.StreamResponse:
        """GET /v1/events/stream — global (``*``) events only: agent.*, approvals,
        task.*, connect_app.updated. Same framing, resume (``last_event_id``) and
        410 rules as the session stream; session-prefixed callers (mcp/a2a) are
        refused by the scope middleware (not in PREFIXED_READ_ROUTES)."""
        return await self._sse_stream(request, "*")

    async def _sse_stream(self, request: web.Request, session_id: str) -> web.StreamResponse:
        try:
            last_event_id = int(request.query.get("last_event_id") or request.headers.get("Last-Event-ID") or 0)
        except ValueError:
            return web.json_response({"error": "last_event_id must be an integer"}, status=400)
        window = self.event_bus.replay_window(session_id, last_event_id)
        if window.get("cursor_expired"):
            return web.json_response(
                {
                    "error": "Resume cursor is no longer retained",
                    "oldest_event_id": window.get("oldest_event_id"),
                    "latest_event_id": window.get("latest_event_id"),
                    "valid_cursor": False,
                },
                status=410,
            )

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        events = self.event_bus.subscribe(session_id, since_event_id=last_event_id)
        pending = asyncio.create_task(anext(events))
        try:
            while True:
                ready, _ = await asyncio.wait({pending}, timeout=getattr(self, "_sse_keepalive_seconds", 10.0))
                if not ready:
                    # Transport-only comment: no model progress, cursor or durable state.
                    await response.write(b": keepalive\n\n")
                    continue
                evt = pending.result()
                payload = json.dumps({
                    "event_id": evt.event_id,
                    "session_id": evt.session_id,
                    "event": evt.event,
                    "data": evt.data,
                    "timestamp": evt.timestamp,
                })
                chunk = f"id: {evt.event_id}\nevent: {evt.event}\ndata: {payload}\n\n"
                await response.write(chunk.encode("utf-8"))
                pending = asyncio.create_task(anext(events))
        except (asyncio.CancelledError, ConnectionResetError, ReplayGap, StopAsyncIteration):
            pass
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await events.aclose()

        return response

    def _approval_origin(self, session_id: str | None) -> dict[str, Any] | None:
        """Where a card filed under a child session (``task:<id>`` worker,
        specialist) belongs: ``{task_id, child_session_id, agent_id,
        parent_session_id}``, or None for a top-level chat."""
        if not session_id:
            return None
        try:
            session = self.store.get_session(session_id) or {}
        except Exception:  # noqa: BLE001 — no origin is the safe answer
            return None
        meta = session.get("metadata") or {}
        parent = str(meta.get("parent_session_id") or "")
        if not parent or parent == session_id:
            return None
        return {
            "task_id": meta.get("task_id"),
            "child_session_id": session_id,
            "agent_id": session.get("agent_id") or meta.get("agent_id") or "native:jaeger",
            "parent_session_id": parent,
        }

    def _publish_approval_request(self, session_id: str, origin: dict[str, Any] | None,
                                  payload: dict[str, Any]) -> None:
        """approval.request on the card's own stream and, for a child card, on
        the parent chat's stream too (same approval_id, with ``origin``)."""
        if origin:
            payload = {**payload, "origin": origin}
        self.event_bus.publish(session_id, "approval.request", payload)
        if origin and origin.get("parent_session_id"):
            self.event_bus.publish(origin["parent_session_id"], "approval.request", payload)

    def _with_origin(self, row: dict[str, Any]) -> dict[str, Any]:
        # Old standalone handoffs predate the session binding. Read the saved
        # handoff, never request data, to recover presentation without mutation.
        if row.get("kind") == "handoff":
            handoff = self.store.get_handoff((row.get("metadata") or {}).get("handoff_id") or "")
            if handoff:
                row = {**row, "session_id": handoff.get("session_id"), "task": handoff.get("task")}
        origin = (row.get("metadata") or {}).get("origin")
        return {**row, "origin": origin} if origin else row

    async def handle_list_approvals(self, request: web.Request) -> web.Response:
        pending = [self._with_origin(row) for row in self.store.list_pending_approvals()]
        sid = (request.query.get("session_id") or "").strip()
        if sid:
            pending = [row for row in pending if row.get("session_id") == sid
                       or ((row.get("origin") or {}).get("parent_session_id") == sid)]
        request_id = (request.query.get("request_id") or "").strip()
        if request_id:
            pending = [row for row in pending if row.get("request_id") == request_id]
        return web.json_response({"approvals": pending})

    async def handle_get_approval(self, request: web.Request) -> web.Response:
        """Status of one approval. Read-only: deciding needs the approve scope.

        An outside caller (MCP, A2A) sees only approvals in its own sessions;
        any other id answers 404 so it cannot probe the owner's approvals.
        """
        approval = self.store.get_approval(request.match_info["id"])
        caller = request.get("caller")
        prefix = getattr(caller, "session_prefix", None)
        if approval is None or (prefix and not str(approval.get("session_id") or "").startswith(prefix)):
            return web.json_response({"error": "Approval not found"}, status=404)
        return web.json_response({
            key: approval.get(key)
            for key in ("approval_id", "session_id", "request_id", "kind", "prompt",
                        "options", "status", "decision", "created_at", "resolved_at")
        })

    async def handle_runtime_frameworks(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import framework_inventory
        return web.json_response({"frameworks": framework_inventory()})

    async def handle_runtime_models(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import provider_model_inventory, webui_model_catalog
        return web.json_response({
            **provider_model_inventory(),
            "webui_catalog": webui_model_catalog(),
        })

    async def handle_runtime_capabilities(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.runtime.truth import capability_snapshot
        return web.json_response(capability_snapshot())

    # ── IDE bridge: the agent asks the operator's editor to do something ──────

    _IDE_KINDS = frozenset({"context", "open_file", "diagnostics"})

    def _ide_request(self, session_id: str, request_id: str, kind: str, args: dict, timeout: float) -> dict[str, Any]:
        """Blocking; called from the agent's worker thread. Publishes ``ide.request`` on the
        session stream, which the IDE extension answers via POST .../ide/{id}."""
        import concurrent.futures

        loop = getattr(self, "_loop", None)
        if kind not in self._IDE_KINDS or loop is None or not loop.is_running():
            return self._ide_context_fallback(session_id, kind, {"ok": False, "error": "The IDE bridge is unavailable"})
        ide_request_id = uuid.uuid4().hex[:12]
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._ide_pending[ide_request_id] = (session_id, future)
        payload = {"ide_request_id": ide_request_id, "request_id": request_id, "kind": kind,
                   "args": {k: (v if isinstance(v, (int, float)) else str(v)[:500]) for k, v in (args or {}).items()}}
        loop.call_soon_threadsafe(self.event_bus.publish, session_id, "ide.request", payload)
        try:
            answer = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            answer = {"ok": False, "error": "The IDE did not answer. Is the Jaeger panel open in your editor?"}
        finally:
            self._ide_pending.pop(ide_request_id, None)
        return self._ide_context_fallback(session_id, kind, answer)

    def _ide_context_fallback(self, session_id: str, kind: str, answer: dict[str, Any]) -> dict[str, Any]:
        """``context`` answers are cleaned to the allow-listed shape; the session's
        workspace folder fills in when the IDE is absent or omits it."""
        if kind != "context":
            return answer
        folder = str((self.store.get_session(session_id) or {}).get("workspace") or "")
        if answer.get("ok") and isinstance(answer.get("result"), dict):
            from jaeger_ai.core.entity.ide_context import clean as clean_ide_context
            result = clean_ide_context(answer["result"]) or {}
            if folder and not result.get("workspace_folder"):
                result["workspace_folder"] = folder
            return {**answer, "result": result}
        if folder:
            return {"ok": True, "result": {"workspace_folder": folder, "workspace_folders": [folder]},
                    "fallback": True, "ide_error": answer.get("error")}
        return answer

    async def handle_ide_result(self, request: web.Request) -> web.Response:
        """POST /v1/sessions/{id}/ide/{ide_request_id}: the extension's answer. First one wins."""
        pending = self._ide_pending.get(request.match_info["ide_request_id"])
        if pending is None or pending[0] != request.match_info["id"]:
            return web.json_response({"error": "No such pending IDE request"}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Body must be an object"}, status=400)
        answer = {"ok": bool(body.get("ok")), **({"result": body["result"]} if body.get("ok") else {"error": str(body.get("error") or "IDE request failed")[:300]})}
        if not pending[1].done():
            pending[1].set_result(answer)
        return web.json_response({"delivered": True})

    def _config_path(self) -> Path | None:
        from jaeger_ai.core.entity.runtime import EntityRuntime

        layout = getattr(EntityRuntime.get_singleton(), "layout", None)
        return getattr(layout, "config_path", None)

    async def handle_get_autonomy(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/autonomy: how much the agent asks before acting (saved setting)."""
        from jaeger_ai.core.runtime.autonomy import AUTONOMY, effective_autonomy

        return web.json_response({"autonomy": effective_autonomy(self._config_path()), "options": list(AUTONOMY)})

    async def handle_set_autonomy(self, request: web.Request) -> web.Response:
        """POST /v1/runtime/autonomy ``{"autonomy": "auto|scoped|ask"}``: saved to the
        instance config, which the approval provider reads on every tool call."""
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
        from jaeger_ai.core.runtime.autonomy import AUTONOMY

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        mode = str((body or {}).get("autonomy") or "").strip().lower() if isinstance(body, dict) else ""
        if mode not in AUTONOMY:
            return web.json_response({"error": f"autonomy must be one of {list(AUTONOMY)}"}, status=400)
        path = self._config_path()
        if path is None or not Path(path).is_file():
            return web.json_response({"error": "No instance config to save to"}, status=409)
        config = load_yaml(Path(path), Config)
        config.automation.autonomy = mode
        dump_yaml(Path(path), config)
        return web.json_response({"autonomy": mode, "options": list(AUTONOMY)})

    def _current_tier(self) -> str:
        """Return the active interaction tier ('chat', 'agent', 'jaeger')."""
        path = self._config_path()
        if path is not None and Path(path).is_file():
            try:
                from jaeger_ai.contract.modes import INTERACTION_TIERS
                from jaeger_ai.core.instance.schemas import Config, load_yaml

                cfg = load_yaml(Path(path), Config)
                tier = getattr(cfg.automation, "interaction_tier", "agent")
                if tier in INTERACTION_TIERS:
                    return tier
            except Exception:
                pass
        return "agent"

    async def handle_get_tier(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/tier: active agency tier ('chat' | 'agent' | 'jaeger')."""
        from jaeger_ai.contract.modes import INTERACTION_TIERS, TIER_DESCRIPTIONS

        tier = self._current_tier()
        return web.json_response({
            "tier": tier,
            "options": list(INTERACTION_TIERS),
            "descriptions": dict(TIER_DESCRIPTIONS),
        })

    async def handle_set_tier(self, request: web.Request) -> web.Response:
        """POST /v1/runtime/tier ``{"tier": "chat"|"agent"|"jaeger"}``: save agency tier."""
        from jaeger_ai.contract.modes import INTERACTION_TIERS
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        tier = str((body or {}).get("tier") or "").strip().lower() if isinstance(body, dict) else ""
        if tier not in INTERACTION_TIERS:
            return web.json_response({"error": f"tier must be one of {list(INTERACTION_TIERS)}"}, status=400)
        path = self._config_path()
        if path is None or not Path(path).is_file():
            return web.json_response({"error": "No instance config to save to"}, status=409)
        config = load_yaml(Path(path), Config)
        config.automation.interaction_tier = tier
        dump_yaml(Path(path), config)
        self.event_bus.publish("*", "runtime.tier.changed", {"tier": tier})
        return web.json_response({"tier": tier, "options": list(INTERACTION_TIERS)})

    async def handle_channels(self, request: web.Request) -> web.Response:
        from jaeger_ai.features.channels.status import snapshot
        return web.json_response(snapshot(self.store))

    async def handle_runtime_diagnostics(self, request: web.Request) -> web.Response:
        return web.json_response({**self.store.diagnostics_snapshot(), 'process_id': os.getpid(),
                                  'server_module_sha256': _GATEWAY_MODULE_SHA256,
                                  'fingerprint_scope': 'server.py bytes captured at module import',
                                  'observed_at': time.time(), 'read_only': True})

    async def handle_runtime_tools(self, request: web.Request) -> web.Response:
        from jaeger_ai.core.gateway.tool_inventory import collect
        query = str(request.query.get('q') or '').strip()
        if len(query) > 200:
            return web.json_response({'error': 'Tool query must be at most 200 characters'}, status=400)
        return web.json_response(collect(query))

    async def handle_runtime_skills(self, request: web.Request) -> web.Response:
        """GET /v1/runtime/skills[?q=text] — the skills a client can offer, one row each.

        Read-only. Rows carry name, category, description and lifecycle, never the
        skill body or its path, so a client menu can list them safely.
        """
        from jaeger_agent.skill_registry.playbook_skills import discover_playbooks

        query = str(request.query.get("q") or "").strip().lower()
        rows = [
            {"name": s.name, "category": s.category, "description": s.description[:300],
             "lifecycle": s.lifecycle}
            for s in discover_playbooks()
            if not query or query in s.name.lower() or query in s.description.lower()
        ]
        return web.json_response({"skills": rows, "count": len(rows)})

    async def handle_runtime_skill_detail(self, request: web.Request) -> web.Response:
        """Inspect registry provenance/requirements only; never load toolsets or scripts."""
        from jaeger_agent.skill_registry.playbook_skills import discover_playbooks
        from jaeger_ai.core.redaction import redact_text
        name, category = request.query.get('name', ''), request.query.get('category', '')
        if not name or not category or len(name) > 200 or len(category) > 200:
            return web.json_response({'error': 'Exact skill name and category required'}, status=400)
        matches = [s for s in discover_playbooks() if s.name == name and s.category == category]
        if len(matches) != 1:
            return web.json_response({'error': 'Skill not found or registry identity ambiguous'}, status=404 if not matches else 409)
        skill = matches[0]
        clean = lambda values: [redact_text(str(value))[:300] for value in values[:100]]
        return web.json_response({'name': skill.name, 'category': skill.category,
            'description': redact_text(skill.description)[:2000], 'origin': skill.origin,
            'lifecycle': skill.lifecycle, 'skill_class': skill.skill_class,
            'platforms': clean(skill.platforms), 'requires_tools': clean(skill.requires_tools),
            'optional_tools': clean(skill.optional_tools), 'requires_toolsets': clean(skill.requires_toolsets),
            'requires_plugins': clean(skill.requires_plugins), 'aliases': clean(skill.aliases),
            'tags': clean(skill.tags), 'auto_activate': bool(skill.auto_activate), 'tier': skill.tier,
            'scope': 'discovered_registry_metadata', 'execution_authorized': False,
            'availability': 'not_probed', 'origin_verified': False})

    async def handle_session_files(self, request: web.Request) -> web.Response:
        session_id = request.match_info['id']
        session = self.store.get_session(session_id)
        if session is None:
            return web.json_response({'error': 'Session not found'}, status=404)
        from .attachment_access import resolve
        rows = []
        for row in self.store.list_attachments(session_id):
            reason = None
            try:
                resolve(row, staged_root=self._staged_upload_dir(session_id), workspace=session.get('workspace') or '')
                if row['size_bytes'] > self.UPLOAD_MAX_BYTES:
                    reason = 'Attachment exceeds supported read size'
            except ValueError as exc:
                reason = str(exc)
            rows.append({**self._upload_view(row), 'readable': reason is None, 'unavailable_reason': reason})
        return web.json_response({'session_id': session_id, 'files': rows, 'max_bytes': self.UPLOAD_MAX_BYTES})

    async def handle_session_file(self, request: web.Request) -> web.Response:
        session_id = request.match_info['id']
        session = self.store.get_session(session_id)
        rows = self.store.list_attachments(session_id) if session else []
        row = next((r for r in rows if r['attachment_id'] == request.match_info['attachment_id']), None)
        if row is None:
            return web.json_response({'error': 'Session attachment not found'}, status=404)
        from .attachment_access import read
        try:
            result = await asyncio.to_thread(read, row, staged_root=self._staged_upload_dir(session_id),
                workspace=session.get('workspace') or '', limit=self.UPLOAD_MAX_BYTES)
        except (OSError, ValueError):
            return web.json_response({'error': 'Attachment missing, changed, or outside its originating workspace; bytes withheld'}, status=409)
        return web.json_response({'session_id': session_id, **result})

    async def handle_list_attachments(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        if self.store.get_session(session_id) is None:
            return web.json_response({"error": "Session not found"}, status=404)
        return web.json_response({"attachments": self.store.list_attachments(session_id)})

    async def handle_add_attachment(self, request: web.Request) -> web.Response:
        session_id = request.match_info["id"]
        session = self.store.get_session(session_id)
        if session is None:
            return web.json_response({"error": "Session not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        path = Path(str(body.get("safe_path") or body.get("path") or ""))
        try:
            from jaeger_ai.core.entity.runtime import EntityRuntime
            from jaeger_ai.core.instance.instance import InstanceLayout
            rt_layout = getattr(EntityRuntime.get_singleton(), "layout", None)
            if rt_layout is not None:
                root = rt_layout.workspace_dir.resolve()
            else:
                from jaeger_ai.core.instance.instance import resolve_instance_dir
                root = InstanceLayout(root=resolve_instance_dir()).workspace_dir.resolve()
            resolved = path.resolve()
            session_ws = Path(session["workspace"]).resolve() if session.get("workspace") else None
            valid = resolved.is_relative_to(root) or (session_ws and resolved.is_relative_to(session_ws))
            if not valid:
                return web.json_response({"error": "attachment path escapes workspace"}, status=400)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=400)
        # The Gateway receives a workspace file reference, not verified client
        # metadata. Freeze the bytes' actual size/hash here for every surface.
        def file_metadata():
            import hashlib

            if not resolved.is_file():
                raise ValueError("attachment must reference an existing regular file")
            digest = hashlib.sha256()
            size = 0
            with resolved.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            return {"safe_path": str(resolved), "size_bytes": size, "sha256": digest.hexdigest()}

        try:
            metadata = await asyncio.to_thread(file_metadata)
        except (OSError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        row = self.store.add_attachment(session_id, {**body, **metadata})
        self.event_bus.publish(session_id, "attachment.added", {"attachment": row})
        return web.json_response(row, status=201)

    async def handle_resolve_approval(self, request: web.Request) -> web.Response:
        """Resolve a pending approval. First writer wins; denial prevents effects."""
        approval_id = request.match_info["id"]
        body = await request.json() if request.can_read_body else {}
        approved = bool(body.get("approved", True))
        decision = str(body.get("decision") or body.get("choice") or ("once" if approved else "deny"))
        if decision not in {"once", "session", "deny", "always", "allow", "yes"}:
            return web.json_response({"error": "Unsupported approval decision"}, status=400)
        approved = decision != "deny"

        if getattr(request, "path", "").endswith("/decision") and not all(
                body.get(key) for key in ("expected_session_id", "expected_request_id", "expected_profile")):
            return web.json_response({"error": "Scoped approval context is required"}, status=400)
        for key in ("expected_session_id", "expected_request_id", "expected_profile"):
            if key in body and (not isinstance(body[key], str) or not body[key].strip()):
                return web.json_response({"error": "Invalid approval context"}, status=400)
        resolved = self.store.resolve_approval(
            approval_id, approved=approved, decision=decision,
            **{key: body[key] for key in ("expected_session_id", "expected_request_id", "expected_profile") if key in body},
        )
        if resolved is None:
            existing = self.store.get_approval(approval_id) or {}
            if existing.get("decision") == "cancelled":
                return web.json_response(
                    {"error": "Request was cancelled; approval no longer applies"}, status=409,
                )
            return web.json_response({"error": "Approval is stale, expired, or its permission context changed"}, status=409 if existing else 404)
        future = self.pending_approvals.pop(approval_id, None)
        if future is not None and not future.done():
            future.set_result(approved)

        handoff_row = None
        if resolved is not None and (resolved.get("metadata") or {}).get("task_id"):
            self.task_owner.resolve(resolved["metadata"]["task_id"], approved)
        if resolved is not None:
            hid = (resolved.get("metadata") or {}).get("handoff_id")
            if hid:
                handoff_row = self.store.get_handoff(str(hid))
            if handoff_row is None:
                for item in self.store.list_handoffs():
                    if item.get("approval_id") == approval_id:
                        handoff_row = item
                        break
            if handoff_row is not None:
                if approved:
                    handoff_row = self.store.save_handoff({**handoff_row, "status": "approved"})
                    rid = handoff_row.get("request_id") or handoff_row["id"]
                    if rid not in self._running_tasks:
                        self._running_tasks[rid] = asyncio.create_task(
                            self._execute_handoff(handoff_row["id"])
                        )
                else:
                    handoff_row = self.store.save_handoff({
                        **handoff_row,
                        "status": "denied",
                        "result": {"ok": False, "status": "denied", "summary": "Handoff denied by operator."},
                    })

        payload = {
            "approval_id": approval_id,
            "resolved": True,
            "approved": approved,
            "decision": decision,
            "handoff": handoff_row,
        }
        row_origin = ((resolved or {}).get("metadata") or {}).get("origin")
        if resolved is not None:
            payload["session_id"] = resolved.get("session_id")
        if row_origin:
            payload["origin"] = row_origin
        self.event_bus.publish("*", "approval.resolved", payload)
        return web.json_response(payload)

    async def _execute_handoff(self, handoff_id: str) -> None:
        record = self.store.get_handoff(handoff_id)
        if record is None:
            return
        if record["status"] not in {"admitted", "approved"}:
            return
        try:
            self.store.save_handoff({**record, "status": "running"})
            from jaeger_agent.cognition.runs import InMemoryRunStore
            from jaeger_agent.delegates.contracts import DelegateRequest
            from jaeger_agent.delegates.executor import DelegateExecutor, DelegateExecutionError
            from jaeger_agent.delegates.registry import DelegateRegistry
            from jaeger_ai.core.agent_registry.specialist_runtime import (
                NativeSpecialistRuntime, bounded_prompt, DEFAULT_TIMEOUT_S,
            )

            meta = dict(record.get("metadata") or {})
            registry = self._registry()
            target = registry.get_agent(record["to_agent_id"])
            display = getattr(target, "display_name", None) or record["to_agent_id"]
            specialty = meta.get("specialty") or (getattr(target, "metadata", None) or {}).get("specialty") or display
            allowed = meta.get("allowed_tools") or []
            prompt = bounded_prompt(
                display_name=str(display),
                specialty=str(specialty),
                task=record["task"],
                permitted_context=str(meta.get("permitted_context") or ""),
                allowed_tools=frozenset(str(x) for x in allowed) if allowed else None,
                workspace=meta.get("workspace") or None,
                project_name=meta.get("project_name") or None,
            )
            timeout = int(meta.get("timeout_seconds") or DEFAULT_TIMEOUT_S)
            runs = InMemoryRunStore()
            child = runs.create(
                f"handoff:{record['id']}",
                owner_pid=os.getpid(),
                payload={"handoff_id": record["id"], "to_agent_id": record["to_agent_id"]},
                parent_run_id=None,
                relation="delegate",
            )
            self.store.save_handoff({**record, "status": "running", "child_run_id": child.id})
            self._post_handoff_request(record)
            runtime = NativeSpecialistRuntime(self._specialist_chat)
            delegates = DelegateRegistry()
            delegates.register(runtime, replace=True)
            executor = DelegateExecutor(delegates, runs)
            request = DelegateRequest(
                task_id=child.id,
                prompt=prompt,
                parent_task_id=str(record.get("parent_run_id") or "") or None,
                timeout_seconds=max(1, timeout),
                idempotency_key=str(record.get("request_id") or record["id"]),
                allowed_tools=frozenset(str(x) for x in allowed),
                metadata={
                    "to_agent_id": record["to_agent_id"],
                    "handoff_id": record["id"],
                    "from_agent_id": record["from_agent_id"],
                    "max_child_timeout_s": int(meta.get("max_child_timeout_s") or 1800),
                    "chat_kwargs": {
                        "workspace": meta.get("workspace") or None,
                        "agent_id": record["to_agent_id"],
                        "project_id": meta.get("project_id") or None,
                        "parent_session_id": record.get("session_id"),
                        "handoff_id": record["id"],
                    },
                },
            )
            result = await executor.execute(runtime.runtime_id, request)
            status = "execution_unknown" if result.metadata.get("execution_unknown") else result.status
            if (self.store.get_handoff(handoff_id) or {}).get("status") == "cancelled":
                status = "cancelled"
            ok = status == "completed"
            saved = self.store.save_handoff({
                **record,
                "status": status,
                "child_run_id": child.id,
                "result": {
                    "ok": ok,
                    "status": result.status,
                    "summary": result.summary,
                    "evidence": list(result.evidence),
                    "metadata": dict(result.metadata),
                    "worker_session_id": result.worker_session_id,
                },
            })
            self._publish_handoff("agent.handoff.finished", saved)
        except Exception as exc:  # noqa: BLE001 — specialist failure must not kill the gateway
            logger.exception("specialist handoff failed: %s", exc)
            saved = self.store.save_handoff({
                **record,
                "status": "failed",
                "result": {"ok": False, "status": "failed", "summary": f"{type(exc).__name__}: {exc}"},
            })
            self._publish_handoff("agent.handoff.finished", saved)
        finally:
            self._running_tasks.pop(record.get("request_id") or handoff_id, None)

    async def _specialist_chat(self, session_id: str, text: str, *, request_id: str,
                               allowed_tools: list[str] | None = None,
                               workspace: str | None = None, agent_id: str | None = None,
                               project_id: str | None = None, parent_session_id: str | None = None,
                               handoff_id: str | None = None) -> tuple[str, str]:
        """Run a handoff child as a real Gateway turn in this process.

        It used to relay to the native MCP server on :8792, which is a
        different process (on a test gateway, the live one). The child is now
        an admitted request on its own session, executed by the same
        ``_execute_turn`` path as a chat turn: the specialist's standing tools
        (``allowed_tools=None``) or the granted subset, its own skills, its
        notes, the project root as the bound workspace, approvals parked on
        that child turn, and a durable receipt in client_requests."""
        import hashlib
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_agent

        child_rid = hashlib.sha256(("handoff:" + request_id).encode()).hexdigest()[:32]
        meta = {
            "agent_id": agent_id or specialist_agent(session_id), "agent_pinned": True,
            "route_checked": True, "handoff_child": True, "handoff_id": handoff_id,
            "parent_session_id": parent_session_id, "project_id": project_id,
        }
        self.store.ensure_session(
            session_id, title=f"Handoff {handoff_id}" if handoff_id else "Specialist task",
            profile="jaeger", workspace=workspace or "",
            metadata={k: v for k, v in meta.items() if v is not None},
        )
        requested: dict[str, Any] = {"interaction_tier": self._current_tier(), "is_subordinate": True}
        # Approved handoffs execute later, often in an owner's HTTP context.
        # Identity comes from durable admission, never from that later context.
        handoff = self.store.get_handoff(handoff_id) if handoff_id else None
        if handoff is not None:
            requested["caller"] = (handoff.get("metadata") or {}).get("caller_actor")
        if allowed_tools is not None:
            requested["allowed_tools"] = list(allowed_tools)
        if workspace:
            requested["workspace"] = workspace
        admitted = self.store.admit_request(session_id, text, request_id=child_rid, requested=requested)
        self._start_admitted_turn(admitted, session_id, text)
        rid = admitted["request_id"]
        task = self._running_tasks.get(rid)
        if task is not None:
            await task
        row = self.store.get_request(rid) or {}
        result = row.get("result") or {}
        if row.get("status") != "completed":
            raise RuntimeError(f"specialist turn {row.get('status')}: {result.get('error') or 'no result'}")
        return str(result.get("output") or ""), f"{result.get('backend') or 'owner-react'}:{result.get('model') or ''}"

    # ── Projects ─────────────────────────────────────────────────────────

    def _project_for_session(self, session_id: str) -> dict[str, Any] | None:
        meta = (self.store.get_session(session_id) or {}).get("metadata") or {}
        pid = meta.get("project_id")
        return self.projects.get(pid) if pid else None

    _PROJECT_SHELL_TOOLS = frozenset({"terminal", "run_shell", "exec_command"})
    _PROJECT_WRITE_TOOLS = frozenset({"write_file", "file_write", "append_file", "patch", "edit_file",
                                      "move_file", "copy_file", "make_directory", "mkdir"})
    _PROJECT_PATH_KEYS = ("path", "file_path", "dest", "destination", "src", "source", "target", "new_path")

    def _project_grant_allows(self, session_id: str, request: Any) -> bool:
        """Owner's project grant: writes and listed commands inside the root.

        Only consulted after grants/autonomy said "ask", and never for a
        PolicyKernel forced prompt. Every allowed call is still executed
        through the ledger and logged here."""
        project = self._project_for_session(session_id)
        if not project:
            return False
        from jaeger_ai.core.agent_registry.projects import command_allowed, path_in_project
        names = {str(getattr(request, "skill", "") or ""), str(getattr(request, "operation", "") or "")}
        args = getattr(request, "arguments", None) or {}
        grants = project.get("grants") or {}
        allowed, why = False, ""
        if names & self._PROJECT_SHELL_TOOLS:
            cmd = str(args.get("command") or args.get("cmd") or "")
            workdir = args.get("workdir")
            if workdir and not path_in_project(project, str(workdir)):
                allowed, why = False, "workdir outside project"
            else:
                allowed, why = command_allowed(project, cmd)
        elif names & self._PROJECT_WRITE_TOOLS and grants.get("writes"):
            paths = [str(args[k]) for k in self._PROJECT_PATH_KEYS if args.get(k)]
            allowed = bool(paths) and all(path_in_project(project, p) for p in paths)
            why = "write inside project root" if allowed else "path outside project root"
        elif "run_build_check" in names:
            root = str(args.get("root") or project["root"])
            allowed, why = path_in_project(project, root), "build check inside project root"
        if allowed:
            logger.info("project grant %s allowed %s %s (%s)", project["id"], sorted(n for n in names if n),
                        _approval_target(request), why)
        return allowed

    async def handle_list_projects(self, request: web.Request) -> web.Response:
        return web.json_response({"projects": self.projects.list()})

    async def handle_get_project(self, request: web.Request) -> web.Response:
        project = self.projects.get(request.match_info["id"])
        if project is None:
            return web.json_response({"error": "Project not found"}, status=404)
        return web.json_response(project)

    async def handle_create_project(self, request: web.Request) -> web.Response:
        """POST /v1/projects {name, root, team?, grants?, limits?, bind_session_id?}."""
        from jaeger_ai.core.agent_registry.projects import ProjectError
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Body must be JSON"}, status=400)
        known = {a.id for a in self._registry().list_agents()}
        try:
            project = self.projects.create(
                name=body.get("name"), root=body.get("root"), team=body.get("team"),
                grants=body.get("grants"), limits=body.get("limits"), known_agents=known,
            )
        except (ProjectError, TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        bind = str(body.get("bind_session_id") or "").strip()
        if bind:
            if self.store.get_session(bind) is None:
                return web.json_response({"error": "bind_session_id not found", "project": project}, status=404)
            self.store.update_metadata(bind, {"project_id": project["id"], "workspace": project["root"]})
        self.event_bus.publish("*", "project.created", {"project": project, "bound_session_id": bind or None})
        return web.json_response(project, status=201)

    async def handle_project_check(self, request: web.Request) -> web.Response:
        """POST /v1/projects/{id}/check {commands?, expect_files?, timeout_s?} — the
        build/test checker, run by the Gateway itself so a pass is recorded."""
        project = self.projects.get(request.match_info["id"])
        if project is None:
            return web.json_response({"error": "Project not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        commands = body.get("commands") or ["npm test"]
        files = body.get("expect_files") or []
        if not isinstance(commands, list) or not isinstance(files, list):
            return web.json_response({"error": "commands and expect_files must be lists"}, status=400)
        from jaeger_agent.tools.build_check import check_project
        result = await asyncio.to_thread(check_project, project["root"], [str(c) for c in commands],
                                         [str(f) for f in files], float(body.get("timeout_s") or 300))
        result["project_id"] = project["id"]
        result["checked_at"] = time.time()
        self.event_bus.publish("*", "project.checked", {"project_id": project["id"], "result": result})
        return web.json_response(result)

    def _task_board_fields(self, body: dict[str, Any]) -> dict[str, Any]:
        """Validate the Tasks-board fields of a task submission (raises ValueError)."""
        out: dict[str, Any] = {}
        registry = None
        if body.get('agent_id'):
            registry = self._registry()
            agent_id = str(body['agent_id']).strip()
            if registry.get_agent(agent_id) is None:
                raise ValueError(f'Unknown agent_id {agent_id!r}')
            out['agent_id'] = agent_id
        if body.get('eta'):
            from datetime import datetime
            eta = str(body['eta']).strip()
            try:
                parsed = datetime.fromisoformat(eta)
            except ValueError as exc:
                raise ValueError('eta must be ISO 8601') from exc
            if parsed.tzinfo is None:
                raise ValueError('eta must carry a UTC offset')
            out['eta'] = eta
        if body.get('runner'):
            runner = str(body['runner']).strip()
            if runner != 'native':
                target = runner[len('delegate:'):] if runner.startswith('delegate:') else ''
                registry = registry or self._registry()
                if not target or registry.get_agent(target) is None:
                    raise ValueError("runner must be 'native' or 'delegate:<agent id>'")
            out['runner'] = runner
        return out

    async def handle_task_submission(self, request: web.Request) -> web.Response:
        session_id = str(request.query.get('session_id') or '')
        request_id = request.match_info['request_id']
        if not session_id or self.store.get_session(session_id) is None:
            return web.json_response({'error': 'Existing originating session required'}, status=404)
        return web.json_response({'session_id': session_id, 'request_id': request_id,
            'tasks': [task.to_dict() for task in self.task_owner.store.client_submissions(session_id, request_id)]})

    async def handle_tasks(self, request: web.Request) -> web.Response:
        if request.method == 'GET':
            tasks = [t.to_dict() for t in self.task_owner.store.list_tasks()]
            agent_filter = request.query.get('agent_id')
            if agent_filter:
                tasks = [t for t in tasks if t.get('agent_id') == agent_filter]
            return web.json_response({'tasks': tasks})
        tier = self._current_tier()
        if tier == "chat":
            return web.json_response({'error': 'Task submission is disabled in Chat mode'}, status=403)
        body = await request.json()
        parent = self.store.get_session(str(body.get('session_id') or ''))
        if parent is None:
            return web.json_response({'error': 'Existing session_id required'}, status=400)
        execution = dict(body.get('execution') or {})
        execution.setdefault('workspace', parent.get('workspace') or '')
        execution['caller'] = request.get('caller_actor')
        try:
            submission_id = body.get('request_id')
            if submission_id is not None and (not isinstance(submission_id, str) or not submission_id.strip() or len(submission_id) > 128):
                raise ValueError('request_id must be nonempty text of at most128 characters')
            board = self._task_board_fields(body)
            board.setdefault('agent_id', self._session_agent_id(parent))
            result = self.task_owner.submit(str(body.get('goal') or ''),
                context={'session_id': parent['session_id'], 'source': 'client', 'execution': execution,
                         'request_id': submission_id, 'client_submission_id': submission_id, **board},
                artifacts=body.get('artifacts'), proposal=bool(body.get('proposal')))
        except ValueError as exc:
            from jaeger_ai.core.tasks.store import TaskConflict
            return web.json_response({'error': str(exc)}, status=409 if isinstance(exc, TaskConflict) else 400)
        return web.json_response({**result, 'request_id': submission_id, 'origin_session_id': parent['session_id']}, status=200 if result['replayed'] else 201)

    async def handle_task(self, request: web.Request) -> web.Response:
        task = self.task_owner.store.get_task(request.match_info['id'])
        return web.json_response(task.to_dict() if task else {'error': 'Task not found'}, status=200 if task else 404)

    async def handle_task_edit(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            task = self.task_owner.edit_proposal(request.match_info["id"],
                goal=str(body.get("goal") or ""), expected_updated_at=float(body["expected_updated_at"]))
            return web.json_response(task)
        except KeyError:
            return web.json_response({"error": "Task or version not found"}, status=404)
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=409)

    async def handle_task_approve(self, request: web.Request) -> web.Response:
        task_id = request.match_info['id']
        task = self.task_owner.store.get_task(task_id)
        if task is None:
            return web.json_response({'error': 'Task not found'}, status=404)
        if task.is_terminal:
            return web.json_response({'error': 'Terminal task cannot be approved', 'task_id': task_id, 'status': task.state.value}, status=409)
        if task.provenance.get('authorized'):
            return web.json_response({'task_id': task_id, 'status': task.state.value})
        if request.can_read_body:
            body = await request.json()
            if "expected_updated_at" in body and body["expected_updated_at"] != task.updated_at:
                return web.json_response({"error": "Task changed; refresh before approving"}, status=409)
        self.task_owner.resolve(task_id, True)
        for approval in self.store.list_pending_approvals():
            if (approval.get('metadata') or {}).get('task_id') == task_id:
                self.store.resolve_approval(approval['approval_id'], approved=True, decision='once')
        current = self.task_owner.store.get_task(task_id)
        return web.json_response({'task_id': task_id, 'status': current.state.value})

    async def handle_task_cancel(self, request: web.Request) -> web.Response:
        cancelled = await self.task_owner.cancel(request.match_info['id'])
        return web.json_response({'cancelled': cancelled}, status=200 if cancelled else 404)

    async def handle_list_orchestration_workers(self, request: web.Request) -> web.Response:
        """List registered IDE orchestration workers and their availability."""
        if self.orchestration is None:
            return web.json_response({"workers": []})
        workers = await self.orchestration.list_workers()
        return web.json_response({"workers": workers})

    async def handle_create_orchestration_task(self, request: web.Request) -> web.Response:
        """Validate and reserve a worker request before acknowledging admission."""
        tier = self._current_tier()
        if tier == "chat":
            return web.json_response({"error": "Orchestration tasks are disabled in Chat mode"}, status=403)
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)

        from jaeger_ai.features.ide_orchestration.contracts import (
            ParentTask,
            TaskBudget,
        )
        from jaeger_ai.features.ide_orchestration.service import (
            DuplicateSubmissionConflict,
            WorkerUnavailableError,
        )

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise TypeError("Request body must be an object")
            for field in ("task_id", "goal", "worker"):
                if not isinstance(body.get(field), str) or not body[field].strip():
                    raise ValueError(f"{field} must be a nonempty string")
            task_id = body["task_id"].strip()
            key = body.get("idempotency_key", task_id)
            if not isinstance(key, str) or not key.strip():
                raise ValueError("idempotency_key must be a nonempty string")
            read_only = body.get("read_only", True)
            if not isinstance(read_only, bool):
                raise TypeError("read_only must be a boolean")
            if not read_only:
                return web.json_response(
                    {
                        "error": (
                            "Writable IDE orchestration requires a server-owned "
                            "authorization and verification plan"
                        )
                    },
                    status=403,
                )
            metadata = body.get("metadata", {})
            if not isinstance(metadata, dict):
                raise TypeError("metadata must be an object")
            capabilities = body.get("required_capabilities", [])
            if not isinstance(capabilities, list) or any(
                not isinstance(value, str) or not value.strip() for value in capabilities
            ):
                raise ValueError("required_capabilities must be a list of nonempty strings")
            workspace = body.get("workspace")
            if workspace is not None and (not isinstance(workspace, str) or not workspace):
                raise ValueError("workspace must be an absolute path or null")
            budget_raw = body.get("budget", {})
            if not isinstance(budget_raw, dict):
                raise TypeError("budget must be an object")
            for field in ("max_seconds", "max_cost_usd"):
                value = budget_raw.get(field, 300.0 if field == "max_seconds" else 0.0)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError(f"{field} must be numeric")
            turns = budget_raw.get("max_turns", 1)
            if isinstance(turns, bool) or not isinstance(turns, int):
                raise TypeError("max_turns must be an integer")
            parent_task = ParentTask(
                task_id=task_id,
                goal=body["goal"].strip(),
                assigned_worker=body["worker"].strip(),
                idempotency_key=key.strip(),
                workspace=Path(workspace) if workspace is not None else None,
                read_only=read_only,
                budget=TaskBudget(
                    max_seconds=float(budget_raw.get("max_seconds", 300.0)),
                    max_turns=turns,
                    max_cost_usd=float(budget_raw.get("max_cost_usd", 0.0)),
                ),
                metadata=metadata,
                required_capabilities=frozenset(capabilities),
            )
            raw_artifacts = body.get("artifacts") or []
            if not isinstance(raw_artifacts, list) or any(not isinstance(a, str) or not a.strip() for a in raw_artifacts):
                raise TypeError("artifacts must be a list of nonempty strings")
            # Declared deliverables are what the task owner can verify. Resolve them
            # first so a bad path never leaves a dispatched worker without a card.
            self.task_owner.artifact_paths(str(workspace or ""), raw_artifacts)
            operation, replayed = self.orchestration.admit_parent_task(parent_task)
        except DuplicateSubmissionConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except WorkerUnavailableError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except (ValueError, TypeError, OverflowError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

        if not replayed:
            # Reuse the Gateway's existing shutdown/cancellation tracking. There
            # is no untracked fire-and-forget task or guessed queued response.
            operation_key = ("orchestration", task_id)
            self._running_tasks[operation_key] = operation

            def completed(done: asyncio.Task) -> None:
                if self._running_tasks.get(operation_key) is done:
                    self._running_tasks.pop(operation_key, None)
                if not done.cancelled() and done.exception() is not None:
                    logger.error("Orchestration task %s failed: %s", task_id, done.exception())

            operation.add_done_callback(completed)
            # The worker's own "completed" is a transport status. The task owner holds
            # the card and settles it from evidence it can check.
            try:
                self.task_owner.open_dispatch(
                    orchestration_id=task_id, goal=body["goal"].strip(), worker=body["worker"].strip(),
                    workspace=str(workspace or ""), artifacts=raw_artifacts,
                    session_id=str(body.get("session_id") or ""),
                )
                operation.add_done_callback(lambda done, oid=task_id: self._settle_dispatch(oid, done))
            except Exception:
                logger.exception("could not open a task card for orchestration task %s", task_id)
        return web.json_response(
            self.orchestration.get_task(task_id), status=200 if replayed else 201,
        )

    async def handle_get_orchestration_task(self, request: web.Request) -> web.Response:
        """Get the current process-local worker task, progress and result."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        task_id = request.match_info["id"]
        task = self.orchestration.get_task(task_id)
        if task is None:
            return web.json_response({"error": f"Task {task_id} not found"}, status=404)
        card = self.task_owner.store.get_task(f"orch:{task_id}")
        # ``state`` is the worker's own status. ``task_state`` is the owner's verdict.
        return web.json_response({**task, "task_state": card.state.value if card else None,
                                  "task_id_owner": card.task_id if card else None})

    async def handle_cancel_orchestration_task(self, request: web.Request) -> web.Response:
        """Cancel an in-flight orchestration task."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        task_id = request.match_info["id"]
        cancelled = await self.orchestration.cancel_task(task_id)
        return web.json_response({"cancelled": cancelled, "task_id": task_id})

    async def handle_follow_up_orchestration_task(self, request: web.Request) -> web.Response:
        """Continue a completed worker task in its existing conversation."""
        if self.orchestration is None:
            return web.json_response({"error": "IDE orchestration service unavailable"}, status=503)
        from jaeger_ai.features.ide_orchestration.contracts import ParentTask, TaskBudget
        from jaeger_ai.features.ide_orchestration.service import (
            DuplicateSubmissionConflict,
            WorkerUnavailableError,
        )
        parent_id = request.match_info["id"]
        parent = self.orchestration.get_task(parent_id)
        if parent is None:
            return web.json_response({"error": f"Task {parent_id} not found"}, status=404)
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("task_id"), str):
                raise ValueError("task_id must be a nonempty string")
            goal = body.get("goal")
            if not isinstance(goal, str) or not goal.strip():
                raise ValueError("goal must be a nonempty string")
            task_id = body["task_id"].strip()
            key = body.get("idempotency_key", task_id)
            if not isinstance(key, str) or not key.strip():
                raise ValueError("idempotency_key must be a nonempty string")
            task = ParentTask(
                task_id=task_id,
                goal=goal.strip(),
                assigned_worker=str(parent["worker"]),
                idempotency_key=key.strip(),
                read_only=bool(parent.get("read_only", True)),
                budget=TaskBudget(max_seconds=float(body.get("max_seconds", 300.0))),
                metadata={"parent_task_id": parent_id},
            )
            operation, replayed = self.orchestration.admit_follow_up(parent_id, task)
        except DuplicateSubmissionConflict as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except WorkerUnavailableError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        except (ValueError, TypeError, OverflowError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        if not replayed:
            operation_key = ("orchestration", task_id)
            self._running_tasks[operation_key] = operation
            operation.add_done_callback(
                lambda done: self._running_tasks.pop(operation_key, None)
                if self._running_tasks.get(operation_key) is done else None
            )
            try:
                self.task_owner.open_dispatch(
                    orchestration_id=task_id, goal=goal.strip(), worker=str(parent["worker"]),
                    session_id=str(body.get("session_id") or ""),
                )
                operation.add_done_callback(lambda done, oid=task_id: self._settle_dispatch(oid, done))
            except Exception:
                logger.exception("could not open a task card for follow-up task %s", task_id)
        return web.json_response(
            self.orchestration.get_task(task_id), status=200 if replayed else 201
        )


def create_gateway_server(
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
    store: GatewaySessionStore | None = None,
    orchestration: Any | None = None,
) -> tuple[JaegerGatewayApp, web.AppRunner]:
    gateway = JaegerGatewayApp(store=store, orchestration=orchestration)
    runner = web.AppRunner(gateway.app)
    return gateway, runner


async def run_gateway_forever(
    host: str = DEFAULT_GATEWAY_HOST,
    port: int = DEFAULT_GATEWAY_PORT,
) -> None:
    gateway, runner = create_gateway_server(host, port)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    global _BOUND_GATEWAY_PORT
    _BOUND_GATEWAY_PORT = int(port)
    print(f"[jaeger-gateway] Listening on http://{host}:{port}", flush=True)
    if getattr(gateway, "_pending_recovery_report", False):
        try:
            gateway._preserve_unknown_requests()
        except Exception:
            logger.debug("post-listen recovery report skipped", exc_info=True)
        gateway._pending_recovery_report = False
    try:
        while not gateway._lifecycle_shutdown.is_set():
            try:
                await asyncio.wait_for(gateway._lifecycle_shutdown.wait(), timeout=3600)
            except asyncio.TimeoutError:
                continue
        logger.warning("Gateway leaving after lifecycle shutdown")
        await leave_after_lifecycle_shutdown(gateway)
    finally:
        await runner.cleanup()


async def leave_after_lifecycle_shutdown(gateway: JaegerGatewayApp) -> None:
    """Boot the launchd jobs out, then stop this process.

    The plists restart a job only after a crash (KeepAlive SuccessfulExit
    false), and this path exits 0. bootout also unloads the jobs, so neither
    launchd nor a stale load can start a privileged gateway again. The menu
    bar has already retired the lease, so a race that loses the bootout still
    fails closed.
    """
    if _is_launchd_stack_gateway():
        try:
            from jaeger_ai.core.runtime.stack import stack_down
            stack_down(wait_timeout=2.0)
        except Exception:
            logger.error("lifecycle stack shutdown failed", exc_info=True)
    else:
        # A foreground, test-port or scratch Gateway owns only itself. It
        # must never boot out the operator's launchd stack.
        logger.warning("Not the launchd stack Gateway; leaving without stack down")
    await gateway._bounded_shutdown(gateway.app)


def _is_launchd_stack_gateway() -> bool:
    """True only for the Gateway job launchd started from the stack plist.

    launchd sets XPC_SERVICE_NAME to the job label and is the job's parent.
    Requiring both keeps a child process or a shell-launched Gateway that
    inherited the variable from taking the stack down.
    """
    from jaeger_ai.core.runtime.stack import SERVICE_BY_ID
    return (
        os.environ.get("XPC_SERVICE_NAME") == SERVICE_BY_ID["gateway"].label
        and os.getppid() == 1
    )


def main(argv: list[str] | None = None) -> int:
    """``jaeger gateway daemon`` — run the Jaeger Gateway on :data:`GATEWAY_PORT`.

    This is the daemon AGENTS.md §3 describes: persistent SQLite session
    state and SSE multi-client broadcast, with the native app, WebUI and
    CLI attaching as decoupled clients.

    It had no route for a whole release. ``jaeger gateway`` goes to
    ``features.gateway``, which manages the *external* Agentgateway on
    :8811/:8812 — a different process entirely — while
    ``jaeger_ai/features/webui/api/jaeger_agents.py`` and
    ``scripts/run-jaeger-webui.sh`` both pointed clients at the Gateway with
    nothing listening. Adding the route is what makes those clients real.

    Binds loopback by default; publish to a tailnet rather than widening
    the bind.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="jaeger gateway daemon",
        description="Run the Jaeger Gateway daemon (sessions + SSE).",
    )
    parser.add_argument("--host", default=DEFAULT_GATEWAY_HOST,
                        help=f"bind address (default {DEFAULT_GATEWAY_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_GATEWAY_PORT,
                        help=f"bind port (default {DEFAULT_GATEWAY_PORT})")
    args = parser.parse_args(argv)

    try:
        asyncio.run(run_gateway_forever(args.host, args.port))
    except KeyboardInterrupt:
        print("\n[jaeger-gateway] stopped", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover — process entry point
    raise SystemExit(main())
