"""Single authoritative stack orchestrator for JaegerAI (Ollama-style).

Owns the lifecycle of all Jaeger host services via launchd in ``~/.jaeger/launchd/``:
- No unmanaged plists in ``~/Library/LaunchAgents`` (so macOS never auto-starts services at login).
- The Mac menu-bar app is the sovereign owner: app up -> stack up; app quit -> stack down.
- Hard termination: bootout followed by PID/port sweep and SIGKILL for any lingering stragglers.
- Verification: reset and health checks run real synthetic test turns through the Gateway.
- Code freshness: tracks running process commit vs repo HEAD to flag stale code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from jaeger_ai.contract.ports import (
    A2A_PORT,
    GATEWAY_PORT,
    HERMES_NATIVE_API_PORT,
    LOOPBACK,
    MCP_HTTP_PORT,
    OLLAMA_PORT,
    WEBUI_ADAPTER_PORT,
    WEBUI_PORT,
)
from jaeger_ai.core.instance.instance import operator_state_root

REPO_ROOT = Path(__file__).resolve().parents[3]


def _current_git_commit() -> str:
    """Return HEAD commit hash or 'unknown'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _launchd_dir() -> Path:
    d = operator_state_root() / "launchd"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logs_dir() -> Path:
    d = operator_state_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_python() -> str:
    venv_py = operator_state_root() / "venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


@dataclass(frozen=True)
class ServiceDef:
    id: str
    name: str
    label: str
    port: int | None
    health_path: str | None
    command_builder: Callable[[], list[str]]
    env_builder: Callable[[], dict[str, str]]


def _ollama_command() -> list[str]:
    exe = shutil.which("ollama") or "/usr/local/bin/ollama"
    return [exe, "serve"]


def _gateway_command() -> list[str]:
    return [_default_python(), "-u", "-B", "-m", "jaeger_ai.core.gateway.server"]


def _bridge_command() -> list[str]:
    return [_default_python(), "-u", "-B", "-m", "jaeger_ai.interfaces.bridge", "jaeger"]


def _webui_command() -> list[str]:
    run_script = REPO_ROOT / "scripts" / "run-jaeger-webui.sh"
    if run_script.exists():
        return ["/bin/zsh", str(run_script)]
    return [_default_python(), "-u", "-B", "-m", "jaeger_ai.features.webui.server"]


def _runner_command() -> list[str]:
    return [
        _default_python(),
        "-u",
        "-B",
        "-m",
        "jaeger_ai.interfaces.hermes_webui_adapter",
        "--host",
        LOOPBACK,
        "--port",
        str(WEBUI_ADAPTER_PORT),
        "--instance",
        "jaeger",
    ]


def _mcp_command() -> list[str]:
    return [
        _default_python(),
        "-m",
        "jaeger_ai.interfaces.mcp_server",
        "--http",
        "--instance",
        "jaeger",
    ]


def _a2a_command() -> list[str]:
    return [_default_python(), "-m", "jaeger_ai.interfaces.a2a_server"]


def _hermes_command() -> list[str]:
    script = REPO_ROOT / "scripts" / "hermes-native-api-service.py"
    return [_default_python(), "-B", str(script)]


def _common_env() -> dict[str, str]:
    state_root = operator_state_root()
    pycache = Path.home() / ".cache" / "jaeger" / "pycache"
    pythonpath = f"{REPO_ROOT}:{REPO_ROOT}/packages/jaeger-agent:{REPO_ROOT}/packages/jaeger-os"
    return {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(pycache),
        "PYTHONPATH": pythonpath,
        "PYTHONUNBUFFERED": "1",
        "JAEGER_STATE_DIR": str(state_root),
        "JAEGER_STATE_HOME": str(state_root),
    }


def _bridge_env() -> dict[str, str]:
    """The managed bridge is always a client of the execution owner.

    A GUI-launched attach process already sets this variable, but the
    launchd-owned bridge has no parent shell to inherit it from.  Omitting it
    silently selects the legacy local runtime and creates a second entity.
    """
    env = _common_env()
    env["JAEGER_BRIDGE_EXECUTION"] = "gateway"
    return env


def _gateway_env() -> dict[str, str]:
    env = _common_env()
    env.update({
        "JAEGER_GATEWAY_HOST": LOOPBACK,
        "JAEGER_GATEWAY_PORT": str(GATEWAY_PORT),
        "JAEGER_WEBUI_URL": f"http://{LOOPBACK}:{WEBUI_PORT}",
        "JAEGER_BRIDGE_HEALTH_URL": f"http://{LOOPBACK}:{WEBUI_ADAPTER_PORT}/health",
    })
    return env


