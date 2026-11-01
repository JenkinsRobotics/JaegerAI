"""A2A protocol surface for JaegerAI.

Ports the official ``a2a-sdk`` AgentCard + JSON-RPC routes that already
worked in ARES. The executor body is Jaeger: it drives the live instance
bridge (``BridgeClient.turn``) instead of ARES AutomationService.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import threading
from typing import Any

from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import TaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    Part,
    SecurityRequirement,
    SecurityScheme,
    StringList,
    TaskState,
)
from starlette.applications import Starlette
from starlette.routing import Route

from jaeger_ai.contract.ports import A2A_PORT, A2A_URL, LOOPBACK

A2A_PROTOCOL_VERSION = "1.0"
#: The same endpoint also serves v0.3 JSON-RPC (``enable_v0_3_compat``), so the
#: card advertises it as a second interface at no cost.
A2A_COMPAT_PROTOCOL_VERSION = "0.3"
A2A_BEARER_SCHEME = "bearer"
CANCEL_CONFIRM_TIMEOUT_S = float(os.environ.get("JAEGER_A2A_CANCEL_CONFIRM_S", "30"))
A2A_HOST = LOOPBACK
A2A_PUBLIC_URL = A2A_URL


def build_agent_card() -> AgentCard:
    public_url = os.environ.get("JAEGER_A2A_PUBLIC_URL", A2A_PUBLIC_URL).strip() or A2A_PUBLIC_URL
    return AgentCard(
        name="Jaeger",
        description=(
            "JaegerAI reasoning runtime. Chat and task delegation go through "
            "the live instance bridge; Jaeger remains the sole reasoner."
        ),
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False,
                                       extended_agent_card=False),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=public_url,
                           protocol_version=A2A_PROTOCOL_VERSION),
            AgentInterface(protocol_binding="JSONRPC", url=public_url,
                           protocol_version=A2A_COMPAT_PROTOCOL_VERSION),
        ],
        security_schemes={
            A2A_BEARER_SCHEME: SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="Bearer",
                description="Jaeger Gateway caller token (loopback; issued by `jaeger auth init`).",
            )),
        },
        security_requirements=[SecurityRequirement(schemes={A2A_BEARER_SCHEME: StringList(list=[])})],
        skills=[
            AgentSkill(
                id="chat",
                name="Chat",
                description="Send a message to the live Jaeger agent and return its reply.",
                input_modes=["text/plain"],
                output_modes=["text/plain"],
                tags=["chat", "jaeger"],
                examples=["What is the current instance status?", "Summarize the latest run"],
            ),
            AgentSkill(
                id="delegate",
                name="Delegate",
                description=(
                    "Ask Jaeger to handle a task, including routing through "
                    "delegate_task when the reasoner decides to fan work out."
                ),
                input_modes=["text/plain"],
                output_modes=["text/plain"],
                tags=["delegation", "coordination"],
                examples=["delegate: review this diff", "Plan and dispatch the remaining board work"],
            ),
        ],
    )


class JaegerBridgeExecutor(AgentExecutor):
    """Translate A2A tasks into live Jaeger bridge turns."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active: dict[str, dict[str, Any]] = {}
        self._active_lock = threading.RLock()

    def _bridge(self) -> Any:
        if self._client is not None:
            return self._client
        from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge

        self._client = jaeger_bridge()
        return self._client

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)

        message = get_message_text(context.message) or ""
        objective = message.strip()
        if not objective:
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message("A text request is required."),
            )
            return

        await updater.update_status(
            state=TaskState.TASK_STATE_WORKING,
            message=new_text_message("Jaeger is working the A2A task over the live bridge."),
        )
        session = f"a2a:{task.context_id or task.id}"
        # A2A task id == Gateway request id: the bridge hands ``turn_id`` to
        # the Gateway as ``request_id``, so receipts, approvals, Activity and
        # cancellation all key on the same id the A2A client holds.
        control = {"turn_id": task.id, "accepted": False, "cancel_requested": False,
                   "approval": None, "done": threading.Event(), "outcome": None}
        loop = asyncio.get_running_loop()
        with self._active_lock:
            if task.id in self._active:
                raise ValueError("A2A task is already active")
            self._active[task.id] = control

        def publish(state, text, metadata=None):
            future = asyncio.run_coroutine_threadsafe(
                updater.update_status(state=state, message=new_text_message(text),
                                      metadata=metadata), loop)
            try:
                future.result(timeout=10)
            except Exception:  # noqa: BLE001 - status projection must not break the turn
                pass

        def event(frame):
            kind = frame.get("type")
            if kind in {"queued", "state"}:
                with self._active_lock:
                    control["accepted"] = True
                    cancel = control["cancel_requested"]
                if cancel:
                    self._bridge().control("cancel", turn_id=control["turn_id"])
            approval_id = str(frame.get("approval_id") or "")
            if kind == "state" and approval_id and frame.get("approval") == "pending":
                # Approvals stay in Jaeger: the owner decides on the Gateway
                # card; A2A only sees that the task is waiting on it.
                control["approval"] = approval_id
                publish(TaskState.TASK_STATE_INPUT_REQUIRED,
                        f"Waiting for the owner to approve {frame.get('tool') or 'an action'} in Jaeger "
                        f"(approval {approval_id}). A2A cannot answer this approval.",
                        {"jaeger.approval_id": approval_id, "jaeger.request_id": task.id})
            elif control["approval"] and kind in {"delta", "tool", "reasoning"}:
                control["approval"] = None
                publish(TaskState.TASK_STATE_WORKING, "Approval resolved in Jaeger; work resumed.",
                        {"jaeger.request_id": task.id})

        try:
            # The Gateway runs A2A work as the ``a2a`` caller (untrusted actor,
            # ``a2a:`` sessions only), never as the bridge.
            def run_turn():
                # Track the native turn itself, not this coroutine: the SDK
                # cancels the producer on CancelTask while the turn thread is
                # still stopping; cancel() waits on this for confirmation.
                outcome = "finished"
                try:
                    res = self._bridge().turn(objective, session, on_event=event,
                                              turn_id=control["turn_id"], gateway_caller="a2a")
                    if isinstance(res, dict) and (res.get("cancelled")
                                                  or res.get("halt_reason") == "interrupted"):
                        outcome = "cancelled"
                    return res
                finally:
                    control["outcome"] = outcome
                    control["done"].set()

            native = asyncio.ensure_future(asyncio.to_thread(run_turn))
            try:
                result = await asyncio.shield(native)
            except asyncio.CancelledError:
                # CancelTask cancels this producer; the native turn keeps
                # running until Jaeger confirms the stop. Report its real end.
                # Any other cancellation (server shutdown) propagates; the
                # Gateway request keeps its own durable record.
                if not control["cancel_requested"]:
                    raise
                result = await asyncio.wait_for(asyncio.shield(native), CANCEL_CONFIRM_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Jaeger bridge could not complete the task: {exc}"),
            )
            return
        finally:
            with self._active_lock:
                self._active.pop(task.id, None)

        text = str((result or {}).get("text") or "")
        error = (result or {}).get("error")
        if _auth_denied(result):
            await updater.update_status(
                state=TaskState.TASK_STATE_AUTH_REQUIRED,
                message=new_text_message(f"The a2a caller is not authorized for this work: {error}"),
                metadata={"jaeger.request_id": task.id},
            )
            return
        if result.get("cancelled") or result.get("halt_reason") == "interrupted":
            await updater.update_status(state=TaskState.TASK_STATE_CANCELED,
                                        message=new_text_message("Jaeger confirmed native cancellation."))
            return
        await updater.add_artifact(
            parts=[new_text_part(text=text or str(error or "No result text was returned."), media_type="text/plain")],
            name=f"Jaeger turn {session}",
            metadata={"jaeger.request_id": task.id},
        )
        files = _result_files(result)
        if files:
            await updater.add_artifact(
                parts=[Part(url=_file_url(path), filename=os.path.basename(path)) for path in files],
                name="Jaeger result files",
                metadata={"jaeger.request_id": task.id, "jaeger.local_only": True},
            )
        if result.get("execution_unknown"):
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Jaeger could not confirm what ran; check request {task.id} in Jaeger."),
                metadata={"jaeger.execution_unknown": True, "jaeger.request_id": task.id},
            )
            return
        if error:
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Jaeger turn finished with error: {error}"),
            )
            return
        await updater.update_status(
            state=TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Jaeger completed before cancellation was confirmed." if control["cancel_requested"]
                                     else "Jaeger completed the A2A task."),
        )

    async def cancel(self, context: RequestContext, _event_queue: EventQueue) -> None:
        task = context.current_task
        with self._active_lock:
            control = self._active.get(task.id) if task else None
            if control is None:
                raise ValueError("A2A task has no active native execution to cancel")
            control["cancel_requested"] = True
            accepted = control["accepted"]
        try:
            if accepted:
                await asyncio.to_thread(self._bridge().control, "cancel", turn_id=control["turn_id"])
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Jaeger bridge could not cancel the task: {exc}") from exc
        # execute() reports CANCELED only once Jaeger confirms the native stop.


