"""Security, encryption, and data redaction utilities for the Jaeger Finance Engine.

Enforces:
- Keychain-backed AES-256-GCM encryption for sensitive data at rest.
- Strict PII masking (account numbers truncated to last 4 digits).
- Prompt injection defenses for untrusted merchant strings and transaction notes.
- Fail-closed secret handling (never leaks into logs or model prompts).
"""

from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("jaeger_ai.features.finance.security")

KEYCHAIN_SERVICE = "JaegerAI.Finance"
KEYCHAIN_ACCOUNT = "master_key"
FALLBACK_KEY_FILE = ".master.key"

# Detect prompt injection patterns in merchant names and transaction notes
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"\[/INST\]", re.IGNORECASE),
    re.compile(r"\{\{.*\}\}"),
    re.compile(r"eval\(", re.IGNORECASE),
    re.compile(r"exec\(", re.IGNORECASE),
]

_ACCOUNT_MASK_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_TOKEN_RE = re.compile(r"(?i)(bearer|token|secret|password|key)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{12,})['\"]?")


def _state_root() -> Path:
    raw = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".jaeger").resolve()


def _get_key_from_keychain() -> bytes | None:
    """Attempt to retrieve master key from macOS Keychain."""
    try:
        cmd = [
            "/usr/bin/security",
            "find-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", KEYCHAIN_ACCOUNT,
            "-w",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return base64.b64decode(res.stdout.strip())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Keychain read failed (fallback enabled): %s", type(exc).__name__)
    return None


def _set_key_in_keychain(key: bytes) -> bool:
    """Store master key in macOS Keychain."""
    try:
        b64_key = base64.b64encode(key).decode("ascii")
        cmd = [
            "/usr/bin/security",
            "add-generic-password",
            "-U",
            "-s", KEYCHAIN_SERVICE,
            "-a", KEYCHAIN_ACCOUNT,
            "-w", b64_key,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception as exc:  # noqa: BLE001
        logger.debug("Keychain write failed (fallback enabled): %s", type(exc).__name__)
        return False


def get_or_create_master_key(custom_dir: Path | None = None) -> bytes:
    """Obtain or generate a 256-bit AES-GCM master key.
    
    Priority:
    1. macOS Keychain (production Mac standard).
    2. File-based fallback (~/.jaeger/finance/.master.key) with strict 0600 permissions.
    """
    key = _get_key_from_keychain()
    if key and len(key) == 32:
        return key

    key_dir = custom_dir or (_state_root() / "finance")
    key_dir.mkdir(parents=True, exist_ok=True)
    key_file = key_dir / FALLBACK_KEY_FILE

    if key_file.is_file():
        try:
            mode = key_file.stat().st_mode & 0o777
            if mode != 0o600:
                key_file.chmod(0o600)
            data = base64.b64decode(key_file.read_text(encoding="utf-8").strip())
            if len(data) == 32:
                # Try to promote to keychain
                _set_key_in_keychain(data)
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read fallback master key: %s", type(exc).__name__)

    # Generate fresh 256-bit key
    fresh_key = AESGCM.generate_key(bit_length=256)
    _set_key_in_keychain(fresh_key)

    # Persist backup to 0600 file
    key_file.write_text(base64.b64encode(fresh_key).decode("ascii"), encoding="utf-8")
    key_file.chmod(0o600)
    return fresh_key


class FinanceCipher:
    """Authenticated encryption (AES-256-GCM) for sensitive fields."""

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key or get_or_create_master_key()
        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext string into base64-encoded nonce + ciphertext."""
        if not plaintext:
            return ""
        nonce = os.urandom(12)  # 96-bit nonce
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        combined = nonce + ct
        return base64.b64encode(combined).decode("ascii")

    def decrypt(self, encoded: str) -> str:
        """Decrypt base64-encoded ciphertext."""
        if not encoded:
            return ""
        try:
            raw = base64.b64decode(encoded.encode("ascii"))
            if len(raw) < 13:
                return encoded  # Not encrypted / legacy
            nonce = raw[:12]
            ct = raw[12:]
            pt = self._aesgcm.decrypt(nonce, ct, None)
            return pt.decode("utf-8")
        except Exception:
            # Fallback in case raw text was stored
            return encoded


class SecuritySanitizer:
    """Sanitize untrusted statements, merchant names, and notes."""

    @staticmethod
    def sanitize_untrusted_text(text: str | None, max_len: int = 255) -> str:
        """Strip control characters, prompt injection markers, and bounded length."""
        if not text:
            return ""
        clean = str(text)
        # Remove null bytes and non-printable control characters
        clean = "".join(ch for ch in clean if ch.isprintable() or ch in " \t\n")
        # Check and defang prompt injection markers
        for pat in _INJECTION_PATTERNS:
            clean = pat.sub("[REDACTED_INJECTION]", clean)
        # Strip excessive whitespace
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean[:max_len]

    @staticmethod
    def mask_account_identifier(account_number: str | None) -> str:
        """Mask account number to last 4 digits (e.g. *1234)."""
        if not account_number:
            return ""
        digits = re.sub(r"\D", "", str(account_number))
        if len(digits) <= 4:
            return f"*{digits}" if digits else ""
        return f"*{digits[-4:]}"

    @staticmethod
    def redact_pii(text: str) -> str:
        """Redact SSNs, full credit card numbers, and secret tokens from strings."""
        if not text:
            return ""
        s = _SSN_RE.sub("[SSN_REDACTED]", text)
        s = _ACCOUNT_MASK_RE.sub("[CARD_REDACTED]", s)
        s = _TOKEN_RE.sub(r"\1=[TOKEN_REDACTED]", s)
        return s
