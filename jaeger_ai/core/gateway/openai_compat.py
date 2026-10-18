"""OpenAI-compatible surface on the Jaeger Gateway (phase 1).

For the IDE fork of Copilot Chat (VS Code's Custom Endpoint provider, apiType
``chat-completions``) and anything else that speaks the OpenAI wire format.
It is a translation layer only; Jaeger keeps its own sessions, tools and
approvals:

* ``GET /v1/models`` lists ``jaeger`` (the Gateway's current model) and
  ``jaeger/<model>`` for every reachable model in ``/v1/runtime/models``.
* ``POST /v1/chat/completions`` maps onto the Gateway's own API:
  ``POST /v1/sessions`` → ``POST /v1/sessions/{id}/turns`` → the session's
  SSE stream → ``chat.completion.chunk`` events ending in ``data: [DONE]``
  (or one ``chat.completion`` object when ``stream`` is false).

The calls go back through this Gateway over loopback with the caller's own
bearer token, so the same caller auth, scopes, Stop and lease checks apply
as for any other client; nothing here bypasses them.

Phase 1 reports ``toolCalling: false``. Jaeger runs its tools server-side;
mapping VS Code's tool round-trip is phase 2, so ``tools`` in a request is
ignored.

Sessions: a stable conversation key (``X-Jaeger-Session-Id`` header, else the
OpenAI ``user`` field) reuses one Gateway session and only the newest user
message is sent, because the Gateway already holds the history. Without a
key every request gets a fresh session and the earlier messages are folded
into the turn text so the model still sees the conversation.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from aiohttp import ClientSession, ClientTimeout, web

MODEL_PREFIX = "jaeger"
SESSION_HEADER = "X-Jaeger-Session-Id"
SESSION_PREFIX = "openai-"
TERMINAL_EVENTS = frozenset({
    "turn.finish", "turn.failed", "turn.cancelled", "turn.unknown", "turn.reconciled",
})
DONE = b"data: [DONE]\n\n"
CAPABILITIES = {"toolCalling": False, "vision": False}


class CompatError(Exception):
    """A request the adapter refuses, with the OpenAI-style status and type."""

    def __init__(self, message: str, status: int = 400, kind: str = "invalid_request_error") -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind


# ── pure mapping (unit-tested) ─────────────────────────────────────────────


def error_body(message: str, kind: str = "invalid_request_error", code: str | None = None) -> dict[str, Any]:
    return {"error": {"message": message, "type": kind, "param": None, "code": code}}


def models_payload(runtime_models: dict[str, Any], created: int | None = None) -> dict[str, Any]:
    """OpenAI ``/v1/models`` list from the Gateway's ``/v1/runtime/models``."""
    created = int(time.time()) if created is None else int(created)
    entries = [_model_entry(MODEL_PREFIX, "jaeger", created)]
    seen = {MODEL_PREFIX}
    catalog = runtime_models.get("webui_catalog") if isinstance(runtime_models, dict) else None
    groups = (catalog or {}).get("groups") if isinstance(catalog, dict) else None
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        owner = str(group.get("provider_id") or group.get("provider") or "jaeger")
        for model in group.get("models") or []:
            name = str((model or {}).get("id") or "").strip() if isinstance(model, dict) else ""
            model_id = f"{MODEL_PREFIX}/{name}"
            if name and model_id not in seen:
                seen.add(model_id)
                entries.append(_model_entry(model_id, owner, created))
    return {"object": "list", "data": entries}


def _model_entry(model_id: str, owner: str, created: int) -> dict[str, Any]:
    return {"id": model_id, "object": "model", "created": created, "owned_by": owner,
            "capabilities": dict(CAPABILITIES)}


def requested_model(model: Any) -> str | None:
    """``jaeger`` → no override; ``jaeger/<model>`` → ``<model>``."""
    value = str(model or "").strip()
    if not value or value == MODEL_PREFIX:
        return None
    if value.startswith(MODEL_PREFIX + "/"):
        return value[len(MODEL_PREFIX) + 1:] or None
    raise CompatError(f"Unknown model {value!r}; use 'jaeger' or an id from /v1/models",
                      status=404, kind="invalid_request_error")


