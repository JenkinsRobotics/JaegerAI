"""Auto-managed on-demand lifecycle supervisor for Jaeger's Gateway-owned browser worker.

Resolution order (zero manual env vars required):
1. If ``JAEGER_BROWSER_PORT`` + ``JAEGER_BROWSER_TOKEN`` are set, connect to that external worker.
2. Otherwise, auto-launch either the packaged Steel Browser runtime (`JAEGER_BROWSER_BUNDLE` or
   `<state_dir>/runtimes/browser`) OR the standalone Playwright worker
   (`packages/jaeger-browser/standalone_worker.mjs`) on a private loopback port with a fresh
   random bearer token and stdin-EOF lifetime lease.
3. Closes cleanly when the Gateway shuts down so zero orphan Chromium processes survive.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jaeger_youtube.browse import BrowserWorkerClient

__all__ = ["BrowserWorkerManager"]


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _probe_ready(port: int, token: str, timeout: float = 1.0) -> bool:
    req = Request(
        f"http://127.0.0.1:{port}/jaeger/ready",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return int(resp.status) == 200
    except (HTTPError, URLError, OSError):
        return False


class BrowserWorkerManager:
    """Lazy, thread-safe supervisor for Jaeger's private localhost browser worker."""

    def __init__(self, state_dir: Path, workspace: Path | None = None) -> None:
        self._state_dir = Path(state_dir).expanduser().resolve()
        self._workspace = Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._port: int = 0
        self._token: str = ""
        self._mode: str = "unconfigured"

    def _find_launch_spec(self) -> tuple[str, list[str], dict[str, str], Path] | None:
        # 1. Packaged Steel browser bundle (release runtime)
        bundle_candidates: list[Path] = []
        env_bundle = (os.environ.get("JAEGER_BROWSER_BUNDLE") or "").strip()
        if env_bundle:
            bundle_candidates.append(Path(env_bundle).expanduser())
        bundle_candidates.append(self._state_dir / "runtimes" / "browser")
        for bundle in bundle_candidates:
            worker = bundle / "worker.mjs"
            node_bin = bundle / "node" / "bin" / "node"
            if worker.is_file() and node_bin.is_file():
                return ("steel-bundle", [str(node_bin), str(worker)], {}, bundle)

        # 2. Standalone Playwright worker using repo/system Node + Playwright
        node_sys = shutil.which("node") or ("/opt/homebrew/bin/node" if Path("/opt/homebrew/bin/node").is_file() else "")
        if not node_sys:
            return None
        repo_candidates = [
            self._workspace,
            Path(__file__).resolve().parents[4],
        ]
        for root in repo_candidates:
            standalone = root / "packages" / "jaeger-browser" / "standalone_worker.mjs"
            pw_entry = root / "jaeger_ai" / "interfaces" / "ui" / "node_modules" / "playwright" / "index.mjs"
            if standalone.is_file() and pw_entry.is_file():
                return (
                    "playwright-standalone",
                    [node_sys, str(standalone)],
                    {"JAEGER_PLAYWRIGHT_MODULE": str(pw_entry)},
                    standalone.parent,
                )
        return None

    def ensure_client(self, *, startup_timeout_s: float = 15.0) -> BrowserWorkerClient:
        # Respect explicit external worker env vars first (backwards compatible).
        env_port = int(os.environ.get("JAEGER_BROWSER_PORT") or "0")
        env_token = os.environ.get("JAEGER_BROWSER_TOKEN") or ""
        if env_port and env_token:
            return BrowserWorkerClient(port=env_port, token=env_token)

        with self._lock:
            if self._proc is not None and self._proc.poll() is None and self._port and self._token:
                return BrowserWorkerClient(port=self._port, token=self._token)
            self._stop_locked()

            spec = self._find_launch_spec()
            if spec is None:
                raise RuntimeError(
                    "browser worker unavailable: neither JAEGER_BROWSER_PORT/JAEGER_BROWSER_TOKEN, "
                    "packaged Steel runtime, nor Playwright standalone worker could be located"
                )
            mode, argv, extra_env, cwd = spec
            port = _pick_free_port()
            token = secrets.token_hex(24)
            env = {
                **os.environ,
                **extra_env,
                "JAEGER_BROWSER_PORT": str(port),
                "JAEGER_BROWSER_TOKEN": token,
                "PORT": str(port),
                "HOST": "127.0.0.1",
            }
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            deadline = time.monotonic() + max(2.0, float(startup_timeout_s))
            ready = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                if _probe_ready(port, token, timeout=0.5):
                    ready = True
                    break
                time.sleep(0.15)
            if not ready:
                err_tail = ""
                try:
                    if proc.poll() is not None and proc.stderr:
                        err_tail = proc.stderr.read().decode("utf-8", errors="replace")[-300:]
                except Exception:  # noqa: BLE001
                    pass
                try:
                    proc.terminate()
                    proc.wait(timeout=2.0)
                except Exception:  # noqa: BLE001
                    proc.kill()
                raise RuntimeError(f"Auto-managed browser worker ({mode}) failed to become ready. {err_tail}".strip())

            self._proc = proc
            self._port = port
            self._token = token
            self._mode = mode
            return BrowserWorkerClient(port=port, token=token)

    def status(self) -> dict[str, Any]:
        env_port = int(os.environ.get("JAEGER_BROWSER_PORT") or "0")
        env_token = os.environ.get("JAEGER_BROWSER_TOKEN") or ""
        if env_port and env_token:
            return {"mode": "external-env", "running": True, "port": env_port}
        with self._lock:
            running = self._proc is not None and self._proc.poll() is None
            available = self._find_launch_spec() is not None
            return {
                "mode": self._mode if running else ("auto-ready" if available else "unavailable"),
                "running": running,
                "port": self._port if running else None,
            }

    def _stop_locked(self) -> None:
        proc = self._proc
        self._proc = None
        self._port = 0
        self._token = ""
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def close(self) -> None:
        with self._lock:
            self._stop_locked()
