"""Independent health and bounded recovery for the three-agent fabric.

This process deliberately contains no model calls.  It remains able to recover
Jaeger, Hermes WebUI, and OpenClaw when any one reasoning runtime is unhealthy.
Sessions and configuration live outside the processes it restarts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from .agent_workspaces import container_name

FAILURE_THRESHOLD = 3
REPAIR_COOLDOWN_S = 120
POLL_INTERVAL_S = 20
REPO_ROOT = Path(__file__).resolve().parents[3]
JAEGER_RUNTIME_ROOT = (Path(os.environ["JAEGER_HOME"]) / "shared" if os.environ.get("JAEGER_HOME")
                       else REPO_ROOT / ".jaeger_ai" / "shared")
HONCHO_LAN_URL = "http://10.15.0.239:8088"
MAC_OLLAMA_URL = "http://192.168.64.1:11434"


@dataclass(frozen=True)
class Component:
    name: str
    probe: Callable[[], bool]
    repair: Callable[[], bool]


def _http(url: str, *, accepted: tuple[int, ...] = (200,)) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            return response.status in accepted
    except Exception:  # noqa: BLE001
        return False


def _tcp(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def _run(command: list[str], *, timeout: int = 30) -> bool:
    try:
        return subprocess.run(command, capture_output=True, timeout=timeout).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _kickstart(label: str) -> bool:
    """Start a missing worker; never kill a live worker after a failed probe.

    A slow model, pending approval or network failure does not establish that
    a running process is safe to terminate. Explicit operator restart remains
    available through the lifecycle command.
    """
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    try:
        result = subprocess.run(
            ["/bin/launchctl", "print", target], capture_output=True,
            text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode == 0:
        if re.search(r"(?m)^\s*pid = [1-9][0-9]*\s*$", result.stdout):
            return False
        return _run(["/bin/launchctl", "kickstart", target])
    # A failed inspection may mean launchd itself is inaccessible. Only its
    # explicit missing-service response permits bootstrapping an installed job.
    if "Could not find service" not in result.stderr:
        return False
    path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    return path.is_file() and _run(["/bin/launchctl", "bootstrap", domain, str(path)])


def _bridge_ready() -> bool:
    try:
        from jaeger_ai.interfaces.hermes_webui_adapter.bridge_client import BridgeClient
        result = BridgeClient("jaeger").health()
        return bool(result.get("ok") and result.get("ready", {}).get("agent") == "ready")
    except Exception:  # noqa: BLE001
        return False


def _start_jaeger_gateway() -> bool:
    """Restore Jaeger's own MCP/A2A proxy, never the ARES host-tools proxy."""
    try:
        from jaeger_ai.features.gateway.service import start, status
        current = status()
        if current.get("running") and not (_tcp("127.0.0.1", 8811) and _tcp("127.0.0.1", 8812)):
            # A half-responsive gateway may still own an in-flight MCP/A2A
            # request.  Automatic recovery must not kill ambiguous work.  An
            # operator can explicitly stop it after checking the run ledger.
            return False
        start()
        return _tcp("127.0.0.1", 8811) and _tcp("127.0.0.1", 8812)
    except Exception:  # noqa: BLE001
        return False


def _repair_jaeger() -> bool:
    # Preserve healthy dependencies when only one endpoint has failed.
    bridge = _bridge_ready() or _kickstart("com.jenkinsrobotics.jaeger-bridge")
    mcp = _tcp("127.0.0.1", 8792) or _kickstart("com.jenkinsrobotics.jaeger-mcp-http")
    adapter = _http("http://192.168.64.1:8642/v1/health") or _kickstart("com.jenkinsrobotics.jaeger-hermes-adapter")
    gateway = _start_jaeger_gateway()
    return bridge and mcp and adapter and gateway


def _repair_a2a() -> bool:
    backend = (_http("http://127.0.0.1:8796/.well-known/agent-card.json")
               or _kickstart("com.jenkinsrobotics.jaeger-a2a"))
    gateway = _start_jaeger_gateway()
    return backend and gateway


def _repair_openclaw() -> bool:
    native = _tcp("127.0.0.1", 18789) or _restart_container(container_name("openclaw"))
    adapter = (_http("http://192.168.64.1:8644/v1/health")
               or _kickstart("com.jenkinsrobotics.openclaw-hermes-adapter"))
    return native and adapter


def _rack_enabled() -> bool:
    """The rack is optional until it has headless services, not a boot dependency."""
    return os.environ.get("JAEGER_RACK_SERVICES", "").strip().lower() in {"1", "true", "yes"}


def _restart_container(name: str) -> bool:
    # ``start`` preserves the container's external session/config mounts.  A
    # running-but-unhealthy container may still own a tool call, so the
    # supervisor fails closed instead of blindly interrupting it.
    try:
        raw = subprocess.check_output(
            ["/opt/homebrew/bin/container", "inspect", name], timeout=5,
        )
        state = json.loads(raw)[0]['status']['state']
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, ValueError):
        return False  # Unknown state is not authorization for a blind restart.
    if state != 'stopped':
        return False
    return _run(["/opt/homebrew/bin/container", "start", name], timeout=60)


