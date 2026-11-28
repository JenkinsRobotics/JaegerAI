"""Pluggable ExecutionBackend protocol, opt-in allowlisted SSHBackend & Tailscale discovery.

Respects JaegerAI Golden Rules:
- Zero hardcoded user IPs, hostnames, or credentials (config lives in `<state_dir>/remote_hosts.json`).
- Tailscale-first trust boundary: `discover_tailscale_peers` and `register_tailscale_peer`
  only admit machines verified to be on the owner's active Tailscale tailnet.
- Fail-closed: only explicitly enabled hosts in the owner allowlist can be targeted.
- Non-interactive (`BatchMode=yes`), bounded timeouts, strict input validation, and
  automatic secret redaction on command outputs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

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
    "TailscalePeer",
    "discover_tailscale_peers",
    "find_tailscale_bin",
    "probe_tailscale_ssh",
    "register_tailscale_peer",
    "ssh_setup_hint",
]

_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")
_USER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")
_VALID_STRICT_MODES = frozenset({"yes", "accept-new"})
_TAILSCALE_CANDIDATES = (
    "/opt/homebrew/bin/tailscale",
    "/usr/local/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/usr/bin/tailscale",
)


class RemoteExecError(RuntimeError):
    """Raised when a remote host configuration or execution violates fail-closed policy."""


class ExecutionBackend(Protocol):
    """Minimal pluggable execution backend interface (local, SSH, container, etc.)."""

    def run(self, command: str, *, timeout_s: float = 30.0) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class TailscalePeer:
    """One device discovered on the owner's active Tailscale tailnet."""

    hostname: str
    dns_name: str
    tailscale_ip: str
    os_name: str
    online: bool
    has_ssh_host_keys: bool = False
    is_self: bool = False

    def suggested_alias(self) -> str:
        raw = re.sub(r"[^A-Za-z0-9._-]+", "-", (self.hostname or self.tailscale_ip).strip()).strip("-._")
        if not raw or not _ALIAS_RE.match(raw):
            raw = f"ts-{self.tailscale_ip.replace('.', '-')}"
        return raw[:48].lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "dns_name": self.dns_name,
            "tailscale_ip": self.tailscale_ip,
            "os": self.os_name,
            "online": self.online,
            "has_ssh_host_keys": self.has_ssh_host_keys,
            "is_self": self.is_self,
            "suggested_alias": self.suggested_alias(),
        }


def find_tailscale_bin() -> str | None:
    """Locate the local ``tailscale`` CLI binary on PATH or standard macOS/Linux paths."""
    found = shutil.which("tailscale")
    if found:
        return found
    for cand in _TAILSCALE_CANDIDATES:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _parse_tailscale_peer(raw: Mapping[str, Any], *, is_self: bool = False) -> TailscalePeer | None:
    ips = [str(ip).strip() for ip in (raw.get("TailscaleIPs") or ()) if str(ip).strip()]
    ipv4 = next((ip for ip in ips if "." in ip), ips[0] if ips else "")
    if not ipv4:
        return None
    hostname = str(raw.get("HostName") or "").strip() or ipv4
    dns_name = str(raw.get("DNSName") or "").strip().rstrip(".")
    os_name = str(raw.get("OS") or "").strip()
    online = bool(raw.get("Online", is_self))
    ssh_keys = raw.get("sshHostKeys") or raw.get("SSHHostKeys") or []
    return TailscalePeer(
        hostname=hostname,
        dns_name=dns_name,
        tailscale_ip=ipv4,
        os_name=os_name,
        online=online,
        has_ssh_host_keys=bool(ssh_keys),
        is_self=is_self,
    )


