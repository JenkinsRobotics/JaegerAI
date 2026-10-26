"""Unit tests for the WebSocket module."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Test the WebSocket data classes
from jaeger_ai.core.gateway.websocket import (
    WSEvent,
    WSMessageType,
    WSRequest,
    WSResponse,
    WebSocketConnection,
    WebSocketHandler,
)


class TestWSMessageTypes:
    """Test WebSocket message type enum."""
    
    def test_message_types(self):
        assert WSMessageType.REQUEST.value == "req"
        assert WSMessageType.RESPONSE.value == "res"
        assert WSMessageType.EVENT.value == "event"
        assert WSMessageType.ERROR.value == "error"
        assert WSMessageType.PING.value == "ping"
        assert WSMessageType.PONG.value == "pong"


class TestWSRequest:
    """Test WSRequest dataclass."""
    
    def test_basic_request(self):
        req = WSRequest(id="req-1", method="sessions.list", params={"limit": 10})
        result = req.to_dict()
        
        assert result["type"] == "req"
        assert result["id"] == "req-1"
        assert result["method"] == "sessions.list"
        assert result["params"] == {"limit": 10}
    
    def test_request_default_params(self):
        req = WSRequest(id="req-2", method="health")
        result = req.to_dict()
        
        assert result["params"] == {}


class TestWSResponse:
    """Test WSResponse dataclass."""
    
    def test_success_response(self):
        resp = WSResponse(id="req-1", ok=True, payload={"sessions": []})
        result = resp.to_dict()
        
        assert result["type"] == "res"
        assert result["id"] == "req-1"
        assert result["ok"] is True
        assert result["payload"] == {"sessions": []}
        assert "error" not in result
    
    def test_error_response(self):
        resp = WSResponse(id="req-2", ok=False, error="Session not found")
        result = resp.to_dict()
        
        assert result["ok"] is False
        assert result["error"] == {"message": "Session not found"}
        assert "payload" not in result
    
    def test_error_response_default_message(self):
        resp = WSResponse(id="req-3", ok=False)
        result = resp.to_dict()
        
        assert result["error"] == {"message": "Unknown error"}


class TestWSEvent:
    """Test WSEvent dataclass."""
    
    def test_basic_event(self):
        event = WSEvent(event="turn.delta", payload={"content": "Hello"}, seq=1)
        result = event.to_dict()
        
        assert result["type"] == "event"
        assert result["event"] == "turn.delta"
        assert result["payload"] == {"content": "Hello"}
        assert result["seq"] == 1
    
    def test_event_no_payload(self):
        event = WSEvent(event="ping")
        result = event.to_dict()
        
        assert result["type"] == "event"
        assert result["event"] == "ping"
        assert "payload" not in result
        assert "seq" not in result


class TestWebSocketConnection:
    """Test WebSocketConnection."""
    
    @pytest.fixture
    def mock_ws(self):
        """Create a mock WebSocket."""
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        return ws
    
    @pytest.fixture
    def connection(self, mock_ws):
        """Create a WebSocketConnection with mock WebSocket."""
        return WebSocketConnection(mock_ws, "conn-123")
    
    @pytest.mark.asyncio
    async def test_send(self, connection, mock_ws):
        """Test sending a message."""
        await connection.send({"type": "test"})
        mock_ws.send_json.assert_called_once_with({"type": "test"})
    
    @pytest.mark.asyncio
    async def test_send_response(self, connection, mock_ws):
        """Test sending a response."""
        response = WSResponse(id="req-1", ok=True, payload={"ok": True})
        await connection.send_response(response)
        
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "res"
        assert call_args["ok"] is True
    
    @pytest.mark.asyncio
    async def test_send_event(self, connection, mock_ws):
        """Test sending an event."""
        event = WSEvent(event="test.event", payload={"data": "value"})
        await connection.send_event(event)
        
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "event"
        assert call_args["event"] == "test.event"
    
    @pytest.mark.asyncio
    async def test_send_error(self, connection, mock_ws):
        """Test sending an error."""
        await connection.send_error("req-1", "Something went wrong", -32603)
        
        mock_ws.send_json.assert_called_once()
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "res"
        assert call_args["ok"] is False
        assert call_args["error"]["message"] == "Something went wrong"
        assert call_args["error"]["code"] == -32603
    
    def test_is_alive(self, connection):
        """Test connection liveness check."""
        assert connection.is_alive(timeout=60.0)
        
        # Simulate old ping
        connection.last_ping = 0
        assert not connection.is_alive(timeout=60.0)


class TestWebSocketHandler:
    """Test WebSocketHandler."""
    
    @pytest.fixture
    def mock_gateway(self):
        """Create a mock gateway app."""
        gateway = MagicMock()
        gateway.session_store = MagicMock()
        return gateway
    
    @pytest.fixture
    def handler(self, mock_gateway):
        """Create a WebSocketHandler."""
        return WebSocketHandler(mock_gateway)
    
    def test_handler_initialization(self, handler):
        """Test handler initializes with default methods."""
        expected_methods = [
            "sessions.list", "sessions.get", "sessions.create", "sessions.delete",
            "sessions.send", "sessions.subscribe",
            "chat.send", "chat.sendStream",
            "tools.list", "tools.invoke",
            "files.list", "files.read", "files.upload",
            "memory.search", "memory.remember",
            "agents.list", "agents.get",
            "models.list", "models.set",
            "events.subscribe",
            "ping", "health",
        ]
        
        for method in expected_methods:
            assert method in handler.method_handlers, f"Missing method: {method}"
    
    def test_connections_dict(self, handler):
        """Test connections dictionary is initialized."""
        assert isinstance(handler.connections, dict)
        assert len(handler.connections) == 0
    
    def test_event_subscribers(self, handler):
        """Test event subscribers dictionary is initialized."""
        assert isinstance(handler._event_subscribers, dict)
        assert len(handler._event_subscribers) == 0
    
    @pytest.mark.asyncio
    async def test_handle_ping(self, handler):
        """Test ping handler."""
        conn = MagicMock()
        result = await handler._handle_ping(conn, {})
        assert "pong" in result
    
    @pytest.mark.asyncio
    async def test_handle_health(self, handler):
        """Test health handler."""
        conn = MagicMock()
        result = await handler._handle_health(conn, {})
        assert result["status"] == "ok"
        assert "connections" in result


class TestWebSocketBroadcast:
    """Test WebSocket broadcasting."""
    
    @pytest.fixture
    def handler(self):
        """Create a handler with mock connections."""
        gateway = MagicMock()
        handler = WebSocketHandler(gateway)
        
        # Add mock connections
        for i in range(3):
            conn = MagicMock()
            conn.connection_id = f"conn-{i}"
            conn.send_event = AsyncMock()
            handler.connections[f"conn-{i}"] = conn
        
        return handler
    
    @pytest.mark.asyncio
    async def test_broadcast_all(self, handler):
        """Test broadcasting to all connections."""
        await handler.broadcast("test.event", {"data": "value"})
        
        for conn in handler.connections.values():
            conn.send_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_broadcast_specific(self, handler):
        """Test broadcasting to specific connections."""
        targets = {"conn-0", "conn-2"}
        await handler.broadcast("test.event", {"data": "value"}, targets)
        
        handler.connections["conn-0"].send_event.assert_called_once()
        handler.connections["conn-1"].send_event.assert_not_called()
        handler.connections["conn-2"].send_event.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_broadcast_to_subscribers(self, handler):
        """Test broadcasting to event subscribers."""
        handler._event_subscribers["test.event"] = {"conn-0", "conn-1"}
        
        await handler.broadcast_to_subscribers("test.event", {"data": "value"})
        
        # Only subscribers receive the event
        handler.connections["conn-0"].send_event.assert_called_once()
        handler.connections["conn-1"].send_event.assert_called_once()
        handler.connections["conn-2"].send_event.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
