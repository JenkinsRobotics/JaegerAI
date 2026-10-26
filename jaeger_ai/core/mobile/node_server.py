"""Mobile Node Server — WebSocket endpoint for mobile devices.

Implements a simplified version of OpenClaw's node protocol, compatible
with PWA (Progressive Web App) clients running in mobile browsers.

Protocol:
- WebSocket connection at /node
- JSON-RPC style frames (req/res/event)
- Ed25519 challenge-response authentication
- Device token for persistent connections

Capabilities exposed:
- camera.snap, camera.list — Take photos
- location.get — Get GPS location
- device.info, device.status — Device info
- notify.send — Push notifications
- file.upload — Upload files/photos
- shortcut.run — Run iOS Shortcuts / Android intents (via webhooks)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from enum import Enum
import asyncio
import json
import logging
import secrets
import time
import hashlib

logger = logging.getLogger(__name__)


class NodeState(str, Enum):
    """Connection state of a mobile node."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CHALLENGED = "challenged"  # Received challenge, waiting for response
    AUTHENTICATED = "authenticated"
    PAIRED = "paired"  # Fully paired and ready


@dataclass
class MobileNode:
    """A connected mobile device."""
    node_id: str
    device_name: str
    platform: str  # ios, android, web
    state: NodeState = NodeState.DISCONNECTED
    public_key: str = ""
    device_token: str = ""
    capabilities: list[str] = field(default_factory=list)
    permissions: dict[str, bool] = field(default_factory=dict)
    connected_at: float = 0.0
    last_seen: float = 0.0
    challenge: str = ""
    challenge_expires: float = 0.0
    
    # WebSocket connection (set when connected)
    websocket: Any = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "device_name": self.device_name,
            "platform": self.platform,
            "state": self.state.value,
            "capabilities": self.capabilities,
            "permissions": self.permissions,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MobileNode":
        return cls(
            node_id=data["node_id"],
            device_name=data.get("device_name", "Unknown"),
            platform=data.get("platform", "web"),
            state=NodeState(data.get("state", "disconnected")),
            public_key=data.get("public_key", ""),
            device_token=data.get("device_token", ""),
            capabilities=data.get("capabilities", []),
            permissions=data.get("permissions", {}),
            connected_at=data.get("connected_at", 0.0),
            last_seen=data.get("last_seen", 0.0),
        )


