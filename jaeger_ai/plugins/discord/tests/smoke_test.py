"""Smoke test for the discord plugin.

Confirms the bridge class is importable even when discord.py isn't
installed and DISCORD_BOT_TOKEN isn't set. Actual Discord connectivity
is NOT tested — that requires real credentials.
"""

from __future__ import annotations


def test_bridge_importable() -> None:
    from jaeger_ai.plugins.discord import DiscordBridge

    assert DiscordBridge is not None
    # Instantiation should defer the discord.py import to start() so the
    # class itself is loadable without the SDK present.


if __name__ == "__main__":
    test_bridge_importable()
    print("discord plugin smoke: OK")
