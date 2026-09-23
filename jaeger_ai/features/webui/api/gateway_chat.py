"""Default-off Hermes Gateway bridge for browser-originated chat turns."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from api.config import (
    AGENT_INSTANCES,
    CANCEL_FLAGS,
    PENDING_GOAL_CONTINUATION,
    STREAM_GOAL_RELATED,
    STREAMS,
    STREAMS_LOCK,
    STREAM_LAST_EVENT_ID,
    STREAM_LIVE_TOOL_CALLS,
    STREAM_PARTIAL_TEXT,
    STREAM_REASONING_TEXT,
    _get_session_agent_lock,
    _parse_provider_qualified_model_id,
    clear_session_writeback_owner_if_owned,
    coerce_reasoning_effort_for_model,
    gateway_approval_unavailable_reason,
    gateway_supports_approval,
    register_active_run,
    unregister_active_run,
    unregister_stream_owner,
    update_active_run,
)
from api.helpers import _redact_text, redact_session_data
from api.models import clear_process_wakeup_pause, get_session, merge_session_messages_append_only
from api.run_journal import RunJournalWriter, bound_run_journal_snapshot_args

logger = logging.getLogger(__name__)

# Maps stream_id -> gateway run_id for approval response relay.
_STREAM_RUN_IDS: dict[str, str] = {}
_STREAM_RUN_LIFECYCLE: dict[str, dict[str, Any]] = {}
_STREAM_RUN_STARTING_CONDITION = threading.Condition()
GATEWAY_RUN_ID_WAIT_TIMEOUT = 5.0


def _mark_gateway_run_starting(stream_id: str) -> None:
    with _STREAM_RUN_STARTING_CONDITION:
        _STREAM_RUN_IDS.pop(stream_id, None)
        _STREAM_RUN_LIFECYCLE[stream_id] = {
            "phase": "pending",
            "run_id": "",
            "waiters": 0,
            "owner_done": False,
        }


def _publish_gateway_run_id(stream_id: str, run_id: str) -> None:
    with _STREAM_RUN_STARTING_CONDITION:
        _STREAM_RUN_IDS[stream_id] = run_id
        state = _STREAM_RUN_LIFECYCLE.get(stream_id) or {}
        _STREAM_RUN_LIFECYCLE[stream_id] = {
            "phase": "ready",
            "run_id": run_id,
            "waiters": int(state.get("waiters") or 0),
            "owner_done": bool(state.get("owner_done")),
        }
        _STREAM_RUN_STARTING_CONDITION.notify_all()


def _finish_gateway_run_starting(stream_id: str, *, result: str = "failed") -> None:
    with _STREAM_RUN_STARTING_CONDITION:
        state = _STREAM_RUN_LIFECYCLE.get(stream_id) or {}
        if str(state.get("phase") or "").strip().lower() == "ready":
            return
        _STREAM_RUN_IDS.pop(stream_id, None)
        _STREAM_RUN_LIFECYCLE[stream_id] = {
            "phase": "fallback" if result == "fallback" else "failed",
            "run_id": "",
            "waiters": int(state.get("waiters") or 0),
            "owner_done": bool(state.get("owner_done")),
        }
        _STREAM_RUN_STARTING_CONDITION.notify_all()


def _retire_gateway_run_starting_if_done(stream_id: str) -> bool:
    state = _STREAM_RUN_LIFECYCLE.get(stream_id)
    if not state:
        return False
    if int(state.get("waiters") or 0) > 0:
        return False
    if not bool(state.get("owner_done")):
        return False
    _STREAM_RUN_LIFECYCLE.pop(stream_id, None)
    _STREAM_RUN_IDS.pop(stream_id, None)
    return True


def _clear_gateway_run_starting(stream_id: str) -> None:
    with _STREAM_RUN_STARTING_CONDITION:
        state = _STREAM_RUN_LIFECYCLE.get(stream_id)
        if state:
            state["owner_done"] = True
        _retire_gateway_run_starting_if_done(stream_id)
        _STREAM_RUN_STARTING_CONDITION.notify_all()


def gateway_run_id_pending(stream_id: str) -> bool:
    with _STREAM_RUN_STARTING_CONDITION:
        return str((_STREAM_RUN_LIFECYCLE.get(stream_id) or {}).get("phase") or "").strip().lower() == "pending"


def wait_for_gateway_run_id(stream_id: str, timeout: float) -> tuple[bool, str | None]:
    deadline = time.monotonic() + max(0.0, float(timeout))
    with _STREAM_RUN_STARTING_CONDITION:
        state = _STREAM_RUN_LIFECYCLE.get(stream_id)
        if state:
            state["waiters"] = int(state.get("waiters") or 0) + 1
        try:
            while True:
                state = _STREAM_RUN_LIFECYCLE.get(stream_id)
                phase = str((state or {}).get("phase") or "").strip().lower()
                if phase == "fallback":
                    return False, None
                if phase == "failed":
                    return True, None
                run_id = str(_STREAM_RUN_IDS.get(stream_id) or "").strip()
                if phase == "ready":
                    stored_run_id = str((state or {}).get("run_id") or "").strip()
                    return True, run_id or stored_run_id or None
                if run_id:
                    return True, run_id
                if not state:
                    return False, None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True, None
                _STREAM_RUN_STARTING_CONDITION.wait(timeout=remaining)
        finally:
            state = _STREAM_RUN_LIFECYCLE.get(stream_id)
            if state:
                waiters = max(0, int(state.get("waiters") or 0) - 1)
                state["waiters"] = waiters
                if _retire_gateway_run_starting_if_done(stream_id):
                    _STREAM_RUN_STARTING_CONDITION.notify_all()

_WEBUI_CHAT_BACKEND_ENV = "HERMES_WEBUI_CHAT_BACKEND"
_WEBUI_GATEWAY_BASE_URL_ENV = "HERMES_WEBUI_GATEWAY_BASE_URL"
_WEBUI_GATEWAY_API_KEY_ENV = "HERMES_WEBUI_GATEWAY_API_KEY"
_WEBUI_GATEWAY_USE_RUNS_API_ENV = "HERMES_WEBUI_GATEWAY_USE_RUNS_API"
_GATEWAY_CHAT_BACKENDS = {"gateway", "api_server", "api-server"}


def _gateway_model_field(model: str | None) -> str:
    """Return the bare model name to put in a gateway request body.

    The picker and ``_resolve_compatible_session_model_state`` intentionally
    keep the full ``@provider:model`` string for internal routing (#1253), but
    the gateway expects a bare model name and carries the provider separately.
    Sent verbatim, ``@ollama-cloud:minimax-m2.7`` is forwarded to the upstream
    provider API, which 404s on the ``@``-prefixed string (#6722).

    Parsing is delegated to ``config._parse_provider_qualified_model_id()`` so
    a multi-segment custom provider ID (``@custom:backup:model-a``) yields the
    real model (``model-a``) instead of a positional-split fragment.
    """
    if not model:
        return ""
    value = str(model).strip()
    parsed = _parse_provider_qualified_model_id(value)
    if parsed:
        return str(parsed[0] or "").strip()
    return value


# Total byte-silence budget (seconds) for the gateway SSE socket, applied via
# ``urlopen(timeout=...)``. A stream that emits ANY byte within the window never
# trips it, so a genuinely alive (if slow) token stream is untouched; only more
# than this much *total* byte-silence is treated as a dead/stalled gateway.
#
# This is a TERMINAL budget, not a per-read grace: CPython's ``socket.makefile``
# latches ``_timeout_occurred`` on the first ``socket.timeout``, after which every
# further read raises a bare ``OSError`` — the connection cannot be resumed. So a
# read timeout ends the turn (surfacing Stop if pressed). It replaces the old flat
# 600s timeout, under which a half-open gateway (TCP open, zero bytes) pinned the
# worker for the full 10 minutes and ignored Stop (cancel is only re-checked
# between SSE lines). We KEEP the 600s default budget: there is no Gateway
# protocol heartbeat guaranteeing sub-600s progress bytes, so a legitimately
# long/fully-silent server-side tool call must not be terminated early — reducing
# the default below 600s would kill currently-working turns (gate finding, #5789).
# The win here is that a read timeout is now TERMINAL and Stop-honoring (the old
# flat timeout ignored Stop on a half-open gateway); the budget itself stays 600s
# for backward compatibility. Deployments that want a tighter dead-gateway cap can
# lower ``HERMES_WEBUI_GATEWAY_READ_TIMEOUT``.
_GATEWAY_READ_TIMEOUT_ENV = "HERMES_WEBUI_GATEWAY_READ_TIMEOUT"
_GATEWAY_READ_TIMEOUT_DEFAULT = 600.0


def _gateway_read_timeout_secs() -> float:
    """Total byte-silence budget for gateway SSE reads (default 600s, env-tunable)."""
    raw = os.environ.get(_GATEWAY_READ_TIMEOUT_ENV)
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return _GATEWAY_READ_TIMEOUT_DEFAULT


def _iter_sse_lines_cancellable(resp, cancel_event):
    """Yield raw SSE lines from ``resp``, unblocking cleanly on a read timeout.

    ``resp``'s socket carries a read timeout (``urlopen(timeout=...)``). A read
    that blocks past it raises ``socket.timeout``, and that timeout is TERMINAL:
    CPython's ``socket.makefile`` latches ``_timeout_occurred`` on the first
    timeout, so every subsequent read raises a bare ``OSError`` ("cannot read
    from timed out object") — there is no multi-read grace to reclaim. So on a
    read timeout (or the poisoned-socket ``OSError``/any read error) this either
    surfaces the user's Stop or tears the stalled turn down:

      - cancel set -> yield ``b""`` (the caller's ``if cancel_event.is_set()``
        branch emits its cancel event), then stop. This is why the old flat 600s
        pin — where a stalled gateway ignored Stop until it eventually errored —
        is gone: Stop is honored within one timeout window.
      - otherwise -> re-raise, so the caller's error handling reports the stall.

    A stream that keeps emitting bytes within the timeout window never trips it,
    so a genuinely alive (if slow) token stream is untouched. Emitting ``b""`` is
    safe: the SSE loops decode it to an empty line and ``continue`` (same as a
    real blank line).

    Iterates ``resp`` via the iterator protocol so a real ``HTTPResponse`` and the
    test fakes (which implement ``__iter__``) behave identically.
    """
    resp_iter = iter(resp)
    while True:
        try:
            raw_line = next(resp_iter)
        except StopIteration:
            return  # EOF
        except OSError:
            # socket.timeout / TimeoutError are OSError subclasses, as is the
            # post-timeout poisoned-socket "cannot read" error. All are terminal
            # for this connection.
            if cancel_event.is_set():
                yield b""  # let the caller emit its cancel event
                return
            raise
        yield raw_line


def webui_chat_backend_mode(config_data=None, environ: dict[str, str] | None = None) -> str:
    """Return the explicitly selected browser chat backend.

    The default remains the in-process WebUI runtime unless JAEGER_GATEWAY_URL,
    HERMES_WEBUI_GATEWAY_URL, or explicit gateway backend env is set.
    """
    source = os.environ if environ is None else environ
    cfg = config_data if isinstance(config_data, dict) else {}
    raw = str(
        source.get(_WEBUI_CHAT_BACKEND_ENV)
        or cfg.get("webui_chat_backend")
        or ""
    ).strip().lower()
    if raw in _GATEWAY_CHAT_BACKENDS:
        return "gateway"
    if source.get("JAEGER_GATEWAY_URL") or source.get("HERMES_WEBUI_GATEWAY_URL"):
        return "gateway"
    return "legacy"


def webui_gateway_chat_enabled(config_data=None, environ: dict[str, str] | None = None) -> bool:
    return webui_chat_backend_mode(config_data, environ) == "gateway"


def _gateway_base_url(config_data=None, environ: dict[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    cfg = config_data if isinstance(config_data, dict) else {}
    raw = str(
        source.get("JAEGER_GATEWAY_URL")
        or source.get("HERMES_WEBUI_GATEWAY_URL")
        or source.get(_WEBUI_GATEWAY_BASE_URL_ENV)
        or cfg.get("webui_gateway_base_url")
        or "http://127.0.0.1:8810"
    ).strip()
    return raw.rstrip("/") or "http://127.0.0.1:8810"


def _is_jaeger_gateway(base_url: str) -> bool:
    """Return True if base_url targets a canonical Jaeger Gateway daemon."""
    target = (base_url or "").rstrip("/")
    jg = (os.environ.get("JAEGER_GATEWAY_URL") or "").rstrip("/")
    if jg and target == jg:
        return True
    if target.endswith(":8810"):
        return True
    try:
        req = urllib.request.Request(f"{target}/version", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
            if data.get("component") == "jaeger-gateway":
                return True
    except Exception:
        pass
    return False


def _gateway_api_key(environ: dict[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return str(
        source.get(_WEBUI_GATEWAY_API_KEY_ENV)
        or source.get("API_SERVER_KEY")
        or ""
    ).strip()


def _gateway_use_runs_api_enabled(config_data=None, environ: dict[str, str] | None = None) -> bool:
    """Return True only when the operator has explicitly opted into the runs API path."""
    source = os.environ if environ is None else environ
    cfg = config_data if isinstance(config_data, dict) else {}
    raw = str(
        source.get(_WEBUI_GATEWAY_USE_RUNS_API_ENV)
        or cfg.get("webui_gateway_use_runs_api")
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _gateway_reasoning_effort_for_request(cfg, *, model=None, model_provider=None):
    """Read and coerce user-configured reasoning effort for a gateway request."""
    try:
        cfg_data = cfg if isinstance(cfg, dict) else {}
        effort_cfg = cfg_data.get("agent", {}) if isinstance(cfg_data, dict) else {}
        effort_raw = effort_cfg.get("reasoning_effort") if isinstance(effort_cfg, dict) else None
        coerced = coerce_reasoning_effort_for_model(
            effort_raw,
            model,
            provider_id=model_provider,
        )
        # Preserve explicit "none" while still omitting absent or invalid effort.
        return None if not coerced else str(coerced)
    except Exception:
        return None


def _gateway_session_yolo_enabled(session_id: str) -> bool:
    """Return the WebUI-owned, in-memory YOLO state for a browser session."""
    try:
        from tools.approval import is_session_yolo_enabled

        return bool(is_session_yolo_enabled(str(session_id or "")))
    except Exception:
        return False


def _settle_gateway_run_approval(
    session_id: str,
    approval_data: dict,
    base_url: str,
    api_key: str,
) -> tuple[bool, dict | None, int]:
    """Auto-approve or mirror one run approval at a session-linearized point."""
    from api.route_approvals import gateway_yolo_handoff, submit_gateway_pending_mirror

    run_id = str(approval_data.get("run_id") or "").strip()
    identity_v1 = bool(approval_data.get("_gateway_agent_identity_v1"))
    with gateway_yolo_handoff(session_id):
        if _gateway_session_yolo_enabled(session_id):
            try:
                _auto_approve_gateway_run(
                    base_url,
                    api_key,
                    run_id,
                    approval_data["approval_id"] if identity_v1 else "",
                )
                return True, None, 0
            except Exception:
                # Fail closed: if remote approval fails, surface the real card
                # before allowing a same-session toggle to pass the handoff.
                logger.warning(
                    "WebUI YOLO could not auto-approve run %s; showing approval card",
                    run_id,
                    exc_info=True,
                )
        head, total = submit_gateway_pending_mirror(session_id, approval_data)
        return False, head, total


def _auto_approve_gateway_run(
    base_url: str,
    api_key: str,
    run_id: str,
    approval_id: str,
) -> None:
    """Resolve one Runs API prompt using only the shipped approval contract.

    This is a WebUI-owned compatibility path: the Runs API does not yet expose
    session YOLO, so WebUI answers each approval request while its own session
    flag is enabled. Native Agent-side YOLO would be preferable because it can
    bypass gates before they pause and also covers Agent-owned computer-use
    policy; https://github.com/NousResearch/hermes-agent/pull/61946 tracks that
    API capability. Until then, do not send speculative fields to the Agent.
    """
    from api.runner_client import HttpRunnerClient

    HttpRunnerClient(base_url=base_url, api_key=api_key).respond_approval(
        run_id,
        approval_id,
        "once",
    )


def gateway_chat_config_status(config_data=None, environ: dict[str, str] | None = None) -> dict:
    """Return redacted Gateway-backed chat configuration status."""
    mode = webui_chat_backend_mode(config_data, environ)
    base_url = _gateway_base_url(config_data, environ)
    return {
        "enabled": mode == "gateway",
        "backend": mode,
        "base_url_configured": bool(base_url),
        "api_key_configured": bool(_gateway_api_key(environ)),
    }


def _gateway_http_error_event(exc: urllib.error.HTTPError, err_body: str, *, api_key_configured: bool) -> dict:
    safe = _redact_text(err_body or str(exc))[:500]
    if exc.code == 401:
        return {
            "label": "Gateway authentication failed",
            "type": "gateway_auth_error",
            "message": "Gateway rejected the WebUI API key (HTTP 401).",
            "hint": (
                "Set HERMES_WEBUI_GATEWAY_API_KEY to the same value as the Hermes Gateway "
                "API_SERVER_KEY, or disable HERMES_WEBUI_CHAT_BACKEND=gateway."
                if not api_key_configured
                else "Check that HERMES_WEBUI_GATEWAY_API_KEY matches the Hermes Gateway API_SERVER_KEY."
            ),
        }
    return {
        "label": "Gateway request failed",
        "type": "gateway_http_error",
        "message": f"Gateway returned HTTP {exc.code}.",
        "hint": safe or "Check the configured Gateway API server.",
    }


def _gateway_sse_delta(payload: dict) -> str:
    """Extract assistant text from an OpenAI-compatible streaming chunk."""
    try:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str):
            return content
        message = choice.get("message") or {}
        content = message.get("content")
        return content if isinstance(content, str) else ""
    except Exception:
        return ""


def _gateway_sse_reasoning_delta(payload: dict) -> str:
    """Extract reasoning text from OpenAI-compatible streaming chunks."""
    try:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning
        message = choice.get("message") or {}
        reasoning = message.get("reasoning_content")
        return reasoning if isinstance(reasoning, str) and reasoning.strip() else ""
    except Exception:
        return ""


def _gateway_stream_usage(payload: dict) -> dict:
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return {}
    return {
        "input_tokens": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        "estimated_cost": usage.get("estimated_cost") or usage.get("estimated_cost_usd") or 0,
    }


def _gateway_reasoning_delta(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("text", "preview", "delta", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _gateway_tool_progress_event(payload: dict) -> tuple[str, dict] | None:
    """Translate Hermes Gateway tool-progress SSE payloads to WebUI events."""
    if not isinstance(payload, dict):
        return None
    event_type = str(payload.get("event") or "").strip().lower()
    if event_type == "reasoning.available":
        reason_delta = _gateway_reasoning_delta(payload)
        if not reason_delta:
            return None
        return "reasoning", {"text": reason_delta}
    name = str(payload.get("tool") or payload.get("name") or payload.get("function_name") or "").strip()
    if not name:
        return None
    if name == "_thinking":
        reason_delta = _gateway_reasoning_delta(payload)
        if not reason_delta:
            return None
        return "reasoning", {"text": reason_delta}
    if name.startswith("_"):
        return None
    status = str(payload.get("status") or "running").strip().lower()
    tid = payload.get("toolCallId") or payload.get("tool_call_id") or payload.get("id")
    is_complete = event_type == "tool.completed" or status in {"completed", "complete", "success", "error", "failed"}
    event_payload = {
        "event_type": "tool.completed" if is_complete else "tool.started",
        "name": name,
        "preview": payload.get("label") or payload.get("preview"),
        "args": bound_run_journal_snapshot_args(payload.get("args"))
        if isinstance(payload.get("args"), dict)
        else {},
        "is_error": bool(payload.get("error")) or status in {"error", "failed"},
    }
    if tid:
        event_payload["tid"] = str(tid)
    return ("tool_complete" if is_complete else "tool"), event_payload


def _gateway_runs_approval_event(payload: dict) -> dict | None:
    """Map a runs-API approval.request payload to the WebUI approval contract."""
    if not isinstance(payload, dict):
        return None
    tool = str(payload.get("tool") or payload.get("function_name") or payload.get("pattern_key") or "").strip()
    command = str(payload.get("command") or "").strip()
    description = str(payload.get("description") or "").strip()
    pattern_keys = payload.get("pattern_keys") if isinstance(payload.get("pattern_keys"), list) else []
    pattern_key = str(payload.get("pattern_key") or "").strip()
    args = payload.get("args") if isinstance(payload.get("args"), (list, dict)) else []
    run_id = str(payload.get("run_id") or "").strip()
    raw_approval_id = str(payload.get("approval_id") or payload.get("id") or "").strip()
    approval_id = raw_approval_id
    if not approval_id:
        approval_id = uuid.uuid4().hex
    risk = str(payload.get("risk_level") or "high").strip()
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    allow_permanent = payload.get("allow_permanent")
    if allow_permanent is None:
        allow_permanent = "always" in choices
    if not (tool or command or description):
        return None
    return {
        "tool": tool,
        "command": command,
        "description": description,
        "pattern_key": pattern_key,
        "pattern_keys": pattern_keys or ([pattern_key] if pattern_key else []),
        "args": args,
        "risk_level": risk,
        "run_id": run_id,
        "approval_id": approval_id,
        "_gateway_raw_approval_id_present": bool(raw_approval_id),
        "choices": choices,
        "allow_permanent": bool(allow_permanent),
    }


def _run_gateway_runs_api_streaming(
    session_id, msg_text, model, workspace, stream_id,
    base_url, api_key, prefill_messages, body_extras,
    *, put_gateway_event, cancel_event,
    attachments=None, cfg=None, session=None,
    active_provider: str = "",
):
    """Submit via POST /v1/runs and relay SSE events including approval."""
    try:
        url_runs = f"{base_url.rstrip('/')}/v1/runs"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Hermes-Session-Id": session_id,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-Hermes-Session-Key"] = f"webui:{session_id}"
        message_content: Any = str(msg_text or "")
        if attachments:
            try:
                from api.streaming import _build_native_multimodal_message

                message_content = _build_native_multimodal_message("", str(msg_text or ""), attachments, str(workspace), cfg=cfg, active_provider=active_provider, active_model=(model or ""), requested_provider=active_provider)
            except Exception:
                logger.debug("Failed to build runs-API multimodal attachment payload", exc_info=True)
                message_content = str(msg_text or "")
        from api.streaming import _strip_oob_blocks

        instructions_parts = []
        conversation_history = []
        for entry in getattr(session, "context_messages", None) or []:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = entry.get("content")
            if content is not None:
                content = _strip_oob_blocks(content)
                conversation_history.append({"role": role, "content": content})
        for entry in prefill_messages or []:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role") or "").strip().lower()
            content = entry.get("content")
            if role == "system":
                if isinstance(content, str) and content.strip():
                    instructions_parts.append(content)
                elif content is not None:
                    instructions_parts.append(str(content))
                continue
            if role not in {"user", "assistant"}:
                continue
            if content is not None:
                content = _strip_oob_blocks(content)
            conversation_history.append({"role": role, "content": content})
        run_input = message_content
        if isinstance(run_input, list):
            run_input = [{"role": "user", "content": run_input}]
        run_body = {
            "model": _gateway_model_field(model) or "default",
            "input": run_input,
            **body_extras,
            "session_id": session_id,
            "workspace": str(workspace),
        }
        if instructions_parts:
            run_body["instructions"] = "\n\n".join(part for part in instructions_parts if part)
        if conversation_history:
            run_body["conversation_history"] = conversation_history
        req = urllib.request.Request(
            url_runs,
            data=json.dumps(run_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        update_active_run(stream_id, phase="gateway-request")
        with urllib.request.urlopen(req, timeout=30) as resp:
            run_data = json.loads(resp.read(65536))
        run_id = str(run_data.get("run_id") or run_data.get("id") or "").strip()
        if not run_id:
            raise ValueError(f"Gateway runs API returned no run_id: {run_data!r}")
    except Exception:
        _finish_gateway_run_starting(stream_id)
        raise

    usage: dict = {}
    from api.jaeger_gateway_routes import remember
    remember(run_id, base_url, api_key)
    _publish_gateway_run_id(stream_id, run_id)

    url_events = f"{base_url.rstrip('/')}/v1/runs/{run_id}/events"
    headers_sse = dict(headers)
    headers_sse["Accept"] = "text/event-stream"
    req_events = urllib.request.Request(url_events, headers=headers_sse, method="GET")
    final_text = ""
    sse_event = "message"
    with urllib.request.urlopen(req_events, timeout=_gateway_read_timeout_secs()) as resp:
        for raw_line in _iter_sse_lines_cancellable(resp, cancel_event):
            if cancel_event.is_set():
                put_gateway_event("cancel", {"message": "Cancelled by user"})
                return None, usage
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                sse_event = "message"
                continue
            if line.startswith("event:"):
                sse_event = line[6:].strip() or "message"
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            payload_event = str(payload.get("event") or payload.get("type") or sse_event).strip() or "message"
            if payload_event == "approval.request":
                approval_data = _gateway_runs_approval_event(payload)
                if approval_data:
                    approval_data["run_id"] = run_id
                    from api.config import gateway_supports_approval_identity_v1
                    identity_v1 = bool(approval_data.get("_gateway_raw_approval_id_present")) and gateway_supports_approval_identity_v1(base_url, api_key)
                    approval_data["_gateway_agent_identity_v1"] = identity_v1
                    auto_approved, head, total = _settle_gateway_run_approval(
                        session_id,
                        approval_data,
                        base_url,
                        api_key,
                    )
                    if auto_approved:
                        sse_event = "message"
                        continue
                    put_gateway_event("approval", {**(head or approval_data), "pending_count": total})
                sse_event = "message"
                continue
            if payload_event in {"tool.started", "tool.completed", "reasoning.available"}:
                translated = _gateway_tool_progress_event(payload)
                if translated:
                    event_name, event_payload = translated
                    if event_name == "reasoning":
                        reason_delta = event_payload.get("text")
                        if reason_delta and stream_id in STREAM_REASONING_TEXT:
                            STREAM_REASONING_TEXT[stream_id] += reason_delta
                    elif stream_id in STREAM_LIVE_TOOL_CALLS:
                        if event_name == "tool":
                            STREAM_LIVE_TOOL_CALLS[stream_id].append({
                                "name": event_payload.get("name"),
                                "args": event_payload.get("args") or {},
                                "done": False,
                                **({"tid": event_payload.get("tid")} if event_payload.get("tid") else {}),
                            })
                        elif event_name == "tool_complete":
                            for shared_tc in reversed(STREAM_LIVE_TOOL_CALLS[stream_id]):
                                if shared_tc.get("done"):
                                    continue
                                if (
                                    event_payload.get("tid") and shared_tc.get("tid") == event_payload.get("tid")
                                ) or shared_tc.get("name") == event_payload.get("name"):
                                    shared_tc["done"] = True
                                    shared_tc["is_error"] = bool(event_payload.get("is_error"))
                                    break
                    put_gateway_event(event_name, event_payload)
                    if event_name != "reasoning":
                        update_active_run(stream_id, phase="gateway-tool", latest_tool=event_payload.get("name"))
                sse_event = "message"
                continue
            if payload_event == "message.delta":
                delta = str(payload.get("delta") or "")
                if delta:
                    final_text += delta
                    if stream_id in STREAM_PARTIAL_TEXT:
                        STREAM_PARTIAL_TEXT[stream_id] += delta
                    put_gateway_event("token", {"text": delta})
                sse_event = "message"
                continue
            if payload_event == "run.completed":
                from api.route_approvals import retire_gateway_pending_mirror
                retire_gateway_pending_mirror(session_id, run_id=run_id)
                if payload.get("error"):
                    raise RuntimeError(str(payload["error"]))
                output = str(payload.get("output") or "")
                if output and not final_text:
                    final_text = output
                    if stream_id in STREAM_PARTIAL_TEXT:
                        STREAM_PARTIAL_TEXT[stream_id] = output
                usage.update({k: v for k, v in _gateway_stream_usage(payload).items() if v})
                sse_event = "message"
                continue
            if payload_event == "run.failed":
                from api.route_approvals import retire_gateway_pending_mirror
                retire_gateway_pending_mirror(session_id, run_id=run_id)
                raise RuntimeError(str(payload.get("error") or "Gateway run failed"))
            if payload_event == "run.cancelled":
                from api.route_approvals import retire_gateway_pending_mirror
                retire_gateway_pending_mirror(session_id, run_id=run_id)
                put_gateway_event("cancel", {"message": "Cancelled by gateway"})
                return None, usage
            reasoning_delta = _gateway_sse_reasoning_delta(payload)
            if reasoning_delta:
                if stream_id in STREAM_REASONING_TEXT:
                    STREAM_REASONING_TEXT[stream_id] += reasoning_delta
                put_gateway_event("reasoning", {"text": reasoning_delta})
            delta = _gateway_sse_delta(payload)
            if delta:
                final_text += delta
                if stream_id in STREAM_PARTIAL_TEXT:
                    STREAM_PARTIAL_TEXT[stream_id] += delta
                put_gateway_event("token", {"text": delta})
            usage.update({k: v for k, v in _gateway_stream_usage(payload).items() if v})
    return final_text, usage


def stop_gateway_run(run_id: str) -> bool:
    """Request interruption; confirm the canonical owner's terminal outcome.

    Jaeger's cancel endpoint acknowledges delivery before execution settles.
    The caller must not tear down SSE or admit another turn on that receipt.
    """
    run_id = str(run_id or "").strip()
    if not run_id:
        return False
    from api.config import get_config, stream_owner_session_id

    cfg = get_config()
    base_url = _gateway_base_url(cfg)
    api_key = _gateway_api_key()
    from api.jaeger_gateway_routes import lookup
    pinned_route = lookup(run_id)
    if pinned_route:
        base_url, api_key = pinned_route

    owner_sid = stream_owner_session_id(run_id)
    if _is_jaeger_gateway(base_url) and owner_sid:
        cancel_url = f"{base_url.rstrip('/')}/v1/sessions/{urllib.parse.quote(owner_sid, safe='')}/cancel"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            cancel_url,
            data=json.dumps({"request_id": run_id}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
                if not 200 <= status < 300:
                    return False
                payload = json.loads(response.read() or b"{}")
            status_req = urllib.request.Request(
                f"{base_url.rstrip('/')}/v1/sessions/{urllib.parse.quote(owner_sid, safe='')}/requests/"
                f"{urllib.parse.quote(run_id, safe='')}",
                headers=headers, method="GET",
            )
            deadline = time.monotonic() + 5.0
            while isinstance(payload, dict):
                if payload.get("execution_unknown") is True:
                    return False
                if payload.get("status") in {"cancelled", "completed", "failed"}:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                with urllib.request.urlopen(status_req, timeout=remaining) as response:
                    payload = json.loads(response.read() or b"{}")
                if isinstance(payload, dict) and payload.get("status") in {"running", "cancelling", "queued"}:
                    time.sleep(0.05)
            return False
        except urllib.error.HTTPError as http_err:
            logger.debug("Jaeger Gateway cancel failed for run %s: %s", run_id, http_err, exc_info=True)
            return False
        except Exception:
            logger.debug("Jaeger Gateway cancel failed for run %s", run_id, exc_info=True)
            return False

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/runs/{urllib.parse.quote(run_id, safe='')}/stop",
        data=b"{}",
        headers=headers,
        method="POST",
    )
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=10) as response:
            final_url = str(getattr(response, "geturl", lambda: req.full_url)() or "")
            status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
            if not (200 <= status < 300 and final_url == req.full_url):
                return False
            payload = json.loads(response.read() or b"{}")
            if "cancellation_confirmed" in payload:
                return (payload.get("status") == "cancelled"
                        and payload.get("cancellation_confirmed") is True
                        and payload.get("execution_unknown") is False)
            return True
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        logger.debug("Gateway stop failed for run %s", run_id, exc_info=True)
        return False


def _settle_gateway_terminal_error(session_id, stream_id, workspace, model, model_provider, terminal_error):
    from api.streaming import (
        _classify_provider_error,
        _materialize_pending_user_turn_before_error,
        _provider_error_payload,
        _session_payload_with_full_messages,
        _snapshot_and_append_partial_on_error,
        _terminal_turn_duration,
    )

    with _get_session_agent_lock(session_id):
        session = get_session(session_id)
        if not _stream_writeback_is_current(session, stream_id):
            return None
        error_classification = _classify_provider_error(terminal_error)
        error_payload = _provider_error_payload(
            terminal_error,
            error_classification["type"],
            error_classification.get("hint", ""),
        )
        turn_duration = _terminal_turn_duration(session)
        _materialize_pending_user_turn_before_error(session)
        session.active_stream_id = None
        session.pending_user_message = None
        session.pending_attachments = []
        session.pending_started_at = None
        session.pending_user_source = None
        try:
            _snapshot_and_append_partial_on_error(session, stream_id)
        except Exception:
            logger.debug("Failed to snapshot gateway partials on terminal error", exc_info=True)
        error_message = {
            "role": "assistant",
            "content": (
                f"**{error_classification['label']}:** "
                f"{error_payload.get('message') or error_classification['label']}"
            ) + (f"\n\n*{error_payload['hint']}*" if error_payload.get("hint") else ""),
            "timestamp": int(time.time()),
            "_error": True,
        }
        if turn_duration is not None:
            error_message["_turnDuration"] = turn_duration
        if error_payload.get("details"):
            error_message["provider_details"] = error_payload["details"]
        if not isinstance(session.messages, list):
            session.messages = []
        session.messages.append(error_message)
        session.workspace = str(workspace)
        session.model = model
        session.model_provider = model_provider
        terminal_session_persisted = False
        try:
            session.save()
            terminal_session_persisted = True
        except Exception:
            logger.debug("Failed to persist gateway terminal error settlement", exc_info=True)
        error_payload["session"] = redact_session_data(
            _session_payload_with_full_messages(session, tool_calls=[])
        )
        error_payload["session_id"] = session.session_id
        error_payload["terminal_session_persisted"] = terminal_session_persisted
        if terminal_session_persisted:
            error_payload["terminal_session_persisted_session_id"] = session.session_id
        return error_payload


def _stream_writeback_is_current(session: Any, stream_id: str) -> bool:
    return bool(stream_id and getattr(session, "active_stream_id", None) == stream_id)


def _clear_gateway_pending_state(session: Any, stream_id: str) -> None:
    if not _stream_writeback_is_current(session, stream_id):
        return
    session.active_stream_id = None
    session.pending_user_message = None
    session.pending_attachments = None
    session.pending_started_at = None
    session.pending_user_source = None
    session.save()
    try:
        from api.config import LOCK, SESSIONS
        with LOCK:
            SESSIONS[session.session_id] = session
    except Exception:
        pass


def _cleanup_gateway_pending_mirror(session_id: str) -> None:
    try:
        from api.route_approvals import (
            retire_gateway_pending_mirror,
        )

        retire_gateway_pending_mirror(session_id)
    except Exception:
        logger.debug("Failed to reconcile gateway pending mirror during teardown", exc_info=True)


def _run_jaeger_gateway_streaming(
    session_id: str,
    msg_text: str,
    model: str,
    workspace: Any,
    stream_id: str,
    base_url: str,
    api_key: str,
    *,
    attachments: list | None = None,
    model_provider: str | None = None,
    options: dict[str, Any] | None = None,
    put_gateway_event: Any,
    cancel_event: threading.Event,
    cfg: dict[str, Any] | None = None,
    session: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Bridge WebUI turn through the canonical Jaeger Gateway on /v1/sessions."""
    if session is None:
        put_gateway_event("apperror", {
            "label": "WebUI session unavailable",
            "type": "session_error",
            "message": "The conversation session could not be loaded. Reload it and try again.",
            "session_id": session_id,
        })
        return "", {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0}

    from api.jaeger_gateway_routes import remember
    remember(stream_id, base_url, api_key)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 1. Ensure session exists on Jaeger Gateway
    profile = getattr(session, "profile", "jaeger") or "jaeger"
    sess_body = json.dumps({
        "session_id": session_id,
        "profile": profile,
        "workspace": str(workspace or ""),
        "source": "webui",
    }).encode("utf-8")
    try:
        sess_req = urllib.request.Request(f"{base_url}/v1/sessions", data=sess_body, headers=headers, method="POST")
        with urllib.request.urlopen(sess_req, timeout=5.0):
            pass
    except Exception:
        logger.debug("Gateway ensure_session notice for %s", session_id, exc_info=True)

    # Never admit a partial attachment set: an invalid item or malformed upload
    # receipt must be visible to the sender, not silently discarded.
    attachment_ids = []
    for att in attachments or []:
        att_path = ""
        try:
            if not isinstance(att, dict):
                raise ValueError("Attachment metadata must be an object")
            aid = att.get("attachment_id") or att.get("id")
            if aid:
                if not isinstance(aid, str) or not aid.strip():
                    raise ValueError("Attachment ID must be a nonempty string")
                attachment_ids.append(aid)
            else:
                att_path = str(att.get("path") or "").strip()
                if not att_path:
                    raise ValueError("Attachment requires an ID or file path")
                att_body = json.dumps({
                    "filename": att.get("name") or att.get("filename") or os.path.basename(att_path),
                    "path": att_path,
                    "mime": att.get("mime") or "application/octet-stream",
                    "size": att.get("size") or 0,
                }).encode("utf-8")
                att_req = urllib.request.Request(
                    f"{base_url}/v1/sessions/{urllib.parse.quote(session_id, safe='')}/attachments",
                    data=att_body, headers=headers, method="POST",
                )
                with urllib.request.urlopen(att_req, timeout=5.0) as att_resp:
                    uploaded = json.loads(att_resp.read().decode("utf-8") or "{}")
                uploaded_id = uploaded.get("attachment_id") if isinstance(uploaded, dict) else None
                if not isinstance(uploaded_id, str) or not uploaded_id.strip():
                    raise ValueError("Gateway upload response did not include an attachment ID")
                attachment_ids.append(uploaded_id)
        except Exception as exc:
            logger.warning("Failed to forward attachment to gateway", exc_info=True)
            put_gateway_event("apperror", {
                "label": "Attachment upload failed",
                "type": "attachment_error",
                "message": (
                    f"The attachment {os.path.basename(att_path) or 'file'} could not be sent "
                    "to Jaeger. The message was not submitted."
                ),
                "details": _redact_text(str(exc))[:500],
                "session_id": session_id,
            })
            return "", {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0}

    # 2. Post turn to /v1/sessions/{id}/turns
    turn_body = {
        "text": str(msg_text or ""),
        "request_id": stream_id,
        "model": _gateway_model_field(model) or model or "default",
    }
    if model_provider:
        turn_body["provider"] = model_provider
    if workspace:
        turn_body["workspace"] = str(workspace)
    if options:
        turn_body["options"] = dict(options)
    # An omitted field means "all session attachments" to the Gateway.  The
    # WebUI must send [] explicitly so files from earlier turns are not reused.
    turn_body["attachment_ids"] = attachment_ids

    turn_req = urllib.request.Request(
        f"{base_url}/v1/sessions/{urllib.parse.quote(session_id, safe='')}/turns",
        data=json.dumps(turn_body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    admitted: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(turn_req, timeout=10.0) as turn_resp:
            admitted = json.loads(turn_resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        err_body = exc.read(2048).decode("utf-8", errors="replace")
        put_gateway_event("apperror", _gateway_http_error_event(exc, err_body, api_key_configured=bool(api_key)))
        return "", {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0}
    except Exception as exc:
        safe = _redact_text(str(exc))[:500]
        put_gateway_event("apperror", {
            "label": "Gateway turn failed",
            "type": "gateway_error",
            "message": safe or "Failed to start turn on Jaeger Gateway.",
        })
        return "", {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0}

    # Cancellation may target this ID only after the owner has admitted it.
    # Publishing earlier races /cancel against an as-yet nonexistent request.
    _publish_gateway_run_id(stream_id, stream_id)

    # 3. Stream events from GET /v1/sessions/{session_id}/stream
    start_event_id = admitted.get("start_event_id")
    stream_url = f"{base_url}/v1/sessions/{urllib.parse.quote(session_id, safe='')}/stream"
    if start_event_id is not None:
        last_id = max(0, int(start_event_id) - 1)
        stream_url += f"?last_event_id={last_id}"

    stream_req = urllib.request.Request(
        stream_url,
        headers={
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="GET",
    )
    update_active_run(stream_id, phase="gateway-streaming")
    final_text = ""
    # Absence of owner telemetry is not proof of a free, zero-token turn.
    usage = {"input_tokens": None, "output_tokens": None, "estimated_cost": None, "measured": False}
    current_sse_event = "message"
    saw_finish = False

    with urllib.request.urlopen(stream_req, timeout=_gateway_read_timeout_secs()) as resp:
        for raw_line in _iter_sse_lines_cancellable(resp, cancel_event):
            if cancel_event.is_set():
                cancel_req = urllib.request.Request(
                    f"{base_url}/v1/sessions/{urllib.parse.quote(session_id, safe='')}/cancel",
                    data=json.dumps({"request_id": stream_id}).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(cancel_req, timeout=5.0):
                        pass
                except Exception:
                    pass
                put_gateway_event("cancel", {"message": "Cancelled by user"})
                return final_text, usage

            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                current_sse_event = "message"
                continue
            if line.startswith("event:"):
                current_sse_event = line[6:].strip() or "message"
                continue
            if line.startswith("data:"):
                data_str = line[5:].strip()
                try:
                    payload_json = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                evt_name = payload_json.get("event") or current_sse_event
                evt_data = payload_json.get("data") if isinstance(payload_json, dict) and "data" in payload_json else payload_json
                if not isinstance(evt_data, dict):
                    evt_data = {}

                req_id = evt_data.get("request_id")
                if req_id and str(req_id) != str(stream_id) and evt_name.startswith("turn."):
                    continue

                if evt_name == "turn.delta":
                    delta = str(evt_data.get("delta") or "")
                    if delta:
                        final_text += delta
                        with STREAMS_LOCK:
                            STREAM_PARTIAL_TEXT[stream_id] = final_text
                        put_gateway_event("token", {"text": delta})

                elif evt_name == "turn.reasoning":
                    r_text = str(evt_data.get("text") or "")
                    if r_text:
                        with STREAMS_LOCK:
                            curr = STREAM_REASONING_TEXT.get(stream_id, "")
                            STREAM_REASONING_TEXT[stream_id] = curr + r_text
                        put_gateway_event("reasoning", {"text": r_text})

                elif evt_name == "approval.request":
                    put_gateway_event("approval", evt_data)

                elif evt_name == "turn.finish":
                    saw_finish = True
                    output = evt_data.get("output")
                    if output and not final_text:
                        final_text = str(output)
                    raw_usage = evt_data.get("usage")
                    if isinstance(raw_usage, dict):
                        prompt_tokens = raw_usage.get("prompt_tokens", raw_usage.get("input_tokens"))
                        completion_tokens = raw_usage.get("completion_tokens", raw_usage.get("output_tokens"))
                        cost = raw_usage.get("estimated_cost")
                        usage["input_tokens"] = int(prompt_tokens) if prompt_tokens is not None else None
                        usage["output_tokens"] = int(completion_tokens) if completion_tokens is not None else None
                        usage["estimated_cost"] = float(cost) if cost is not None else None
                        usage["measured"] = prompt_tokens is not None and completion_tokens is not None
                    break

                elif evt_name == "turn.cancelled":
                    # The canonical owner has reached a durable terminal state.
                    # Release the WebUI admission guard before telling the
                    # browser cancellation is complete, so its next send is
                    # accepted on the first attempt rather than transiently 409.
                    _clear_gateway_pending_state(session, stream_id)
                    unregister_active_run(stream_id)
                    put_gateway_event("cancel", {"message": "Cancelled by user"})
                    return final_text, usage

                elif evt_name in ("turn.failed", "turn.unknown"):
                    err_msg = str(evt_data.get("error") or "Gateway turn failed")
                    put_gateway_event("apperror", {
                        "label": "Gateway execution failed",
                        "type": "gateway_error",
                        "message": err_msg,
                    })
                    return final_text, usage

    # Terminal success guard: stream EOF without turn.finish is a connection drop/failure
    if not saw_finish:
        put_gateway_event("apperror", {
            "label": "Gateway stream dropped",
            "type": "gateway_stream_error",
            "message": "Gateway stream closed before completion.",
            "session_id": session_id,
        })
        return final_text, usage

    # Persist session messages on successful finish
    if session is not None:
        with _get_session_agent_lock(session_id):
            if not isinstance(session.messages, list):
                session.messages = []
            user_msg = {
                "role": "user",
                "content": str(msg_text or ""),
                "timestamp": getattr(session, "pending_started_at", None) or time.time(),
            }
            asst_msg = {
                "role": "assistant",
                "content": final_text,
                "timestamp": time.time(),
            }
            if not session.messages or session.messages[-1].get("content") != user_msg["content"] or session.messages[-1].get("role") != "user":
                session.messages.append(user_msg)
            session.messages.append(asst_msg)
            session.pending_user_message = None
            session.active_stream_id = None
            session.updated_at = time.time()
            session.last_message_at = time.time()
            session.save()
            try:
                from api.models import LOCK, SESSIONS
                with LOCK:
                    SESSIONS[session.session_id] = session
            except Exception:
                pass

    from api.streaming import _session_payload_with_full_messages
    gateway_session_payload = _session_payload_with_full_messages(session, tool_calls=[])
    put_gateway_event("done", {"session": redact_session_data(gateway_session_payload), "usage": usage})
    put_gateway_event("stream_end", {"session_id": session_id})
    return final_text, usage


def _run_gateway_chat_streaming(
    session_id,
    msg_text,
    model,
    workspace,
    stream_id,
    attachments=None,
    *,
    model_provider=None,
    goal_related=False,
    regeneration=False,
):
    """Bridge a WebUI chat turn through Hermes Gateway's API server.

    This default-off path keeps the browser contract unchanged: /api/chat/start
    still returns a local stream_id and /api/chat/stream still receives WebUI SSE
    event names. The worker translates OpenAI-compatible streaming chunks from
    the configured Gateway API server into those local events and persists the
    final user/assistant turn back into the WebUI session.
    """
    q = STREAMS.get(stream_id)
    if q is None:
        _finish_gateway_run_starting(stream_id, result="fallback")
        _clear_gateway_run_starting(stream_id)
        # Cancelled before the worker started; release the owner entry the route
        # layer registered so STREAM_SESSION_OWNERS does not leak (no teardown finally runs).
        unregister_stream_owner(stream_id)
        # Also release the writeback-owner entry the route layer registered, so
        # SESSION_WRITEBACK_OWNERS does not leak on this pre-start cancellation
        # path (the teardown finally below never runs when we early-return here).
        clear_session_writeback_owner_if_owned(session_id, stream_id)
        return
    register_active_run(
        stream_id,
        session_id=session_id,
        started_at=time.time(),
        phase="gateway-starting",
        workspace=str(workspace),
        model=model,
        provider=model_provider,
        backend="gateway",
    )
    try:
        run_journal = RunJournalWriter(session_id, stream_id)
    except Exception:
        run_journal = None
        logger.debug("Failed to initialize gateway run journal for stream %s", stream_id, exc_info=True)
    cancel_event = threading.Event()
    with STREAMS_LOCK:
        CANCEL_FLAGS[stream_id] = cancel_event
        STREAM_PARTIAL_TEXT[stream_id] = ""
        STREAM_REASONING_TEXT[stream_id] = ""
        STREAM_LIVE_TOOL_CALLS[stream_id] = []

    success_writeback_committed = False
    runs_api_pending_marked = True

    def put_gateway_event(event, data):
        if cancel_event.is_set() and not success_writeback_committed and event not in ("cancel", "error", "apperror"):
            return
        if event == "apperror" and isinstance(data, dict):
            data = data.copy()
            data.setdefault("session_id", session_id)
        event_id = None
        if run_journal is not None:
            try:
                journaled = run_journal.append_sse_event(event, data)
                event_id = (journaled or {}).get("event_id") if isinstance(journaled, dict) else None
                if event_id:
                    STREAM_LAST_EVENT_ID[stream_id] = event_id
            except Exception:
                logger.debug("Failed to append gateway event %s for stream %s", event, stream_id, exc_info=True)
        if event_id and hasattr(q, "note_last_event_id"):
            try:
                q.note_last_event_id(event_id)
            except Exception:
                logger.debug("Failed to note gateway event_id %s for stream %s", event_id, stream_id, exc_info=True)
        try:
            queue_item = (event, data, event_id) if event_id and hasattr(q, "subscribe_with_snapshot") else (event, data)
            q.put_nowait(queue_item)
        except Exception:
            logger.debug("Failed to put gateway event to queue")

    s = None
    final_text = ""
    terminal_error = ""
    usage = {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0}
    try:
        s = get_session(session_id)
        from api.config import _load_yaml_config_file, _apply_config_defaults
        from api.profiles import get_hermes_home_for_profile

        # This runs on a detached worker.  Reading ambient get_config() here
        # silently selected the process-wide root profile (and therefore the
        # fallback 127.0.0.1:8642 gateway) for named-profile sessions. Resolve
        # configuration from the persisted session owner explicitly instead.
        profile_home = get_hermes_home_for_profile(getattr(s, "profile", None) or "default")
        # Never use get_config() here, even when thread-local home matches.
        # Its global cache can be replaced by a simultaneous tab/profile request.
        from pathlib import Path
        cfg = _load_yaml_config_file(Path(profile_home) / "config.yaml")
        _apply_config_defaults(cfg)
        reasoning_effort = _gateway_reasoning_effort_for_request(
            cfg,
            model=model,
            model_provider=model_provider,
        )
        base_url = _gateway_base_url(cfg)
        api_key = str(cfg.get("webui_gateway_api_key") or _gateway_api_key())
        try:
            from api.config import _main_model_request_overrides
            _gw_overrides = _main_model_request_overrides(
                cfg,
                effective_model=model,
                effective_provider=model_provider,
            )
        except Exception:
            _gw_overrides = {}
        if _is_jaeger_gateway(base_url):
            try:
                options = {}
                if reasoning_effort:
                    options["reasoning_effort"] = reasoning_effort
                if _gw_overrides:
                    options.update(_gw_overrides)
                final_text, usage = _run_jaeger_gateway_streaming(
                    session_id,
                    msg_text,
                    model,
                    workspace,
                    stream_id,
                    base_url,
                    api_key,
                    attachments=attachments,
                    model_provider=model_provider,
                    options=options,
                    put_gateway_event=put_gateway_event,
                    cancel_event=cancel_event,
                    cfg=cfg,
                    session=s,
                )
            except Exception as exc:
                error_payload = _settle_gateway_terminal_error(
                    session_id,
                    stream_id,
                    workspace,
                    model,
                    model_provider,
                    str(exc),
                )
                if error_payload is not None:
                    put_gateway_event("apperror", error_payload)
            return

        _runs_api_enabled = _gateway_use_runs_api_enabled(cfg)
        _use_runs_api = _runs_api_enabled and gateway_supports_approval(base_url, api_key)
        if not _use_runs_api and runs_api_pending_marked:
            _finish_gateway_run_starting(stream_id, result="fallback")
            runs_api_pending_marked = False
        try:
            from api.streaming import (
                _load_webui_prefill_context,
                _prefill_messages_with_webui_context,
                _normalize_prefill_messages_before_user_turn,
                _public_prefill_context_status,
                _webui_ephemeral_system_prompt,
            )

            prefill_context = _load_webui_prefill_context(cfg)
            # #3324: the WebUI session/delivery context (connected platforms,
            # home channels, delivery hints, session framing) is now carried in
            # the ephemeral system prompt rather than a prefill `user` message.
            # The gateway-backed path must build the SAME system prompt so that
            # context is not silently dropped on Gateway-routed WebUI chats.
            _gateway_system_prompt = _webui_ephemeral_system_prompt(
                None,
                surface_context={
                    "source": "webui",
                    "session_id": session_id,
                    "profile": getattr(s, "profile", None),
                    "workspace": s.workspace if s is not None else str(workspace),
                },
                config_data=cfg,
            )
            prefill_messages = _prefill_messages_with_webui_context(prefill_context, cfg)
            prefill_messages = _normalize_prefill_messages_before_user_turn(prefill_messages)
            prefill_messages = [
                {"role": "system", "content": _gateway_system_prompt},
                *prefill_messages,
            ]
            put_gateway_event("context_status", {
                "session_id": session_id,
                "prefill": _public_prefill_context_status(prefill_context),
            })
        except Exception:
            logger.debug("Failed to load WebUI gateway prefill context", exc_info=True)
            prefill_messages = []
        if _use_runs_api:
            body_extras = {}
            if model_provider:
                body_extras["provider"] = model_provider
            if reasoning_effort is not None:
                body_extras["reasoning_effort"] = reasoning_effort
            if _gw_overrides.get("service_tier"):
                body_extras["service_tier"] = _gw_overrides["service_tier"]
            try:
                final_text, usage = _run_gateway_runs_api_streaming(
                    session_id, msg_text, model, workspace, stream_id,
                    base_url, api_key, prefill_messages, body_extras,
                    put_gateway_event=put_gateway_event,
                    cancel_event=cancel_event,
                    attachments=attachments,
                    cfg=cfg,
                    session=s,
                    active_provider=(model_provider or ""),
                )
            except Exception as exc:
                error_payload = _settle_gateway_terminal_error(
                    session_id,
                    stream_id,
                    workspace,
                    model,
                    model_provider,
                    str(exc),
                )
                if error_payload is None:
                    return
                put_gateway_event("apperror", error_payload)
                return
            if final_text is None:
                return
        else:
            # Legacy gateway path: emit unsupported approval notice once per session,
            # but only when the gateway genuinely lacks approval capability.
            approval_reason = gateway_approval_unavailable_reason(base_url, api_key)
            if approval_reason is not None:
                if not hasattr(s, "_approval_notice_emitted"):
                    s._approval_notice_emitted = False
                if not s._approval_notice_emitted:
                    approval_message = "Approvals require a newer gateway. Upgrade the connected Hermes gateway to enable this."
                    approval_type = "approval_gateway_unsupported"
                    if approval_reason == "unreachable":
                        approval_type = "approval_gateway_offline"
                        approval_message = "Gateway connection failed. Check that the connected Hermes gateway is running and reachable."
                    put_gateway_event("warning", {
                        "type": approval_type,
                        "message": approval_message,
                    })
                    s._approval_notice_emitted = True

            url = f"{base_url}/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "X-Hermes-Session-Id": session_id,
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
                # Scope Gateway long-term continuity to this WebUI conversation
                # without exposing the browser's auth cookie or CSRF material.
                headers["X-Hermes-Session-Key"] = f"webui:{session_id}"
            message_content: Any = str(msg_text or "")
            if attachments:
                try:
                    from api.streaming import _build_native_multimodal_message

                    message_content = _build_native_multimodal_message("", str(msg_text or ""), attachments, str(workspace), cfg=cfg, active_provider=(model_provider or ""), active_model=(model or ""), requested_provider=(model_provider or ""))
                except Exception:
                    logger.debug("Failed to build gateway multimodal attachment payload", exc_info=True)
                    message_content = str(msg_text or "")
            body = {
                "model": _gateway_model_field(model) or "default",
                "stream": True,
                "messages": [*prefill_messages, {"role": "user", "content": message_content}],
            }
            if model_provider:
                body["provider"] = model_provider
            if reasoning_effort is not None:
                body["reasoning_effort"] = reasoning_effort
            if _gw_overrides.get("service_tier"):
                body["service_tier"] = _gw_overrides["service_tier"]
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            update_active_run(stream_id, phase="gateway-request")
            last_payload = {}
            sse_event = "message"
            with urllib.request.urlopen(req, timeout=_gateway_read_timeout_secs()) as resp:
                for raw_line in _iter_sse_lines_cancellable(resp, cancel_event):
                    if cancel_event.is_set():
                        put_gateway_event("cancel", {"message": "Cancelled by user"})
                        return
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        sse_event = "message"
                        continue
                    if line.startswith("event:"):
                        sse_event = line[6:].strip() or "message"
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    _payload_event = str(payload.get("event") or payload.get("type") or sse_event).strip()
                    if _payload_event in {"hermes.approval.request", "approval.request"}:
                        approval_data = _gateway_runs_approval_event(payload)
                        if approval_data:
                            # Record the gateway run_id so /api/approval/respond
                            # can relay the choice back and resume the parked run
                            # (legacy path never creates a local run; without this
                            # the card renders but approve/deny returns ok:false).
                            # No-op when the payload omits run_id.
                            _approval_run_id = str(approval_data.get("run_id") or "").strip()
                            if _approval_run_id:
                                _STREAM_RUN_IDS[stream_id] = _approval_run_id
                            try:
                                from api.route_approvals import submit_gateway_pending_mirror
                                head, total = submit_gateway_pending_mirror(session_id, approval_data)
                                approval_data = {**(head or approval_data), "pending_count": total}
                            except Exception:
                                logger.debug("submit_gateway_pending_mirror failed", exc_info=True)
                            put_gateway_event("approval", approval_data)
                        else:
                            logger.debug("Ignoring malformed gateway approval payload")
                        sse_event = "message"
                        continue
                    if sse_event == "hermes.tool.progress":
                        translated = _gateway_tool_progress_event(payload)
                        if translated:
                            event_name, event_payload = translated
                            if event_name == "reasoning":
                                reason_delta = event_payload.get("text")
                                if reason_delta and stream_id in STREAM_REASONING_TEXT:
                                    STREAM_REASONING_TEXT[stream_id] += reason_delta
                            elif stream_id in STREAM_LIVE_TOOL_CALLS:
                                if event_name == "tool":
                                    STREAM_LIVE_TOOL_CALLS[stream_id].append({
                                        "name": event_payload.get("name"),
                                        "args": event_payload.get("args") or {},
                                        "done": False,
                                        **({"tid": event_payload.get("tid")} if event_payload.get("tid") else {}),
                                    })
                                else:
                                    for shared_tc in reversed(STREAM_LIVE_TOOL_CALLS[stream_id]):
                                        if shared_tc.get("done"):
                                            continue
                                        if (
                                            event_payload.get("tid") and shared_tc.get("tid") == event_payload.get("tid")
                                        ) or shared_tc.get("name") == event_payload.get("name"):
                                            shared_tc["done"] = True
                                            shared_tc["is_error"] = bool(event_payload.get("is_error"))
                                            break
                            put_gateway_event(event_name, event_payload)
                            if event_name != "reasoning":
                                update_active_run(stream_id, phase="gateway-tool", latest_tool=event_payload.get("name"))
                        sse_event = "message"
                        continue
                    if sse_event == "reasoning.available":
                        reason_delta = _gateway_reasoning_delta(payload)
                        if reason_delta:
                            if stream_id in STREAM_REASONING_TEXT:
                                STREAM_REASONING_TEXT[stream_id] += reason_delta
                            put_gateway_event("reasoning", {"text": reason_delta})
                        sse_event = "message"
                        continue
                    last_payload = payload
                    if payload.get("error"):
                        terminal_error = str(payload["error"])
                    reasoning_delta = _gateway_sse_reasoning_delta(payload)
                    if reasoning_delta:
                        if stream_id in STREAM_REASONING_TEXT:
                            STREAM_REASONING_TEXT[stream_id] += reasoning_delta
                        put_gateway_event("reasoning", {"text": reasoning_delta})
                    delta = _gateway_sse_delta(payload)
                    if delta:
                        final_text += delta
                        if stream_id in STREAM_PARTIAL_TEXT:
                            STREAM_PARTIAL_TEXT[stream_id] += delta
                        put_gateway_event("token", {"text": delta})
                    usage.update({k: v for k, v in _gateway_stream_usage(payload).items() if v})
            usage.update({k: v for k, v in _gateway_stream_usage(last_payload).items() if v})
        assistant_text = final_text.strip()
        if terminal_error:
            error_payload = _settle_gateway_terminal_error(
                session_id,
                stream_id,
                workspace,
                model,
                model_provider,
                terminal_error,
            )
            if error_payload is None:
                return
            put_gateway_event("apperror", error_payload)
            return
        if not assistant_text:
            put_gateway_event("apperror", {
                "label": "Gateway returned no response",
                "type": "gateway_empty_response",
                "message": "Gateway returned no assistant message for this turn.",
                "hint": "Check that Hermes Gateway API server is running and reachable.",
            })
            return
        with _get_session_agent_lock(session_id):
            s = get_session(session_id)
            if not _stream_writeback_is_current(s, stream_id):
                return
            # A late Stop can land after Gateway has yielded a full answer but
            # before success writeback. Treat it as cancellation so any
            # credential-exhausted process-wakeup pause stays in place.
            if cancel_event.is_set():
                put_gateway_event("cancel", {"message": "Cancelled by user"})
                return
            now = time.time()
            # Preserve subsecond ordering for gateway-backed turns. Using an
            # integer seconds timestamp gives the user and assistant rows the
            # same sort key; later transcript merges can then fall back to
            # role/content ordering instead of turn order.
            assistant_ts = now + 0.000001
            pending_source = getattr(s, "pending_user_source", None) or "webui"
            from api.streaming import _active_turn_authority, _materialize_active_turn_user

            active_turn_identity = _active_turn_authority(s, stream_id, msg_text)
            user_msg = _materialize_active_turn_user(
                active_turn_identity,
                str(msg_text or ""),
                pending_source,
            )
            user_msg["timestamp"] = float(
                active_turn_identity.get("timestamp") or now
            )
            assistant_msg = {"role": "assistant", "content": assistant_text, "timestamp": assistant_ts}
            saved_reasoning = STREAM_REASONING_TEXT.get(stream_id, "")
            if saved_reasoning:
                assistant_msg["reasoning"] = saved_reasoning
            previous_messages = list(getattr(s, "messages", None) or [])
            stored_context = getattr(s, "context_messages", None)
            previous_context = list(
                stored_context
                if isinstance(stored_context, list) and (regeneration or stored_context)
                else getattr(s, "messages", None) or []
            )
            previous_process_wakeup_pause = dict(getattr(s, "process_wakeup_pause", {}) or {})
            # Stamp stable ids on the two new rows (shared with the display merge
            # below) so display and model-context copies share an id for the
            # fork/truncate aligner (#context-message-stable-id).
            try:
                from api.streaming import _assign_stable_message_ids

                _assign_stable_message_ids(
                    [user_msg, assistant_msg],
                    previous_context,
                    list(getattr(s, "messages", None) or []),
                )
            except Exception:
                logger.debug("Failed to stamp stable ids on gateway turn rows", exc_info=True)
            s.context_messages = previous_context + [user_msg, assistant_msg]
            try:
                from api.streaming import _is_context_compression_marker

                display_context = [
                    msg
                    for msg in previous_context
                    if not _is_context_compression_marker(msg)
                ]
            except Exception:
                logger.debug("Failed to filter gateway display context markers", exc_info=True)
                display_context = previous_context
            display = merge_session_messages_append_only(
                previous_messages,
                display_context,
            )
            try:
                from api.streaming import _merge_display_messages_after_agent_result

                s.messages = _merge_display_messages_after_agent_result(
                    display,
                    previous_context,
                    s.context_messages,
                    str(msg_text or ""),
                    source=pending_source,
                )
            except Exception:
                logger.debug("Failed to merge gateway display transcript", exc_info=True)
                # Avoid duplicating the eager-save checkpointed user message.
                if display:
                    latest = display[-1]
                    if isinstance(latest, dict) and latest.get("role") == "user":
                        latest_text = " ".join(str(latest.get("content") or "").split())
                        msg_norm = " ".join(str(msg_text or "").split())
                        if latest_text == msg_norm:
                            display = display[:-1]
                s.messages = display + [user_msg, assistant_msg]
            s.active_stream_id = None
            s.pending_user_message = None
            s.pending_attachments = None
            s.pending_started_at = None
            s.pending_user_source = None
            s.workspace = str(workspace)
            s.model = model
            s.model_provider = model_provider

            def _restore_cancelled_success_writeback():
                if pending_source == "process_wakeup":
                    s.context_messages = previous_context
                    s.messages = previous_messages
                    s.process_wakeup_pause = dict(previous_process_wakeup_pause)
                elif previous_process_wakeup_pause:
                    s.process_wakeup_pause = dict(previous_process_wakeup_pause)
                else:
                    clear_process_wakeup_pause(s, reason="run_completed")
                s.save()
                put_gateway_event("cancel", {"message": "Cancelled by user"})

            # Recheck immediately before clearing the pause; Stop can arrive
            # while the success transcript is being assembled.
            if cancel_event.is_set():
                _restore_cancelled_success_writeback()
                return
            clear_process_wakeup_pause(s, reason="run_completed")
            if cancel_event.is_set():
                _restore_cancelled_success_writeback()
                return
            s.save()
            if cancel_event.is_set():
                _restore_cancelled_success_writeback()
                return
            success_writeback_committed = True
        try:
            from api.goals import evaluate_goal_after_turn, has_active_goal
            from api.profiles import get_hermes_home_for_profile

            profile_home = get_hermes_home_for_profile(getattr(s, "profile", None))
            if goal_related and has_active_goal(session_id, profile_home=profile_home):
                put_gateway_event("goal", {
                    "session_id": session_id,
                    "state": "evaluating",
                    "message": "Evaluating goal progress…",
                    "message_key": "goal_evaluating_progress",
                })
                decision = evaluate_goal_after_turn(
                    session_id,
                    assistant_text,
                    user_initiated=True,
                    profile_home=profile_home,
                ) or {}
                goal_message = str(decision.get("message") or "").strip()
                if goal_message:
                    put_gateway_event("goal", {
                        "session_id": session_id,
                        "state": "continuing" if decision.get("should_continue") else "idle",
                        "message": goal_message,
                        "message_key": decision.get("message_key") or (
                            "goal_continuing" if goal_message else ""
                        ),
                        "message_args": decision.get("message_args") or [],
                        "decision": decision,
                    })
                if decision.get("should_continue"):
                    continuation_prompt = str(decision.get("continuation_prompt") or "").strip()
                    if continuation_prompt:
                        PENDING_GOAL_CONTINUATION.add(session_id)
                        put_gateway_event("goal_continue", {
                            "session_id": session_id,
                            "continuation_prompt": continuation_prompt,
                            "text": continuation_prompt,
                            "message": goal_message,
                            "message_key": decision.get("message_key") or "goal_continuing",
                            "message_args": decision.get("message_args") or [],
                            "decision": decision,
                        })
        except Exception as goal_exc:
            logger.debug(
                "Gateway goal continuation hook failed for session %s: %s",
                session_id,
                goal_exc,
            )
        from api.streaming import _session_payload_with_full_messages
        gateway_session_payload = _session_payload_with_full_messages(s, tool_calls=[])
        put_gateway_event("done", {"session": redact_session_data(gateway_session_payload), "usage": usage})
        put_gateway_event("stream_end", {"session_id": session_id})
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read(2048).decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        put_gateway_event(
            "apperror",
            _gateway_http_error_event(exc, err_body, api_key_configured=bool(_gateway_api_key())),
        )
    except Exception as exc:
        safe = _redact_text(str(exc))[:500]
        put_gateway_event("apperror", {
            "label": "Gateway request failed",
            "type": "gateway_error",
            "message": safe or "Gateway request failed.",
            "hint": "Check HERMES_WEBUI_GATEWAY_BASE_URL and Gateway API server health.",
        })
    finally:
        mapped_run_id = str(_STREAM_RUN_IDS.get(stream_id) or "").strip()
        if mapped_run_id:
            try:
                from api.route_approvals import retire_gateway_pending_mirror
                retire_gateway_pending_mirror(session_id, run_id=mapped_run_id)
            except Exception:
                logger.debug("Failed to retire gateway pending mirrors during teardown", exc_info=True)
        if s is not None:
            try:
                with _get_session_agent_lock(session_id):
                    _clear_gateway_pending_state(get_session(session_id), stream_id)
            except Exception:
                logger.debug("Failed to clear gateway stream state", exc_info=True)
            _cleanup_gateway_pending_mirror(session_id)
        with STREAMS_LOCK:
            AGENT_INSTANCES.pop(stream_id, None)
            CANCEL_FLAGS.pop(stream_id, None)
            STREAM_GOAL_RELATED.pop(stream_id, None)
            STREAM_PARTIAL_TEXT.pop(stream_id, None)
            STREAM_REASONING_TEXT.pop(stream_id, None)
            STREAM_LIVE_TOOL_CALLS.pop(stream_id, None)
            STREAM_LAST_EVENT_ID.pop(stream_id, None)
            STREAMS.pop(stream_id, None)
        if runs_api_pending_marked and gateway_run_id_pending(stream_id):
            _finish_gateway_run_starting(stream_id)
        _clear_gateway_run_starting(stream_id)
        unregister_stream_owner(stream_id)
        unregister_active_run(stream_id)
        # Release the writeback-owner entry the route layer registered for this
        # Gateway run so SESSION_WRITEBACK_OWNERS does not grow unbounded across
        # the process lifetime (compare-and-clear: only clears if still owned by
        # this stream, mirroring the local streaming teardown).
        clear_session_writeback_owner_if_owned(session_id, stream_id)
