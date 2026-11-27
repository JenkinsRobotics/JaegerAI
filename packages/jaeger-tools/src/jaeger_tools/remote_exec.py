"""Pluggable ExecutionBackend protocol and opt-in allowlisted SSHBackend.

Respects JaegerAI Golden Rules:
- Zero hardcoded user IPs, hostnames, or credentials (config lives in `<state_dir>/remote_hosts.json`).
- Fail-closed: only explicitly enabled hosts in the owner allowlist can be targeted.
- Non-interactive (`BatchMode=yes`), bounded timeouts, strict input validation, and
  automatic secret redaction on command outputs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

try:
    from jaeger_authority import redact_text
except ImportError:  # pragma: no cover - standalone fallback
    def redact_text(text: str) -> str:
        return text

__all__ = [
    "ExecutionBackend",
    "LocalSubprocessBackend",
    "RemoteExecError",
    "RemoteHostConfig",
    "RemoteHostRegistry",
    "SSHBackend",
]

_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")
_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")
_VALID_STRICT_MODES = frozenset({"yes", "accept-new"})


class RemoteExecError(RuntimeError):
    """Raised when a remote host configuration or execution violates fail-closed policy."""


class ExecutionBackend(Protocol):
    """Minimal pluggable execution backend interface (local, SSH, container, etc.)."""

    def run(self, command: str, *, timeout_s: float = 30.0) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RemoteHostConfig:
    alias: str
    hostname: str
    user: str = ""
    port: int = 22
    identity_file: str = ""
    strict_host_key: str = "accept-new"
    allowed_prefixes: tuple[str, ...] = ()
    enabled: bool = True
    notes: str = ""

    def validated(self) -> RemoteHostConfig:
        if not _ALIAS_RE.match(self.alias):
            raise RemoteExecError(f"Invalid host alias {self.alias!r}")
        if not _HOST_RE.match(self.hostname):
            raise RemoteExecError(f"Invalid hostname {self.hostname!r}")
        if self.user and not _USER_RE.match(self.user):
            raise RemoteExecError(f"Invalid SSH user {self.user!r}")
        if not (1 <= int(self.port) <= 65535):
            raise RemoteExecError(f"Invalid SSH port {self.port!r}")
        if self.strict_host_key not in _VALID_STRICT_MODES:
            raise RemoteExecError(f"strict_host_key must be one of {sorted(_VALID_STRICT_MODES)}")
        if self.identity_file:
            if any(ord(c) < 0x20 or c in ("\x7f",) for c in self.identity_file):
                raise RemoteExecError("identity_file contains control characters")
        return self

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "hostname": self.hostname,
            "user": self.user,
            "port": self.port,
            "identity_file": self.identity_file,
            "strict_host_key": self.strict_host_key,
            "allowed_prefixes": list(self.allowed_prefixes),
            "enabled": self.enabled,
            "notes": self.notes,
        }


class RemoteHostRegistry:
    """Owner-managed JSON allowlist of authorized remote hosts (`<state_dir>/remote_hosts.json`)."""

    def __init__(self, config_path: Path) -> None:
        self._path = Path(config_path).expanduser().resolve()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, RemoteHostConfig]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        hosts_raw = raw.get("hosts") if isinstance(raw, Mapping) else None
        if not isinstance(hosts_raw, Mapping):
            return {}
        out: dict[str, RemoteHostConfig] = {}
        for alias, entry in hosts_raw.items():
            if not isinstance(entry, Mapping):
                continue
            try:
                cfg = RemoteHostConfig(
                    alias=str(alias),
                    hostname=str(entry.get("hostname") or "").strip(),
                    user=str(entry.get("user") or "").strip(),
                    port=int(entry.get("port") or 22),
                    identity_file=str(entry.get("identity_file") or "").strip(),
                    strict_host_key=str(entry.get("strict_host_key") or "accept-new").strip(),
                    allowed_prefixes=tuple(str(p).strip() for p in (entry.get("allowed_prefixes") or ()) if str(p).strip()),
                    enabled=bool(entry.get("enabled", True)),
                    notes=str(entry.get("notes") or "")[:240],
                ).validated()
                out[cfg.alias] = cfg
            except (RemoteExecError, ValueError, TypeError):
                continue
        return out

    def save(self, hosts: Mapping[str, RemoteHostConfig]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "hosts": {
                alias: {k: v for k, v in asdict(cfg.validated()).items() if k != "alias"}
                for alias, cfg in sorted(hosts.items())
            }
        }
        tmp = self._path.with_name(f".{self._path.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self._path)

    def upsert(self, cfg: RemoteHostConfig) -> RemoteHostConfig:
        validated = cfg.validated()
        hosts = self.load()
        hosts[validated.alias] = validated
        self.save(hosts)
        return validated

    def remove(self, alias: str) -> bool:
        hosts = self.load()
        if alias not in hosts:
            return False
        del hosts[alias]
        self.save(hosts)
        return True

    def list_public(self) -> list[dict[str, Any]]:
        return [cfg.to_public_dict() for cfg in self.load().values()]


class LocalSubprocessBackend:
    """Default local execution backend."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = Path(workspace).expanduser().resolve()

    def run(self, command: str, *, timeout_s: float = 30.0) -> dict[str, Any]:
        proc = subprocess.run(
            ["/bin/sh", "-c", command],
            cwd=str(self._workspace),
            capture_output=True,
            text=True,
            timeout=max(1.0, min(float(timeout_s), 120.0)),
        )
        return {
            "ok": proc.returncode == 0,
            "host": "local",
            "returncode": proc.returncode,
            "stdout": redact_text(proc.stdout or "")[:16_000],
            "stderr": redact_text(proc.stderr or "")[:8_000],
        }


