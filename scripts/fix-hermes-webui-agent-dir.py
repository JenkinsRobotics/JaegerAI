#!/usr/bin/env python3
"""Recreate jaeger-hermes-webui with working HERMES_WEBUI_AGENT_DIR/PYTHON.

Preserves the live image and mounts; only rewrites agent env so WebUI uses
/app/hermes-agent-src + /app/venv. Does not archive profiles or touch sibling
repos. Arguments/environment may contain secrets: never print the create command.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaeger_ai.core.runtime import agent_workspaces as aw

ENGINE = "/opt/homebrew/bin/container"
NAME = aw.MANAGED_CONTAINERS["hermes"]


def run(*args: str, timeout: int = 120) -> str:
    result = subprocess.run([ENGINE, *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"container {args[0]} failed (exit {result.returncode})")
    return result.stdout


def create_args_from_live(config: dict) -> list[str]:
    """Like create_arguments, but keep this managed container's image/name."""
    if config.get("id") != NAME:
        raise ValueError(f"Expected live container {NAME}")
    process = config["initProcess"]
    if process.get("rlimits") or process.get("supplementalGroups") or process.get("terminal"):
        raise ValueError("Nonstandard process features require manual review")
    if any(config.get(key) for key in ("ssh", "virtualization", "rosetta", "publishedSockets", "sysctls", "capAdd", "capDrop")):
        raise ValueError("Nonstandard container features require manual review")
    user = process["user"].get("raw", {}).get("userString")
    if not user:
        raise ValueError("Cannot preserve container user")
    image = config["image"]["reference"]
    args = [
        "create", "--name", NAME, "--user", user,
        "--workdir", process["workingDirectory"],
        "--entrypoint", process["executable"],
        "--cpus", str(config["resources"]["cpus"]),
        "--memory", str(config["resources"]["memoryInBytes"]),
    ]
    if config.get("readOnly"):
        args.append("--read-only")
    if config.get("useInit"):
        args.append("--init")
    environment = aw.normalize_hermes_webui_environment(list(process["environment"]))
    for value in environment:
        args.extend(["--env", value])
    for network in config["networks"]:
        args.extend(["--network", f"{network['network']},mtu={network.get('options', {}).get('mtu', 1280)}"])
    dns = config.get("dns", {})
    for key, flag in (("nameservers", "--dns"), ("searchDomains", "--dns-search"), ("options", "--dns-option")):
        for value in dns.get(key, []):
            args.extend([flag, value])
    for port in config["publishedPorts"]:
        if port.get("count", 1) != 1:
            raise ValueError("Port ranges require manual review")
        args.extend([
            "--publish",
            f"{port['hostAddress']}:{port['hostPort']}:{port['containerPort']}/{port['proto']}",
        ])
    for mount in config["mounts"]:
        if "virtiofs" not in mount["type"] or set(mount.get("options", [])) - {"ro"}:
            raise ValueError("Unsupported existing mount")
        suffix = ":ro" if "ro" in mount.get("options", []) else ""
        args.extend(["--volume", f"{mount['source']}:{mount['destination']}{suffix}"])
    return [*args, image, *process["arguments"]]


def wait_healthy(timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            status = json.loads(run("inspect", NAME, timeout=5))[0]["status"]
            address = status["networks"][0]["ipv4Address"].split("/")[0]
            with urllib.request.urlopen(f"http://{address}:8787/health", timeout=3) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(1)
    raise RuntimeError(f"Hermes WebUI did not become healthy: {last}")


def main() -> int:
    inspect = json.loads(run("inspect", NAME))[0]
    config = inspect["configuration"]
    plan = create_args_from_live(config)
    # Prove normalization without dumping secrets.
    env = [a for i, a in enumerate(plan) if i and plan[i - 1] == "--env"]
    agent = next(v for v in env if v.startswith("HERMES_WEBUI_AGENT_DIR="))
    python = next(v for v in env if v.startswith("HERMES_WEBUI_PYTHON="))
    print(f"Repairing {NAME}")
    print(f"  {agent}")
    print(f"  {python}")
    print(f"  image={config['image']['reference']}")
    run("stop", "--time", "20", NAME)
    run("delete", NAME)
    run(*plan, timeout=180)
    run("start", NAME)
    wait_healthy()
    sync = Path(__file__).resolve().with_name("sync-hermes-webui-static.py")
    sync_result = subprocess.run([sys.executable, str(sync)], capture_output=True, text=True)
    if sync_result.returncode:
        raise RuntimeError(sync_result.stderr or sync_result.stdout or "static sync failed")
    print(sync_result.stdout.strip() or "static synced")
    print("Hermes WebUI healthy with working agent dir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
