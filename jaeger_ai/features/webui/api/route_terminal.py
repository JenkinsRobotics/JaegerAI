"""Terminal API routes and helper functions.

Decomposed from routes.py for modular WebUI backend architecture.
Handles starting PTY sessions, writing input, resizing, closing, and streaming SSE terminal output.
"""
from __future__ import annotations

import logging
from pathlib import Path
import queue
from typing import Any
from urllib.parse import parse_qs

from .config import get_config
from .helpers import bad, j, require, _sanitize_error
from .sse_chunked import end_sse_headers
from .streaming import _sse, _sse_set_write_deadline
from .workspace import _is_remote_terminal_backend, resolve_trusted_workspace

logger = logging.getLogger("hermes.webui")

_REMOTE_TERMINAL_BACKEND_UNSUPPORTED_ERROR = "remote_terminal_backend_unsupported"
_REMOTE_TERMINAL_BACKEND_UNSUPPORTED_MESSAGE = (
    "Embedded terminal is only supported for local terminal backends."
)
_EMBEDDED_TERMINAL_GATE_DENIED_MESSAGE = (
    "Embedded terminal is only available from local networks when authentication "
    "is not configured. Configure a password/passkey, or set "
    "HERMES_WEBUI_ONBOARDING_OPEN=1 to allow it on a deliberately-exposed server."
)
_SSE_HEARTBEAT_INTERVAL_SECONDS = 5


def _get_session(session_id: str):
    try:
        from api.models import get_session
        return get_session(session_id)
    except Exception:
        from .models import get_session
        return get_session(session_id)


def _terminal_session_lookup(body_or_query: dict) -> tuple[str, Any]:
    sid = str(body_or_query.get("session_id", "")).strip()
    if not sid:
        raise ValueError("session_id required")
    try:
        s = _get_session(sid)
    except KeyError:
        raise KeyError("Session not found")
    return sid, s


def _terminal_remote_backend_enabled() -> bool:
    terminal_cfg = get_config().get("terminal", {})
    return _is_remote_terminal_backend(terminal_cfg)


def _embedded_terminal_gate_allows(handler: Any) -> bool:
    try:
        from api.routes import _embedded_terminal_gate_allows as gate_check
        return gate_check(handler)
    except Exception:
        return True


def _sse_with_id(handler: Any, event: str, data: Any, event_id: Any = None) -> None:
    if event_id:
        handler.wfile.write(f"id: {event_id}\n".encode("utf-8"))
    _sse(handler, event, data)


def handle_terminal_start(handler: Any, body: dict) -> bool:
    try:
        if not _embedded_terminal_gate_allows(handler):
            return bad(handler, _EMBEDDED_TERMINAL_GATE_DENIED_MESSAGE, 403)
        sid, session = _terminal_session_lookup(body)
        if _terminal_remote_backend_enabled():
            return j(
                handler,
                {
                    "error": _REMOTE_TERMINAL_BACKEND_UNSUPPORTED_ERROR,
                    "message": _REMOTE_TERMINAL_BACKEND_UNSUPPORTED_MESSAGE,
                },
                status=400,
            )
        workspace = resolve_trusted_workspace(getattr(session, "workspace", "") or "")
        try:
            from api.terminal import start_terminal
        except Exception:
            from .terminal import start_terminal

        term = start_terminal(
            sid,
            workspace,
            rows=int(body.get("rows") or 24),
            cols=int(body.get("cols") or 80),
            restart=bool(body.get("restart")),
        )
        return j(
            handler,
            {
                "ok": True,
                "session_id": sid,
                "workspace": term.workspace,
                "running": term.is_alive(),
            },
        )
    except KeyError as e:
        return bad(handler, str(e), 404)
    except ValueError as e:
        return bad(handler, str(e), 400)
    except Exception as e:
        return bad(handler, _sanitize_error(e), 500)


def handle_terminal_input(handler: Any, body: dict) -> bool:
    try:
        if not _embedded_terminal_gate_allows(handler):
            return bad(handler, _EMBEDDED_TERMINAL_GATE_DENIED_MESSAGE, 403)
        require(body, "session_id")
        data = str(body.get("data", ""))
        if len(data) > 8192:
            return bad(handler, "input too large", 413)
        try:
            from api.terminal import write_terminal
        except Exception:
            from .terminal import write_terminal

        write_terminal(body["session_id"], data)
        return j(handler, {"ok": True})
    except KeyError as e:
        return bad(handler, str(e), 404)
    except ValueError as e:
        return bad(handler, str(e), 400)
    except Exception as e:
        return bad(handler, _sanitize_error(e), 500)


def handle_terminal_resize(handler: Any, body: dict) -> bool:
    try:
        if not _embedded_terminal_gate_allows(handler):
            return bad(handler, _EMBEDDED_TERMINAL_GATE_DENIED_MESSAGE, 403)
        require(body, "session_id")
        try:
            from api.terminal import resize_terminal
        except Exception:
            from .terminal import resize_terminal

        resize_terminal(
            body["session_id"],
            rows=int(body.get("rows") or 24),
            cols=int(body.get("cols") or 80),
        )
        return j(handler, {"ok": True})
    except KeyError as e:
        return bad(handler, str(e), 404)
    except ValueError as e:
        return bad(handler, str(e), 400)
    except Exception as e:
        return bad(handler, _sanitize_error(e), 500)


def handle_terminal_close(handler: Any, body: dict) -> bool:
    try:
        if not _embedded_terminal_gate_allows(handler):
            return bad(handler, _EMBEDDED_TERMINAL_GATE_DENIED_MESSAGE, 403)
        require(body, "session_id")
        try:
            from api.terminal import close_terminal
        except Exception:
            from .terminal import close_terminal

        closed = close_terminal(body["session_id"])
        return j(handler, {"ok": True, "closed": closed})
    except ValueError as e:
        return bad(handler, str(e), 400)


def handle_terminal_output(handler: Any, parsed: Any) -> bool:
    if not _embedded_terminal_gate_allows(handler):
        return bad(handler, _EMBEDDED_TERMINAL_GATE_DENIED_MESSAGE, 403)
    qs = parse_qs(parsed.query)
    sid = qs.get("session_id", [""])[0]
    if not sid:
        return bad(handler, "session_id required")
    try:
        from api.terminal import attach_terminal
    except Exception:
        from .terminal import attach_terminal

    after_seq = None
    last_event_id = str(handler.headers.get("Last-Event-ID", "") or "").strip()
    if last_event_id:
        try:
            after_seq = max(0, int(last_event_id))
        except ValueError:
            pass

    attached = attach_terminal(sid, after_seq=after_seq)
    if attached is None:
        return j(handler, {"error": "terminal not running"}, status=404)
    term, output = attached

    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("X-Accel-Buffering", "no")
        handler.send_header("Connection", "close")
        end_sse_headers(handler)
        _sse_set_write_deadline(handler)
        while True:
            try:
                event_seq, event, data = output.get(timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                handler.wfile.write(b": terminal heartbeat\n\n")
                handler.wfile.flush()
                if term.closed.is_set() and output.empty():
                    _sse(handler, "terminal_closed", {"exit_code": term.proc.poll()})
                    break
                continue
            _sse_with_id(handler, event, data, event_id=event_seq)
            if event in ("terminal_closed", "terminal_error"):
                break
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        pass
    finally:
        term.unsubscribe(output)
    return True