class SSHBackend:
    """Allowlist-gated non-interactive SSH execution backend (BatchMode=yes)."""

    def __init__(self, registry: RemoteHostRegistry, *, ssh_bin: str = "ssh") -> None:
        self._registry = registry
        self._ssh_bin = ssh_bin

    def build_argv(self, host: RemoteHostConfig, command: str) -> list[str]:
        cfg = host.validated()
        if not cfg.enabled:
            raise RemoteExecError(f"Remote host {cfg.alias!r} is disabled")
        clean_cmd = (command or "").strip()
        if not clean_cmd or len(clean_cmd) > 8000:
            raise RemoteExecError("command must be 1-8000 characters")
        if cfg.allowed_prefixes and not any(clean_cmd.startswith(p) for p in cfg.allowed_prefixes):
            raise RemoteExecError(
                f"Command is not permitted by allowed_prefixes on host {cfg.alias!r}"
            )
        argv = [
            self._ssh_bin,
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", f"StrictHostKeyChecking={cfg.strict_host_key}",
            "-p", str(cfg.port),
        ]
        if cfg.identity_file:
            key_path = str(Path(cfg.identity_file).expanduser())
            argv.extend(["-i", key_path])
        target = f"{cfg.user}@{cfg.hostname}" if cfg.user else cfg.hostname
        argv.extend(["--", target, clean_cmd])
        return argv

    def run(self, command: str, *, host_alias: str, timeout_s: float = 30.0) -> dict[str, Any]:
        hosts = self._registry.load()
        cfg = hosts.get(host_alias)
        if cfg is None:
            raise RemoteExecError(
                f"Remote host {host_alias!r} is not in owner allowlist ({self._registry.path})"
            )
        argv = self.build_argv(cfg, command)
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=max(1.0, min(float(timeout_s), 120.0)),
        )
        return {
            "ok": proc.returncode == 0,
            "host": cfg.alias,
            "hostname": cfg.hostname,
            "returncode": proc.returncode,
            "stdout": redact_text(proc.stdout or "")[:16_000],
            "stderr": redact_text(proc.stderr or "")[:8_000],
        }
