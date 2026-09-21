"""Integration descriptors and lifecycle for commissioning.

Lifecycle: DISCOVER → auth? → authorize → configure → test → register.

This module is the architecture. Existing plugins and host capabilities
are adapted first; new integrations plug in later.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REGISTRY_FILENAME = "integration_registry.json"


@dataclass
class IntegrationDescriptor:
    id: str
    title: str
    capabilities: list[str] = field(default_factory=list)
    requires_auth: bool = False
    discovered: bool = False
    authorized: bool = False
    configured: bool = False
    healthy: bool = False
    tools: list[str] = field(default_factory=list)
    sensors: list[str] = field(default_factory=list)
    detail: str = ""
    auth_kind: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registry_path(instance_root: Path | Any) -> Path:
    from jaeger_ai.core.instance.first_boot import instance_dir
    return instance_dir(instance_root) / REGISTRY_FILENAME


def load_integrations(instance_root: Path | Any) -> list[IntegrationDescriptor]:
    path = registry_path(instance_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = data.get("integrations") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[IntegrationDescriptor] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        out.append(IntegrationDescriptor(
            id=str(row["id"]),
            title=str(row.get("title") or row["id"]),
            capabilities=list(row.get("capabilities") or []),
            requires_auth=bool(row.get("requires_auth")),
            discovered=bool(row.get("discovered")),
            authorized=bool(row.get("authorized")),
            configured=bool(row.get("configured")),
            healthy=bool(row.get("healthy")),
            tools=list(row.get("tools") or []),
            sensors=list(row.get("sensors") or []),
            detail=str(row.get("detail") or ""),
            auth_kind=str(row.get("auth_kind") or ""),
        ))
    return out


def save_integrations(instance_root: Path | Any, items: list[IntegrationDescriptor]) -> None:
    path = registry_path(instance_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"updated_at": _stamp(), "integrations": [i.as_dict() for i in items]},
        indent=2, sort_keys=True,
    )
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".integ.", suffix=".tmp")
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


def _bundled_plugins() -> list[IntegrationDescriptor]:
    items: list[IntegrationDescriptor] = []
    root = Path(__file__).resolve().parents[2] / "plugins"
    if not root.is_dir():
        return items
    try:
        from jaeger_ai.plugins.manifest import load_manifest
    except Exception:
        return items
    for folder in sorted(root.iterdir()):
        manifest_path = folder / "plugin.yaml"
        if not folder.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = load_manifest(manifest_path)
        except Exception:
            continue
        name = str(getattr(manifest, "name", folder.name) or folder.name)
        requires = getattr(manifest, "requires", None)
        env = list(getattr(requires, "env", None) or []) if requires is not None else []
        provides = getattr(manifest, "provides", None)
        tools = list(getattr(provides, "tools", None) or []) if provides is not None else []
        items.append(IntegrationDescriptor(
            id=name,
            title=str(getattr(manifest, "title", None) or name),
            capabilities=list(getattr(manifest, "capabilities", None) or []),
            requires_auth=bool(env),
            discovered=True,
            tools=tools,
            auth_kind="credential" if env else "",
            detail="bundled plugin",
        ))
    return items


def discover_integrations(
    instance_root: Path | Any,
    *,
    host: dict[str, Any] | None = None,
) -> list[IntegrationDescriptor]:
    """Discover existing plugins plus built-in host integrations."""
    host = host or {}
    development = host.get("development") or {}
    audio = host.get("audio") or {}
    vision = host.get("vision") or {}
    builtin = [
        IntegrationDescriptor(
            id="filesystem",
            title="Files and projects",
            capabilities=["filesystem.read", "filesystem.write"],
            discovered=True,
            tools=["read_file", "write_file", "edit_file"],
        ),
        IntegrationDescriptor(
            id="git",
            title="Git",
            capabilities=["git"],
            discovered=bool(development.get("git")),
            tools=["git_status", "git_diff", "git_commit"],
        ),
        IntegrationDescriptor(
            id="github",
            title="GitHub",
            capabilities=["github"],
            requires_auth=True,
            discovered=bool(development.get("git")),
            authorized=bool(development.get("github_auth")),
            auth_kind="gh",
            tools=["gh"],
        ),
        IntegrationDescriptor(
            id="browser",
            title="Browser",
            capabilities=["browser"],
            discovered=True,
            tools=["web_search", "browser_open"],
        ),
        IntegrationDescriptor(
            id="microphone",
            title="Microphone",
            capabilities=["microphone", "stt"],
            discovered=bool(audio.get("microphone")),
            sensors=["microphone"],
        ),
        IntegrationDescriptor(
            id="camera",
            title="Camera",
            capabilities=["camera"],
            discovered=bool(vision.get("camera_available")),
            sensors=["camera"],
        ),
        IntegrationDescriptor(
            id="screen",
            title="Screen",
            capabilities=["screen"],
            discovered=bool(vision.get("screen_capture_capability")),
            sensors=["screen"],
        ),
        IntegrationDescriptor(
            id="email",
            title="Email",
            capabilities=["email"],
            requires_auth=True,
            discovered=True,
            authorized=False,
            auth_kind="oauth",
        ),
        IntegrationDescriptor(
            id="calendar",
            title="Calendar",
            capabilities=["calendar"],
            requires_auth=True,
            discovered=True,
            authorized=False,
            auth_kind="oauth",
        ),
    ]
    plugins = _bundled_plugins()
    by_id = {item.id: item for item in builtin}
    for plugin in plugins:
        by_id.setdefault(plugin.id, plugin)
    items = list(by_id.values())
    save_integrations(instance_root, items)
    return items


def pending_auth(items: list[IntegrationDescriptor]) -> list[IntegrationDescriptor]:
    """Integrations that need a person to sign in before they can be used.

    First boot only asks for integrations the person already enabled.
    Newly discovered optional services stay pending until later.
    """
    return [
        item for item in items
        if item.requires_auth and item.discovered and not item.authorized
        and item.id in {"github"} and item.authorized is False
    ]


def mark_authorized(instance_root: Path | Any, integration_id: str) -> list[IntegrationDescriptor]:
    items = load_integrations(instance_root)
    for item in items:
        if item.id == integration_id:
            item.authorized = True
            item.configured = True
    save_integrations(instance_root, items)
    return items


def health_check(item: IntegrationDescriptor) -> bool:
    if item.id == "git":
        import shutil
        item.healthy = shutil.which("git") is not None
        return item.healthy
    if item.id == "github":
        item.healthy = bool(item.authorized)
        return item.healthy
    if not item.requires_auth:
        item.healthy = item.discovered
        return item.healthy
    item.healthy = bool(item.authorized)
    return item.healthy


__all__ = [
    "IntegrationDescriptor",
    "discover_integrations",
    "health_check",
    "load_integrations",
    "mark_authorized",
    "pending_auth",
    "save_integrations",
]
