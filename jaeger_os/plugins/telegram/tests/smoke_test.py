"""Smoke test for the telegram plugin. Confirms importability without
python-telegram-bot installed."""

from __future__ import annotations


def test_bridge_importable() -> None:
    from jaeger_os.plugins.telegram import TelegramBridge

    assert TelegramBridge is not None


if __name__ == "__main__":
    test_bridge_importable()
    print("telegram plugin smoke: OK")
