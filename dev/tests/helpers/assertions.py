"""Custom assertions for JaegerAI tests."""

from __future__ import annotations

from typing import Any


def assert_valid_session(data: dict[str, Any]) -> None:
    """Assert that data is a valid session."""
    assert "id" in data, "Session must have 'id'"
    assert "title" in data, "Session must have 'title'"
    assert isinstance(data["id"], str)
    assert isinstance(data["title"], str)


def assert_valid_message(data: dict[str, Any]) -> None:
    """Assert that data is a valid message."""
    assert "id" in data, "Message must have 'id'"
    assert "role" in data, "Message must have 'role'"
    assert "content" in data, "Message must have 'content'"
    assert data["role"] in ("user", "assistant", "system", "tool")


def assert_valid_ws_response(data: dict[str, Any], request_id: str | None = None) -> None:
    """Assert that data is a valid WebSocket response."""
    assert data.get("type") == "res", "Must be a response"
    assert data.get("ok") is True, "Response must be ok"
    if request_id:
        assert data.get("id") == request_id, f"Response ID must match request: {request_id}"


def assert_valid_ws_event(data: dict[str, Any], event_type: str | None = None) -> None:
    """Assert that data is a valid WebSocket event."""
    assert data.get("type") == "event", "Must be an event"
    assert "event" in data, "Event must have 'event' field"
    if event_type:
        assert data["event"] == event_type, f"Event type must be '{event_type}'"


def assert_valid_tool_call(data: dict[str, Any]) -> None:
    """Assert that data is a valid tool call."""
    assert "id" in data
    assert "name" in data
    assert "arguments" in data
    assert isinstance(data["arguments"], dict)