def discover_tailscale_peers(
    *,
    tailscale_bin: str | None = None,
    timeout_s: float = 8.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """Discover machines on the owner's active Tailscale tailnet via ``tailscale status --json``."""
    binary = tailscale_bin or find_tailscale_bin()
    if not binary:
        return {
            "ok": False,
            "error": "Tailscale CLI not found on this machine. Install/sign into Tailscale first.",
            "self": None,
            "peers": [],
        }
    exec_fn = runner or subprocess.run
    try:
        proc = exec_fn(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=max(2.0, min(float(timeout_s), 20.0)),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"tailscale status failed: {exc}", "self": None, "peers": []}
    if proc.returncode != 0:
        err = redact_text((proc.stderr or proc.stdout or "").strip())[:400]
        return {
            "ok": False,
            "error": err or f"tailscale status exited {proc.returncode}",
            "self": None,
            "peers": [],
        }
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"invalid tailscale status JSON: {exc}", "self": None, "peers": []}

    self_peer = _parse_tailscale_peer(payload.get("Self") or {}, is_self=True) if isinstance(payload.get("Self"), Mapping) else None
    peers: list[TailscalePeer] = []
    raw_peers = payload.get("Peer")
    if isinstance(raw_peers, Mapping):
        for entry in raw_peers.values():
            if not isinstance(entry, Mapping):
                continue
            parsed = _parse_tailscale_peer(entry, is_self=False)
            if parsed is not None:
                peers.append(parsed)
    peers.sort(key=lambda p: (not p.online, p.hostname.lower()))
    return {
        "ok": True,
        "backend_state": str(payload.get("BackendState") or ""),
        "self": self_peer.to_dict() if self_peer else None,
        "peers": [p.to_dict() for p in peers],
        "online_count": sum(1 for p in peers if p.online),
        "total_count": len(peers),
    }


def ssh_setup_hint(os_name: str, *, tailscale_ip: str = "", hostname: str = "") -> str:
    """Return a concise, single-step OS command to enable SSH/Tailscale SSH on the target machine."""
    low = (os_name or "").strip().lower()
    target = hostname or tailscale_ip or "the target computer"
    if "win" in low:
        return (
            f"On {target} (PowerShell as Administrator), enable OpenSSH Server once: "
            "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0; "
            "Start-Service sshd; Set-Service -Name sshd -StartupType Automatic"
        )
    if "mac" in low or "darwin" in low:
        return (
            f"On {target}, enable Tailscale SSH once with `tailscale set --ssh` "
            "(or turn on System Settings -> General -> Sharing -> Remote Login)."
        )
    return f"On {target}, enable Tailscale SSH once with `sudo tailscale set --ssh`."


