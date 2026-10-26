"""WebSocket support for Jaeger Gateway.

Adds bidirectional WebSocket RPC to Jaeger Gateway, matching
Hermes Agent and OpenClaw's real-time capabilities.

Protocol:
- JSON-RPC 2.0 style frames over WebSocket
- Request:  {"type": "req", "id": "...", "method": "...", "params": {...}}
- Response: {"type": "res", "id": "...", "ok": true, "payload": {...}}
- Event:    {"type": "event", "event": "...", "payload": {...}, "seq": N}

Methods:
- sessions.list, sessions.get, sessions.create, sessions.delete
- sessions.send (with streaming)
- sessions.subscribe (for real-time updates)
- chat.send (OpenAI-compatible streaming)
- tools.list, tools.invoke
- files.upload, files.list, files.read
- memory.search, memory.remember
- agents.list, agents.get
- models.list, models.set
- events.subscribe (global event stream)

Usage:
    # Server side
    from jaeger_ai.core.gateway.websocket import WebSocketHandler
    handler = WebSocketHandler(gateway_app)
    # Routes added automatically

    # Client side (frontend)
    import { GatewayWebSocket } from './gateway-ws'
    const ws = new GatewayWebSocket('ws://127.0.0.1:33418/ws')
    await ws.connect()
    const result = await ws.request('sessions.list', {})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable
from enum import Enum
import asyncio
import json
import logging
import secrets
import time
import uuid

from aiohttp import web, WSMsgType

logger = logging.getLogger(__name__)


class WSMessageType(str, Enum):
    """WebSocket message types."""
    REQUEST = "req"
    RESPONSE = "res"
    EVENT = "event"
    ERROR = "error"
    PING = "ping"
    PONG = "pong"


@dataclass
class WSRequest:
    """A WebSocket request."""
    id: str
    method: str
    params: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "type": WSMessageType.REQUEST.value,
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }


@dataclass
class WSResponse:
    """A WebSocket response."""
    id: str
    ok: bool
    payload: Any = None
    error: str | None = None
    
    def to_dict(self) -> dict:
        result: dict = {
            "type": WSMessageType.RESPONSE.value,
            "id": self.id,
            "ok": self.ok,
        }
        if self.ok:
            result["payload"] = self.payload
        else:
            result["error"] = {"message": self.error or "Unknown error"}
        return result


@dataclass
class WSEvent:
    """A WebSocket event (server-pushed)."""
    event: str
    payload: Any = None
    seq: int = 0
    
    def to_dict(self) -> dict:
        result: dict = {
            "type": WSMessageType.EVENT.value,
            "event": self.event,
        }
        if self.payload is not None:
            result["payload"] = self.payload
        if self.seq:
            result["seq"] = self.seq
        return result


class WebSocketConnection:
    """A single WebSocket connection."""
    
    def __init__(self, ws: web.WebSocketResponse, connection_id: str):
        self.ws = ws
        self.connection_id = connection_id
        self.subscriptions: set[str] = set()
        self.metadata: dict[str, Any] = {}
        self.created_at = time.time()
        self.last_ping = time.time()
        self._send_lock = asyncio.Lock()
    
    async def send(self, message: dict[str, Any]) -> None:
        """Send a message to the client."""
        async with self._send_lock:
            try:
                await self.ws.send_json(message)
            except Exception as e:
                logger.error(f"Failed to send to {self.connection_id}: {e}")
    
    async def send_response(self, response: WSResponse) -> None:
        """Send a response."""
        await self.send(response.to_dict())
    
    async def send_event(self, event: WSEvent) -> None:
        """Send an event."""
        await self.send(event.to_dict())
    
    async def send_error(self, request_id: str, message: str, code: int = -32603) -> None:
        """Send an error response."""
        await self.send({
            "type": WSMessageType.RESPONSE.value,
            "id": request_id,
            "ok": False,
            "error": {"message": message, "code": code},
        })
    
    def is_alive(self, timeout: float = 60.0) -> bool:
        """Check if connection is alive."""
        return (time.time() - self.last_ping) < timeout


class WebSocketHandler:
    """WebSocket handler for Jaeger Gateway.
    
    Manages WebSocket connections and dispatches RPC requests.
    """
    
    def __init__(self, gateway_app: Any):
        self.gateway = gateway_app
        self.connections: dict[str, WebSocketConnection] = {}
        self.method_handlers: dict[str, Callable] = {}
        self.event_seq = 0
        self._event_subscribers: dict[str, set[str]] = {}  # event_type → connection_ids
        
        # Register default method handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self) -> None:
        """Register default RPC method handlers."""
        # Session methods
        self.method_handlers["sessions.list"] = self._handle_sessions_list
        self.method_handlers["sessions.get"] = self._handle_sessions_get
        self.method_handlers["sessions.create"] = self._handle_sessions_create
        self.method_handlers["sessions.delete"] = self._handle_sessions_delete
        self.method_handlers["sessions.send"] = self._handle_sessions_send
        self.method_handlers["sessions.subscribe"] = self._handle_sessions_subscribe
        
        # Chat methods (OpenAI-compatible)
        self.method_handlers["chat.send"] = self._handle_chat_send
        self.method_handlers["chat.sendStream"] = self._handle_chat_send_stream
        
        # Tool methods
        self.method_handlers["tools.list"] = self._handle_tools_list
        self.method_handlers["tools.invoke"] = self._handle_tools_invoke
        
        # File methods
        self.method_handlers["files.list"] = self._handle_files_list
        self.method_handlers["files.read"] = self._handle_files_read
        self.method_handlers["files.upload"] = self._handle_files_upload
        
        # Memory methods
        self.method_handlers["memory.search"] = self._handle_memory_search
        self.method_handlers["memory.remember"] = self._handle_memory_remember
        
        # Agent methods
        self.method_handlers["agents.list"] = self._handle_agents_list
        self.method_handlers["agents.get"] = self._handle_agents_get
        
        # Model methods
        self.method_handlers["models.list"] = self._handle_models_list
        self.method_handlers["models.set"] = self._handle_models_set
        
        # Event subscription
        self.method_handlers["events.subscribe"] = self._handle_events_subscribe
        
        # Utility
        self.method_handlers["ping"] = self._handle_ping
        self.method_handlers["health"] = self._handle_health
    
    async def handle_connection(self, request: web.Request) -> web.WebSocketResponse:
        """Handle a new WebSocket connection."""
        ws = web.WebSocketResponse(
            timeout=30.0,
            heartbeat=30.0,
            max_msg_size=10 * 1024 * 1024,  # 10MB
        )
        await ws.prepare(request)
        
        connection_id = str(uuid.uuid4())
        conn = WebSocketConnection(ws, connection_id)
        self.connections[connection_id] = conn
        
        logger.info(f"WebSocket connected: {connection_id}")
        
        try:
            # Send welcome message
            await conn.send({
                "type": "event",
                "event": "connected",
                "payload": {
                    "connectionId": connection_id,
                    "protocol": 1,
                    "server": {"version": "0.13.0"},
                },
            })
            
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(conn, msg.data)
                elif msg.type == WSMsgType.BINARY:
                    # Handle binary data (file uploads, audio)
                    await self._handle_binary(conn, msg.data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                    break
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    break
        
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        
        finally:
            # Cleanup
            self.connections.pop(connection_id, None)
            for event_type, subscribers in self._event_subscribers.items():
                subscribers.discard(connection_id)
            logger.info(f"WebSocket disconnected: {connection_id}")
        
        return ws
    
    async def _handle_message(self, conn: WebSocketConnection, data: str) -> None:
        """Handle an incoming message."""
        try:
            message = json.loads(data)
            msg_type = message.get("type")
            
            if msg_type == WSMessageType.REQUEST.value:
                await self._handle_request(conn, message)
            elif msg_type == WSMessageType.PING.value:
                conn.last_ping = time.time()
                await conn.send({"type": WSMessageType.PONG.value})
            elif msg_type == WSMessageType.PONG.value:
                conn.last_ping = time.time()
            else:
                await conn.send_error(
                    message.get("id", ""),
                    f"Unknown message type: {msg_type}",
                    -32600,
                )
        
        except json.JSONDecodeError:
            await conn.send_error("", "Invalid JSON", -32700)
        except Exception as e:
            logger.exception("Error handling message")
            await conn.send_error("", str(e), -32603)
    
    async def _handle_request(self, conn: WebSocketConnection, message: dict[str, Any]) -> None:
        """Handle a request message."""
        request_id = message.get("id", "")
        method = message.get("method", "")
        params = message.get("params", {})
        
        if not method:
            await conn.send_error(request_id, "Missing method", -32602)
            return
        
        handler = self.method_handlers.get(method)
        if not handler:
            await conn.send_error(request_id, f"Unknown method: {method}", -32601)
            return
        
        try:
            result = await handler(conn, params)
            await conn.send_response(WSResponse(id=request_id, ok=True, payload=result))
        except Exception as e:
            logger.exception(f"Error handling {method}")
            await conn.send_error(request_id, str(e), -32603)
    
    async def _handle_binary(self, conn: WebSocketConnection, data: bytes) -> None:
        """Handle binary data (file uploads, audio)."""
        # TODO: Implement binary protocol (header + payload)
        logger.warning(f"Binary data from {conn.connection_id}: {len(data)} bytes")
    
    # ─────────────────────────────────────────────────────────────
    # Broadcasting
    # ─────────────────────────────────────────────────────────────
    
    async def broadcast(self, event: str, payload: Any = None, 
                       connection_ids: set[str] | None = None) -> None:
        """Broadcast an event to all or specific connections."""
        self.event_seq += 1
        ws_event = WSEvent(event=event, payload=payload, seq=self.event_seq)
        
        targets = connection_ids or set(self.connections.keys())
        for conn_id in targets:
            conn = self.connections.get(conn_id)
            if conn:
                await conn.send_event(ws_event)
    
    async def broadcast_to_subscribers(self, event_type: str, payload: Any = None) -> None:
        """Broadcast to subscribers of a specific event type."""
        subscribers = self._event_subscribers.get(event_type, set())
        await self.broadcast(event_type, payload, subscribers)
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Sessions
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_sessions_list(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """List all sessions."""
        # Delegate to existing HTTP handler logic
        limit = params.get("limit", 50)
        # Get sessions from store
        sessions = []
        try:
            store = self.gateway.session_store
            if hasattr(store, "list_sessions"):
                sessions = store.list_sessions(limit=limit)
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
        
        return {"sessions": sessions, "total": len(sessions)}
    
    async def _handle_sessions_get(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Get a specific session."""
        session_id = params.get("sessionId") or params.get("session_id")
        if not session_id:
            raise ValueError("sessionId required")
        
        # TODO: Implement session get
        return {"sessionId": session_id, "messages": []}
    
    async def _handle_sessions_create(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Create a new session."""
        # TODO: Implement session creation
        session_id = f"sess-{secrets.token_hex(8)}"
        return {
            "sessionId": session_id,
            "createdAt": time.time(),
        }
    
    async def _handle_sessions_delete(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Delete a session."""
        session_id = params.get("sessionId") or params.get("session_id")
        if not session_id:
            raise ValueError("sessionId required")
        
        # TODO: Implement session deletion
        return {"deleted": True, "sessionId": session_id}
    
    async def _handle_sessions_send(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Send a message to a session (non-streaming)."""
        session_id = params.get("sessionId") or params.get("session_id")
        message = params.get("message", "")
        
        if not session_id or not message:
            raise ValueError("sessionId and message required")
        
        # TODO: Implement message sending
        # For now, return a placeholder
        return {
            "sessionId": session_id,
            "response": "Message received (TODO: implement)",
            "turnId": f"turn-{secrets.token_hex(8)}",
        }
    
    async def _handle_sessions_subscribe(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Subscribe to session events."""
        session_id = params.get("sessionId") or params.get("session_id")
        events = params.get("events", ["*"])
        
        if session_id:
            conn.subscriptions.add(session_id)
        
        return {"subscribed": True, "sessionId": session_id, "events": events}
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Chat (OpenAI-compatible)
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_chat_send(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Send a chat message (non-streaming, OpenAI-compatible)."""
        messages = params.get("messages", [])
        model = params.get("model")
        
        # TODO: Implement chat completion
        return {
            "id": f"chatcmpl-{secrets.token_hex(8)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model or "jaeger",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "TODO: Implement chat completion",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    
    async def _handle_chat_send_stream(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Send a chat message with streaming response.
        
        Events are pushed to the client via WebSocket:
        - chat.delta: Partial response
        - chat.done: Completion
        - chat.error: Error
        """
        request_id = params.get("requestId", secrets.token_hex(8))
        messages = params.get("messages", [])
        
        # Send initial acknowledgment
        await conn.send_event(WSEvent(
            event="chat.started",
            payload={"requestId": request_id},
        ))
        
        # TODO: Implement streaming chat
        # Stream deltas
        for i in range(3):
            await asyncio.sleep(0.5)
            await conn.send_event(WSEvent(
                event="chat.delta",
                payload={
                    "requestId": request_id,
                    "delta": {"content": f"Chunk {i+1}... "},
                },
            ))
        
        # Send completion
        await conn.send_event(WSEvent(
            event="chat.done",
            payload={
                "requestId": request_id,
                "finishReason": "stop",
                "usage": {"total_tokens": 100},
            },
        ))
        
        return {"streaming": True, "requestId": request_id}
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Tools
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_tools_list(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """List available tools."""
        # TODO: Get from tool registry
        return {
            "tools": [
                {"name": "read_file", "description": "Read a file"},
                {"name": "write_file", "description": "Write a file"},
                {"name": "run_command", "description": "Run a shell command"},
            ],
        }
    
    async def _handle_tools_invoke(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Invoke a tool directly."""
        tool_name = params.get("name") or params.get("tool")
        arguments = params.get("arguments", {})
        
        if not tool_name:
            raise ValueError("Tool name required")
        
        # TODO: Implement tool invocation
        return {
            "tool": tool_name,
            "result": f"TODO: Invoke {tool_name}",
        }
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Files
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_files_list(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """List files in a directory."""
        path = params.get("path", ".")
        # TODO: Implement file listing with safety checks
        return {
            "path": path,
            "files": [],
        }
    
    async def _handle_files_read(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Read a file."""
        path = params.get("path")
        if not path:
            raise ValueError("path required")
        
        # TODO: Implement safe file reading
        return {
            "path": path,
            "content": "TODO: Read file",
        }
    
    async def _handle_files_upload(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Upload a file (base64 encoded in params)."""
        filename = params.get("filename")
        content_b64 = params.get("content", "")
        
        if not filename:
            raise ValueError("filename required")
        
        # TODO: Implement file upload
        return {
            "filename": filename,
            "size": len(content_b64),
            "uploaded": True,
        }
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Memory
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_memory_search(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Search memory."""
        query = params.get("query", "")
        limit = params.get("limit", 10)
        
        # TODO: Implement memory search
        return {
            "query": query,
            "results": [],
        }
    
    async def _handle_memory_remember(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Store a memory."""
        content = params.get("content", "")
        if not content:
            raise ValueError("content required")
        
        # TODO: Implement memory storage
        return {
            "stored": True,
            "id": f"mem-{secrets.token_hex(8)}",
        }
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Agents
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_agents_list(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """List all agents."""
        # TODO: Get from agent registry
        return {"agents": []}
    
    async def _handle_agents_get(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Get a specific agent."""
        agent_id = params.get("agentId") or params.get("agent_id")
        if not agent_id:
            raise ValueError("agentId required")
        return {"agentId": agent_id}
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Models
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_models_list(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """List available models."""
        return {"models": []}
    
    async def _handle_models_set(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Set the active model."""
        model = params.get("model")
        if not model:
            raise ValueError("model required")
        return {"model": model, "active": True}
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Events
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_events_subscribe(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Subscribe to global events."""
        events = params.get("events", ["*"])
        for event_type in events:
            if event_type not in self._event_subscribers:
                self._event_subscribers[event_type] = set()
            self._event_subscribers[event_type].add(conn.connection_id)
        
        return {"subscribed": events}
    
    # ─────────────────────────────────────────────────────────────
    # Method Handlers — Utility
    # ─────────────────────────────────────────────────────────────
    
    async def _handle_ping(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Ping/pong."""
        return {"pong": time.time()}
    
    async def _handle_health(self, conn: WebSocketConnection, params: dict[str, Any]) -> Any:
        """Health check."""
        return {
            "status": "ok",
            "connections": len(self.connections),
            "uptime": time.time() - self.gateway.start_time if hasattr(self.gateway, "start_time") else 0,
        }


def register_websocket_routes(app: web.Application, gateway_app: Any) -> WebSocketHandler:
    """Register WebSocket routes on the aiohttp app.
    
    Returns the WebSocketHandler for broadcasting events.
    """
    handler = WebSocketHandler(gateway_app)
    
    # Register WebSocket endpoint
    app.router.add_get("/ws", handler.handle_connection)
    app.router.add_get("/api/ws", handler.handle_connection)  # Alias
    
    logger.info("WebSocket routes registered: /ws, /api/ws")
    return handler


__all__ = [
    "WebSocketHandler",
    "WebSocketConnection",
    "WSRequest",
    "WSResponse",
    "WSEvent",
    "WSMessageType",
    "register_websocket_routes",
]
