"""Locate, start, stop, and inspect the Jaeger-owned Agentgateway process."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from .config import ensure_config
from .constants import (
    A2A_BACKEND_PORT,
    A2A_GATEWAY_PORT,
    MCP_GATEWAY_PORT,
    MCP_HTTP_PORT,
    READINESS_ADDR,
    STATS_ADDR,
    VERSION,
    bin_dir,
    binary_link,
    binary_path,
    config_path,
    pid_path,
    token_path,
)
from .install import existing_verified_binary


class GatewayError(RuntimeError):
    pass


def locate_binary(root: Path | None = None) -> Path | None:
    """Find a Jaeger-owned agentgateway binary. Never searches archive trees."""
    ordered = [
        binary_link(root),
        binary_path(root),
        Path.home() / ".local" / "bin" / "agentgateway",
    ]
    jaeger_bin = bin_dir(root).resolve()
    seen: set[str] = set()
    for candidate in ordered:
        if not candidate.exists():
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if candidate == Path.home() / ".local" / "bin" / "agentgateway":
            if jaeger_bin not in resolved.parents and resolved.parent != jaeger_bin:
                continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    verified = existing_verified_binary(root)
    if verified is not None:
        try:
            resolved = verified.resolve()
        except OSError:
            return verified
        if jaeger_bin in resolved.parents or resolved.parent == jaeger_bin:
            return resolved
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_pid(root: Path | None = None) -> int | None:
    path = pid_path(root)
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _write_pid(root: Path | None, pid: int) -> None:
    path = pid_path(root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(f".{pid}.tmp")
    tmp.write_text(f"{pid}\n", encoding="utf-8")
    os.replace(tmp, path)


def _is_gateway_process(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:  # noqa: BLE001
        return True
    return "agentgateway" in out


def start(root: Path | None = None) -> dict[str, Any]:
    binary = locate_binary(root)
    if binary is None:
        raise GatewayError(
            "Agentgateway is not installed. Run `jaeger gateway install`."
        )
    cfg = ensure_config(root)
    existing = read_pid(root)
    if existing is not None and _is_gateway_process(existing):
        return {
            "ok": True,
            "already_running": True,
            "pid": existing,
            "binary": str(binary),
            "config": str(cfg),
        }
    env = os.environ.copy()
    env["STATS_ADDR"] = STATS_ADDR
    env["READINESS_ADDR"] = READINESS_ADDR
    log_path = cfg.parent / "agentgateway.log"
    handle = log_path.open("ab")
    proc = subprocess.Popen(  # noqa: S603
        [str(binary), "--file", str(cfg)],
        env=env,
        stdout=handle,
        stderr=handle,
        start_new_session=True,
    )
    handle.close()
    _write_pid(root, proc.pid)
    return {
        "ok": True,
        "already_running": False,
        "pid": proc.pid,
        "binary": str(binary),
        "config": str(cfg),
        "log": str(log_path),
    }


def stop(root: Path | None = None) -> dict[str, Any]:
    existing = read_pid(root)
    path = pid_path(root)
    if existing is None:
        return {"ok": True, "stopped": False, "reason": "not running"}
    if _is_gateway_process(existing):
        os.kill(existing, signal.SIGTERM)
    try:
        path.unlink()
    except OSError:
        pass
    return {"ok": True, "stopped": True, "pid": existing}


def status(root: Path | None = None) -> dict[str, Any]:
    binary = locate_binary(root)
    cfg = config_path(root)
    existing = read_pid(root)
    running = existing is not None and _is_gateway_process(existing)
    return {
        "ok": True,
        "version": VERSION,
        "running": running,
        "pid": existing if running else None,
        "binary": str(binary) if binary else None,
        "config": str(cfg) if cfg.exists() else None,
        "token_file": str(token_path(root)),
        "ports": {
            "mcp_gateway": MCP_GATEWAY_PORT,
            "a2a_gateway": A2A_GATEWAY_PORT,
            "mcp_http": MCP_HTTP_PORT,
            "a2a_backend": A2A_BACKEND_PORT,
        },
    }