def message_text(content: Any) -> str:
    """Text of an OpenAI message ``content`` (string or list of parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") in {"text", "input_text"}:
                parts.append(str(part.get("text") or ""))
        return "\n".join(p for p in parts if p)
    return str(content)


@dataclass(frozen=True)
class ChatPlan:
    session_id: str
    reuse: bool
    text: str
    title: str
    model: str | None
    stream: bool


def session_id_for_key(key: str) -> str:
    return SESSION_PREFIX + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def map_chat_request(body: Any, headers: Any = None) -> ChatPlan:
    """Validate an OpenAI chat request and decide what the Gateway is sent."""
    if not isinstance(body, dict):
        raise CompatError("Body must be a JSON object")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise CompatError("'messages' must be a non-empty list")
    rows: list[tuple[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise CompatError("Each message must be an object")
        role = str(message.get("role") or "").strip()
        if role not in {"system", "developer", "user", "assistant", "tool"}:
            raise CompatError(f"Unsupported message role {role!r}")
        rows.append((role, message_text(message.get("content")).strip()))
    last_user = next((i for i in range(len(rows) - 1, -1, -1) if rows[i][0] == "user" and rows[i][1]), None)
    if last_user is None:
        raise CompatError("No user message with text to send")
    model = requested_model(body.get("model"))
    header_key = ""
    if headers is not None:
        header_key = str(headers.get(SESSION_HEADER) or "").strip()
    key = header_key or str(body.get("user") or "").strip()
    latest = rows[last_user][1]
    title = latest.splitlines()[0][:60] or "OpenAI-compatible chat"
    if key:
        return ChatPlan(session_id_for_key(key), True, latest, title, model, bool(body.get("stream")))
    earlier = [(r, t) for r, t in rows[:last_user] if t]
    if earlier:
        transcript = "\n\n".join(f"[{role}]\n{text}" for role, text in earlier)
        text = f"Conversation so far:\n\n{transcript}\n\n[user]\n{latest}"
    else:
        text = latest
    return ChatPlan(SESSION_PREFIX + uuid.uuid4().hex, False, text, title, model, bool(body.get("stream")))


def chunk(completion_id: str, model: str, created: int, *, content: str | None = None,
          role: str | None = None, finish_reason: str | None = None) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    return {
        "id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def completion(completion_id: str, model: str, created: int, text: str) -> dict[str, Any]:
    return {
        "id": completion_id, "object": "chat.completion", "created": created, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": "stop"}],
        "usage": None,
    }


def remaining_text(streamed: str, final: str) -> str:
    """What to send after the stream so the client ends with the final answer.

    Streamed deltas are provisional. If the final output extends them, send the
    rest; if nothing streamed, send it all; if they diverged, nothing can be
    retracted over SSE, so nothing more is sent (the turn record keeps the truth).
    """
    if not final:
        return ""
    if not streamed:
        return final
    if final.startswith(streamed):
        return final[len(streamed):]
    return ""


# ── the Gateway behind the adapter ─────────────────────────────────────────


class Upstream(Protocol):
    async def runtime_models(self) -> dict[str, Any]: ...
    async def ensure_session(self, session_id: str, title: str) -> None: ...
    async def send_turn(self, session_id: str, text: str, model: str | None) -> dict[str, Any]: ...
    def events(self, session_id: str, since: int) -> AsyncIterator[tuple[int, str, dict[str, Any]]]: ...
    async def request_result(self, session_id: str, request_id: str) -> dict[str, Any]: ...
    async def cancel(self, session_id: str, request_id: str) -> None: ...
    async def close(self) -> None: ...


class UpstreamError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class LoopbackGateway:
    """This Gateway's own API over loopback, presenting the caller's token."""

    def __init__(self, base_url: str, authorization: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": authorization, "Accept": "application/json"}
        self._http = ClientSession(timeout=ClientTimeout(total=None, sock_connect=10))

    async def close(self) -> None:
        await self._http.close()

    async def _json(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._http.request(method, self.base_url + path, json=body, headers=self._headers,
                                      timeout=ClientTimeout(total=30)) as resp:
            try:
                payload = await resp.json(content_type=None)
            except Exception:  # noqa: BLE001 - non-JSON upstream answer
                payload = {"error": (await resp.text())[:300]}
            if resp.status >= 400:
                raise UpstreamError(resp.status, str((payload or {}).get("error") or f"HTTP {resp.status}"))
            return payload if isinstance(payload, dict) else {"result": payload}

    async def runtime_models(self) -> dict[str, Any]:
        return await self._json("GET", "/v1/runtime/models")

    async def ensure_session(self, session_id: str, title: str) -> None:
        await self._json("POST", "/v1/sessions", {
            "session_id": session_id, "title": title, "profile": "jaeger", "source": "api",
            "metadata": {"client": "openai-compat"},
        })

    async def send_turn(self, session_id: str, text: str, model: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text, "request_id": uuid.uuid4().hex}
        if model:
            body["model"] = model
        receipt = await self._json("POST", f"/v1/sessions/{session_id}/turns", body)
        return {**receipt, "request_id": receipt.get("request_id") or body["request_id"]}

    async def events(self, session_id: str, since: int) -> AsyncIterator[tuple[int, str, dict[str, Any]]]:
        url = f"{self.base_url}/v1/sessions/{session_id}/stream?last_event_id={since}"
        headers = {**self._headers, "Accept": "text/event-stream"}
        async with self._http.get(url, headers=headers, timeout=ClientTimeout(total=None, sock_read=None)) as resp:
            if resp.status >= 400:
                raise UpstreamError(resp.status, f"stream HTTP {resp.status}")
            async for raw in resp.content:
                if not raw.startswith(b"data: "):
                    continue
                try:
                    record = json.loads(raw[6:])
                except ValueError:
                    continue
                data = record.get("data") if isinstance(record.get("data"), dict) else {}
                yield int(record.get("event_id") or since), str(record.get("event") or ""), data

    async def request_result(self, session_id: str, request_id: str) -> dict[str, Any]:
        return await self._json("GET", f"/v1/sessions/{session_id}/requests/{request_id}")

    async def cancel(self, session_id: str, request_id: str) -> None:
        try:
            await self._json("POST", f"/v1/sessions/{session_id}/cancel", {"request_id": request_id})
        except Exception:  # noqa: BLE001 - best effort when the client went away
            pass


UPSTREAM_FACTORY_KEY: web.AppKey[Any] = web.AppKey("jaeger.openai_compat.upstream", object)


def _loopback_base(request: web.Request) -> str:
    sockname = request.transport.get_extra_info("sockname") if request.transport else None
    host, port = "127.0.0.1", request.url.port
    if isinstance(sockname, tuple) and len(sockname) >= 2:
        bound, port = str(sockname[0]), int(sockname[1])
        if bound not in {"0.0.0.0", "::", ""}:
            host = bound
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def _upstream(request: web.Request) -> Upstream:
    factory = request.app.get(UPSTREAM_FACTORY_KEY)
    authorization = request.headers.get("Authorization", "")
    if factory is not None:
        return factory(request, authorization)
    return LoopbackGateway(_loopback_base(request), authorization)


def _error(message: str, status: int, kind: str = "invalid_request_error") -> web.Response:
    return web.json_response(error_body(message, kind), status=status)


def _kind_for(status: int) -> str:
    return {401: "authentication_error", 403: "permission_error", 404: "not_found_error",
            409: "conflict_error", 423: "unavailable_error"}.get(status, "api_error")


# ── handlers ───────────────────────────────────────────────────────────────


async def handle_models(request: web.Request) -> web.Response:
    upstream = _upstream(request)
    try:
        runtime = await upstream.runtime_models()
    except UpstreamError as exc:
        return _error(str(exc), exc.status, _kind_for(exc.status))
    finally:
        await upstream.close()
    return web.json_response(models_payload(runtime))


async def handle_chat_completions(request: web.Request) -> web.StreamResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _error("Body must be JSON", 400)
    try:
        plan = map_chat_request(body, request.headers)
    except CompatError as exc:
        return _error(str(exc), exc.status, exc.kind)
    model_name = str(body.get("model") or MODEL_PREFIX)
    completion_id = "chatcmpl-" + uuid.uuid4().hex
    created = int(time.time())
    upstream = _upstream(request)
    try:
        try:
            await upstream.ensure_session(plan.session_id, plan.title)
            receipt = await upstream.send_turn(plan.session_id, plan.text, plan.model)
        except UpstreamError as exc:
            return _error(str(exc), exc.status, _kind_for(exc.status))
        rid = str(receipt["request_id"])
        cursor = max(int(receipt.get("start_event_id") or 1) - 1, 0)
        if plan.stream:
            return await _stream(request, upstream, plan, rid, cursor, completion_id, model_name, created)
        return await _collect(upstream, plan, rid, cursor, completion_id, model_name, created)
    finally:
        await upstream.close()


async def _follow(upstream: Upstream, session_id: str, rid: str, cursor: int
                  ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """This request's events, in order, through its terminal one."""
    async for _event_id, name, data in upstream.events(session_id, cursor):
        if data.get("request_id") != rid:
            continue
        yield name, data
        if name in TERMINAL_EVENTS:
            return


