"""Explicit Mac mounts and active container identities for the agent fabric.

Deployment state is local and contains no credentials. Defaults preserve older
installations; migration keeps the old containers stopped for rollback.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_PATH = REPO_ROOT / ".jaeger_ai/shared/container-workspaces.json"
LEGACY_CONTAINERS = {"hermes": "hermes-webui-hermes-webui", "openclaw": "ares-openclaw"}
MANAGED_CONTAINERS = {"hermes": "jaeger-hermes-webui", "openclaw": "jaeger-openclaw"}
EXPANDED_CONTAINERS = {"hermes": "jaeger-hermes-workspaces", "openclaw": "jaeger-openclaw-workspaces"}
HERMES_IMAGE = "hermes-webui:jaeger-native-runs-20260906"


def container_name(role: str) -> str:
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
        name = state.get("containers", {}).get(role)
        if name:
            if name not in (LEGACY_CONTAINERS[role], MANAGED_CONTAINERS[role], EXPANDED_CONTAINERS[role]):
                raise ValueError(f"Unexpected managed container for {role}")
            return name
    return LEGACY_CONTAINERS[role]


def workspace_mounts(home: Path | None = None, *, include_personal: bool = False) -> list[tuple[Path, str]]:
    home = home or Path.home()
    mounts = [(home / "GitHub", "/mnt/host/GitHub")]
    if not include_personal:
        return mounts
    return mounts + [
        (home / "Desktop", "/mnt/host/Desktop"),
        (home / "Documents", "/mnt/host/Documents"),
        (Path("/Volumes/Jenkins_Robotics"), "/mnt/nas/Jenkins_Robotics"),
        (Path("/Volumes/Personal-Drive"), "/mnt/nas/Personal-Drive"),
    ]


def create_arguments(config: dict, role: str, *, home: Path | None = None,
                     include_personal: bool = False, expand: bool = False) -> list[str]:
    """Preserve the inspected launch contract and add only explicit mounts.

    Unknown privileged features are refused, not silently stripped. Returned
    arguments can contain inherited secrets: never print the command.
    """
    source_names = MANAGED_CONTAINERS if expand else LEGACY_CONTAINERS
    targets = EXPANDED_CONTAINERS if expand else MANAGED_CONTAINERS
    if config.get("id") != source_names[role]:
        raise ValueError("Migration source must be the expected managed container" if expand
                         else "Migration source must be the expected legacy container")
    if expand and not include_personal:
        raise ValueError("Expanded migration requires explicit personal workspace selection")
    if any(config.get(key) for key in ("ssh", "virtualization", "rosetta", "publishedSockets", "sysctls", "capAdd", "capDrop")):
        raise ValueError("Nonstandard container features require manual review")
    process = config["initProcess"]
    if process.get("rlimits") or process.get("supplementalGroups") or process.get("terminal"):
        raise ValueError("Nonstandard process features require manual review")
    user = process["user"].get("raw", {}).get("userString")
    if not user:
        raise ValueError("Cannot preserve container user")
    image = config["image"]["reference"]
    if role == "hermes":
        image = HERMES_IMAGE
    args = ["create", "--name", targets[role], "--user", user,
            "--workdir", process["workingDirectory"], "--entrypoint", process["executable"],
            "--cpus", str(config["resources"]["cpus"]),
            "--memory", str(config["resources"]["memoryInBytes"])]
    if config.get("readOnly"):
        args.append("--read-only")
    if config.get("useInit"):
        args.append("--init")
    for value in process["environment"]:
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
        args.extend(["--publish", f"{port['hostAddress']}:{port['hostPort']}:{port['containerPort']}/{port['proto']}"])
    destinations = {}
    for mount in config["mounts"]:
        if "virtiofs" not in mount["type"] or set(mount.get("options", [])) - {"ro"}:
            raise ValueError("Unsupported existing mount")
        if mount["destination"] in destinations:
            raise ValueError("Duplicate existing workspace mount")
        destinations[mount["destination"]] = mount
        suffix = ":ro" if "ro" in mount.get("options", []) else ""
        args.extend(["--volume", f"{mount['source']}:{mount['destination']}{suffix}"])
    for source, destination in workspace_mounts(home, include_personal=include_personal):
        if not source.is_dir():
            raise ValueError(f"Workspace is not mounted/present: {source}")
        if destination in destinations:
            existing = destinations[destination]
            if expand and Path(existing["source"]).resolve() == source.resolve() and not existing.get("options"):
                continue  # Keep the already-published RW GitHub mount once.
            raise ValueError(f"Conflicting workspace mount: {destination}")
        args.extend(["--volume", f"{source}:{destination}"])
    return [*args, image, *process["arguments"]]