_AUTH_CODES = frozenset({"unauthorized", "forbidden", "scope_denied", "auth_required"})


def _auth_denied(result: dict[str, Any]) -> bool:
    code = str(result.get("halt_code") or "").lower()
    error = str(result.get("error") or "").lower()
    return code in _AUTH_CODES or error.startswith(("401", "403")) or "not authorized" in error


def _result_files(result: dict[str, Any]) -> list[str]:
    """Result file lists (worker ``artifacts`` / ``files``) → A2A file parts."""
    out: list[str] = []
    for key in ("artifacts", "files"):
        value = result.get(key)
        if isinstance(value, list):
            out.extend(str(item) for item in value if isinstance(item, str) and item.strip())
    return list(dict.fromkeys(out))[:20]


def _file_url(path: str) -> str:
    if "://" in path:
        return path
    from pathlib import Path as _P

    return _P(path).expanduser().absolute().as_uri()


#: Discovery routes stay public (they describe Jaeger, they run nothing).
A2A_PUBLIC_PATHS = frozenset({"/.well-known/agent-card.json", "/.well-known/agent.json"})


def resolve_inbound_tokens() -> dict[str, str]:
    """Bearer tokens accepted for A2A work: the ``a2a`` Gateway caller token
    (agentgateway presents it via backendAuth). Values never printed."""
    from jaeger_ai.core.gateway.caller_auth import TokenStoreError, read_token

    try:
        value = read_token("a2a")
    except TokenStoreError:
        value = None
    return {"a2a": value} if value else {}