async def _final(upstream: Upstream, session_id: str, rid: str) -> tuple[str, str, str | None]:
    row = await upstream.request_result(session_id, rid)
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    return str(row.get("status") or ""), str(result.get("output") or ""), result.get("error")


async def _collect(upstream: Upstream, plan: ChatPlan, rid: str, cursor: int,
                   completion_id: str, model: str, created: int) -> web.Response:
    terminal = ""
    try:
        async for name, _data in _follow(upstream, plan.session_id, rid, cursor):
            terminal = name
        status, output, error = await _final(upstream, plan.session_id, rid)
    except UpstreamError as exc:
        return _error(str(exc), exc.status, _kind_for(exc.status))
    if status != "completed":
        return _error(str(error or f"Jaeger turn ended {status or terminal or 'without a result'}"), 502,
                      "api_error")
    response = web.json_response(completion(completion_id, model, created, output))
    response.headers[SESSION_HEADER] = plan.session_id
    return response


async def _stream(request: web.Request, upstream: Upstream, plan: ChatPlan, rid: str, cursor: int,
                  completion_id: str, model: str, created: int) -> web.StreamResponse:
    response = web.StreamResponse(status=200, headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-cache", SESSION_HEADER: plan.session_id,
    })
    await response.prepare(request)
    streamed: list[str] = []
    finished = False
    try:
        await response.write(sse(chunk(completion_id, model, created, role="assistant", content="")))
        async for name, data in _follow(upstream, plan.session_id, rid, cursor):
            if name == "turn.delta":
                piece = str(data.get("delta") or "")
                if piece:
                    streamed.append(piece)
                    await response.write(sse(chunk(completion_id, model, created, content=piece)))
        status, output, error = await _final(upstream, plan.session_id, rid)
        if status == "completed":
            tail = remaining_text("".join(streamed), output)
            if tail:
                await response.write(sse(chunk(completion_id, model, created, content=tail)))
        else:
            await response.write(sse(error_body(
                str(error or f"Jaeger turn ended {status or 'without a result'}"), "api_error")))
        await response.write(sse(chunk(completion_id, model, created, finish_reason="stop")))
        await response.write(DONE)
        finished = True
    except UpstreamError as exc:
        await response.write(sse(error_body(str(exc), _kind_for(exc.status))))
        await response.write(DONE)
        finished = True
    except (ConnectionResetError, OSError):
        pass
    finally:
        if not finished:
            await upstream.cancel(plan.session_id, rid)
    return response


def register(app: web.Application) -> None:
    """Add the OpenAI-compatible routes to the Gateway app."""
    app.router.add_get("/v1/models", handle_models)
    app.router.add_post("/v1/chat/completions", handle_chat_completions)


__all__ = [
    "CAPABILITIES", "ChatPlan", "CompatError", "DONE", "LoopbackGateway", "SESSION_HEADER",
    "UPSTREAM_FACTORY_KEY", "chunk", "completion", "error_body", "map_chat_request",
    "message_text", "models_payload", "register", "remaining_text", "requested_model",
    "session_id_for_key", "sse",
]