def _ollama_env() -> dict[str, str]:
    env = _common_env()
    env["OLLAMA_HOST"] = "0.0.0.0:11434"
    return env


# Authoritative service registry in boot order
STACK_SERVICES: list[ServiceDef] = [
    ServiceDef(
        id="ollama",
        name="Ollama",
        label="com.jenkinsrobotics.ares-ollama",
        port=OLLAMA_PORT,
        health_path="/api/tags",
        command_builder=_ollama_command,
        env_builder=_ollama_env,
    ),
    ServiceDef(
        id="gateway",
        name="Gateway",
        label="com.jenkinsrobotics.jaeger-gateway",
        port=GATEWAY_PORT,
        health_path="/health",
        command_builder=_gateway_command,
        env_builder=_gateway_env,
    ),
    ServiceDef(
        id="agent",
        name="Jaeger Agent",
        label="com.jenkinsrobotics.jaeger-bridge",
        port=None,
        health_path=None,
        command_builder=_bridge_command,
        env_builder=_bridge_env,
    ),
    ServiceDef(
        id="runner",
        name="Chat Runner",
        label="com.jenkinsrobotics.jaeger-hermes-webui-adapter",
        port=WEBUI_ADAPTER_PORT,
        health_path="/health",
        command_builder=_runner_command,
        env_builder=_common_env,
    ),
    ServiceDef(
        id="webui",
        name="Web UI",
        label="com.jenkinsrobotics.jaeger-webui",
        port=WEBUI_PORT,
        health_path="/health",
        command_builder=_webui_command,
        env_builder=_common_env,
    ),
    ServiceDef(
        id="mcp",
        name="Native MCP",
        label="com.jenkinsrobotics.jaeger-mcp-http",
        port=MCP_HTTP_PORT,
        health_path="/mcp",
        command_builder=_mcp_command,
        env_builder=_common_env,
    ),
    ServiceDef(
        id="a2a",
        name="A2A Server",
        label="com.jenkinsrobotics.jaeger-a2a",
        port=A2A_PORT,
        health_path=None,
        command_builder=_a2a_command,
        env_builder=_common_env,
    ),
    ServiceDef(
        id="hermes",
        name="Hermes API",
        label="com.jenkinsrobotics.hermes-native-api",
        port=HERMES_NATIVE_API_PORT,
        health_path=None,
        command_builder=_hermes_command,
        env_builder=_common_env,
    ),
]

SERVICE_BY_ID = {s.id: s for s in STACK_SERVICES}
SERVICE_BY_LABEL = {s.label: s for s in STACK_SERVICES}