def _container_http(name: str, port: int, path: str = "/health") -> bool:
    """Apple Container assigns a new address after a restart; discover it."""
    try:
        raw = subprocess.check_output(
            ["/opt/homebrew/bin/container", "inspect", name], timeout=5,
        )
        status = json.loads(raw)[0]["status"]
        if status.get("state") != "running":
            return False
        address = status["networks"][0]["ipv4Address"].split("/")[0]
        return _http(f"http://{address}:{port}{path}")
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, ValueError):
        return False


def _restart_honcho_on_rack() -> bool:
    """Restart persistent Honcho containers over LAN-addressed rack SSH."""
    return _run([
        "/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        "10.15.0.239", "docker", "start", "honcho-db", "honcho-redis",
        "honcho-api", "honcho-deriver",
    ], timeout=60)


def components() -> tuple[Component, ...]:
    bridge = "192.168.64.1"
    local = [
        Component(
            "jaeger",
            lambda: _bridge_ready() and _http(f"http://{bridge}:8642/v1/health")
            and _tcp("127.0.0.1", 8792) and _tcp("127.0.0.1", 8811),
            _repair_jaeger,
        ),
        Component(
            "hermes",
            lambda: _container_http(container_name("hermes"), 8787),
            lambda: _restart_container(container_name("hermes")),
        ),
        Component(
            "openclaw",
            lambda: _http(f"http://{bridge}:8644/v1/health") and _tcp("127.0.0.1", 18789),
            _repair_openclaw,
        ),
        Component(
            "roundtable",
            lambda: _http(f"http://{bridge}:8643/v1/health"),
            lambda: _kickstart("com.jenkinsrobotics.roundtable-hermes-adapter"),
        ),
        Component(
            "a2a",
            lambda: _http("http://127.0.0.1:8796/.well-known/agent-card.json")
            and _http("http://127.0.0.1:8812/.well-known/agent-card.json"),
            _repair_a2a,
        ),
        Component(
            "ollama",
            lambda: _http(f"{MAC_OLLAMA_URL}/api/version"),
            lambda: _kickstart("com.jenkinsrobotics.ares-ollama"),
        ),
    ]
    if _rack_enabled():
        local.append(Component(
            "honcho",
            lambda: _http(f"{HONCHO_LAN_URL}/health"),
            _restart_honcho_on_rack,
        ))
    return tuple(local)


class Supervisor:
    def __init__(self, items: tuple[Component, ...] | None = None) -> None:
        self.items = items or components()
        self.failures = {item.name: 0 for item in self.items}
        self.last_repair = {item.name: 0.0 for item in self.items}

    def tick(self, now: float | None = None) -> dict[str, dict[str, object]]:
        now = time.time() if now is None else now
        result: dict[str, dict[str, object]] = {}
        for item in self.items:
            healthy = _safe_check(item.probe)
            self.failures[item.name] = 0 if healthy else self.failures[item.name] + 1
            repaired = False
            repair_ok: bool | None = None
            repair_command_ok: bool | None = None
            eligible = (
                not healthy
                and self.failures[item.name] >= FAILURE_THRESHOLD
                and now - self.last_repair[item.name] >= REPAIR_COOLDOWN_S
            )
            if eligible:
                repaired = True
                repair_command_ok = _safe_check(item.repair)
                self.last_repair[item.name] = now
                healthy = _safe_check(item.probe)
                repair_ok = repair_command_ok and healthy
                if repair_ok:
                    self.failures[item.name] = 0
            result[item.name] = {
                "healthy": healthy,
                "consecutive_failures": self.failures[item.name],
                "repair_attempted": repaired,
                "repair_ok": repair_ok,
                "repair_command_ok": repair_command_ok,
            }
        return result


def _safe_check(callback: Callable[[], bool]) -> bool:
    """One dependency failure must not terminate monitoring of the others."""
    try:
        return bool(callback())
    except Exception:
        return False


def _state_path() -> Path:
    path = JAEGER_RUNTIME_ROOT / "health" / "agent-fabric.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_state(status: dict[str, dict[str, object]]) -> None:
    payload = {
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "components": status,
    }
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor and recover the agent fabric")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--repair",
        choices=("jaeger", "hermes", "openclaw", "roundtable", "a2a", "honcho", "ollama"),
        help="explicitly run one component's bounded recovery action",
    )
    args = parser.parse_args(argv)
    supervisor = Supervisor()
    if args.repair:
        item = next((item for item in supervisor.items if item.name == args.repair), None)
        if item is None:
            # Honcho is deliberately absent while rack services are paused.
            # Do not raise StopIteration or silently enable a remote substrate.
            return 2
        command_ok = _safe_check(item.repair)
        healthy = _safe_check(item.probe)
        ok = command_ok and healthy
        write_state({
            args.repair: {
                "healthy": healthy,
                "consecutive_failures": 0,
                "repair_attempted": True,
                "repair_ok": ok,
                "repair_command_ok": command_ok,
            },
        })
        return 0 if ok else 1
    while True:
        write_state(supervisor.tick())
        if args.once:
            return 0
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
