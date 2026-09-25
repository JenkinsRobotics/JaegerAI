"""Lifecycle management verbs: ``jaeger start``, ``jaeger stop``, ``jaeger restart``, ``jaeger status``.

Controls the complete multi-agent system:
  1. macOS App (JaegerAI.app menu bar application)
  2. Background services (launchd jobs for bridge, a2a, mcp, adapters, gateway)
  3. Fabric Supervisor (agent-fabric-supervisor health watchdog)
  4. Linux Containers (OpenClaw only; Hermes Agent runs on the host)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from jaeger_ai.core.native_app import swift_app_bundle
from typing import Any, Sequence
from urllib.parse import urlsplit

from jaeger_ai.contract.ports import OLLAMA_PORT, OLLAMA_URL

REPO_ROOT = Path(__file__).resolve().parents[3]

SERVICES_ORDERED = (
    ("com.jenkinsrobotics.jaeger-gateway", "Jaeger Gateway", 8810),
    # The bridge uses a Unix socket; :8791 may belong to the legacy webhook
    # service, so an open HTTP port is not evidence of bridge readiness.
    ("com.jenkinsrobotics.jaeger-bridge", "Jaeger Bridge", None),
    ("com.jenkinsrobotics.jaeger-mcp-http", "Jaeger MCP HTTP", 8792),
    ("com.jenkinsrobotics.jaeger-a2a", "Jaeger A2A", 8796),
    ("com.jenkinsrobotics.jaeger-hermes-adapter", "Jaeger Adapter", 8642),
    ("com.jenkinsrobotics.roundtable-hermes-adapter", "Roundtable Adapter", 8643),
    ("com.jenkinsrobotics.openclaw-hermes-adapter", "OpenClaw Adapter", 8644),
    ("com.jenkinsrobotics.hermes-native-api", "Hermes Native API", 8645),
    ("com.jenkinsrobotics.agent-fabric-supervisor", "Fabric Supervisor", None),
)

SUPERVISOR_SERVICE = "com.jenkinsrobotics.agent-fabric-supervisor"
APP_PROCESS_NAME = "JaegerAI"


def _container_names() -> tuple[str, ...]:
    from jaeger_ai.core.runtime.agent_workspaces import container_name
    return (container_name("openclaw"),)


def _command(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    """Bound operator commands and preserve failure instead of claiming success."""
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", type(exc).__name__)


# ── Color & Styling Helpers ──────────────────────────────────────────

def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if sys.stdout.isatty() else text


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if sys.stdout.isatty() else text


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if sys.stdout.isatty() else text


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m" if sys.stdout.isatty() else text


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m" if sys.stdout.isatty() else text


def _cyan(text: str) -> str:
    return f"\033[36m{text}\033[0m" if sys.stdout.isatty() else text


# ── Process & System Inspection ──────────────────────────────────────

def _is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get_launchd_jobs() -> dict[str, dict[str, Any]]:
    """Return map of label -> {pid, status} from `launchctl list`."""
    try:
        proc = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Cannot inspect launchd; lifecycle actions were not attempted") from exc
    jobs = {}
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3:
            raw_pid, raw_status, label = parts[0], parts[1], parts[2]
            pid = int(raw_pid) if raw_pid.isdigit() else None
            status = int(raw_status) if raw_status.lstrip("-").isdigit() else None
            jobs[label] = {"pid": pid, "status": status}
    return jobs


def _find_app_pids() -> list[int]:
    """Find running PIDs for JaegerAI.app."""
    try:
        proc = subprocess.run(["pgrep", "-f", "JaegerAI.app/Contents/MacOS/JaegerAI"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            return [int(line.strip()) for line in proc.stdout.splitlines() if line.strip().isdigit()]
    except Exception:
        pass
    return []


def _find_app_bundle() -> Path | None:
    """Find an external JaegerAI.app bundle, then well-known install locations.

    The in-repo .build path is NOT checked here — build output is external
    by design (JAEGER_SWIFT_BUILD / ~/.jaeger/apps/swift-build).
    """
    from jaeger_ai.cli._common import swift_app_bundle
    from jaeger_ai.core.instance.instance import install_root
    candidates: list[Path] = []
    try:
        candidates.append(swift_app_bundle(install_root()))
    except ValueError as exc:
        print(f"Invalid Swift build configuration: {exc}", file=sys.stderr)
        return None
    candidates += [
        Path.home() / "Applications" / "JaegerAI.app",
        Path("/Applications/JaegerAI.app"),
        Path("/Applications/Jaeger AI.app"),
        Path.home() / "Applications" / "Jaeger AI.app",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _open_app_bundle(bundle: Path) -> subprocess.CompletedProcess:
    """External builds cannot find the checkout by ascending from their bundle."""
    return _command(["open", "--env", f"JAEGER_REPO={REPO_ROOT}", str(bundle)])


def _get_container_cli() -> str | None:
    discovered = shutil.which("container")
    if discovered:
        return discovered
    fallback = Path("/opt/homebrew/bin/container")
    return str(fallback) if fallback.exists() else None


def _get_containers_state() -> dict[str, dict[str, str]]:
    """Return map of name -> {state, ip, image}."""
    cli = _get_container_cli()
    if not cli:
        return {}
    try:
        proc = subprocess.run([cli, "list", "--all"], capture_output=True, text=True, check=True, timeout=5)
    except Exception:
        return {}
    results = {}
    lines = proc.stdout.splitlines()
    if len(lines) < 2:
        return {}
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 5:
            cid, img, os_arch, arch, state = parts[0], parts[1], parts[2], parts[3], parts[4]
            ip = parts[5] if state == "running" and len(parts) > 5 else "—"
            results[cid] = {"state": state, "ip": ip, "image": img}
    return results


def _service_port_open(
    label: str,
    port: int | None,
    containers: dict[str, dict[str, str]],
) -> bool | None:
    if port is None:
        return None
    if label in {
        "com.jenkinsrobotics.jaeger-hermes-adapter",
        "com.jenkinsrobotics.roundtable-hermes-adapter",
        "com.jenkinsrobotics.openclaw-hermes-adapter",
    }:
        return _is_port_open(port) or _is_port_open(port, "192.168.64.1")
    if label == "com.jenkinsrobotics.hermes-native-api":
        return _is_port_open(port, "127.0.0.1")
    return _is_port_open(port)


# ── Verb: jaeger stop ────────────────────────────────────────────────

def _cmd_stop_argv(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger stop", description="Stop the managed Jaeger stack.")
    parser.add_argument("--no-app", action="store_true")
    parser.add_argument("--no-containers", action="store_true")
    parser.add_argument("--no-webui", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    print("\n  Stopping Jaeger AI stack...\n")
    domain = f"gui/{os.getuid()}"
    try:
        jobs = _get_launchd_jobs()
    except RuntimeError as exc:
        print(f"  {exc}")
        return 1
    names = () if args.no_containers else _container_names()
    failures = []

    # Disable recovery before touching any work-owning service. If this fails,
    # leave the rest intact rather than race the supervisor's repair loop.
    order = [SUPERVISOR_SERVICE] + [
        label for label, _, _ in reversed(SERVICES_ORDERED) if label != SUPERVISOR_SERVICE
    ]
    for label in order:
        if label not in jobs:
            continue
        if args.dry_run:
            print(f"  [dry-run] Would bootout {label}")
            continue
        result = _command(["launchctl", "bootout", f"{domain}/{label}"])
        if result.returncode:
            print(f"  Failed to stop {label}: {result.stderr.strip()}")
            failures.append(label)
            if label == SUPERVISOR_SERVICE:
                return 1
        else:
            print(f"  Stopped {label}")

    if not args.no_app:
        pids = _find_app_pids()
        if args.dry_run:
            if pids:
                print(f"  [dry-run] Would terminate JaegerAI.app (PID(s): {pids})")
        else:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError:
                    failures.append("desktop app")
            if pids:
                for _ in range(10):
                    if not set(pids).intersection(_find_app_pids()):
                        break
                    time.sleep(0.2)
                else:
                    failures.append("desktop app still running")

    if not args.no_webui:
        if args.dry_run:
            print("  [dry-run] Would stop Jaeger WebUI")
        else:
            try:
                from jaeger_ai.features.webui import WebUIService
                WebUIService().stop()
                print("  Stopped Jaeger WebUI")
            except Exception:
                pass

    # Do not stop dependencies if their host services could not be stopped.
    if failures:
        print("  Shutdown incomplete; dependent containers and gateway preserved.")
        return 1
    if names and args.dry_run:
        for name in names:
            print(f"  [dry-run] Would stop container {name}")
    elif names:
        cli = _get_container_cli()
        if cli is None:
            failures.append("container CLI unavailable")
        else:
            states = _get_containers_state()
            for name in names:
                state = states.get(name, {}).get("state")
                if state == "stopped":
                    continue
                if args.dry_run:
                    print(f"  [dry-run] Would stop container {name}")
                elif state != "running":
                    failures.append(f"unknown container state: {name}")
                else:
                    result = _command([cli, "stop", name], timeout=60)
                    if result.returncode:
                        failures.append(f"container stop: {name}")
                    else:
                        print(f"  Stopped container {name}")
    if args.dry_run:
        print("  [dry-run] Would stop Jaeger-owned MCP/A2A gateway")
    else:
        try:
            from jaeger_ai.features.agentgateway.service import stop
            if not stop().get("ok"):
                failures.append("Jaeger gateway")
        except Exception:
            failures.append("Jaeger gateway")
    if failures:
        print("  Shutdown incomplete: " + "; ".join(failures))
        return 1
    print("\n  Shutdown preview complete." if args.dry_run else "\n  Jaeger AI stack is stopped.")
    return 0


def _cmd_start_argv(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger start", description="Start missing managed services without restarting active work.")
    parser.add_argument("--instance", default=None, help="Instance name for the resident Agent")
    parser.add_argument("--no-app", action="store_true")
    parser.add_argument("--no-containers", action="store_true")
    parser.add_argument("--no-webui", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.instance:
        os.environ["JAEGER_INSTANCE_NAME"] = str(args.instance)
    print("\n  Starting Jaeger AI stack...\n")
    print("  Preserving installed configurations")
    domain = f"gui/{os.getuid()}"
    agents_dir = Path.home() / "Library/LaunchAgents"
    try:
        jobs = _get_launchd_jobs()
    except RuntimeError as exc:
        print(f"  {exc}")
        return 1
    states = _get_containers_state()
    names = () if args.no_containers else _container_names()
    failures = []

    # OpenClaw remains containerized. Hermes Agent and its native API run on
    # the Mac, so WebUI lifecycle never starts a Hermes WebUI container.
    if names:
        cli = _get_container_cli()
        if cli is None:
            failures.append("container CLI unavailable")
        elif not states and not args.dry_run:
            print("  Container runtime is offline (run 'container system start' to start containers)")
        else:
            for name in names:
                state = states.get(name, {}).get("state")
                if state == "running":
                    print(f"  Already running: {name}")
                    continue
                if args.dry_run:
                    print(f"  [dry-run] Would start container {name}")
                    continue
                if cli and state == "stopped":
                    if _command([cli, "start", name], timeout=60).returncode:
                        failures.append(f"container: {name}")
                    else:
                        print(f"  Started container: {name}")
                elif cli and not state:
                    # list may omit stopped containers depending on runtime state cache
                    started = _command([cli, "start", name], timeout=60)
                    if started.returncode:
                        failures.append(f"container: {name}")
                    else:
                        print(f"  Started container: {name}")
                else:
                    failures.append(f"unknown container state: {name}")
        if not args.dry_run:
            states = _get_containers_state()

    def ensure_service(label: str, friendly_name: str) -> bool:
        if label in jobs:
            if jobs[label].get("pid"):
                print(f"  Already running: {friendly_name}")
                return True
            if args.dry_run:
                print(f"  [dry-run] Would start loaded service {friendly_name}")
                return True
            # No force flag: if launchd starts it between inspection and this
            # command, its live process must remain untouched.
            result = _command(["launchctl", "kickstart", f"{domain}/{label}"])
            return result.returncode == 0
        path = agents_dir / f"{label}.plist"
        if not path.exists():
            print(f"  Missing plist: {friendly_name}")
            return False
        if args.dry_run:
            print(f"  [dry-run] Would bootstrap {friendly_name} ({label})")
            return True
        result = _command(["launchctl", "bootstrap", domain, str(path)])
        if result.returncode:
            print(f"  Failed to start {friendly_name}: {result.stderr.strip()}")
            return False
        print(f"  Loaded {friendly_name}")
        return True

    for label, name, port in SERVICES_ORDERED:
        if label == SUPERVISOR_SERVICE:
            continue
        if not ensure_service(label, name):
            failures.append(name)
        elif not args.dry_run and port is not None:
            # Readiness is distinct from process admission. Bound the wait;
            # report a warming/failed service without killing it to retry.
            for attempt in range(150):
                if _service_port_open(label, port, states):
                    break
                time.sleep(0.2)
            else:
                failures.append(f"not ready: {name}")

    if args.dry_run:
        print("  [dry-run] Would start Jaeger-owned MCP/A2A gateway")
    else:
        try:
            from jaeger_ai.features.agentgateway.service import start
            if not start().get("ok"):
                failures.append("Jaeger gateway")
            else:
                for _ in range(10):
                    if _is_port_open(8811) and _is_port_open(8812):
                        break
                    time.sleep(0.2)
                else:
                    failures.append("Jaeger gateway readiness")
        except Exception:
            failures.append("Jaeger gateway")

    # Do not bring up automatic recovery over an incompletely started stack.
    if not failures or args.dry_run:
        if not ensure_service(SUPERVISOR_SERVICE, "Fabric Supervisor"):
            failures.append("Fabric Supervisor")

    if not args.no_app:
        app_pids = _find_app_pids()
        if app_pids:
            print(f"  Already running: Desktop App (PID: {', '.join(str(p) for p in app_pids)})")
        else:
            bundle = _find_app_bundle()
            if bundle and args.dry_run:
                print(f"  [dry-run] Would launch {bundle}")
            elif bundle:
                res = _open_app_bundle(bundle)
                if res.returncode:
                    failures.append("desktop app")
                else:
                    print(f"  Launched Desktop App: {bundle.name}")
            else:
                failures.append("desktop app bundle not found")

    if not args.no_webui:
        if args.dry_run:
            print("  [dry-run] Would start Jaeger WebUI")
        else:
            try:
                from jaeger_ai.features.webui import WebUIService
                webui_svc = WebUIService()
                w_status = webui_svc.status()
                webui_running = bool(w_status.get("webui", {}).get("running")) or _is_port_open(8790)
                adapter_running = bool(w_status.get("adapter", {}).get("running")) or _is_port_open(8791)
                if webui_running and adapter_running:
                    ts = None
                    try:
                        from jaeger_ai.features.webui.service.service import _tailscale_ipv4
                        ts = _tailscale_ipv4()
                    except Exception:
                        ts = None
                    local = "http://127.0.0.1:8790/"
                    remote = f"http://{ts}:8790/" if ts else "http://0.0.0.0:8790/"
                    print(f"  Already running: Web UI ({local} / {remote})")
                else:
                    res = webui_svc.start()
                    if res.get("ok"):
                        ts = None
                        try:
                            from jaeger_ai.features.webui.service.service import _tailscale_ipv4
                            ts = _tailscale_ipv4()
                        except Exception:
                            ts = None
                        open_url = res.get("open", "http://127.0.0.1:8790/")
                        print(f"  Started Web UI: {open_url}")
                        if ts:
                            print(f"  Tailscale Web UI: http://{ts}:8790/")
                    else:
                        failures.append("web ui")
                        print(f"  Failed to start Web UI: {res.get('error') or res}")
            except Exception as exc:
                failures.append("web ui")
                print(f"  Failed to start Web UI: {exc}")

    if args.dry_run:
        print("\n  Startup preview complete.")
        return 0
    if failures:
        print("\n  Startup incomplete: " + "; ".join(failures))
        return 1
    if not _wait_runtime_ready(timeout_s=45.0):
        print("\n  Startup incomplete: resident runtime not READY (Gateway / EntityRuntime / Event Fabric).")
        return 1
    print("\n  Jaeger AI stack started successfully.")
    return 0


def _wait_runtime_ready(*, timeout_s: float = 45.0) -> bool:
    """Boot gate: process fork is not success; EntityRuntime + Gateway must be READY."""
    import urllib.request
    deadline = time.time() + timeout_s
    url = "http://127.0.0.1:8810/v1/runtime/status"
    last = ""
    while time.time() < deadline:
        if not _is_port_open(8810):
            time.sleep(0.4)
            continue
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
            last = str(payload.get("Agent", {}).get("entity_id") or "")
            if payload.get("ready") and last:
                print(f"  Resident runtime READY entity_id={last}")
                return True
        except Exception:
            pass
        time.sleep(0.5)
    if last:
        print(f"  Resident runtime warming entity_id={last} (not READY)")
    return False


# ── Verb: jaeger restart ─────────────────────────────────────────────

def _cmd_restart_argv(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger restart",
        description="Restart the full Jaeger AI stack.",
    )
    parser.add_argument("--no-app", action="store_true", help="Do not touch JaegerAI.app")
    parser.add_argument("--no-containers", action="store_true", help="Do not restart containers")
    parser.add_argument("--no-webui", action="store_true", help="Do not touch Web UI")
    parser.add_argument("--instance", default=None, help="Instance name for the resident Agent")
    parser.add_argument("--dry-run", action="store_true", help="Preview without stopping or starting anything")
    args = parser.parse_args(argv)

    stop_args = []
    start_args = []
    if args.instance:
        start_args.extend(["--instance", args.instance])
    if args.dry_run:
        stop_args.append("--dry-run")
        start_args.append("--dry-run")
    if args.no_app:
        stop_args.append("--no-app")
        start_args.append("--no-app")
    if args.no_containers:
        stop_args.append("--no-containers")
        start_args.append("--no-containers")
    if args.no_webui:
        stop_args.append("--no-webui")
        start_args.append("--no-webui")

    rc = _cmd_stop_argv(stop_args)
    if rc != 0:
        return rc
    if not args.dry_run:
        time.sleep(1.0)
    return _cmd_start_argv(start_args)


# ── Verb: jaeger status ──────────────────────────────────────────────

def _cmd_status_argv(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger status",
        description="Display complete live status dashboard for the Jaeger AI multi-agent fabric.",
    )
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    parser.add_argument("--instance", default=None, help="Instance name")
    args = parser.parse_args(argv)
    if args.instance:
        os.environ["JAEGER_INSTANCE_NAME"] = str(args.instance)

    try:
        jobs = _get_launchd_jobs()
    except RuntimeError as exc:
        print(json.dumps({"error": str(exc)}) if args.json else str(exc))
        return 1
    app_pids = _find_app_pids()
    containers = _get_containers_state()

    # Collect service statuses
    services_report = []
    for label, friendly_name, port in SERVICES_ORDERED:
        job = jobs.get(label)
        is_running = False
        pid = None
        port_open = _service_port_open(label, port, containers)
        if job and job["pid"]:
            is_running = True
            pid = job["pid"]
        services_report.append({
            "label": label,
            "name": friendly_name,
            "port": port,
            "port_open": port_open,
            "running": is_running,
            "pid": pid,
        })

    # Collect OpenClaw container status. Hermes Agent is a host service.
    containers_report = []
    for cname in _container_names():
        cdata = containers.get(cname)
        if cdata is None:
            cdata = {"state": "stopped", "ip": "—"}
        containers_report.append({
            "name": cname,
            "state": cdata.get("state", "stopped"),
            "ip": cdata.get("ip", "—"),
        })

    # Mac Ollama is the default. Rack services remain explicitly paused until
    # they can be managed headlessly.
    ollama_endpoint = urlsplit(OLLAMA_URL)
    ollama_name = ollama_endpoint.hostname or "127.0.0.1"
    ollama_port = ollama_endpoint.port or OLLAMA_PORT
    ollama_ok = _is_port_open(ollama_port, ollama_name, timeout=0.5)
    ollama_host = f"{ollama_name}:{ollama_port}"
    rack_enabled = os.environ.get("JAEGER_RACK_SERVICES", "").strip().lower() in {"1", "true", "yes"}
    honcho_ok = _is_port_open(8088, "10.15.0.239", timeout=1.0) if rack_enabled else False

    # Collect Web UI status
    try:
        from jaeger_ai.features.webui import WebUIService
        from jaeger_ai.features.webui.service.service import _tailscale_ipv4
        wsvc = WebUIService()
        wstatus = wsvc.status()
        webui_running = bool(wstatus.get("webui", {}).get("running")) or _is_port_open(8790)
        ts = _tailscale_ipv4()
        webui_url = f"http://{ts}:8790/" if (webui_running and ts) else "http://127.0.0.1:8790/"
    except Exception:
        webui_running = _is_port_open(8790)
        webui_url = "http://127.0.0.1:8790/"

    runtime_doc: dict[str, Any] = {}
    try:
        from jaeger_ai.core.entity.runtime_status import collect_runtime_status
        runtime_doc = collect_runtime_status(include_network=True)
    except Exception as exc:
        runtime_doc = {"error": str(exc), "ready": False}

    if args.json:
        doc = {
            "app": {"running": len(app_pids) > 0, "pids": app_pids},
            "webui": {"running": webui_running, "url": webui_url},
            "services": services_report,
            "containers": containers_report,
            "substrates": {
                "ollama": {"host": ollama_host, "reachable": ollama_ok},
                "honcho": {"host": "10.15.0.239:8088", "reachable": honcho_ok, "enabled": rack_enabled},
            },
            "runtime": runtime_doc,
        }
        print(json.dumps(doc, indent=2))
        return 0 if runtime_doc.get("ready") or runtime_doc.get("error") else 0

    # Pretty Terminal Dashboard
    print()
    print(f"  {_bold('=== Jaeger AI Fabric Status ===')}")
    print()
    agent = runtime_doc.get("Agent") or {}
    if agent.get("entity_id"):
        print(f"  {_bold('Agent:')}        {agent.get('entity_id')}  instance={agent.get('instance')}  {agent.get('status')}")
        print(f"  {_bold('Events:')}       {runtime_doc.get('Runtime', {}).get('event_count')}  latest={runtime_doc.get('Runtime', {}).get('latest_event_id')}")
    print()

    # App Status
    if app_pids:
        print(f"  {_bold('Desktop App:')}  {_green('● Running')} (PID: {', '.join(str(p) for p in app_pids)})")
    else:
        print(f"  {_bold('Desktop App:')}  {_dim('○ Stopped')}")

    # Web UI Status
    if webui_running:
        print(f"  {_bold('Web UI:')}       {_green('● Running')} ({webui_url})")
    else:
        print(f"  {_bold('Web UI:')}       {_dim('○ Stopped')}")
    print()

    # Services Table
    print(f"  {_bold('Host Services:')}")
    print(f"    {'SERVICE':<26} {'STATUS':<14} {'PID':<8} {'PORT':<10}")
    print(f"    {'-'*26} {'-'*14} {'-'*8} {'-'*10}")
    for s in services_report:
        if s["running"]:
            status_str = _green("● Running")
            pid_str = str(s["pid"])
        else:
            status_str = _dim("○ Stopped")
            pid_str = "—"
        if s["port"]:
            port_str = f":{s['port']} " + (_green("✔") if s["port_open"] else _red("✗"))
        else:
            port_str = "—"
        print(f"    {s['name']:<26} {status_str:<23} {pid_str:<8} {port_str}")
    print()

    # Containers Table
    print(f"  {_bold('Linux Containers:')}")
    print(f"    {'CONTAINER':<26} {'STATE':<14} {'IP ADDRESS':<16}")
    print(f"    {'-'*26} {'-'*14} {'-'*16}")
    for c in containers_report:
        if c["state"] == "running":
            state_str = _green("● Running")
        else:
            state_str = _dim(f"○ {c['state']}")
        print(f"    {c['name']:<26} {state_str:<23} {c['ip']:<16}")
    print()

    # Substrates
    print(f"  {_bold('Network Substrates:')}")
    ollama_badge = _green("● Reachable") if ollama_ok else _red("○ Offline")
    honcho_badge = (_green("● Reachable") if honcho_ok else _red("○ Offline")) if rack_enabled else _dim("○ Paused")
    print(f"    Ollama ({ollama_host}) -> {ollama_badge}")
    print(f"    Honcho (10.15.0.239:8088)   -> {honcho_badge}")
    print()

    return 0
