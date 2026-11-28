"""Tests for standalone jaeger-channels package and Hermes secret redaction."""

from __future__ import annotations

from pathlib import Path

from jaeger_authority import redact_object, redact_text
from jaeger_channels import ChannelHub


def test_hermes_redaction_masks_tokens_and_urls() -> None:
    raw = "Auth: Bearer sk-proj-1234567890abcdef123456 and https://api.example.com/v1?api_key=supersecret999&ok=1"
    red = redact_text(raw)
    assert "1234567890abcdef" not in red
    assert "supersecret999" not in red
    assert "ok=1" in red

    obj = redact_object({"nested": {"api_key": "ghp_1234567890abcdefghij123456", "safe": "hello"}})
    assert obj["nested"]["safe"] == "hello"
    assert "abcdefghij" not in obj["nested"]["api_key"]


def test_channel_hub_redacts_and_gates_external_delivery(tmp_path: Path) -> None:
    hub = ChannelHub(tmp_path)
    sent_log: list[tuple[str, str]] = []
    hub.register_adapter("telegram", lambda r, b: sent_log.append((r, b)) or {"ok": True})

    # External telegram send without approval stays queued AND scrubs secret!
    m1 = hub.enqueue(
        channel="telegram",
        recipient="@owner",
        body="Episode ready! Key sk-live-1234567890abcdefghij",
        approved=False,
    )
    assert m1.status == "queued_for_approval"
    assert "1234567890abcdef" not in m1.body
    assert sent_log == []

    # Approved external send delivers cleanly
    m2 = hub.enqueue(channel="telegram", recipient="@owner", body="Episode 1 ready for review", approved=True)
    assert m2.status == "sent"
    assert len(sent_log) == 1
    assert hub.status()["sent_count"] == 1


def test_discord_ambient_room_buffer_and_bot_loop_guard() -> None:
    import asyncio
    from jaeger_channels import AmbientRoomBuffer, BotLoopGuard, DiscordChannelPoller

    buf = AmbientRoomBuffer(max_per_channel=5)
    buf.record("123456", "alice", "working on the rover CAD")
    buf.record("123456", "bob", "stepper bracket looks tight")
    ctx = buf.format_context("123456")
    assert "untrusted external chatter" in ctx and "alice" in ctx and "bob" in ctx

    guard = BotLoopGuard(max_replies_per_window=2, window_s=60.0, max_consecutive_bot_turns=1)
    assert guard.allow_inbound("123456", is_bot_author=True, now=100.0)[0] is True
    assert guard.allow_inbound("123456", is_bot_author=True, now=101.0)[0] is False
    # Human message resets bot streak
    assert guard.allow_inbound("123456", is_bot_author=False, now=102.0)[0] is True
    guard.record_reply("123456", now=102.0)
    guard.record_reply("123456", now=103.0)
    assert guard.allow_inbound("123456", is_bot_author=False, now=104.0)[0] is False

    # Mention-gated Discord poller buffers unmentioned chatter & injects it when mentioned
    delivered: list[tuple[str, str]] = []
    poller = DiscordChannelPoller(
        "tok_1234567890abcdef",
        ["1234567890"],
        on_message=lambda _ch, cid, _mid, sender, text, _auto: delivered.append((sender, text)),
        mention_tokens=["@jaeger"],
    )
    poller._fetch_channel_sync = lambda _cid: [  # type: ignore[method-assign]
        {"id": "1", "author": {"id": "u1", "username": "alice", "bot": False}, "content": "servo wiring done"},
        {"id": "2", "author": {"id": "b1", "username": "otherbot", "bot": True}, "content": "@jaeger ping"},
        {"id": "3", "author": {"id": "u2", "username": "bob", "bot": False}, "content": "@jaeger what did alice finish?"},
    ]
    count = asyncio.run(poller.poll_once())
    assert count == 1
    assert len(delivered) == 1
    assert delivered[0][0] == "bob"
    assert "alice: servo wiring done" in delivered[0][1]
    assert "@jaeger what did alice finish?" in delivered[0][1]
