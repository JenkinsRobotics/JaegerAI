"""A2A AgentCard shape via the official a2a-sdk routes. No live model."""

from __future__ import annotations

from starlette.testclient import TestClient

from jaeger_ai.interfaces.a2a_server import (
    A2A_PROTOCOL_VERSION,
    A2A_PUBLIC_URL,
    JaegerBridgeExecutor,
    build_agent_card,
    build_app,
    parse_args,
)


class _FakeBridge:
    def __init__(self) -> None:
        self.turns: list[tuple[str, str]] = []
        self.cancelled = False

    def turn(self, text, session):
        self.turns.append((text, session))
        return {"text": f"echo:{text}", "error": None}

    def control(self, operation, **payload):
        del payload
        if operation == "cancel":
            self.cancelled = True


def test_agent_card_declares_jaeger_chat_and_delegate():
    card = build_agent_card()
    assert card.name == "Jaeger"
    skill_ids = [skill.id for skill in card.skills]
    assert skill_ids == ["chat", "delegate"]
    assert card.supported_interfaces[0].url == A2A_PUBLIC_URL
    assert card.supported_interfaces[0].protocol_version == A2A_PROTOCOL_VERSION


def test_agent_card_route_uses_official_a2a_sdk():
    app = build_app(client=_FakeBridge())
    with TestClient(app) as client:
        response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Jaeger"
    assert body["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert body["supportedInterfaces"][0]["protocolVersion"] == "0.3"
    assert body["supportedInterfaces"][0]["url"] == A2A_PUBLIC_URL
    skill_ids = {skill["id"] for skill in body["skills"]}
    assert skill_ids == {"chat", "delegate"}


def test_executor_drives_bridge_turn_without_a_model():
    import asyncio

    from a2a.helpers import new_task_from_user_message, new_text_message
    from a2a.server.events import EventQueueLegacy
    from a2a.types import Role

    bridge = _FakeBridge()
    executor = JaegerBridgeExecutor(bridge)
    message = new_text_message("hello from a2a", role=Role.ROLE_USER)
    task = new_task_from_user_message(message)

    ctx = type("Ctx", (), {})()
    ctx.current_task = task
    ctx.message = message

    async def _run():
        queue = EventQueueLegacy()
        await executor.execute(ctx, queue)

    asyncio.run(_run())
    assert bridge.turns
    assert bridge.turns[0][0] == "hello from a2a"


def test_parse_args_defaults_to_loopback_backend():
    args = parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 8796