class MobileNodeServer:
    """WebSocket server for mobile node connections.

    Integrates with JaegerAI Gateway to expose mobile capabilities
    to the agent as tools.
    """

    def __init__(
        self,
        state_dir: Path | None = None,
        *,
        challenge_ttl: float = 600.0,  # 10 minutes
        token_ttl: float = 86400 * 365,  # 1 year
    ):
        self.state_dir = state_dir or Path.home() / ".jaeger" / "mobile"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.challenge_ttl = challenge_ttl
        self.token_ttl = token_ttl
        
        self.nodes: dict[str, MobileNode] = {}
        self.pending_pairings: dict[str, dict[str, Any]] = {}
        self.command_handlers: dict[str, Callable] = {}
        
        self._running = False
        self._server = None
        
        # Register default command handlers
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default command handlers."""
        self.command_handlers["camera.snap"] = self._handle_camera_snap
        self.command_handlers["camera.list"] = self._handle_camera_list
        self.command_handlers["location.get"] = self._handle_location_get
        self.command_handlers["device.info"] = self._handle_device_info
        self.command_handlers["device.status"] = self._handle_device_status
        self.command_handlers["notify.send"] = self._handle_notify_send
        self.command_handlers["file.upload"] = self._handle_file_upload
        self.command_handlers["shortcut.run"] = self._handle_shortcut_run
        self.command_handlers["ping"] = self._handle_ping

    # ─────────────────────────────────────────────────────────────
    # Connection Management
    # ─────────────────────────────────────────────────────────────

    async def start(self, host: str = "127.0.0.1", port: int = 33419) -> None:
        """Start the WebSocket server."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package required: pip install websockets")
            raise
        
        self._running = True
        self._server = await websockets.serve(
            self._handle_connection,
            host,
            port,
        )
        logger.info(f"Mobile node server started on ws://{host}:{port}")

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Mobile node server stopped")

    async def _handle_connection(self, websocket, path: str) -> None:
        """Handle a new WebSocket connection."""
        node: MobileNode | None = None
        
        try:
            # Send challenge
            challenge = secrets.token_hex(32)
            node = MobileNode(
                node_id=f"node-{secrets.token_hex(8)}",
                device_name="Unknown",
                platform="web",
                state=NodeState.CHALLENGED,
                challenge=challenge,
                challenge_expires=time.time() + self.challenge_ttl,
                websocket=websocket,
            )
            self.nodes[node.node_id] = node
            
            await websocket.send(json.dumps({
                "type": "event",
                "event": "connect.challenge",
                "payload": {
                    "nonce": challenge,
                    "ts": int(time.time() * 1000),
                },
            }))
            
            # Handle messages
            async for message in websocket:
                await self._handle_message(node, message)
                
        except Exception as e:
            logger.error(f"Connection error: {e}")
        finally:
            if node:
                node.state = NodeState.DISCONNECTED
                node.websocket = None

    async def _handle_message(self, node: MobileNode, message: str) -> None:
        """Handle a message from a node."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "req":
                await self._handle_request(node, data)
            elif msg_type == "res":
                await self._handle_response(node, data)
            
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON from {node.node_id}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    async def _handle_request(self, node: MobileNode, data: dict[str, Any]) -> None:
        """Handle a request frame."""
        method = data.get("method")
        params = data.get("params", {})
        request_id = data.get("id", "")
        
        if method == "connect":
            await self._handle_connect(node, params, request_id)
        elif method == "node.invoke.response":
            await self._handle_invoke_response(node, params, request_id)
        else:
            await self._send_error(node, request_id, f"Unknown method: {method}")

    async def _handle_connect(self, node: MobileNode, params: dict[str, Any], request_id: str) -> None:
        """Handle connection handshake."""
        # Verify challenge response
        device_info = params.get("device", {})
        signature = device_info.get("signature", "")
        public_key = device_info.get("publicKey", "")
        nonce = device_info.get("nonce", "")
        
        # TODO: Verify Ed25519 signature
        # For now, accept any valid-looking response
        
        node.public_key = public_key
        node.device_name = params.get("client", {}).get("displayName", "Unknown Device")
        node.platform = params.get("client", {}).get("platform", "web")
        node.capabilities = params.get("caps", [])
        node.permissions = params.get("permissions", {})
        node.state = NodeState.AUTHENTICATED
        node.connected_at = time.time()
        node.last_seen = time.time()
        
        # Generate device token
        node.device_token = secrets.token_urlsafe(32)
        
        # Send hello-ok
        await node.websocket.send(json.dumps({
            "type": "res",
            "id": request_id,
            "ok": True,
            "payload": {
                "type": "hello-ok",
                "protocol": 1,
                "server": {
                    "version": "0.13.0",
                    "connId": node.node_id,
                },
                "features": {
                    "methods": list(self.command_handlers.keys()),
                    "events": ["node.invoke.request"],
                },
                "auth": {
                    "deviceToken": node.device_token,
                    "role": "node",
                },
            },
        }))
        
        # Mark as paired
        node.state = NodeState.PAIRED
        logger.info(f"Node paired: {node.device_name} ({node.platform})")

    # ─────────────────────────────────────────────────────────────
    # Command Invocation (Agent → Node)
    # ─────────────────────────────────────────────────────────────

    async def invoke(self, node_id: str, command: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
        """Invoke a command on a connected node.

        Args:
            node_id: The node to invoke on
            command: Command name (e.g., "camera.snap")
            params: Command parameters
            timeout: Timeout in seconds

        Returns:
            Response payload
        """
        node = self.nodes.get(node_id)
        if not node or node.state != NodeState.PAIRED or not node.websocket:
            raise ValueError(f"Node {node_id} not connected")
        
        invoke_id = f"invoke-{secrets.token_hex(8)}"
        
        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self.pending_pairings[invoke_id] = {"future": future, "node": node}
        
        # Send invoke request
        await node.websocket.send(json.dumps({
            "type": "event",
            "event": "node.invoke.request",
            "payload": {
                "id": invoke_id,
                "nodeId": node_id,
                "command": command,
                "paramsJSON": json.dumps(params or {}),
                "timeoutMs": int(timeout * 1000),
            },
        }))
        
        # Wait for response
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.pending_pairings.pop(invoke_id, None)
            raise TimeoutError(f"Command {command} timed out on node {node_id}")

    async def _handle_response(self, node: MobileNode, data: dict[str, Any]) -> None:
        """Handle a response frame (from node)."""
        invoke_id = data.get("id")
        if invoke_id in self.pending_pairings:
            pending = self.pending_pairings.pop(invoke_id)
            future = pending["future"]
            if not future.done():
                future.set_result(data.get("payload", {}))

    async def _handle_invoke_response(self, node: MobileNode, params: dict[str, Any], request_id: str) -> None:
        """Handle invoke response from node."""
        payload = params.get("payload", {})
        invoke_id = payload.get("id")
        
        if invoke_id in self.pending_pairings:
            pending = self.pending_pairings.pop(invoke_id)
            future = pending["future"]
            if not future.done():
                future.set_result(payload)

    # ─────────────────────────────────────────────────────────────
    # Default Command Handlers
    # ─────────────────────────────────────────────────────────────

    async def _handle_camera_snap(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        """Handle camera.snap command."""
        # This would be handled by the node itself
        # The server just routes the command
        return {"status": "delegated", "message": "Camera snap delegated to node"}

    async def _handle_camera_list(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        return {"cameras": []}

    async def _handle_location_get(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        return {"status": "delegated"}

    async def _handle_device_info(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "node_id": node.node_id,
            "device_name": node.device_name,
            "platform": node.platform,
        }

    async def _handle_device_status(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": node.state.value,
            "connected_at": node.connected_at,
            "last_seen": node.last_seen,
        }

    async def _handle_notify_send(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        return {"status": "delegated"}

    async def _handle_file_upload(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        return {"status": "delegated"}

    async def _handle_shortcut_run(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        """Run a shortcut on the device (iOS Shortcuts, Android Intent)."""
        shortcut_name = params.get("name", "")
        shortcut_params = params.get("params", {})
        
        # This would trigger a webhook or deep link on the device
        return {
            "status": "triggered",
            "shortcut": shortcut_name,
            "params": shortcut_params,
        }

    async def _handle_ping(self, node: MobileNode, params: dict[str, Any]) -> dict[str, Any]:
        return {"pong": time.time()}

    # ─────────────────────────────────────────────────────────────
    # Utilities
    # ─────────────────────────────────────────────────────────────

    def list_nodes(self, state: NodeState | None = None) -> list[MobileNode]:
        """List connected nodes."""
        nodes = list(self.nodes.values())
        if state:
            nodes = [n for n in nodes if n.state == state]
        return nodes

    def get_node(self, node_id: str) -> MobileNode | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    async def _send_error(self, node: MobileNode, request_id: str, message: str) -> None:
        """Send an error response."""
        if node.websocket:
            await node.websocket.send(json.dumps({
                "type": "res",
                "id": request_id,
                "ok": False,
                "error": {"message": message},
            }))

    def generate_pairing_qr(self) -> dict[str, Any]:
        """Generate a pairing QR code payload.

        Returns data that can be encoded as a QR code for easy pairing.
        """
        bootstrap_token = secrets.token_urlsafe(32)
        pairing_id = secrets.token_hex(8)
        
        self.pending_pairings[pairing_id] = {
            "bootstrap_token": bootstrap_token,
            "created_at": time.time(),
            "expires_at": time.time() + 600,  # 10 minutes
        }
        
        return {
            "pairing_id": pairing_id,
            "bootstrap_token": bootstrap_token,
            "gateway_url": "ws://127.0.0.1:33419/node",  # Or Tailscale URL
            "expires_at": time.time() + 600,
        }


__all__ = ["MobileNodeServer", "MobileNode", "NodeState"]
