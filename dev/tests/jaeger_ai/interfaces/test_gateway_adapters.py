"""Unit tests for multi-channel messaging gateway adapters."""

import pytest
import asyncio
from jaeger_ai.interfaces.gateway import (
    BaseMessagingGateway,
    TelegramGateway,
    DiscordGateway,
    SlackGateway,
    GatewayManager,
)


def test_base_messaging_gateway_turn_execution():
    async def run_test():
        async def mock_runner(text: str) -> str:
            return f"Echo: {text}"

        gateway = BaseMessagingGateway("test_platform", mock_runner)
        reply = await gateway.on_message_received("user123", "Hello world")
        assert reply == "Echo: Hello world"

    asyncio.run(run_test())


def test_telegram_gateway_user_whitelist():
    async def run_test():
        gateway = TelegramGateway(allowed_users=[111, 222], agent_runner=lambda t: "OK")
        assert gateway.is_user_allowed(111) is True
        assert gateway.is_user_allowed(333) is False

        unauth_update = {
            "message": {
                "text": "test",
                "chat": {"id": 999},
                "from": {"id": 333},
            }
        }
        result = await gateway.handle_update(unauth_update)
        assert result is not None
        assert "Unauthorized" in result["text"]

    asyncio.run(run_test())


def test_discord_gateway_channel_filter():
    async def run_test():
        gateway = DiscordGateway(allowed_channels=[1001, 1002], agent_runner=lambda t: "Discord response")
        assert gateway.is_channel_allowed(1001) is True
        assert gateway.is_channel_allowed(9999) is False

        res_allowed = await gateway.handle_discord_message(1001, "u1", "Hi Discord")
        assert res_allowed == {"channel_id": 1001, "content": "Discord response"}

        res_blocked = await gateway.handle_discord_message(9999, "u1", "Hi Discord")
        assert res_blocked is None

    asyncio.run(run_test())


def test_slack_gateway_event_handling():
    async def run_test():
        gateway = SlackGateway(allowed_channels=["C12345"], agent_runner=lambda t: "Slack response")
        res = await gateway.handle_slack_event("C12345", "U67890", "Hi Slack", thread_ts="1234.5678")
        assert res == {
            "channel": "C12345",
            "text": "Slack response",
            "thread_ts": "1234.5678",
        }

    asyncio.run(run_test())


def test_gateway_manager_discovery():
    manager = GatewayManager(agent_runner=lambda t: "OK")
    gateways = manager.setup_gateways()
    assert isinstance(gateways, dict)


def test_gateway_allowlists_fail_closed():
    assert TelegramGateway(allowed_users=[]).is_user_allowed(1) is False
    assert DiscordGateway(allowed_channels=[]).is_channel_allowed(1) is False
    assert SlackGateway(allowed_channels=[]).is_channel_allowed("C1") is False


def test_telegram_missing_sender_cannot_bypass_allowlist():
    async def run_test():
        gateway = TelegramGateway(allowed_users=[111], agent_runner=lambda text: "should not run")
        result = await gateway.handle_update({"message": {"text": "test", "chat": {"id": 999}}})
        assert result is not None
        assert "Unauthorized" in result["text"]

    asyncio.run(run_test())


def test_sync_runner_does_not_block_event_loop():
    import time

    async def run_test():
        gateway = BaseMessagingGateway("test", lambda text: (time.sleep(0.05), "OK")[1])
        turn = asyncio.create_task(gateway.on_message_received("u", "hello"))
        await asyncio.sleep(0.01)
        assert not turn.done()
        assert await turn == "OK"

    asyncio.run(run_test())
