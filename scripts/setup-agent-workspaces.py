#!/usr/bin/env python3
"""Deploy explicit Mac bind mounts, retaining old containers for rollback.

Run with the repo's .venv Python. Inspection/config backups are private local
state. This never deletes containers, copies credentials into images, or pushes.
"""
import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaeger_ai.core.runtime import agent_workspaces as aw
from jaeger_ai.core.frameworks.setup import (
    _configure_agent_connectivity,
    _configure_webui_workspaces,
)
from jaeger_ai.features.agentgateway.service import start as start_gateway
from jaeger_ai.features.agentgateway.service import stop as stop_gateway

ENGINE = "/opt/homebrew/bin/container"


def run(*args, timeout=60):
    try:
        result = subprocess.run([ENGINE, *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"container {args[0]} exceeded {timeout}s; check macOS privacy prompts and container status") from None
    if result.returncode:
        # Arguments/environment and stderr may contain credentials.
        raise RuntimeError(f"container {args[0]} failed (exit {result.returncode}); inspect private container logs")
    return result.stdout


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".workspace-tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def managed_context(existing, block):
    start = "<!-- JAEGER-MAC-CONNECTION-BEGIN -->"
    end = "<!-- JAEGER-MAC-CONNECTION-END -->"
    if start in existing or end in existing:
        if existing.count(start) != 1 or existing.count(end) != 1 or existing.index(end) < existing.index(start):
            raise ValueError("Malformed managed context; refusing to overwrite")
        before, rest = existing.split(start, 1)
        _, after = rest.split(end, 1)
        existing = before + after
    return block.rstrip() + "\n\n" + existing.lstrip()


def configure(backup):
    home = Path.home()
    def save(path):
        index_path = backup / "files-index.json"
        index = json.loads(index_path.read_text()) if index_path.exists() else []
        entry = {"path": str(path), "existed": path.exists(),
                 "mode": path.stat().st_mode & 0o777 if path.exists() else None,
                 "symlink": os.readlink(path) if path.is_symlink() else None}
        if path.exists():
            target = backup / "files" / str(path).lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, target)
            target.chmod(0o600)
        index.append(entry)
        atomic_write(index_path, json.dumps(index, indent=2))

    profile_homes = [home / ".hermes"] + [home / ".hermes/profiles" / name for name in ("jaeger", "roundtable", "openclaw")]
    for profile_home in profile_homes:
        save(profile_home / "config.yaml")
        state_dir = profile_home if profile_home == home / ".hermes" else profile_home / "webui_state"
        save(state_dir / "workspaces.json")
    _configure_agent_connectivity(home)
    _configure_webui_workspaces(home)

    block = (aw.REPO_ROOT / "integrations/agent_workspaces/AGENT_CONTEXT.md").read_text()
    for path in (home / ".hermes/SOUL.md", home / ".jaeger/openclaw/workspace/TOOLS.md"):
        save(path)
        atomic_write(path, managed_context(path.read_text() if path.exists() else "", block))



def restore_configuration(backup):
    index_path = backup / "files-index.json"
    if not index_path.exists():
        return
    for entry in reversed(json.loads(index_path.read_text())):
        path = Path(entry["path"])
        if not entry["existed"]:
            path.unlink(missing_ok=True)
        elif entry["symlink"]:
            temporary = path.with_name(path.name + ".restore-link")
            temporary.symlink_to(entry["symlink"])
            os.replace(temporary, path)
        else:
            saved = backup / "files" / str(path).lstrip("/")
            atomic_write(path, saved.read_text())
            path.chmod(entry["mode"])


def restart_host_gateway():
    """Restart the Jaeger-owned proxy retained for compatibility clients."""
    stop_gateway()
    start_gateway()


def healthy(role):
    name = aw.MANAGED_CONTAINERS[role]
    port = 18789
    status = json.loads(run("inspect", name, timeout=5))[0]["status"]
    address = status["networks"][0]["ipv4Address"].split("/")[0]
    with urllib.request.urlopen(f"http://{address}:{port}/health", timeout=3) as response:
        return response.status == 200


def deploy(include_personal=False):
    existing = set(run("list", "--all", "--quiet").splitlines())
    if any(name in existing for name in aw.MANAGED_CONTAINERS.values()):
        raise RuntimeError("Managed containers already exist; inspect them rather than recreating blindly")
    plans, configs = {}, {}
    for role, name in aw.LEGACY_CONTAINERS.items():
        configs[role] = json.loads(run("inspect", name))[0]["configuration"]
        plans[role] = aw.create_arguments(configs[role], role, include_personal=include_personal)
    # Ensure the validated OpenClaw image is local before interrupting it.
    image = configs["openclaw"]["image"]["reference"]
    run("image", "inspect", image)
    # Trigger mount/OS-permission errors before stopping any working service.
    probe = ["run", "--rm", "--name", "jaeger-workspace-mount-preflight", "--entrypoint", "true"]
    for source, destination in aw.workspace_mounts(include_personal=include_personal):
        probe.extend(["--volume", f"{source}:{destination}"])
    run(*probe, image, timeout=30)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = aw.STATE_PATH.parent / f"workspace-migration-{stamp}"
    backup.mkdir(parents=True, mode=0o700)
    atomic_write(backup / "containers.json", json.dumps(configs, indent=2))
    changed = []
    try:
        configure(backup)
        restart_host_gateway()
        for role, old in aw.LEGACY_CONTAINERS.items():
            run("stop", "--time", "15", old)
            changed.append(role)
            run(*plans[role])
            run("start", aw.MANAGED_CONTAINERS[role])
            deadline = time.monotonic() + 60
            while True:
                try:
                    if healthy(role):
                        break
                except Exception:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Replacement {role} did not become healthy")
                time.sleep(1)
            print(f"{role}: replacement healthy; original retained stopped", flush=True)
        atomic_write(aw.STATE_PATH, json.dumps({"containers": aw.MANAGED_CONTAINERS, "backup": str(backup),
            "mounted_workspaces": [target for _, target in aw.workspace_mounts(include_personal=include_personal)]}, indent=2))
    except Exception:
        restore_configuration(backup)
        restart_host_gateway()
        for role in reversed(changed):
            try:
                run("stop", "--time", "10", aw.MANAGED_CONTAINERS[role])
            except Exception:
                pass
            run("start", aw.LEGACY_CONTAINERS[role])
        raise
    print(f"Deployment state: {aw.STATE_PATH}\nPrivate configuration backup: {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--include-personal", action="store_true", help="Also mount Desktop, Documents and NAS; requires macOS privacy approval")
    args = parser.parse_args()
    if args.deploy:
        deploy(args.include_personal)
    else:
        for role in aw.LEGACY_CONTAINERS:
            print(role, aw.container_name(role))
        for source, destination in aw.workspace_mounts(include_personal=args.include_personal):
            print(f"{source} -> {destination} (present={source.is_dir()})")
