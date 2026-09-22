"""Security Hardening Layer (Workstream 19).

Enforces security boundaries across:
- Trust domain classification
- Safe archive extraction (Zip-slip & traversal prevention)
- Tool argument sanitization and privilege escalation prevention
- CSRF validation for WebUI and Gateway endpoints
"""
from __future__ import annotations

from enum import Enum
import io
import os
from pathlib import Path
import re
from typing import Any
import zipfile


class SecurityError(Exception):
    """Raised when a security invariant or boundary check is violated."""
    pass


class TrustDomain(str, Enum):
    """Explicit trust domains for Jaeger architecture."""
    TRUSTED_KERNEL_CODE = "trusted_kernel_code"
    TRUSTED_INSTALLED_CAPABILITY = "trusted_installed_capability"
    UNTRUSTED_CANDIDATE_CAPABILITY = "untrusted_candidate_capability"
    UNTRUSTED_RETRIEVED_DATA = "untrusted_retrieved_data"
    UNTRUSTED_USER_ATTACHMENT = "untrusted_user_attachment"
    UNTRUSTED_MODEL_OUTPUT = "untrusted_model_output"


class SafeArchiveExtractor:
    """Safely extracts archives preventing Zip Slip and symlink traversal attacks."""

    @staticmethod
    def extract_zip(zip_source: Path | str | bytes, dest_dir: Path | str) -> list[Path]:
        """Extract all files in zip_source to dest_dir safely.

        Raises SecurityError if any file attempts directory traversal or resolves
        outside dest_dir.
        """
        dest_path = Path(dest_dir).resolve()
        dest_path.mkdir(parents=True, exist_ok=True)
        extracted: list[Path] = []

        if isinstance(zip_source, bytes):
            zf = zipfile.ZipFile(io.BytesIO(zip_source))
        else:
            zf = zipfile.ZipFile(zip_source)

        with zf:
            for member in zf.infolist():
                # Disallow absolute paths and traversal sequences
                norm_name = os.path.normpath(member.filename)
                if norm_name.startswith("/") or norm_name.startswith("\\") or ".." in norm_name.split(os.sep):
                    raise SecurityError(
                        f"Zip Slip attempt detected: unsafe member path '{member.filename}'"
                    )

                target_file = (dest_path / norm_name).resolve()
                if not str(target_file).startswith(str(dest_path)):
                    raise SecurityError(
                        f"Zip Slip traversal attempt: resolved path '{target_file}' escapes destination '{dest_path}'"
                    )

                if member.is_dir():
                    target_file.mkdir(parents=True, exist_ok=True)
                else:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as source, open(target_file, "wb") as target:
                        target.write(source.read())
                    extracted.append(target_file)

        return extracted


class ToolArgumentSanitizer:
    """Validates tool arguments against unauthorized shell escalation and sensitive path access."""

    # Prohibited targets for model-proposed shell commands
    FORBIDDEN_COMMAND_PATTERNS = [
        re.compile(r"\brm\s+(-[rfRF]+\s+)?(/|~|\$HOME)\s*$"),
        re.compile(r"(curl|wget)\s+[^\n]*\|\s*(bash|sh|zsh)"),
        re.compile(r">\s*/etc/(passwd|shadow|hosts)"),
        re.compile(r"\bcat\s+~?/\.(ssh|aws|gnupg)"),
        re.compile(r"\bexport\s+.*TOKEN.*=.*(curl|wget)"),
        re.compile(r":\(\)\s*\{\s*:\|\:&\s*\};:"),  # Fork bomb
    ]

    FORBIDDEN_PATHS = [
        "~/.ssh",
        "~/.aws",
        "~/.gnupg",
        "/etc/shadow",
        "/etc/sudoers",
    ]

    @classmethod
    def validate_command(cls, command: str) -> tuple[bool, str | None]:
        """Inspect a proposed shell command for dangerous exploit patterns."""
        cmd_strip = command.strip()
        for pattern in cls.FORBIDDEN_COMMAND_PATTERNS:
            if pattern.search(cmd_strip):
                return False, f"Command violates security policy pattern: {pattern.pattern}"

        for p in cls.FORBIDDEN_PATHS:
            if p in cmd_strip:
                return False, f"Command references protected system path '{p}'"

        return True, None

    @classmethod
    def validate_path(cls, path: str, sandbox_root: Path | str | None = None) -> tuple[bool, str | None]:
        """Ensure file path is not escaping sandbox or accessing sensitive files."""
        for p in cls.FORBIDDEN_PATHS:
            if p in path:
                return False, f"Path references sensitive system location '{p}'"

        if sandbox_root:
            try:
                resolved = Path(path).resolve()
                root = Path(sandbox_root).resolve()
                if not str(resolved).startswith(str(root)):
                    return False, f"Path '{path}' escapes designated sandbox '{sandbox_root}'"
            except Exception as exc:
                return False, f"Invalid path syntax: {exc}"

        return True, None


class CsrfGuard:
    """Validates HTTP request headers to prevent Cross-Site Request Forgery."""

    @staticmethod
    def validate_origin_or_referer(
        origin: str | None,
        referer: str | None,
        allowed_hosts: list[str] | None = None,
    ) -> bool:
        """Verify that Origin or Referer matches an allowed local host."""
        allowed = set(allowed_hosts or [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
        ])

        header = origin or referer
        if not header:
            # Direct non-browser clients (CLI, Swift app) may not send Origin/Referer
            return True

        # Extract hostname from URL
        m = re.match(r"^https?://([^/:]+)", header)
        if not m:
            return False

        host = m.group(1).lower()
        return host in allowed
