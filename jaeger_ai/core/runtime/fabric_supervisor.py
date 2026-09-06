"""Independent health and bounded recovery for the three-agent fabric.

This process deliberately contains no model calls.  It remains able to recover
Jaeger, Hermes WebUI, and OpenClaw when any one reasoning runtime is unhealthy.
Sessions and configuration live outside the processes it restarts.
"""

from __future__ import annotations

import argparse
import json
import os
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
    return _run([
        "/bin/launchctl", "kickstart", "-k",
        f"gui/{os.getuid()}/{label}",
    ])


def _restart_container(name: str) -> bool:
    # ``start`` preserves the container's external session/config mounts.  If
    # already running, use a bounded stop/start instead of deleting state.
    try:
        raw = subprocess.check_output(
            ["/opt/homebrew/bin/container", "inspect", name], timeout=5,
        )
        state = json.loads(raw)[0]['status']['state']
    except (OSError, subprocess.SubprocessError, KeyError, IndexError, ValueError):
        return False  # Unknown state is not authorization for a blind restart.
    if state not in ('running', 'stopped'):
        return False
    if state == 'running' and not _run([
        "/opt/homebrew/bin/container", "stop", "--time", "10", name,
    ]):
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
    return (
        Component(
            "jaeger",
            lambda: _http(f"http://{bridge}:8642/v1/health") and _tcp("127.0.0.1", 8811),
            lambda: _kickstart("com.jenkinsrobotics.jaeger-hermes-adapter")
            and _kickstart("com.jenkinsrobotics.jaeger-mcp-http"),
        ),
        Component(
            "hermes",
            lambda: _container_http(container_name("hermes"), 8787),
            lambda: _restart_container(container_name("hermes")),
        ),
        Component(
            "openclaw",
            lambda: _http(f"http://{bridge}:8644/v1/health") and _tcp("127.0.0.1", 18789),
            lambda: _restart_container(container_name("openclaw"))
            and _kickstart("com.jenkinsrobotics.openclaw-hermes-adapter"),
        ),
        Component(
            "roundtable",
            lambda: _http(f"http://{bridge}:8643/v1/health"),
            lambda: _kickstart("com.jenkinsrobotics.roundtable-hermes-adapter"),
        ),
        Component(
            "a2a",
            lambda: _http("http://127.0.0.1:8796/.well-known/agent-card.json"),
            lambda: _kickstart("com.jenkinsrobotics.jaeger-a2a"),
        ),
        Component(
            "honcho",
            lambda: _http(f"{HONCHO_LAN_URL}/health"),
            _restart_honcho_on_rack,
        ),
        Component(
            "ollama",
            lambda: _http("http://10.15.0.239:11434/api/version"),
            lambda: _run([
                "/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "rackpc001-3", "schtasks", "/Run", "/TN", "Ollama Serve",
            ]),
        ),
    )


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
        item = next(item for item in supervisor.items if item.name == args.repair)
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
