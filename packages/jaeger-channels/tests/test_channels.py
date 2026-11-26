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
