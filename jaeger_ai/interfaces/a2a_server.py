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
import uuid
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
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    TaskState,
)
from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.routing import Route

from jaeger_ai.contract.ports import A2A_PORT, A2A_URL, LOOPBACK

A2A_PROTOCOL_VERSION = "0.3"
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
        capabilities=AgentCapabilities(streaming=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=public_url,
                protocol_version=A2A_PROTOCOL_VERSION,
            )
        ],
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
        control = {"turn_id": uuid.uuid4().hex, "accepted": False, "cancel_requested": False}
        with self._active_lock:
            if task.id in self._active:
                raise ValueError("A2A task is already active")
            self._active[task.id] = control

        def event(frame):
            if frame.get("type") in {"queued", "state"}:
                with self._active_lock:
                    control["accepted"] = True
                    cancel = control["cancel_requested"]
                if cancel:
                    self._bridge().control("cancel", turn_id=control["turn_id"])

        try:
            # The Gateway runs A2A work as the ``a2a`` caller (untrusted actor,
            # ``a2a:`` sessions only), never as the bridge.
            result = await asyncio.to_thread(self._bridge().turn, objective, session,
                                            on_event=event, turn_id=control["turn_id"],
                                            gateway_caller="a2a")
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
        if result.get("cancelled"):
            await updater.update_status(state=TaskState.TASK_STATE_CANCELED,
                                        message=new_text_message("Jaeger confirmed native cancellation."))
            return
        await updater.add_artifact(
            parts=[new_text_part(text=text or str(error or "No result text was returned."), media_type="text/plain")],
            name=f"Jaeger turn {session}",
        )
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
              tokens: dict[str, str] | None = None) -> Any:
    """Official SDK card + JSON-RPC routes behind mandatory bearer auth.

    The agent card is public; every JSON-RPC call needs the ``a2a`` caller
    token. There is no unauthenticated mode."""
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=executor or JaegerBridgeExecutor(client),
        task_store=InMemoryTaskStore(),
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
