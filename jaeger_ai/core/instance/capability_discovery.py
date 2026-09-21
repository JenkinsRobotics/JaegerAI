"""Capability registry — what can actually work on this host.

Capabilities are independent of raw hardware. A microphone may exist
while STT is not authorized; Git may be installed while GitHub is not
authenticated. Commissioning reads this registry to decide what to
configure, what to ask a person, and what to leave for later.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REGISTRY_FILENAME = "capability_registry.json"

CAPABILITY_IDS = (
    "filesystem.read",
    "filesystem.write",
    "git",
    "github",
    "browser",
    "email",
    "calendar",
    "microphone",
    "camera",
    "screen",
    "notifications",
    "local_ai",
    "cloud_ai",
    "stt",
    "tts",
    "shell",
    "self_modification",
)


@dataclass
class Capability:
    id: str
    available: bool = False
    configured: bool = False
    authorized: bool = False
    tested: bool = False
    healthy: bool = False
    adapter: str = ""
    provider: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityRegistry:
    capabilities: dict[str, Capability] = field(default_factory=dict)
    updated_at: str = ""

    def get(self, capability_id: str) -> Capability:
        if capability_id not in self.capabilities:
            self.capabilities[capability_id] = Capability(id=capability_id)
        return self.capabilities[capability_id]

    def as_dict(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "capabilities": {k: v.as_dict() for k, v in self.capabilities.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CapabilityRegistry":
        doc = data or {}
        caps: dict[str, Capability] = {}
        raw = doc.get("capabilities") or {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if not isinstance(value, dict):
                    continue
                caps[str(key)] = Capability(
                    id=str(value.get("id") or key),
                    available=bool(value.get("available")),
                    configured=bool(value.get("configured")),
                    authorized=bool(value.get("authorized")),
                    tested=bool(value.get("tested")),
                    healthy=bool(value.get("healthy")),
                    adapter=str(value.get("adapter") or ""),
                    provider=str(value.get("provider") or ""),
                    detail=str(value.get("detail") or ""),
                )
        return cls(capabilities=caps, updated_at=str(doc.get("updated_at") or ""))


def registry_path(instance_root: Path | Any) -> Path:
    from jaeger_ai.core.instance.first_boot import instance_dir
    return instance_dir(instance_root) / REGISTRY_FILENAME


def load_registry(instance_root: Path | Any) -> CapabilityRegistry:
    path = registry_path(instance_root)
    if not path.is_file():
        return CapabilityRegistry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CapabilityRegistry.from_dict(data if isinstance(data, dict) else {})
    except Exception:
        return CapabilityRegistry()


def save_registry(instance_root: Path | Any, registry: CapabilityRegistry) -> None:
    path = registry_path(instance_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = json.dumps(registry.as_dict(), indent=2, sort_keys=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".capreg.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with __import__("contextlib").suppress(OSError):
            os.unlink(tmp)
        raise


def discover_capabilities(
    instance_root: Path | Any,
    host: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> CapabilityRegistry:
    """Build the registry from a host report plus persisted authority policy."""
    from jaeger_ai.core.instance.system_discovery import discover_host

    report = host if isinstance(host, dict) else discover_host().as_dict()
    policy = policy if isinstance(policy, dict) else {}
    registry = load_registry(instance_root)

    system = report.get("system") or {}
    audio = report.get("audio") or {}
    vision = report.get("vision") or {}
    ai = report.get("ai") or {}
    development = report.get("development") or {}
    compute = report.get("compute") or {}

    def _set(cid: str, **kwargs: Any) -> None:
        cap = registry.get(cid)
        for key, value in kwargs.items():
            setattr(cap, key, value)

    disk_ok = float(system.get("available_disk_gb") or 0) > 0
    _set("filesystem.read", available=disk_ok, adapter="local")
    _set("filesystem.write", available=disk_ok, adapter="local")
    _set("git", available=bool(development.get("git")), adapter="git")
    _set(
        "github",
        available=bool(development.get("git")),
        authorized=bool(development.get("github_auth")),
        adapter="gh",
    )
    _set("browser", available=True, adapter="web")
    _set("email", available=True, authorized=False, adapter="mail")
    _set("calendar", available=True, authorized=False, adapter="calendar")
    _set(
        "microphone",
        available=bool(audio.get("microphone")),
        adapter="avfoundation" if system.get("os") == "Darwin" else "portaudio",
    )
    _set(
        "camera",
        available=bool(vision.get("camera_available")),
        adapter="avfoundation",
    )
    _set(
        "screen",
        available=bool(vision.get("screen_capture_capability")),
        adapter="screencapture",
    )
    _set("notifications", available=system.get("os") == "Darwin", adapter="osascript")
    local_ai = bool(
        (ai.get("ollama") or {}).get("online")
        or (ai.get("lm_studio") or {}).get("online")
        or ai.get("installed_local_model_files")
        or compute.get("metal")
    )
    cloud_ai = any((ai.get("configured_cloud_providers") or {}).values()) or bool(
        (ai.get("ollama") or {}).get("online")
    )
    _set("local_ai", available=local_ai, adapter="ollama")
    _set("cloud_ai", available=cloud_ai, adapter="provider")
    _set("stt", available=bool(audio.get("stt_capability")), adapter="whisper")
    _set("tts", available=bool(audio.get("tts_capability")), adapter="kokoro")
    _set("shell", available=True, adapter="subprocess")
    _set("self_modification", available=True, adapter="worktree")

    files = policy.get("filesystem") or {}
    if files.get("read"):
        registry.get("filesystem.read").authorized = True
        registry.get("filesystem.read").configured = True
    if files.get("write"):
        registry.get("filesystem.write").authorized = True
        registry.get("filesystem.write").configured = True
    git_policy = policy.get("git") or {}
    if git_policy.get("local_commit"):
        registry.get("git").authorized = True
        registry.get("git").configured = True
    if git_policy.get("push") or policy.get("github"):
        registry.get("github").authorized = True
    if (policy.get("shell") or {}).get("risk_mode") in {"confirm", "allow"}:
        registry.get("shell").authorized = True
        registry.get("shell").configured = True
    if policy.get("microphone"):
        registry.get("microphone").authorized = True
    if policy.get("camera"):
        registry.get("camera").authorized = True
    if policy.get("screen"):
        registry.get("screen").authorized = True
    if (policy.get("email") or {}).get("read") or (policy.get("email") or {}).get("send"):
        registry.get("email").authorized = True
    if (policy.get("calendar") or {}).get("read") or (policy.get("calendar") or {}).get("modify"):
        registry.get("calendar").authorized = True
    if policy.get("self_modification_worktree"):
        registry.get("self_modification").authorized = True
        registry.get("self_modification").configured = True

    save_registry(instance_root, registry)
    return registry


__all__ = [
    "CAPABILITY_IDS",
    "Capability",
    "CapabilityRegistry",
    "discover_capabilities",
    "load_registry",
    "registry_path",
    "save_registry",
]
