"""Inbound webhook interpretation — GitHub and generic JSON."""

from __future__ import annotations

from jaeger_ai.core.runtime.webhooks import interpret


def test_generic_json_becomes_a_board_card():
    out = interpret("/hook", {"title": "Check billing", "prompt": "look at stripe"})
    assert out["action"] == "board"
    assert out["title"] == "Check billing"
    assert "stripe" in out["prompt"]


def test_explicit_turn_action():
    out = interpret("/hook", {"action": "turn", "prompt": "summarise this"})
    assert out["action"] == "turn"


def test_github_pull_request_payload():
    body = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "Fix lock",
            "user": {"login": "ada"},
        },
        "repository": {"full_name": "org/jaeger"},
    }
    out = interpret("/github", body)
    assert "PR #42" in out["title"]
    assert "org/jaeger" in out["title"]
    assert "ada" in out["prompt"]
