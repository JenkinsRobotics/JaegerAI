"""Mock objects and utilities for testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import json


@dataclass
class MockSession:
    """Mock session for testing."""
    id: str = "test-session-123"
    title: str = "Test Session"
    created_at: float = 1234567890.0
    updated_at: float = 1234567890.0
    message_count: int = 0
    agent_id: str = "test-agent"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "agent_id": self.agent_id,
        }


@dataclass
class MockMessage:
    """Mock message for testing."""
    id: str = "msg-123"
    session_id: str = "test-session-123"
    role: str = "user"
    content: str = "Hello"
    timestamp: float = 1234567890.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }


@dataclass
class MockAgent:
    """Mock agent for testing."""
    id: str = "test-agent"
    name: str = "Test Agent"
    personality: str = "assistant"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "personality": self.personality,
        }


def create_mock_gateway_response(
    method: str,
    payload: Any = None,
    ok: bool = True,
    error: str | None = None,
    request_id: str = "test-req-123",
) -> dict[str, Any]:
    """Create a mock WebSocket response."""
    response: dict[str, Any] = {
        "type": "res",
        "id": request_id,
        "ok": ok,
    }
    if ok:
        response["payload"] = payload
    else:
        response["error"] = {"message": error or "Unknown error"}
    return response


def create_mock_ws_event(
    event: str,
    payload: Any = None,
    seq: int = 1,
) -> dict[str, Any]:
    """Create a mock WebSocket event."""
    result: dict[str, Any] = {
        "type": "event",
        "event": event,
        "seq": seq,
    }
    if payload is not None:
        result["payload"] = payload
    return result


class MockWebSocket:
    """Mock WebSocket for testing."""
    
    def __init__(self):
        self.sent_messages: list[dict[str, Any]] = []
        self.received_messages: list[dict[str, Any]] = []
        self.connected = False
        self._recv_queue: list[dict[str, Any]] = []
    
    async def connect(self, url: str):
        """Mock connect."""
        self.connected = True
        # Send welcome message
        self._recv_queue.append({
            "type": "event",
            "event": "connected",
            "payload": {"connectionId": "test-conn-123"},
        })
    
    async def send(self, message: str | dict[str, Any]):
        """Mock send."""
        if isinstance(message, str):
            message = json.loads(message)
        self.sent_messages.append(message)
    
    async def recv(self) -> str:
        """Mock receive."""
        if not self._recv_queue:
            await asyncio.sleep(0.01)
            if not self._recv_queue:
                raise asyncio.TimeoutError("No message")
        message = self._recv_queue.pop(0)
        return json.dumps(message)
    
    def queue_message(self, message: dict[str, Any]):
        """Queue a message to be received."""
        self._recv_queue.append(message)
    
    async def close(self):
        """Mock close."""
        self.connected = False
