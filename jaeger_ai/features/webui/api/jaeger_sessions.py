"""Proxy WebUI ``/api/jaeger/sessions*`` to Jaeger Gateway :8810 ``/v1/sessions*``.

Companion to ``jaeger_agents.py``, which already proxies ``/v1/agents*`` and
``/v1/handoffs``. Sessions, the SSE event stream and approvals had no proxy,
so the browser had no route to the conversation spine at all — it could list
agents and nothing else.

Browser clients on :8790 cannot reach loopback :8810, so the WebUI process
proxies server-side. Routes mirror the gateway exactly (audited from
``core/gateway/server.py``); nothing is invented:

    GET    /v1/sessions[?profile=]          list
    POST   /v1/sessions                     create
    GET    /v1/sessions/{id}                fetch
    DELETE /v1/sessions/{id}                delete
    POST   /v1/sessions/{id}/turns          send a turn
    POST   /v1/sessions/{id}/cancel         cancel in-flight
    POST   /v1/sessions/{id}/reconcile      reconcile after a drop
    GET    /v1/sessions/{id}/requests/{rid} request status
    GET    /v1/sessions/{id}/stream         SSE events  ← streamed, not buffered
    POST   /v1/approvals/{id}               resolve an approval
    GET    /v1/approvals                    list pending approvals
    GET    /health                          gateway liveness (NOT /v1/health)

Errors are surfaced, never swallowed. A gateway that is down returns 503
with the reason attached so the UI can say "gateway unreachable" instead of
rendering an empty session list that looks like "no conversations yet".
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

#: Read timeout for unary calls. The SSE stream deliberately does not use
#: this — it is long-lived by design and must not be cut off mid-turn.
UNARY_TIMEOUT = 8

#: How long the SSE proxy waits for the first byte from the gateway. After
#: that the stream is pumped until either side closes.
STREAM_CONNECT_TIMEOUT = 10


def gateway_base() -> str:
    return (
        os.environ.get("JAEGER_GATEWAY_URL")
        or os.environ.get("HERMES_WEBUI_GATEWAY_URL")
        or "http://127.0.0.1:8810"
    ).rstrip("/")


# ── unary proxy ──────────────────────────────────────────────────────


def _proxy(handler, method: str, path: str, body: bytes | None = None) -> bool:
    """Forward one request and relay the gateway's status verbatim."""
    from api.helpers import bad, j

    url = f"{gateway_base()}{path}"
    data = body if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} else None
    req = Request(url, data=data, method=method.upper())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=UNARY_TIMEOUT) as resp:
            payload = resp.read()
            try:
                parsed = json.loads(payload.decode("utf-8") or "null")
            except json.JSONDecodeError:
                bad(handler, "gateway returned non-JSON", 502)
                return True
            j(handler, parsed, status=int(getattr(resp, "status", 200) or 200))
            return True
    except HTTPError as exc:
        # Relay the gateway's own error body and status. A 409 (turn already
        # in flight) and a 410 (resume cursor expired) both mean something
        # specific to the UI; flattening them to 500 would lose that.
        raw = exc.read() or b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            parsed = {"error": exc.reason}
        j(handler, parsed, status=int(exc.code))
        return True
    except (URLError, OSError) as exc:
        bad(handler, f"gateway unreachable at {gateway_base()}: {exc}", 503)
        return True


def _body_bytes(handler) -> bytes:
    """The raw JSON body, however the WebUI happened to buffer it."""
    from api.helpers import read_body

    raw = getattr(handler, "_json_body_bytes", None)
    if raw:
        return raw
    return json.dumps(read_body(handler) or {}).encode("utf-8")


# ── SSE streaming proxy ──────────────────────────────────────────────


