"""jaeger-channels: standalone multi-channel notification & messaging relay."""

from .adapters import (
    ChannelConfigError,
    ChannelConfigStore,
    ChannelIngressSupervisor,
    DiscordChannelPoller,
    SlackChannelPoller,
    TelegramPoller,
    build_discord_adapter,
    build_imessage_adapter,
    build_slack_adapter,
    build_telegram_adapter,
)
from .relay import ChannelHub, OutboxMessage, SUPPORTED_CHANNELS
from .webhook import WEBHOOK_TIMEOUT_S, WebhookConfigError, build_webhook_adapter

__all__ = [
    "ChannelConfigError",
    "ChannelConfigStore",
    "ChannelHub",
    "ChannelIngressSupervisor",
    "DiscordChannelPoller",
    "OutboxMessage",
    "SUPPORTED_CHANNELS",
    "SlackChannelPoller",
    "TelegramPoller",
    "WEBHOOK_TIMEOUT_S",
    "WebhookConfigError",
    "build_discord_adapter",
    "build_imessage_adapter",
    "build_slack_adapter",
    "build_telegram_adapter",
    "build_webhook_adapter",
]
