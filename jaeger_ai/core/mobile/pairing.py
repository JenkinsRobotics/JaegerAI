"""Device pairing for mobile integration.

Implements a secure pairing flow inspired by OpenClaw:
1. Gateway generates a bootstrap token (short-lived)
2. Token is encoded in a QR code
3. Mobile device scans QR, connects via WebSocket
4. Device generates Ed25519 keypair
5. Challenge-response authentication
6. Gateway issues long-lived device token
7. Device reconnects with token for persistent connection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from enum import Enum
import secrets
import time
import json
import logging
import hashlib

logger = logging.getLogger(__name__)


class PairingState(str, Enum):
    """State of a pairing session."""
    PENDING = "pending"          # QR generated, waiting for device
    CHALLENGED = "challenged"    # Device connected, challenge sent
    AUTHENTICATED = "authenticated"  # Challenge verified
    APPROVED = "approved"        # Operator approved
    COMPLETED = "completed"      # Token issued
    EXPIRED = "expired"          # Token expired
    REJECTED = "rejected"        # Operator rejected


@dataclass
class PairingSession:
    """A pairing session between gateway and device."""
    session_id: str
    state: PairingState = PairingState.PENDING
    bootstrap_token: str = ""
    device_public_key: str = ""
    device_name: str = ""
    device_platform: str = ""
    challenge: str = ""
    challenge_signature: str = ""
    device_token: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 600)
    approved_by: str = ""
    approved_at: float = 0.0
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "device_name": self.device_name,
            "device_platform": self.device_platform,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired(),
        }


@dataclass
class DevicePairing:
    """A paired device record."""
    device_id: str
    device_name: str
    platform: str
    public_key: str
    device_token_hash: str  # SHA256 of token, not the token itself
    paired_at: float
    last_seen: float
    capabilities: list[str]
    permissions: dict[str, bool]
    approved_by: str
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "platform": self.platform,
            "paired_at": self.paired_at,
            "last_seen": self.last_seen,
            "capabilities": self.capabilities,
            "permissions": self.permissions,
            "approved_by": self.approved_by,
        }


class PairingManager:
    """Manages device pairing sessions and paired devices."""

    def __init__(self, state_dir: Path | None = None):
        self.state_dir = state_dir or Path.home() / ".jaeger" / "mobile" / "pairing"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        self.sessions: dict[str, PairingSession] = {}
        self.devices: dict[str, DevicePairing] = {}
        
        self._load_devices()

    def _load_devices(self) -> None:
        """Load paired devices from disk."""
        devices_file = self.state_dir / "devices.json"
        if devices_file.exists():
            try:
                data = json.loads(devices_file.read_text())
                for device_id, device_data in data.items():
                    self.devices[device_id] = DevicePairing(
                        device_id=device_id,
                        device_name=device_data.get("device_name", "Unknown"),
                        platform=device_data.get("platform", "web"),
                        public_key=device_data.get("public_key", ""),
                        device_token_hash=device_data.get("device_token_hash", ""),
                        paired_at=device_data.get("paired_at", 0),
                        last_seen=device_data.get("last_seen", 0),
                        capabilities=device_data.get("capabilities", []),
                        permissions=device_data.get("permissions", {}),
                        approved_by=device_data.get("approved_by", ""),
                    )
            except Exception as e:
                logger.error(f"Failed to load devices: {e}")

    def _save_devices(self) -> None:
        """Save paired devices to disk."""
        devices_file = self.state_dir / "devices.json"
        data = {did: d.to_dict() for did, d in self.devices.items()}
        # Also save public keys and token hashes
        for did, device in self.devices.items():
            data[did]["public_key"] = device.public_key
            data[did]["device_token_hash"] = device.device_token_hash
        
        devices_file.write_text(json.dumps(data, indent=2))
        devices_file.chmod(0o600)

    def create_pairing_session(self, ttl: float = 600.0) -> PairingSession:
        """Create a new pairing session.

        Args:
            ttl: Time-to-live in seconds (default 10 minutes)

        Returns:
            New pairing session with bootstrap token
        """
        session_id = secrets.token_hex(8)
        bootstrap_token = secrets.token_urlsafe(32)
        
        session = PairingSession(
            session_id=session_id,
            bootstrap_token=bootstrap_token,
            expires_at=time.time() + ttl,
        )
        self.sessions[session_id] = session
        
        logger.info(f"Created pairing session: {session_id}")
        return session

    def get_pairing_qr_data(self, session: PairingSession, gateway_url: str) -> dict[str, Any]:
        """Get data to encode in a QR code for pairing.

        Args:
            session: The pairing session
            gateway_url: WebSocket URL of the gateway

        Returns:
            Dictionary with QR code data
        """
        return {
            "v": 1,  # Protocol version
            "id": session.session_id,
            "token": session.bootstrap_token,
            "url": gateway_url,
            "name": "JaegerAI",
            "expires": int(session.expires_at),
        }

    def start_challenge(self, session_id: str) -> tuple[str, float] | None:
        """Start the challenge-response for a pairing session.

        Args:
            session_id: The pairing session ID

        Returns:
            (challenge, expires_at) or None if session invalid
        """
        session = self.sessions.get(session_id)
        if not session or session.is_expired():
            return None
        
        challenge = secrets.token_hex(32)
        session.challenge = challenge
        session.state = PairingState.CHALLENGED
        session.expires_at = time.time() + 300  # 5 minutes for response
        
        return challenge, session.expires_at

    def verify_challenge(
        self,
        session_id: str,
        public_key: str,
        signature: str,
        nonce: str,
    ) -> bool:
        """Verify the challenge response.

        Args:
            session_id: The pairing session ID
            public_key: Device's Ed25519 public key
            signature: Signature of the challenge
            nonce: The challenge nonce

        Returns:
            True if verification passed
        """
        session = self.sessions.get(session_id)
        if not session or session.is_expired() or session.state != PairingState.CHALLENGED:
            return False
        
        # Verify the challenge matches
        if nonce != session.challenge:
            logger.warning(f"Challenge mismatch for session {session_id}")
            return False
        
        # TODO: Verify Ed25519 signature
        # For now, accept any signature (implement proper crypto verification)
        
        session.device_public_key = public_key
        session.challenge_signature = signature
        session.state = PairingState.AUTHENTICATED
        
        # Generate device ID from public key
        device_id = hashlib.sha256(public_key.encode()).hexdigest()[:16]
        
        return True

    def approve_pairing(
        self,
        session_id: str,
        device_name: str,
        platform: str,
        capabilities: list[str],
        permissions: dict[str, bool],
        approved_by: str = "operator",
    ) -> DevicePairing | None:
        """Approve a pairing and create a device record.

        Args:
            session_id: The pairing session ID
            device_name: Human-readable device name
            platform: Device platform (ios, android, web)
            capabilities: List of device capabilities
            permissions: Permission grants
            approved_by: Who approved this pairing

        Returns:
            The created DevicePairing or None if failed
        """
        session = self.sessions.get(session_id)
        if not session or session.state != PairingState.AUTHENTICATED:
            return None
        
        # Generate device ID from public key
        device_id = hashlib.sha256(session.device_public_key.encode()).hexdigest()[:16]
        
        # Generate device token
        device_token = secrets.token_urlsafe(32)
        device_token_hash = hashlib.sha256(device_token.encode()).hexdigest()
        
        device = DevicePairing(
            device_id=device_id,
            device_name=device_name,
            platform=platform,
            public_key=session.device_public_key,
            device_token_hash=device_token_hash,
            paired_at=time.time(),
            last_seen=time.time(),
            capabilities=capabilities,
            permissions=permissions,
            approved_by=approved_by,
        )
        
        self.devices[device_id] = device
        self._save_devices()
        
        # Update session
        session.device_token = device_token
        session.device_name = device_name
        session.device_platform = platform
        session.state = PairingState.COMPLETED
        session.approved_by = approved_by
        session.approved_at = time.time()
        
        logger.info(f"Device paired: {device_name} ({platform}) as {device_id}")
        return device

    def verify_device_token(self, device_id: str, token: str) -> bool:
        """Verify a device token.

        Args:
            device_id: The device ID
            token: The device token

        Returns:
            True if token is valid
        """
        device = self.devices.get(device_id)
        if not device:
            return False
        
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if token_hash != device.device_token_hash:
            return False
        
        # Update last seen
        device.last_seen = time.time()
        self._save_devices()
        
        return True

    def reject_pairing(self, session_id: str, reason: str = "Operator rejected") -> bool:
        """Reject a pairing session."""
        session = self.sessions.get(session_id)
        if not session:
            return False
        
        session.state = PairingState.REJECTED
        logger.info(f"Pairing rejected: {session_id} ({reason})")
        return True

    def revoke_device(self, device_id: str) -> bool:
        """Revoke a paired device."""
        if device_id in self.devices:
            del self.devices[device_id]
            self._save_devices()
            logger.info(f"Device revoked: {device_id}")
            return True
        return False

    def list_devices(self) -> list[DevicePairing]:
        """List all paired devices."""
        return list(self.devices.values())

    def list_pending_sessions(self) -> list[PairingSession]:
        """List pending pairing sessions."""
        return [
            s for s in self.sessions.values()
            if s.state in (PairingState.PENDING, PairingState.CHALLENGED, PairingState.AUTHENTICATED)
            and not s.is_expired()
        ]

    def cleanup_expired(self) -> int:
        """Clean up expired sessions. Returns count removed."""
        expired = [
            sid for sid, s in self.sessions.items()
            if s.is_expired() and s.state != PairingState.COMPLETED
        ]
        for sid in expired:
            self.sessions[sid].state = PairingState.EXPIRED
            del self.sessions[sid]
        return len(expired)


__all__ = ["PairingManager", "PairingSession", "DevicePairing", "PairingState"]
