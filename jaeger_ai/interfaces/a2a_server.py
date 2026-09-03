"""A2A protocol surface for JaegerAI.

Ports the official ``a2a-sdk`` AgentCard + JSON-RPC routes that already
worked in ARES. The executor body is Jaeger: it drives the live instance
bridge (``BridgeClient.turn``) instead of ARES AutomationService.
"""

from __future__ import annotations

import argparse
import asyncio
import os
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

A2A_PROTOCOL_VERSION = "0.3"
A2A_HOST = "127.0.0.1"
A2A_PORT = 8796
A2A_PUBLIC_URL = "http://127.0.0.1:8812"


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

    def _bridge(self) -> Any:
        if self._client is not None:
            return self._client
        from jaeger_ai.interfaces.hermes_webui_adapter.bridge_client import BridgeClient

        self._client = BridgeClient()
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
        session = f"a2a:{task.id}"
        try:
            result = await asyncio.to_thread(self._bridge().turn, objective, session)
        except Exception as exc:  # noqa: BLE001
            await updater.update_status(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f"Jaeger bridge could not complete the task: {exc}"),
            )
            return

        text = str((result or {}).get("text") or "")
        error = (result or {}).get("error")
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
            message=new_text_message("Jaeger completed the A2A task."),
        )

    async def cancel(self, context: RequestContext, _event_queue: EventQueue) -> None:
        try:
            self._bridge().control("cancel")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Jaeger bridge could not cancel the task: {exc}") from exc


def build_app(client: Any | None = None, executor: AgentExecutor | None = None) -> Starlette:
    """Starlette app with official SDK card + JSON-RPC routes. No homemade RPC."""
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=executor or JaegerBridgeExecutor(client),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = []
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_jsonrpc_routes(handler, "/", enable_v0_3_compat=True))
    return Starlette(routes=routes)


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
        from jaeger_ai.interfaces.hermes_webui_adapter.bridge_client import BridgeClient

        client = BridgeClient(instance=args.instance)
    app = build_app(client=client)
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