def _proxy_stream(handler, session_id: str, query: str) -> bool:
    """Pump the gateway's SSE stream straight through to the browser.

    Deliberately NOT built on ``_proxy``: that reads the whole body before
    replying, which for an event stream means buffering forever and
    delivering nothing. Chunks are relayed as they arrive so a turn renders
    token by token.

    Framing is preserved byte-for-byte (``id:`` / ``event:`` / ``data:``) so
    the browser's own ``EventSource`` handles resume via ``Last-Event-ID``
    without this layer having to understand the payloads.

    Failures are reported IN-BAND as a synthetic ``gateway.error`` event
    once the stream has started, because headers are already sent by then
    and an HTTP status is no longer available. The UI listens for it and
    shows a disconnected state rather than a silently stalled stream.
    """
    url = f"{gateway_base()}/v1/sessions/{session_id}/stream{query}"
    req = Request(url, method="GET")
    req.add_header("Accept", "text/event-stream")
    req.add_header("Cache-Control", "no-cache")

    try:
        upstream = urlopen(req, timeout=STREAM_CONNECT_TIMEOUT)
    except HTTPError as exc:
        # Still pre-headers, so a real status can be returned. 410 here is
        # the gateway saying the resume cursor aged out — the UI must
        # restart the stream from 0 rather than retry the same cursor.
        from api.helpers import j

        raw = exc.read() or b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            parsed = {"error": exc.reason}
        j(handler, parsed, status=int(exc.code))
        return True
    except (URLError, OSError) as exc:
        from api.helpers import bad

        bad(handler, f"gateway unreachable at {gateway_base()}: {exc}", 503)
        return True

    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")  # defeat proxy buffering
    handler.end_headers()

    try:
        while True:
            chunk = upstream.read(1)
            if not chunk:
                break
            # Read whatever else is buffered without blocking on more.
            pending = getattr(upstream, "fp", None)
            if pending is not None:
                try:
                    extra = upstream.read(len(getattr(pending, "_rbuf", b"")) or 0)
                    if extra:
                        chunk += extra
                except Exception:  # noqa: BLE001 — best-effort batching only
                    pass
            handler.wfile.write(chunk)
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        # The browser navigated away or closed the tab. Normal.
        pass
    except Exception as exc:  # noqa: BLE001 — report in-band, never silently stop
        try:
            payload = json.dumps({"error": str(exc), "source": "webui-proxy"})
            handler.wfile.write(
                f"event: gateway.error\ndata: {payload}\n\n".encode("utf-8")
            )
            handler.wfile.flush()
        except Exception:  # noqa: BLE001 — socket already gone
            pass
    finally:
        try:
            upstream.close()
        except Exception:  # noqa: BLE001
            pass
    return True


# ── dispatch ─────────────────────────────────────────────────────────

PREFIXES = ("/api/jaeger/sessions", "/v1/sessions")


def route(handler, parsed, method: str) -> bool:
    """Dispatch a WebUI request to the gateway. ``False`` = not ours.

    Mirrors ``jaeger_agents.route``'s contract so the WebUI's dispatcher
    can try each overlay in turn.
    """
    path = parsed.path
    query = f"?{parsed.query}" if parsed.query else ""

    try:
        from api.remote_phone import route as _remote_route
        if _remote_route(handler, parsed, method):
            return True
    except Exception:
        pass

    if path in ("/api/jaeger/gateway/health", "/api/jaeger/health"):
        # The gateway serves /health, NOT /v1/health — the latter 404s.
        return _proxy(handler, "GET", "/health")

    if path in ("/api/jaeger/runtime/status", "/api/runtime/status"):
        return _proxy(handler, "GET", "/v1/runtime/status")

    if method == "GET" and path in ("/api/jaeger/approvals", "/v1/approvals"):
        return _proxy(handler, "GET", "/v1/approvals")

    if method == "POST" and path.startswith("/api/jaeger/approvals/"):
        approval_id = path.rsplit("/", 1)[-1]
        if not approval_id:
            from api.helpers import bad

            bad(handler, "missing approval id", 400)
            return True
        return _proxy(handler, "POST", f"/v1/approvals/{approval_id}", _body_bytes(handler))

    if not any(path.startswith(p) for p in PREFIXES):
        return False

    # Normalise either prefix down to the gateway's own suffix.
    for prefix in PREFIXES:
        if path.startswith(prefix):
            suffix = path[len(prefix):].strip("/")
            break

    # /v1/sessions
    if not suffix:
        if method == "GET":
            return _proxy(handler, "GET", f"/v1/sessions{query}")
        if method == "POST":
            return _proxy(handler, "POST", "/v1/sessions", _body_bytes(handler))
        return False

    parts = suffix.split("/")
    session_id = parts[0]

    # /v1/sessions/{id}/stream — long-lived, handled separately
    if len(parts) == 2 and parts[1] == "stream" and method == "GET":
        return _proxy_stream(handler, session_id, query)

    # /v1/sessions/{id}/{turns|cancel|reconcile}
    if len(parts) == 2 and method == "POST" and parts[1] in {"turns", "cancel", "reconcile"}:
        return _proxy(
            handler, "POST", f"/v1/sessions/{session_id}/{parts[1]}", _body_bytes(handler),
        )

    # /v1/sessions/{id}/handoff
    if len(parts) == 2 and method == "POST" and parts[1] == "handoff":
        return _proxy(
            handler, "POST", f"/v1/sessions/{session_id}/handoff", _body_bytes(handler),
        )

    # /v1/sessions/{id}/requests/{request_id}
    if len(parts) == 3 and parts[1] == "requests" and method == "GET":
        return _proxy(
            handler, "GET", f"/v1/sessions/{session_id}/requests/{parts[2]}",
        )

    # /v1/sessions/{id}
    if len(parts) == 1:
        if method == "GET":
            return _proxy(handler, "GET", f"/v1/sessions/{session_id}")
        if method == "DELETE":
            return _proxy(handler, "DELETE", f"/v1/sessions/{session_id}")

    return False


__all__ = ["PREFIXES", "gateway_base", "route"]
