"""Native lifecycle service for Apple container virtualization tools.

Manages external agent runtimes, services, and tools (OpenClaw, Hermes, n8n, etc.)
backed by Apple's native container tool (/opt/homebrew/bin/container).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_CONTAINER_CLI = "/opt/homebrew/bin/container"


def normalize_state(value):
    """Apple container CLI sometimes nests state as a dict with a state key."""
    if isinstance(value, dict):
        inner = value.get("state") or value.get("status")
        if isinstance(inner, str) and inner:
            return inner
        return "running" if value.get("startedDate") else "unknown"
    if isinstance(value, str) and value:
        return value
    return "unknown"

CONTAINERS_STORAGE_DIR = Path.home() / "Library/Application Support/com.apple.container/containers"


def resolve_container_cli() -> str:
    """Return the absolute path to the container CLI."""
    return (
        os.environ.get("CONTAINER_CLI")
        or shutil.which("container")
        or DEFAULT_CONTAINER_CLI
    )


def is_system_running() -> bool:
    """Check if the Apple container system daemon (apiserver) is responsive."""
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return False
    try:
        proc = subprocess.run(
            [cli, "system", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0 and "not running" not in proc.stdout.lower()
    except Exception:
        return False


def ensure_system_started(timeout: int = 15) -> bool:
    """Start the container system service if not already running."""
    if is_system_running():
        return True
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return False
    try:
        proc = subprocess.run(
            [cli, "system", "start", "--disable-kernel-install", "--timeout", str(timeout)],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        return proc.returncode == 0
    except Exception:
        return False


def stop_system() -> bool:
    """Stop all running containers and the container system daemon."""
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return False
    try:
        proc = subprocess.run(
            [cli, "system", "stop"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode == 0
    except Exception:
        return False


def list_installed_containers() -> list[dict[str, Any]]:
    """Enumerate all configured containers found in storage."""
    results: list[dict[str, Any]] = []
    if not CONTAINERS_STORAGE_DIR.is_dir():
        return results

    for entry in sorted(CONTAINERS_STORAGE_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        cfg_file = entry / "config.json"
        image_name = ""
        ports: list[dict[str, Any]] = []
        if cfg_file.is_file():
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                ports = data.get("publishedPorts", [])
            except Exception:
                pass
        
        runtime_cfg_file = entry / "runtime-configuration.json"
        if runtime_cfg_file.is_file():
            try:
                rdata = json.loads(runtime_cfg_file.read_text(encoding="utf-8"))
                image_name = rdata.get("image", "") or rdata.get("imageName", "")
            except Exception:
                pass

        results.append({
            "id": entry.name,
            "image": image_name,
            "ports": ports,
            "path": str(entry),
        })
    return results


def list_containers(all: bool = True) -> list[dict[str, Any]]:
    """List containers with live status from CLI if running, or storage metadata."""
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return []

    # If apiserver is alive, query CLI directly
    if is_system_running():
        try:
            cmd = [cli, "list", "--format", "json"]
            if all:
                cmd.append("--all")
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    data = json.loads(proc.stdout)
                    if isinstance(data, list):
                        return data
                except Exception:
                    pass
        except Exception:
            pass

    # Fallback: list from storage directory
    installed = list_installed_containers()
    for item in installed:
        item["state"] = "stopped"
        item["status"] = "stopped (system offline)"
    return installed


def start_container(name: str) -> dict[str, Any]:
    """Ensure system daemon is up, then start the named container."""
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return {"ok": False, "error": f"Container CLI not found at {cli}"}

    if not ensure_system_started():
        return {"ok": False, "error": "Failed to start container system service"}

    try:
        proc = subprocess.run(
            [cli, "start", name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return {"ok": True, "id": name, "state": "running"}
        err = proc.stderr.strip() or proc.stdout.strip()
        return {"ok": False, "id": name, "error": err}
    except Exception as exc:
        return {"ok": False, "id": name, "error": str(exc)}


def stop_container(name: str, timeout: int = 5) -> dict[str, Any]:
    """Stop the named container."""
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return {"ok": False, "error": f"Container CLI not found at {cli}"}

    try:
        proc = subprocess.run(
            [cli, "stop", "--time", str(timeout), name],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        if proc.returncode == 0:
            return {"ok": True, "id": name, "state": "stopped"}
        err = proc.stderr.strip() or proc.stdout.strip()
        return {"ok": False, "id": name, "error": err}
    except Exception as exc:
        return {"ok": False, "id": name, "error": str(exc)}


def delete_container(name: str, force: bool = False) -> dict[str, Any]:
    """Delete the container and its disks."""
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return {"ok": False, "error": f"Container CLI not found at {cli}"}

    if not ensure_system_started():
        return {"ok": False, "error": "Failed to start container system service for delete"}

    try:
        cmd = [cli, "delete"]
        if force:
            cmd.append("--force")
        cmd.append(name)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if proc.returncode == 0:
            return {"ok": True, "id": name, "deleted": True}
        err = proc.stderr.strip() or proc.stdout.strip()
        return {"ok": False, "id": name, "error": err}
    except Exception as exc:
        return {"ok": False, "id": name, "error": str(exc)}


def create_container(
    name: str,
    image: str,
    ports: list[str] | None = None,
    volumes: list[str] | None = None,
    envs: list[str] | None = None,
    cpus: int | None = None,
    memory: str | None = None,
) -> dict[str, Any]:
    """Create a new container tool."""
    cli = resolve_container_cli()
    if not Path(cli).exists():
        return {"ok": False, "error": f"Container CLI not found at {cli}"}

    if not ensure_system_started():
        return {"ok": False, "error": "Failed to start container system service for create"}

    cmd = [cli, "create", "--name", name]
    for p in ports or []:
        cmd.extend(["-p", p])
    for v in volumes or []:
        cmd.extend(["-v", v])
    for e in envs or []:
        cmd.extend(["-e", e])
    if cpus:
        cmd.extend(["--cpus", str(cpus)])
    if memory:
        cmd.extend(["--memory", memory])
    cmd.append(image)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return {"ok": True, "id": name, "image": image}
        err = proc.stderr.strip() or proc.stdout.strip()
        return {"ok": False, "id": name, "error": err}
    except Exception as exc:
        return {"ok": False, "id": name, "error": str(exc)}


def container_status(name: str) -> dict[str, Any]:
    """Get status, ports, and recent logs for a container."""
    containers = list_containers(all=True)
    target = next((c for c in containers if c.get("id") == name), None)
    
    # Check log file in storage
    log_file = CONTAINERS_STORAGE_DIR / name / "stdio.log"
    recent_logs = ""
    if log_file.is_file():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            recent_logs = "\n".join(lines[-20:])
        except Exception:
            pass

    return {
        "found": target is not None,
        "details": target or {"id": name, "state": "not_found"},
        "system_running": is_system_running(),
        "recent_logs": recent_logs,
    }
