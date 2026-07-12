"""Smoke test for the imessage plugin. Confirms importability without
chat.db access."""

from __future__ import annotations


def test_bridge_importable() -> None:
    from jaeger_ai.plugins.imessage import IMessageBridge

    assert IMessageBridge is not None


if __name__ == "__main__":
    test_bridge_importable()
    print("imessage plugin smoke: OK")
