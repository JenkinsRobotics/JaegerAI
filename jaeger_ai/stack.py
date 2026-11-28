"""Modular launchd stack manager for JaegerAI (`./jaeger stack ...`).

Provides a clean, dependency-free CLI and programmatic interface for inspecting
and managing JaegerAI host services on macOS via ``launchd`` (with a detached
``./jaeger start`` fallback for Gateway when no plist is present).

In the modular standalone architecture, ``gateway`` serves the Gateway API
(``:33418``), the 5-Tab Studio WebUI (``:8790``), and the in-process agent
runtime; legacy service names ``webui`` and ``agent`` resolve cleanly to
``gateway``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ServiceDef:
    """Definition of a known JaegerAI host service."""

    id: str
    name: str
    label: str
    default_port: int | None = None
    health_path: str | None = None
    accept_http_4xx: bool = False
    core: bool = False


STACK_SERVICES: tuple[ServiceDef, ...] = (
    ServiceDef(
        id="gateway",
        name="Gateway",
        label="com.jenkinsrobotics.jaeger-gateway",
        default_port=33418,
        health_path="/health",
        core=True,
    ),
    ServiceDef(
        id="mcp",
        name="MCP HTTP",
        label="com.jenkinsrobotics.jaeger-mcp-http",
        default_port=8792,
        health_path="/health",
        accept_http_4xx=True,
        core=False,
    ),
    ServiceDef(
        id="voice",
        name="Voice",
        label="com.jenkinsrobotics.jaeger-voice",
        default_port=8794,
        health_path="/health",
        core=False,
    ),
    ServiceDef(
        id="bridge",
        name="Bridge",
        label="com.jenkinsrobotics.jaeger-bridge",
        default_port=None,
        health_path=None,
        core=False,
    ),
    ServiceDef(
        id="channels",
        name="Channels",
        label="com.jenkinsrobotics.jaeger-channels",
        default_port=None,
        health_path=None,
        core=False,
    ),
    ServiceDef(
        id="droid",
        name="Droid",
        label="com.jenkinsrobotics.jaeger-droid",
        default_port=None,
        health_path=None,
        core=False,
    ),
)

SERVICE_BY_ID: dict[str, ServiceDef] = {svc.id: svc for svc in STACK_SERVICES}
SERVICE_BY_LABEL: dict[str, ServiceDef] = {svc.label: svc for svc in STACK_SERVICES}
CORE_SERVICES: tuple[ServiceDef, ...] = tuple(svc for svc in STACK_SERVICES if svc.core)

# In the modular architecture, WebUI (:8790) and agent runtime live inside Gateway.
SERVICE_ALIASES: dict[str, str] = {
    "webui": "gateway",
    "agent": "gateway",
}


def _gateway_host() -> str:
    return (os.environ.get("JAEGER_GATEWAY_HOST") or "127.0.0.1").strip()


def _gateway_port() -> int:
    raw = os.environ.get("JAEGER_GATEWAY_PORT") or "33418"
    try:
        return int(raw)
    except ValueError:
        return 33418


def _webui_port() -> int:
    raw = os.environ.get("JAEGER_WEBUI_PORT") or "8790"
    try:
        return int(raw)
    except ValueError:
        return 8790


def _service_port(service: ServiceDef) -> int | None:
    if service.id == "gateway":
        return _gateway_port()
    return service.default_port


def _state_dir() -> Path:
    raw = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_STATE_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".jaeger"


def _launchd_dir() -> Path:
    return _state_dir() / "launchd"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _gateway_pidfile() -> Path:
    return _state_dir() / "run" / "gateway.pid"


def _user_domain() -> str:
    return f"gui/{os.getuid()}"


def _current_git_commit() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            if sha:
                return sha
    except Exception:  # noqa: BLE001
        pass
    return None


def _launchctl(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    exe = "/bin/launchctl"
    if not Path(exe).exists():
        return subprocess.CompletedProcess(args=[exe, *args], returncode=127, stdout="", stderr="launchctl unavailable")
    try:
        return subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(args=[exe, *args], returncode=1, stdout="", stderr=str(exc))


def _find_plist(service: ServiceDef) -> Path | None:
    candidates = (
        _launchd_dir() / f"{service.label}.plist",
        _launch_agents_dir() / f"{service.label}.plist",
    )
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def _probe_http(
    url: str,
    *,
    timeout: float = 1.5,
    accept_4xx: bool = False,
) -> tuple[bool, dict[str, Any] | None]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status = int(resp.status)
            body = resp.read().decode("utf-8", "replace")
            payload: dict[str, Any] | None = None
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    payload = parsed
            except ValueError:
                payload = None
            ok = 200 <= status < (500 if accept_4xx else 300)
            if ok and not accept_4xx and payload is not None and payload.get("ok") is False:
                ok = False
            return ok, payload
    except urllib.error.HTTPError as exc:
        if accept_4xx and 200 <= int(exc.code) < 500:
            return True, None
        return False, None
    except Exception:  # noqa: BLE001
        return False, None


def _parse_launchctl_print(output: str) -> dict[str, Any]:
    pid: int | None = None
    raw_state: str | None = None
    git_commit: str | None = None
    plist_path: str | None = None

    m_pid = re.search(r"\bpid\s*=\s*(\d+)", output)
    if m_pid:
        pid = int(m_pid.group(1))

    m_state = re.search(r"\bstate\s*=\s*([A-Za-z0-9_-]+)", output)
    if m_state:
        raw_state = m_state.group(1)

    m_commit = re.search(r"JAEGER_GIT_COMMIT\s*=>\s*([a-fA-F0-9]+)", output)
    if m_commit:
        git_commit = m_commit.group(1)

    m_path = re.search(r"^\s*path\s*=\s*(.+)$", output, flags=re.MULTILINE)
    if m_path:
        plist_path = m_path.group(1).strip()

    return {
        "pid": pid,
        "raw_state": raw_state,
        "git_commit": git_commit,
        "plist_path": plist_path,
    }


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _signal_pid(pid: int, sig: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def _read_pidfile(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        pid = int(raw)
        return pid if pid > 1 else None
    except Exception:  # noqa: BLE001
        return None


def _spawn_detached_gateway() -> int:
    """Fallback launcher when no launchd plist exists for Gateway."""
    state = _state_dir()
    logs_dir = state / "logs"
    run_dir = state / "run"
    logs_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / "gateway.log"
    launcher = REPO_ROOT / "jaeger"
    if launcher.is_file() and os.access(launcher, os.X_OK):
        cmd = [str(launcher), "start"]
    else:
        cmd = [sys.executable, "-B", "-m", "jaeger_ai", "start"]

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("PYTHONPYCACHEPREFIX", str(Path.home() / ".cache" / "jaeger" / "pycache"))

    with log_path.open("ab") as log_handle:
        proc = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    try:
        _gateway_pidfile().write_text(f"{proc.pid}\n", encoding="utf-8")
    except OSError:
        pass
    return int(proc.pid)


def resolve_service_targets(
    requested: list[str] | None,
    *,
    default_services: tuple[ServiceDef, ...] = CORE_SERVICES,
) -> tuple[list[ServiceDef], dict[str, str], list[str]]:
    """Resolve user/plist service names into deduplicated ServiceDefs.

    Returns ``(services, aliases_used, ignored_names)``.
    Legacy names ``webui`` and ``agent`` resolve to ``gateway``.
    Unknown names are returned in ``ignored_names`` instead of raising.
    """
    if not requested:
        return list(default_services), {}, []

    resolved: list[ServiceDef] = []
    seen_ids: set[str] = set()
    aliases_used: dict[str, str] = {}
    ignored: list[str] = []

    for raw in requested:
        token = raw.strip().lower()
        if not token:
            continue
        canonical = SERVICE_ALIASES.get(token, token)
        if canonical != token:
            aliases_used[token] = canonical
        svc = SERVICE_BY_ID.get(canonical) or SERVICE_BY_LABEL.get(raw.strip())
        if svc is None:
            if token not in ignored:
                ignored.append(token)
            continue
        if svc.id not in seen_ids:
            seen_ids.add(svc.id)
            resolved.append(svc)

    return resolved, aliases_used, ignored


def inspect_service(
    service: ServiceDef,
    *,
    head_commit: str | None = None,
) -> dict[str, Any]:
    """Inspect launchd + HTTP health status for one service."""
    head = head_commit if head_commit is not None else _current_git_commit()
    domain = _user_domain()
    port = _service_port(service)
    host = _gateway_host()

    res = _launchctl(["print", f"{domain}/{service.label}"])
    launchctl_loaded = res.returncode == 0
    parsed = _parse_launchctl_print(res.stdout) if launchctl_loaded else {}

    pid: int | None = parsed.get("pid")
    raw_state: str = parsed.get("raw_state") or "stopped"
    git_commit: str | None = parsed.get("git_commit")

    plist_path = _find_plist(service)
    if plist_path is None and parsed.get("plist_path"):
        candidate = Path(parsed["plist_path"])
        if candidate.is_file():
            plist_path = candidate

    is_running = launchctl_loaded and pid is not None and raw_state == "running"
    managed = is_running
    configured = bool(plist_path is not None or launchctl_loaded or service.core)

    webui_port: int | None = None
    webui_ready: bool | None = None
    http_ready = False
    gw_payload: dict[str, Any] | None = None

    if service.id == "gateway" and port is not None:
        webui_port = _webui_port()
        gw_ok, gw_payload = _probe_http(f"http://{host}:{port}/health", accept_4xx=False)
        webui_ok, _ = _probe_http(f"http://{host}:{webui_port}/health", accept_4xx=False)
        webui_ready = webui_ok
        http_ready = gw_ok and webui_ok
        if not is_running and gw_ok:
            # Gateway is live on :33418 outside launchd (e.g., `./jaeger start`).
            if isinstance((gw_payload or {}).get("pid"), int):
                pid = int(gw_payload["pid"])
            managed = False
            raw_state = "unmanaged"
        is_ready = http_ready
    elif port is not None and service.health_path:
        http_ready, _ = _probe_http(
            f"http://{host}:{port}{service.health_path}",
            accept_4xx=service.accept_http_4xx,
        )
        if not is_running and http_ready:
            managed = False
            raw_state = "unmanaged"
        is_ready = http_ready
    else:
        is_ready = is_running

    if is_ready and not managed:
        display_state = "Ready (unmanaged)"
    elif is_ready:
        display_state = "Ready"
    elif is_running:
        display_state = "Running (Unhealthy)"
    elif service.id == "gateway" and raw_state == "unmanaged":
        display_state = "Running (Unhealthy)"
    else:
        display_state = "Stopped"

    is_stale = bool(is_running and git_commit and head and git_commit != head)

    entry: dict[str, Any] = {
        "id": service.id,
        "name": service.name,
        "label": service.label,
        "pid": pid,
        "state": display_state,
        "raw_state": raw_state,
        "ready": is_ready,
        "managed": managed,
        "configured": configured,
        "port": port,
        "git_commit": git_commit,
        "head_commit": head,
        "stale": is_stale,
    }
    if service.id == "gateway":
        entry["webui_port"] = webui_port
        entry["webui_ready"] = webui_ready
    return entry


def _service_present(entry: dict[str, Any], service: ServiceDef) -> bool:
    if service.core:
        return True
    return bool(entry["configured"] or entry["ready"] or entry["managed"] or entry["pid"] is not None)


def stack_status(requested: list[str] | None = None) -> dict[str, Any]:
    """Return status of requested services, or Gateway + any present companions."""
    head = _current_git_commit()
    if requested:
        targets, aliases_used, ignored = resolve_service_targets(requested)
        services = [inspect_service(svc, head_commit=head) for svc in targets]
        return {
            "ok": True,
            "services": services,
            "aliases": aliases_used,
            "ignored": ignored,
        }

    services: list[dict[str, Any]] = []
    for svc in STACK_SERVICES:
        entry = inspect_service(svc, head_commit=head)
        if _service_present(entry, svc):
            services.append(entry)
    return {
        "ok": True,
        "services": services,
    }


BOOTOUT_WAIT_SECONDS: float = 3.0
BOOTSTRAP_RETRY_TIMEOUT: float = 5.0
LAUNCHCTL_POLL_INTERVAL: float = 0.2
TRANSIENT_BOOTSTRAP_EXIT_CODES: frozenset[int] = frozenset({5, 37})


def _wait_until_unloaded(
    target: str,
    *,
    timeout: float | None = None,
    interval: float | None = None,
) -> bool:
    """Poll ``launchctl print`` until launchd finishes unloading ``target``."""
    wait_s = BOOTOUT_WAIT_SECONDS if timeout is None else max(0.0, timeout)
    step_s = LAUNCHCTL_POLL_INTERVAL if interval is None else max(0.0, interval)
    deadline = time.monotonic() + wait_s
    while True:
        if _launchctl(["print", target]).returncode != 0:
            return True
        if time.monotonic() >= deadline:
            return False
        if step_s > 0.0:
            time.sleep(step_s)


def _bootstrap_and_kickstart(
    service: ServiceDef,
    plist_path: Path,
    *,
    force_reload: bool = False,
) -> tuple[bool, str | None]:
    domain = _user_domain()
    target = f"{domain}/{service.label}"

    chk = _launchctl(["print", target])
    loaded = chk.returncode == 0

    if loaded and force_reload:
        _launchctl(["bootout", target])
        # Wait until launchd confirms the job is unloaded before bootstrapping again.
        unloaded = _wait_until_unloaded(target)
        loaded = not unloaded

    if not loaded:
        deadline = time.monotonic() + max(0.0, BOOTSTRAP_RETRY_TIMEOUT)
        last_err = ""
        transient_retries = 0
        while True:
            boot = _launchctl(["bootstrap", domain, str(plist_path)])
            if boot.returncode == 0:
                break
            last_err = (boot.stderr or boot.stdout).strip()
            # Transient launchd EIO (5) or EINPROGRESS (37) right after bootout:
            # wait briefly and explicitly retry bootstrap instead of trusting a stale print.
            if boot.returncode in TRANSIENT_BOOTSTRAP_EXIT_CODES and transient_retries < 2:
                transient_retries += 1
                if time.monotonic() < deadline:
                    if LAUNCHCTL_POLL_INTERVAL > 0.0:
                        time.sleep(LAUNCHCTL_POLL_INTERVAL)
                    continue
            # Already bootstrapped race: check print before giving up
            if _launchctl(["print", target]).returncode == 0:
                break
            if time.monotonic() >= deadline:
                return False, f"Cannot bootstrap {service.label}: {last_err or 'launchctl failed'}"
            if LAUNCHCTL_POLL_INTERVAL > 0.0:
                time.sleep(LAUNCHCTL_POLL_INTERVAL)

    kick = _launchctl(["kickstart", *(["-k"] if force_reload else []), target])
    if kick.returncode != 0:
        if _launchctl(["print", target]).returncode != 0:
            # Recovery if launchd finished unloading right before kickstart ran.
            boot_retry = _launchctl(["bootstrap", domain, str(plist_path)])
            if boot_retry.returncode == 0 or _launchctl(["print", target]).returncode == 0:
                kick = _launchctl(["kickstart", *(["-k"] if force_reload else []), target])
        if kick.returncode != 0:
            err = (kick.stderr or kick.stdout).strip()
            return False, f"Cannot kickstart {service.label}: {err or 'launchctl failed'}"
    return True, None


def _is_gateway_live_on_api() -> bool:
    gw_ok, _ = _probe_http(f"http://{_gateway_host()}:{_gateway_port()}/health", accept_4xx=False)
    return gw_ok


def stack_up(
    requested: list[str] | None = None,
    *,
    wait_timeout: float = 20.0,
) -> dict[str, Any]:
    """Idempotently start Gateway (and any requested managed services)."""
    head = _current_git_commit()
    targets, aliases_used, ignored = resolve_service_targets(requested, default_services=CORE_SERVICES)
    if not targets:
        return {
            "ok": True,
            "step": "done",
            "error": None,
            "commit": head,
            "services": [],
            "skipped_unmanaged": [],
            "aliases": aliases_used,
            "ignored": ignored,
        }

    skipped_unmanaged: list[str] = []
    warnings: list[str] = []
    started_or_checked: list[ServiceDef] = []
    required_ready: list[ServiceDef] = []
    has_core = any(svc.core for svc in targets)

    for svc in targets:
        current = inspect_service(svc, head_commit=head)

        # Idempotent fast path: never kill or restart an already healthy service.
        if svc.id == "gateway" and (current["ready"] or _is_gateway_live_on_api()):
            started_or_checked.append(svc)
            required_ready.append(svc)
            continue
        if current["ready"]:
            started_or_checked.append(svc)
            if svc.core or not has_core:
                required_ready.append(svc)
            continue

        plist_path = _find_plist(svc)
        if plist_path is not None:
            ok_start, start_err = _bootstrap_and_kickstart(svc, plist_path, force_reload=False)
            started_or_checked.append(svc)
            if ok_start:
                if svc.core or not has_core:
                    required_ready.append(svc)
            else:
                if svc.core or not has_core:
                    return {
                        "ok": False,
                        "step": "up",
                        "error": start_err,
                        "commit": head,
                        "services": [inspect_service(s, head_commit=head) for s in targets],
                        "skipped_unmanaged": skipped_unmanaged,
                        "aliases": aliases_used,
                        "ignored": ignored,
                    }
                warnings.append(start_err or f"Failed to start optional service {svc.id}")
                skipped_unmanaged.append(svc.id)
        elif svc.id == "gateway":
            try:
                _spawn_detached_gateway()
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "step": "up",
                    "error": f"Failed to spawn detached gateway: {exc}",
                    "commit": head,
                    "services": [inspect_service(s, head_commit=head) for s in targets],
                    "skipped_unmanaged": skipped_unmanaged,
                    "aliases": aliases_used,
                    "ignored": ignored,
                }
            started_or_checked.append(svc)
            required_ready.append(svc)
        else:
            # Unmanaged companion service (no plist and not running): skip cleanly.
            skipped_unmanaged.append(svc.id)

    # Wait briefly for required services to report healthy.
    deadline = time.monotonic() + max(0.0, wait_timeout)
    final_by_id: dict[str, dict[str, Any]] = {}
    while True:
        final_by_id = {svc.id: inspect_service(svc, head_commit=head) for svc in targets}
        if all(final_by_id[svc.id]["ready"] for svc in required_ready):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.3)

    final_statuses = [final_by_id[svc.id] for svc in targets]
    not_ready = [final_by_id[svc.id]["name"] for svc in required_ready if not final_by_id[svc.id]["ready"]]
    ok = len(not_ready) == 0

    result: dict[str, Any] = {
        "ok": ok,
        "step": "done" if ok else "up",
        "error": None if ok else f"Services failed to become ready: {', '.join(not_ready)}",
        "commit": head,
        "services": final_statuses,
        "skipped_unmanaged": skipped_unmanaged,
        "aliases": aliases_used,
        "ignored": ignored,
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _stop_service(service: ServiceDef, *, wait_timeout: float = 5.0) -> tuple[bool, list[int], list[int]]:
    """Stop one service via launchctl bootout (or tracked fallback pidfile)."""
    domain = _user_domain()
    target = f"{domain}/{service.label}"

    chk = _launchctl(["print", target])
    booted_out = False
    tracked_pids: list[int] = []
    if chk.returncode == 0:
        parsed = _parse_launchctl_print(chk.stdout)
        if isinstance(parsed.get("pid"), int) and parsed["pid"] > 1:
            tracked_pids.append(int(parsed["pid"]))
        _launchctl(["bootout", target])
        booted_out = True
    elif service.id == "gateway":
        pidfile = _gateway_pidfile()
        pid = _read_pidfile(pidfile)
        if pid is not None and _pid_alive(pid):
            tracked_pids.append(pid)
            _signal_pid(pid, signal.SIGTERM)
        try:
            pidfile.unlink(missing_ok=True)
        except OSError:
            pass

    if not tracked_pids:
        if booted_out:
            _wait_until_unloaded(target, timeout=min(BOOTOUT_WAIT_SECONDS, max(0.0, wait_timeout)))
        return True, [], []

    deadline = time.monotonic() + max(0.0, wait_timeout)
    while time.monotonic() < deadline:
        if not any(_pid_alive(p) for p in tracked_pids):
            if booted_out:
                rem_wait = max(0.0, min(BOOTOUT_WAIT_SECONDS, deadline - time.monotonic()))
                _wait_until_unloaded(target, timeout=rem_wait)
            return True, [], []
        time.sleep(LAUNCHCTL_POLL_INTERVAL)

    killed: list[int] = []
    for pid in tracked_pids:
        if _pid_alive(pid) and _signal_pid(pid, signal.SIGKILL):
            killed.append(pid)
    if killed:
        time.sleep(LAUNCHCTL_POLL_INTERVAL)

    if booted_out:
        _wait_until_unloaded(target, timeout=min(1.0, max(0.0, wait_timeout)))

    remaining = [pid for pid in tracked_pids if _pid_alive(pid)]
    return len(remaining) == 0, killed, remaining


def stack_down(
    requested: list[str] | None = None,
    *,
    wait_timeout: float = 5.0,
) -> dict[str, Any]:
    """Stop Gateway (default) or explicitly requested services via launchctl."""
    head = _current_git_commit()
    targets, aliases_used, ignored = resolve_service_targets(requested, default_services=CORE_SERVICES)

    stragglers_killed: list[int] = []
    remaining_pids: list[int] = []
    for svc in targets:
        _ok, killed, remaining = _stop_service(svc, wait_timeout=wait_timeout)
        stragglers_killed.extend(killed)
        remaining_pids.extend(remaining)

    final_statuses = [inspect_service(svc, head_commit=head) for svc in targets]
    ok = len(remaining_pids) == 0
    return {
        "ok": ok,
        "step": "done" if ok else "down",
        "error": None if ok else f"Could not stop processes: {remaining_pids}",
        "commit": head,
        "stragglers_killed": stragglers_killed,
        "remaining_pids": remaining_pids,
        "services": final_statuses,
        "aliases": aliases_used,
        "ignored": ignored,
    }


def stack_restart(
    requested: list[str] | None = None,
    *,
    wait_timeout: float = 20.0,
) -> dict[str, Any]:
    """Restart Gateway (default) or explicitly requested services via launchctl."""
    head = _current_git_commit()
    targets, aliases_used, ignored = resolve_service_targets(requested, default_services=CORE_SERVICES)
    if not targets:
        return {
            "ok": True,
            "step": "done",
            "error": None,
            "commit": head,
            "services": [],
            "skipped_unmanaged": [],
            "aliases": aliases_used,
            "ignored": ignored,
        }

    domain = _user_domain()
    skipped_unmanaged: list[str] = []
    required_ready: list[ServiceDef] = []
    has_core = any(svc.core for svc in targets)

    for svc in targets:
        plist_path = _find_plist(svc)
        target = f"{domain}/{svc.label}"

        if plist_path is not None:
            ok_start, start_err = _bootstrap_and_kickstart(svc, plist_path, force_reload=True)
            if not ok_start:
                if svc.core or not has_core:
                    return {
                        "ok": False,
                        "step": "restart",
                        "error": start_err,
                        "commit": head,
                        "services": [inspect_service(s, head_commit=head) for s in targets],
                        "skipped_unmanaged": skipped_unmanaged,
                        "aliases": aliases_used,
                        "ignored": ignored,
                    }
                skipped_unmanaged.append(svc.id)
                continue
            if svc.core or not has_core:
                required_ready.append(svc)
        elif _launchctl(["print", target]).returncode == 0:
            kick = _launchctl(["kickstart", "-k", target])
            if kick.returncode != 0:
                err = (kick.stderr or kick.stdout).strip() or f"Cannot kickstart {svc.label}"
                if svc.core or not has_core:
                    return {
                        "ok": False,
                        "step": "restart",
                        "error": err,
                        "commit": head,
                        "services": [inspect_service(s, head_commit=head) for s in targets],
                        "skipped_unmanaged": skipped_unmanaged,
                        "aliases": aliases_used,
                        "ignored": ignored,
                    }
                skipped_unmanaged.append(svc.id)
                continue
            if svc.core or not has_core:
                required_ready.append(svc)
        elif svc.id == "gateway":
            _stop_service(svc, wait_timeout=5.0)
            try:
                _spawn_detached_gateway()
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "step": "restart",
                    "error": f"Failed to spawn detached gateway: {exc}",
                    "commit": head,
                    "services": [inspect_service(s, head_commit=head) for s in targets],
                    "skipped_unmanaged": skipped_unmanaged,
                    "aliases": aliases_used,
                    "ignored": ignored,
                }
            required_ready.append(svc)
        else:
            skipped_unmanaged.append(svc.id)

    deadline = time.monotonic() + max(0.0, wait_timeout)
    final_by_id: dict[str, dict[str, Any]] = {}
    while True:
        final_by_id = {svc.id: inspect_service(svc, head_commit=head) for svc in targets}
        if all(final_by_id[svc.id]["ready"] for svc in required_ready):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.3)

    final_statuses = [final_by_id[svc.id] for svc in targets]
    not_ready = [final_by_id[svc.id]["name"] for svc in required_ready if not final_by_id[svc.id]["ready"]]
    ok = len(not_ready) == 0
    return {
        "ok": ok,
        "step": "done" if ok else "restart",
        "error": None if ok else f"Services failed to become ready: {', '.join(not_ready)}",
        "commit": head,
        "services": final_statuses,
        "skipped_unmanaged": skipped_unmanaged,
        "aliases": aliases_used,
        "ignored": ignored,
    }


def _print_status_table(services: list[dict[str, Any]]) -> None:
    print(f"{'SERVICE':<14} {'STATE':<22} {'PID':<8} {'PORT':<8} {'MANAGED':<8} {'STALE':<6} {'COMMIT'}")
    print("-" * 80)
    for svc in services:
        pid_str = str(svc["pid"]) if svc["pid"] is not None else "—"
        port_str = str(svc["port"]) if svc["port"] is not None else "—"
        managed_str = "yes" if svc["managed"] else "no"
        stale_str = "YES" if svc["stale"] else "no"
        commit_str = (svc["git_commit"] or "—")[:10]
        print(
            f"{svc['name']:<14} {svc['state']:<22} {pid_str:<8} {port_str:<8} "
            f"{managed_str:<8} {stale_str:<6} {commit_str}"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jaeger stack",
        description="Manage JaegerAI modular host services (status | up | down | restart)",
    )
    parser.add_argument("--json", action="store_true", default=False, help="Output machine-readable JSON")
    sub = parser.add_subparsers(dest="action", required=True)

    p_status = sub.add_parser("status", help="Inspect service status, launchd state, and health")
    p_status.add_argument("services", nargs="*", help="Optional service IDs or aliases (gateway, webui, agent, mcp, voice, ...)")
    p_status.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output JSON")

    p_up = sub.add_parser("up", help="Idempotently start Gateway (or specified services)")
    p_up.add_argument("services", nargs="*", help="Optional service IDs or aliases")
    p_up.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output JSON")
    p_up.add_argument("--wait", type=float, default=20.0, help="Seconds to wait for service readiness")

    p_down = sub.add_parser("down", help="Stop Gateway (or specified services)")
    p_down.add_argument("services", nargs="*", help="Optional service IDs or aliases")
    p_down.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output JSON")
    p_down.add_argument("--wait", type=float, default=5.0, help="Seconds to wait for clean shutdown")

    p_restart = sub.add_parser("restart", help="Restart Gateway (or specified services)")
    p_restart.add_argument("services", nargs="*", help="Optional service IDs or aliases")
    p_restart.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Output JSON")
    p_restart.add_argument("--wait", type=float, default=20.0, help="Seconds to wait for service readiness")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    requested = list(getattr(args, "services", []) or [])

    if args.action == "status":
        reply = stack_status(requested or None)
        if as_json:
            print(json.dumps(reply, indent=2))
        else:
            _print_status_table(reply["services"])
        return 0

    if args.action == "up":
        reply = stack_up(requested or None, wait_timeout=float(args.wait))
        if as_json:
            print(json.dumps(reply, indent=2))
        else:
            state = "READY" if reply["ok"] else "FAILED"
            commit_short = (reply.get("commit") or "—")[:10]
            print(f"[stack] up: {state} (commit: {commit_short})")
            for svc in reply["services"]:
                print(f"  - {svc['name']:<14}: {svc['state']} (pid: {svc['pid'] or '—'})")
            if reply.get("error"):
                print(f"  error: {reply['error']}", file=sys.stderr)
        return 0 if reply["ok"] else 1

    if args.action == "down":
        reply = stack_down(requested or None, wait_timeout=float(args.wait))
        if as_json:
            print(json.dumps(reply, indent=2))
        else:
            state = "STOPPED" if reply["ok"] else "FAILED"
            print(f"[stack] down: {state}")
            for svc in reply["services"]:
                print(f"  - {svc['name']:<14}: {svc['state']} (pid: {svc['pid'] or '—'})")
            if reply.get("error"):
                print(f"  error: {reply['error']}", file=sys.stderr)
        return 0 if reply["ok"] else 1

    if args.action == "restart":
        reply = stack_restart(requested or None, wait_timeout=float(args.wait))
        if as_json:
            print(json.dumps(reply, indent=2))
        else:
            state = "READY" if reply["ok"] else "FAILED"
            commit_short = (reply.get("commit") or "—")[:10]
            print(f"[stack] restart: {state} (commit: {commit_short})")
            for svc in reply["services"]:
                print(f"  - {svc['name']:<14}: {svc['state']} (pid: {svc['pid'] or '—'})")
            if reply.get("error"):
                print(f"  error: {reply['error']}", file=sys.stderr)
        return 0 if reply["ok"] else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