class RequireA2ABearer:
    """ASGI wrapper: every non-discovery request needs an accepted bearer."""

    def __init__(self, app: Any, tokens: dict[str, str]) -> None:
        if not tokens:
            raise RuntimeError("A2A requires a caller token (run `jaeger auth init`)")
        self.app = app
        self.tokens = [v.encode("utf-8") for v in tokens.values() if v]

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") in A2A_PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        import hmac
        auth = dict((k.decode("latin1").lower(), v) for k, v in scope.get("headers") or []).get(
            "authorization", b"")
        ok = False
        for token in self.tokens:
            expected = b"Bearer " + token
            ok = (len(auth) == len(expected) and hmac.compare_digest(auth, expected)) or ok
        if not ok:
            body = b'{"error":"unauthorized"}'
            await send({"type": "http.response.start", "status": 401, "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="jaeger-a2a"'),
                (b"content-length", str(len(body)).encode("ascii"))]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def build_app(client: Any | None = None, executor: AgentExecutor | None = None,
              tokens: dict[str, str] | None = None, task_store: TaskStore | None = None) -> Any:
    """Official SDK card + JSON-RPC routes behind mandatory bearer auth.

    The agent card is public; every JSON-RPC call needs the ``a2a`` caller
    token. There is no unauthenticated mode."""
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=executor or JaegerBridgeExecutor(client),
        task_store=task_store if task_store is not None else _default_task_store(),
        agent_card=card,
    )
    card_routes = create_agent_card_routes(card)
    routes = []
    if card_routes:
        routes.append(Route("/.well-known/agent.json", card_routes[0].endpoint, methods=["GET"]))
    routes.extend(card_routes)
    routes.extend(create_jsonrpc_routes(handler, "/", enable_v0_3_compat=True))
    return RequireA2ABearer(Starlette(routes=routes),
                            tokens if tokens is not None else resolve_inbound_tokens())


def _default_task_store() -> TaskStore:
    from jaeger_ai.interfaces.a2a_task_store import LedgerTaskStore

    return LedgerTaskStore(os.environ.get("JAEGER_A2A_TASK_DB") or None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jaeger a2a",
        description=(
            "Serve the official A2A AgentCard and JSON-RPC routes on loopback. "
            f"Default bind {A2A_HOST}:{A2A_PORT}; Agentgateway :8812 proxies here."
        ),
    )
    parser.add_argument("--host", default=A2A_HOST)
    parser.add_argument("--port", type=int, default=A2A_PORT)
    parser.add_argument("--instance", default=None, help="Jaeger instance whose live bridge to attach")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    client = None
    if args.instance:
        from jaeger_ai.features.webui.adapter.bridge_client import BridgeClient

        client = BridgeClient(instance=args.instance)
    tokens = resolve_inbound_tokens()
    if not tokens:
        import sys
        print("[jaeger-a2a] No A2A caller token in the Keychain; run `jaeger auth init`. "
              "Refusing to serve A2A without authentication.", file=sys.stderr)
        return 1
    app = build_app(client=client, tokens=tokens)
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