def probe_tailscale_ssh(
    hostname: str,
    *,
    user: str = "",
    port: int = 22,
    identity_file: str = "",
    os_name: str = "",
    ssh_bin: str = "ssh",
    timeout_s: float = 8.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """Run a non-interactive SSH connectivity check (BatchMode=yes) against a Tailscale peer."""
    if not _HOST_RE.match(hostname):
        raise RemoteExecError(f"Invalid hostname {hostname!r}")
    if user and not _USER_RE.match(user):
        raise RemoteExecError(f"Invalid SSH user {user!r}")
    argv = [
        ssh_bin,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
        "-p", str(int(port)),
    ]
    if identity_file:
        argv.extend(["-i", str(Path(identity_file).expanduser())])
    target = f"{user}@{hostname}" if user else hostname
    argv.extend(["--", target, "echo JAEGER_SSH_OK"])
    exec_fn = runner or subprocess.run
    try:
        proc = exec_fn(
            argv,
            capture_output=True,
            text=True,
            timeout=max(2.0, min(float(timeout_s), 20.0)),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "reachable": False,
            "target": target,
            "error": redact_text(str(exc))[:400],
            "setup_hint": ssh_setup_hint(os_name, tailscale_ip=hostname),
        }
    out = redact_text((proc.stdout or "").strip())
    err = redact_text((proc.stderr or "").strip())
    ok = proc.returncode == 0 and "JAEGER_SSH_OK" in out
    res: dict[str, Any] = {
        "reachable": ok,
        "target": target,
        "returncode": proc.returncode,
        "stdout": out[:500],
        "stderr": err[:500],
    }
    if not ok:
        res["setup_hint"] = ssh_setup_hint(os_name, tailscale_ip=hostname)
    return res


def register_tailscale_peer(
    registry: "RemoteHostRegistry",
    peer_query: str,
    *,
    alias: str = "",
    user: str = "",
    port: int = 22,
    identity_file: str = "",
    probe: bool = True,
    tailscale_bin: str | None = None,
    ssh_bin: str = "ssh",
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """Verify *peer_query* exists on the owner's Tailscale tailnet, register it, and probe SSH.

    Enforces Tailscale as the owner's sole remote-trust boundary: unknown/external hosts
    not present on the active tailnet are rejected.
    """
    q = (peer_query or "").strip()
    if not q:
        raise RemoteExecError("peer hostname, DNS name, or Tailscale IP is required")
    discovered = discover_tailscale_peers(tailscale_bin=tailscale_bin, runner=runner)
    if not discovered.get("ok"):
        return {
            "ok": False,
            "error": discovered.get("error") or "Unable to inspect Tailscale tailnet",
        }
    q_low = q.lower()
    matched: dict[str, Any] | None = None
    for peer in discovered.get("peers") or ():
        candidates = {
            str(peer.get("hostname") or "").lower(),
            str(peer.get("dns_name") or "").lower(),
            str(peer.get("tailscale_ip") or "").lower(),
            str(peer.get("suggested_alias") or "").lower(),
        }
        if q_low in candidates:
            matched = peer
            break
    if matched is None:
        # Substring fallback if unique among tailnet peers (e.g. "rack" -> "RackPCExample")
        partials = [
            p for p in (discovered.get("peers") or ())
            if q_low in str(p.get("hostname") or "").lower()
            or q_low in str(p.get("dns_name") or "").lower()
        ]
        if len(partials) == 1:
            matched = partials[0]
        elif len(partials) > 1:
            names = [p.get("hostname") for p in partials]
            return {
                "ok": False,
                "error": f"Ambiguous Tailscale peer {q!r}; matches: {names}. Specify the exact hostname or IP.",
                "matches": partials,
            }
    if matched is None:
        return {
            "ok": False,
            "error": (
                f"No device matching {q!r} found on your Tailscale network. "
                "Add that computer to your Tailscale account first, then ask me to connect again."
            ),
            "available_peers": [
                {"hostname": p.get("hostname"), "tailscale_ip": p.get("tailscale_ip"), "online": p.get("online"), "os": p.get("os")}
                for p in (discovered.get("peers") or ())
            ],
        }

    chosen_alias = (alias or str(matched.get("suggested_alias") or "")).strip().lower()
    target_ip = str(matched["tailscale_ip"])
    os_name = str(matched.get("os") or "")
    notes = f"Tailscale peer {matched.get('hostname')} ({os_name or 'unknown OS'})"
    cfg = RemoteHostConfig(
        alias=chosen_alias,
        hostname=target_ip,
        user=(user or "").strip(),
        port=int(port or 22),
        identity_file=(identity_file or "").strip(),
        strict_host_key="accept-new",
        enabled=True,
        notes=notes[:240],
    )
    saved = registry.upsert(cfg)
    result: dict[str, Any] = {
        "ok": True,
        "registered": saved.to_public_dict(),
        "peer": matched,
        "registry_path": str(registry.path),
    }
    if probe:
        if not matched.get("online"):
            result["ssh_probe"] = {
                "reachable": False,
                "error": f"{matched.get('hostname')} is currently offline on Tailscale.",
                "setup_hint": f"Power on {matched.get('hostname')} and make sure Tailscale is connected.",
            }
        else:
            result["ssh_probe"] = probe_tailscale_ssh(
                target_ip,
                user=saved.user,
                port=saved.port,
                identity_file=saved.identity_file,
                os_name=os_name,
                ssh_bin=ssh_bin,
                runner=runner,
            )
    return result


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