def _xml_text(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_plist(service: ServiceDef, commit_sha: str | None = None) -> str:
    """Generate launchd plist content pointing to ~/.jaeger/logs/."""
    commit = commit_sha or _current_git_commit()
    prog_args = "".join(f"    <string>{_xml_text(a)}</string>\n" for a in service.command_builder())
    log_file = _logs_dir() / f"{service.id}.log"

    env = dict(service.env_builder())
    env["JAEGER_GIT_COMMIT"] = commit

    env_lines = "".join(
        f"    <key>{_xml_text(k)}</key><string>{_xml_text(v)}</string>\n"
        for k, v in sorted(env.items())
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'  <key>Label</key><string>{_xml_text(service.label)}</string>\n'
        '  <key>ProgramArguments</key>\n'
        '  <array>\n'
        f'{prog_args}'
        '  </array>\n'
        '  <key>EnvironmentVariables</key>\n'
        '  <dict>\n'
        f'{env_lines}'
        '  </dict>\n'
        '  <key>KeepAlive</key><true/>\n'
        '  <key>RunAtLoad</key><false/>\n'
        '  <key>ThrottleInterval</key><integer>2</integer>\n'
        f'  <key>WorkingDirectory</key><string>{_xml_text(str(REPO_ROOT))}</string>\n'
        f'  <key>StandardOutPath</key><string>{_xml_text(str(log_file))}</string>\n'
        f'  <key>StandardErrorPath</key><string>{_xml_text(str(log_file))}</string>\n'
        '</dict>\n'
        '</plist>\n'
    )


def plist_path_for(service: ServiceDef) -> Path:
    return _launchd_dir() / f"{service.label}.plist"


def get_user_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def migrate_legacy_launchagents() -> list[str]:
    """Bootout and remove unmanaged legacy plists from ~/Library/LaunchAgents."""
    migrated: list[str] = []
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    if not launch_agents_dir.exists():
        return migrated

    domain = get_user_domain()
    # Also include agent-fabric-supervisor which is retired
    all_targets = set(s.label for s in STACK_SERVICES) | {
        "com.jenkinsrobotics.agent-fabric-supervisor",
        "com.jenkinsrobotics.jaeger-hermes-adapter",
        "com.jenkinsrobotics.openclaw-hermes-adapter",
        "com.jenkinsrobotics.roundtable-hermes-adapter",
    }

    for plist in launch_agents_dir.glob("com.jenkinsrobotics.*.plist"):
        label = plist.stem
        if label in all_targets:
            _launchctl(["bootout", f"{domain}/{label}"])
            try:
                plist.unlink()
                migrated.append(label)
            except OSError:
                pass
    return migrated


def probe_service_health(service: ServiceDef) -> bool:
    """Return True if the service answers a true operational health probe."""
    try:
        if service.id == "agent":
            # Probe bridge AF_UNIX socket
            from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
            return bool(jaeger_bridge().health().get("ok"))

        if service.port:
            # First check if port is reachable
            with socket.create_connection((LOOPBACK, service.port), timeout=1):
                pass
            if service.health_path:
                url = f"http://{LOOPBACK}:{service.port}{service.health_path}"
                try:
                    with urllib.request.urlopen(url, timeout=2) as resp:
                        return 200 <= int(resp.status) < 500
                except urllib.error.HTTPError as exc:
                    return 200 <= int(exc.code) < 500
            return True
    except Exception:
        return False
    return False


def inspect_service(service: ServiceDef, head_commit: str | None = None) -> dict[str, Any]:
    """Inspect PID, running state, git commit, and health for a service."""
    head = head_commit or _current_git_commit()
    domain = get_user_domain()
    res = _launchctl(["print", f"{domain}/{service.label}"])

    pid: int | None = None
    state = "stopped"
    loaded_commit = "unknown"

    if res.returncode == 0:
        out = res.stdout
        m_pid = re.search(r"\bpid = (\d+)", out)
        if m_pid:
            pid = int(m_pid.group(1))

        m_state = re.search(r"\bstate = (\w+)", out)
        if m_state:
            state = m_state.group(1)

        m_commit = re.search(r"JAEGER_GIT_COMMIT\s*=>\s*([a-f0-9]+)", out)
        if m_commit:
            loaded_commit = m_commit.group(1)

    is_running = pid is not None and state == "running"
    is_ready = is_running and probe_service_health(service)
    is_stale = is_running and loaded_commit != "unknown" and head != "unknown" and loaded_commit != head

    display_state = "Ready" if is_ready else ("Running (Unhealthy)" if is_running else "Stopped")

    return {
        "id": service.id,
        "name": service.name,
        "label": service.label,
        "pid": pid,
        "state": display_state,
        "raw_state": state,
        "ready": is_ready,
        "configured": True,
        "port": service.port,
        "git_commit": loaded_commit,
        "head_commit": head,
        "stale": is_stale,
    }


def stack_status(services: list[ServiceDef] | None = None) -> list[dict[str, Any]]:
    target = services or STACK_SERVICES
    head = _current_git_commit()
    return [inspect_service(s, head_commit=head) for s in target]


def sync_plists(commit_sha: str | None = None) -> list[Path]:
    """Write plists for all services to ~/.jaeger/launchd/."""
    head = commit_sha or _current_git_commit()
    ldir = _launchd_dir()
    ldir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for s in STACK_SERVICES:
        p_path = plist_path_for(s)
        p_path.write_text(build_plist(s, commit_sha=head), encoding="utf-8")
        paths.append(p_path)
    return paths


def stack_up(services: list[ServiceDef] | None = None, wait_timeout: float = 25.0) -> dict[str, Any]:
    """Bring the stack up: migrate legacy plists, bootstrap into launchd, wait for health."""
    target = services or STACK_SERVICES
    domain = get_user_domain()
    head = _current_git_commit()

    # Step 1: Migrate legacy LaunchAgents
    migrate_legacy_launchagents()

    # Step 2: Ensure agent models & container networks are configured
    try:
        from jaeger_ai.core.frameworks.setup import _configure_agent_models
        _configure_agent_models()
    except Exception:
        pass

    # Step 3: Write plists to ~/.jaeger/launchd/
    sync_plists()

    # Step 4: Bootstrap each service
    for s in target:
        p_path = plist_path_for(s)
        # Check if already loaded
        chk = _launchctl(["print", f"{domain}/{s.label}"])
        if chk.returncode == 0:
            # Kickstart reload
            _launchctl(["kickstart", "-k", f"{domain}/{s.label}"])
        else:
            _launchctl(["bootstrap", domain, str(p_path)])

    # Step 4: Wait for readiness
    deadline = time.time() + wait_timeout
    all_ready = False
    while time.time() < deadline:
        statuses = stack_status(target)
        if all(st["ready"] for st in statuses):
            all_ready = True
            break
        time.sleep(0.5)

    final_statuses = stack_status(target)
    return {
        "ok": all_ready or all(st["ready"] for st in final_statuses),
        "commit": head,
        "services": final_statuses,
    }


def _find_straggler_pids() -> set[int]:
    """Find lingering processes matching jaeger or bound to stack ports."""
    pids: set[int] = set()
    my_pid = os.getpid()

    # 1. Inspect processes matching jaeger keywords
    try:
        p = subprocess.run(
            ["pgrep", "-fl", "jaeger_ai|hermes-native-api|run-jaeger-webui"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in p.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if parts and parts[0].isdigit():
                pid_num = int(parts[0])
                if pid_num != my_pid:
                    pids.add(pid_num)
    except Exception:
        pass

    # 2. Inspect processes listening on stack ports
    ports_to_check = [
        GATEWAY_PORT,
        WEBUI_PORT,
        WEBUI_ADAPTER_PORT,
        MCP_HTTP_PORT,
        A2A_PORT,
        HERMES_NATIVE_API_PORT,
    ]
    for port in ports_to_check:
        try:
            p = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in p.stdout.splitlines():
                if line.strip().isdigit():
                    pid_num = int(line.strip())
                    if pid_num != my_pid:
                        pids.add(pid_num)
        except Exception:
            pass

    return pids


def stack_down(services: list[ServiceDef] | None = None, wait_timeout: float = 5.0) -> dict[str, Any]:
    """Bring the stack down: bootout services, wait, kill stragglers, verify ports."""
    target = services or STACK_SERVICES
    domain = get_user_domain()

    # 1. Send launchctl bootout
    for s in target:
        _launchctl(["bootout", f"{domain}/{s.label}"])

    # 2. Wait up to wait_timeout for graceful exit
    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        if not _find_straggler_pids():
            break
        time.sleep(0.3)

    # 3. Kill stragglers
    stragglers = _find_straggler_pids()
    killed: list[int] = []
    for pid in stragglers:
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except OSError:
            pass

    if killed:
        time.sleep(0.5)

    remaining = _find_straggler_pids()
    return {
        "ok": len(remaining) == 0,
        "stragglers_killed": killed,
        "remaining_pids": list(remaining),
        "services": stack_status(target),
    }


def run_gateway_test_turn(timeout_s: float = 60.0) -> dict[str, Any]:
    """Execute a real synthetic end-to-end turn through the Gateway (:8810).

    Proves that Gateway, SessionStore, ReAct EntityRuntime, and Model Provider
    are genuinely answering queries.
    """
    base_url = f"http://{LOOPBACK}:{GATEWAY_PORT}"

    # 1. Create session
    req = urllib.request.Request(
        f"{base_url}/v1/sessions",
        data=json.dumps({"title": "stack-verify-probe"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        sess = json.loads(resp.read().decode("utf-8"))
        session_id = sess["session_id"]

    # 2. Send turn
    req = urllib.request.Request(
        f"{base_url}/v1/sessions/{session_id}/turns",
        data=json.dumps({"text": "ping"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        turn_resp = json.loads(resp.read().decode("utf-8"))
        request_id = turn_resp["request_id"]

    # 3. Poll for completion
    deadline = time.time() + timeout_s
    last_status = "unknown"
    result: dict[str, Any] | None = None

    while time.time() < deadline:
        req = urllib.request.Request(f"{base_url}/v1/sessions/{session_id}/requests/{request_id}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                poll_resp = json.loads(resp.read().decode("utf-8"))
                last_status = poll_resp.get("status") or "unknown"
                if last_status == "completed":
                    result = poll_resp.get("result")
                    return {
                        "ok": True,
                        "session_id": session_id,
                        "request_id": request_id,
                        "status": "completed",
                        "result": result,
                    }
                if last_status in {"failed", "cancelled"}:
                    return {
                        "ok": False,
                        "session_id": session_id,
                        "request_id": request_id,
                        "status": last_status,
                        "error": poll_resp.get("error") or "Turn failed in Gateway",
                    }
        except Exception:
            pass
        time.sleep(0.5)

    return {
        "ok": False,
        "session_id": session_id,
        "request_id": request_id,
        "status": last_status,
        "error": f"Gateway test turn timed out after {timeout_s}s",
    }


def stack_reset(timeout_s: float = 60.0) -> dict[str, Any]:
    """Tear down all services, start all services, and verify with a REAL Gateway turn."""
    # 1. Down
    down_res = stack_down(wait_timeout=5.0)
    if not down_res["ok"]:
        return {
            "ok": False,
            "step": "down",
            "error": f"Could not cleanly kill straggler processes: {down_res['remaining_pids']}",
            "details": down_res,
        }

    # 2. Up
    up_res = stack_up(wait_timeout=25.0)
    if not up_res["ok"]:
        unready = [s["name"] for s in up_res["services"] if not s["ready"]]
        return {
            "ok": False,
            "step": "up",
            "error": f"Services failed to become ready: {unready}",
            "details": up_res,
        }

    # 3. Real test turn through Gateway
    turn_res = run_gateway_test_turn(timeout_s=timeout_s)
    if not turn_res["ok"]:
        return {
            "ok": False,
            "step": "verify_turn",
            "error": f"Gateway test turn failed: {turn_res.get('error')}",
            "details": turn_res,
            "services": stack_status(),
        }

    return {
        "ok": True,
        "step": "completed",
        "verify_turn": turn_res,
        "services": stack_status(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger stack",
        description="Authoritative Jaeger stack manager (up | down | reset | status)",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_up = sub.add_parser("up", help="Start all or specified services")
    p_up.add_argument("services", nargs="*", help="Service IDs to start")
    p_up.add_argument("--json", action="store_true", help="Output JSON")

    p_down = sub.add_parser("down", help="Stop all services and kill stragglers")
    p_down.add_argument("--json", action="store_true", help="Output JSON")

    p_reset = sub.add_parser("reset", help="Down + Up + Real Gateway test turn verification")
    p_reset.add_argument("--timeout", type=float, default=60.0, help="Verification timeout in seconds")
    p_reset.add_argument("--json", action="store_true", help="Output JSON")

    p_status = sub.add_parser("status", help="Inspect status, git commit freshness, and health")
    p_status.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args(argv)

    if args.action == "status":
        st = stack_status()
        if args.json:
            print(json.dumps({"ok": True, "services": st}, indent=2))
        else:
            print(f"{'SERVICE':<18} {'STATUS':<22} {'PID':<8} {'PORT':<8} {'STALE':<8} {'GIT COMMIT'}")
            print("-" * 75)
            for s in st:
                stale_flag = "YES" if s["stale"] else "no"
                pid_str = str(s["pid"] or "—")
                port_str = str(s["port"] or "—")
                commit_str = (s["git_commit"] or "—")[:10]
                print(f"{s['name']:<18} {s['state']:<22} {pid_str:<8} {port_str:<8} {stale_flag:<8} {commit_str}")
        return 0

    if args.action == "up":
        target = [SERVICE_BY_ID[s] for s in args.services if s in SERVICE_BY_ID] or None
        res = stack_up(target)
        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            state = "READY" if res["ok"] else "UNHEALTHY"
            print(f"[stack] up: {state} (commit: {res['commit'][:10]})")
            for s in res["services"]:
                print(f"  - {s['name']:<18}: {s['state']} (pid: {s['pid'] or '—'})")
        return 0 if res["ok"] else 1

    if args.action == "down":
        res = stack_down()
        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            print(f"[stack] down: {'CLEAN' if res['ok'] else 'LEAKED'}")
            if res["stragglers_killed"]:
                print(f"  stragglers killed: {res['stragglers_killed']}")
        return 0 if res["ok"] else 1

    if args.action == "reset":
        res = stack_reset(timeout_s=args.timeout)
        if getattr(args, "json", False):
            print(json.dumps(res, indent=2))
        else:
            if res["ok"]:
                print("[stack] reset: READY (test turn passed)")
            else:
                print(f"[stack] reset: FAILED at step '{res.get('step')}': {res.get('error')}", file=sys.stderr)
        return 0 if res["ok"] else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
