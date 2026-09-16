"""Lifecycle helpers for Jaeger's first-party browser UI.

Port map (coherent defaults):
  * Jaeger WebUI (browser) — ``containers.jaeger_webui_port`` (8790)
  * Hermes WebUI adapter (runner-local) — ``containers.adapter_port`` (8791)
  * Instance webhooks — 8793 (moved off 8791 to avoid clashing with the adapter)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

DEFAULT_ADAPTER_PORT = 8791
DEFAULT_ADAPTER_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 8790
REPO_ROOT = Path(__file__).resolve().parents[4]
WEBUI_SCRIPT = REPO_ROOT / "scripts" / "run-jaeger-webui.sh"

from .profile_layout import (
    ensure_webui_profile_layout,
    prepare_webui_home,
)


@dataclass(frozen=True, slots=True)
class WebUIUrls:
    adapter: str
    web_ui: str


def webui_urls(
    *,
    adapter_port: int = DEFAULT_ADAPTER_PORT,
    adapter_host: str = DEFAULT_ADAPTER_HOST,
    webui_port: int = DEFAULT_WEBUI_PORT,
) -> WebUIUrls:
    return WebUIUrls(
        adapter=f"http://{adapter_host}:{adapter_port}/",
        web_ui=f"http://127.0.0.1:{webui_port}/",
    )




def _tailscale_ipv4() -> str | None:
    binary = shutil.which("tailscale")
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return None


def _ensure_shared_profiles(agent_home: Path) -> None:
    """Expose ~/.hermes/profiles and a current-schema state.db to :8790."""
    try:
        prepare_webui_home(agent_home)
    except Exception:
        try:
            ensure_webui_profile_layout()
        except Exception:
            pass


def _load_webui_config(instance: str | None = None) -> dict[str, Any]:
    from jaeger_ai.core.instance.instance import (
        InstanceLayout,
        default_instance_name,
        resolve_instance_dir,
    )
    from jaeger_ai.core.instance.schemas import Config, load_yaml

    name = instance or default_instance_name()
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.exists():
        return {
            "adapter_port": DEFAULT_ADAPTER_PORT,
            "jaeger_webui_port": DEFAULT_WEBUI_PORT,
            "tailscale_publish": False,
            "tailscale_https_port": 8443,
            "layout": None,
            "instance": name,
        }
    cfg = load_yaml(layout.config_path, Config)
    containers = getattr(cfg, "containers", None)
    return {
        "adapter_port": int(
            getattr(containers, "adapter_port", DEFAULT_ADAPTER_PORT)
            or DEFAULT_ADAPTER_PORT
        ),
        "jaeger_webui_port": int(
            getattr(containers, "jaeger_webui_port", DEFAULT_WEBUI_PORT)
            or DEFAULT_WEBUI_PORT
        ),
        "tailscale_publish": bool(getattr(containers, "tailscale_publish", False)),
        "tailscale_https_port": int(
            getattr(containers, "tailscale_https_port", 8443) or 8443
        ),
        "layout": layout,
        "instance": name,
    }


def _webui_run_dir(layout: Any) -> Path:
    root = Path(layout.root) / "run" / "webui"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _adapter_pid_path(layout: Any) -> Path:
    return _webui_run_dir(layout) / "adapter.pid"


def _adapter_log_path(layout: Any) -> Path:
    return _webui_run_dir(layout) / "adapter.log"


def _webui_pid_path(layout: Any) -> Path:
    return _webui_run_dir(layout) / "webui.pid"


def _webui_log_path(layout: Any) -> Path:
    return _webui_run_dir(layout) / "webui.log"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _http_ok(url: str, timeout: float = 2.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {"raw": body[:200]}
            return {"ok": True, "status": getattr(response, "status", 200), "body": payload}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


_BUNDLE_VERSION_RE = re.compile(
    r"__HERMES_WEBUI_BUNDLE_VERSION__\s*=\s*'([^']*)'",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)


def parse_webui_shell(html: str) -> dict[str, str]:
    """Extract identity fields the stale-client banner compares."""
    title_match = _TITLE_RE.search(html or "")
    bundle_match = _BUNDLE_VERSION_RE.search(html or "")
    bundle = unquote(bundle_match.group(1)) if bundle_match else ""
    return {
        "title": (title_match.group(1).strip() if title_match else ""),
        "bundle_version": bundle,
    }


def webui_identity_ok(shell: dict[str, str], settings: dict[str, Any] | None) -> dict[str, Any]:
    """HTTP 200 is process-up. Identity match is product-up.

    The browser stamps ``window.__HERMES_WEBUI_BUNDLE_VERSION__`` from the
    HTML shell and compares it to ``settings.webui_version``. Any extra
    cache-bust suffix on the stamp (e.g. ``.jaegerpd4``) permanently
    raises the 'different WebUI version / hard refresh' banner.
    """
    title = str(shell.get("title") or "")
    bundle = str(shell.get("bundle_version") or "").strip()
    server = unquote(str((settings or {}).get("webui_version") or "")).strip()
    title_ok = "jaeger" in title.lower()
    skew = bool(bundle and server and bundle != server)
    ok = title_ok and bool(bundle) and bool(server) and not skew
    error = None
    if not title_ok:
        error = f"unexpected title {title!r} (want Jaeger)"
    elif not bundle or not server:
        error = "missing bundle or settings.webui_version"
    elif skew:
        error = f"version skew: running {bundle} → server {server}"
    return {
        "ok": ok,
        "title": title,
        "bundle_version": bundle,
        "webui_version": server,
        "skew": skew,
        "error": error,
    }


def probe_webui_identity(url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Fetch the chat shell + /api/settings and report identity honesty."""
    base = url.rstrip("/")
    try:
        with urllib.request.urlopen(base + "/", timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200) or 200)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    if status >= 400:
        return {"ok": False, "error": f"shell HTTP {status}"}
    shell = parse_webui_shell(html)
    settings: dict[str, Any] | None = None
    try:
        with urllib.request.urlopen(base + "/api/settings", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                settings = payload
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "title": shell.get("title", ""),
            "bundle_version": shell.get("bundle_version", ""),
            "webui_version": "",
            "skew": False,
            "error": f"settings: {exc}",
        }
    return webui_identity_ok(shell, settings)


def _listening_pid(port: int) -> int | None:
    try:
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for raw in (proc.stdout or "").split():
        try:
            return int(raw)
        except ValueError:
            continue
    return None


class WebUIService:
    """Start, stop, and inspect the first-party WebUI and runtime adapter."""

    def __init__(self, instance: str | None = None) -> None:
        self._cfg = _load_webui_config(instance)
        self.instance = str(self._cfg["instance"])
        self.adapter_port = int(self._cfg["adapter_port"])
        self.adapter_host = DEFAULT_ADAPTER_HOST
        self.webui_port = int(self._cfg.get("jaeger_webui_port", DEFAULT_WEBUI_PORT))
        self.tailscale_publish = bool(self._cfg.get("tailscale_publish", False))
        self.tailscale_https_port = int(self._cfg.get("tailscale_https_port", 8443))
        self.layout = self._cfg["layout"]

    def urls(self) -> WebUIUrls:
        return webui_urls(
            adapter_port=self.adapter_port,
            adapter_host=self.adapter_host,
            webui_port=self.webui_port,
        )

    def browser_url(self) -> str:
        """Canonical chat URL: host Jaeger WebUI on :8790, never :8787.

        Tailscale IPv4 is preferred when available; otherwise loopback.
        """
        ts = _tailscale_ipv4()
        if ts:
            return f"http://{ts}:{self.webui_port}/"
        return self.urls().web_ui

    def status(self) -> dict[str, Any]:
        urls = self.urls()
        adapter = self._adapter_status()
        webui = self._webui_status()
        adapter_health = _http_ok(urls.adapter.rstrip("/") + "/api/health")
        if not adapter_health.get("ok"):
            adapter_health = _http_ok(urls.adapter)
        webui_health = _http_ok(urls.web_ui, timeout=5.0)
        identity = probe_webui_identity(urls.web_ui) if webui_health.get("ok") else {
            "ok": False,
            "error": webui_health.get("error") or "webui not reachable",
        }
        if webui_health.get("ok") and not identity.get("ok"):
            webui_health = {
                **webui_health,
                "ok": False,
                "error": identity.get("error") or "webui identity mismatch",
            }
        webui_health = {**webui_health, "identity": identity}
        return {
            "instance": self.instance,
            "adapter": {
                **adapter,
                "url": urls.adapter,
                "health": adapter_health,
            },
            "webui": {
                **webui,
                "url": urls.web_ui,
                "health": webui_health,
            },
            "webui_url": urls.web_ui,
            "chat_url": self.browser_url(),
            "ports": {
                "adapter": self.adapter_port,
                "webui": self.webui_port,
                "webhooks": 8793,
            },
        }

    def start(self, *, publish_tailscale: bool | None = None) -> dict[str, Any]:
        """Start Jaeger's WebUI and runtime adapter."""
        if self.layout is None:
            return {"ok": False, "error": f"instance {self.instance!r} not found"}
        try:
            prepare_webui_home()
        except Exception:
            pass
        adapter_res = self._start_adapter()
        if not adapter_res.get("ok"):
            return {"ok": False, "adapter": adapter_res}
        webui_res = self._start_webui()
        tailscale_res: dict[str, Any] = {"ok": True, "skipped": True}
        should_publish = self.tailscale_publish if publish_tailscale is None else publish_tailscale
        if webui_res.get("ok") and should_publish:
            tailscale_res = self.publish_tailscale()
        return {
            "ok": bool(adapter_res.get("ok"))
            and bool(webui_res.get("ok"))
            and bool(tailscale_res.get("ok")),
            "adapter": adapter_res,
            "webui": webui_res,
            "tailscale": tailscale_res,
            "open": self.urls().web_ui,
        }

    def publish_tailscale(self) -> dict[str, Any]:
        """Publish only the loopback WebUI through the current tailnet."""
        binary = shutil.which("tailscale")
        if not binary:
            return {"ok": False, "error": "tailscale CLI is not installed or not on PATH"}
        target = self.urls().web_ui.rstrip("/")
        try:
            proc = subprocess.run(
                [binary, "serve", "--bg", f"--https={self.tailscale_https_port}", target],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": str(exc)}
        output = (proc.stdout or proc.stderr or "").strip()
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "target": target,
            "output": output,
        }

    def stop(self) -> dict[str, Any]:
        adapter_res = self._stop_adapter()
        webui_res = self._stop_webui()
        return {
            "ok": bool(adapter_res.get("ok")) and bool(webui_res.get("ok")),
            "adapter": adapter_res,
            "webui": webui_res,
            "status": self.status(),
        }

    def _adapter_status(self) -> dict[str, Any]:
        return self._listener_status(
            pid_path=_adapter_pid_path(self.layout) if self.layout is not None else None,
            port=self.adapter_port,
        )

    def _webui_status(self) -> dict[str, Any]:
        return self._listener_status(
            pid_path=_webui_pid_path(self.layout) if self.layout is not None else None,
            port=self.webui_port,
        )

    def _listener_status(self, *, pid_path: Path | None, port: int) -> dict[str, Any]:
        """Pid-file OR a live listener counts as running (launchd may not write the pid file)."""
        pid = _read_pid(pid_path) if pid_path is not None else None
        running = bool(pid and _pid_alive(pid))
        source = "pid_file" if running else None
        if pid and not running and pid_path is not None:
            try:
                pid_path.unlink(missing_ok=True)
            except OSError:
                pass
            pid = None
        if not running:
            listener = _listening_pid(port)
            if listener is not None:
                pid = listener
                running = True
                source = "listener"
        return {
            "running": running,
            "pid": pid,
            "pid_file": str(pid_path) if pid_path is not None else None,
            "source": source,
        }

    def _start_webui(self) -> dict[str, Any]:
        assert self.layout is not None
        current = self._webui_status()
        if current.get("running"):
            return {"ok": True, "already_running": True, "pid": current.get("pid")}
        # An orphaned WebUI can hold :8790 after a lost pid file. Reclaim it so
        # profile-link / bind fixes actually take effect.
        if _http_ok(self.urls().web_ui, timeout=1.0).get("ok"):
            try:
                import signal as _signal
                proc = subprocess.run(
                    ["lsof", "-nP", f"-iTCP:{self.webui_port}", "-sTCP:LISTEN", "-t"],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                for raw in (proc.stdout or "").split():
                    try:
                        opid = int(raw)
                    except ValueError:
                        continue
                    try:
                        os.kill(opid, _signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and _http_ok(self.urls().web_ui, timeout=0.5).get("ok"):
                    time.sleep(0.2)
            except Exception:
                pass
        if not WEBUI_SCRIPT.is_file():
            return {"ok": False, "error": f"WebUI launcher is missing: {WEBUI_SCRIPT}"}
        agent_home = Path(
            os.environ.get("JAEGER_WEBUI_AGENT_STATE")
            or (Path.home() / ".jaeger" / "hermes-webui-agent")
        ).expanduser()
        _ensure_shared_profiles(agent_home)
        log_path = _webui_log_path(self.layout)
        pid_path = _webui_pid_path(self.layout)
        env = os.environ.copy()
        env["JAEGER_RUNNER_BASE_URL"] = self.urls().adapter.rstrip("/")
        env["JAEGER_GATEWAY_URL"] = (
            os.environ.get("JAEGER_GATEWAY_URL") or "http://127.0.0.1:8810"
        ).rstrip("/")
        env["JAEGER_WEBUI_PORT"] = str(self.webui_port)
        env["JAEGER_WEBUI_HOST"] = os.environ.get("JAEGER_WEBUI_HOST", "0.0.0.0")
        hermes_agent_src = Path(
            os.environ.get("JAEGER_HERMES_AGENT_SRC")
            or (Path.home() / "GitHub" / "hermes-agent")
        ).expanduser()
        if hermes_agent_src.is_dir():
            env["HERMES_WEBUI_AGENT_DIR"] = str(hermes_agent_src)
            # Ensure hermes_cli imports resolve for profile listing/switch.
            env["PYTHONPATH"] = str(hermes_agent_src) + (
                (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else ""
            )
        env["JAEGER_WEBUI_AGENT_STATE"] = str(agent_home)
        # Popen retains the descriptor after this method returns; explicit
        # lifecycle management is clearer than a context manager here.
        log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        try:
            proc = subprocess.Popen(
                [str(WEBUI_SCRIPT)],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001
            log_f.close()
            return {"ok": False, "error": str(exc)}
        pid_path.write_text(str(proc.pid), encoding="utf-8")
        deadline = time.monotonic() + 10
        health: dict[str, Any] = {"ok": False}
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log_f.close()
                return {"ok": False, "error": f"WebUI exited early (code {proc.returncode})", "log": str(log_path)}
            health = _http_ok(self.urls().web_ui)
            if health.get("ok"):
                break
            time.sleep(0.25)
        log_f.close()
        if not health.get("ok"):
            try:
                os.kill(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            pid_path.unlink(missing_ok=True)
            return {"ok": False, "error": "WebUI did not become healthy within 10 seconds", "pid": proc.pid, "log": str(log_path)}
        return {"ok": True, "pid": proc.pid, "log": str(log_path), "health": health}

    def _start_adapter(self) -> dict[str, Any]:
        assert self.layout is not None
        current = self._adapter_status()
        if current.get("running"):
            return {"ok": True, "already_running": True, "pid": current.get("pid")}

        log_path = _adapter_log_path(self.layout)
        pid_path = _adapter_pid_path(self.layout)
        env = os.environ.copy()
        env["JAEGER_INSTANCE_NAME"] = self.instance
        env["JAEGER_HERMES_WEBUI_ADAPTER_HOST"] = self.adapter_host
        env["JAEGER_HERMES_WEBUI_ADAPTER_PORT"] = str(self.adapter_port)
        cmd = [
            sys.executable,
            "-m",
            "jaeger_ai.features.webui.adapter",
            "--host",
            self.adapter_host,
            "--port",
            str(self.adapter_port),
            "--instance",
            self.instance,
        ]
        log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001
            log_f.close()
            return {"ok": False, "error": str(exc)}
        pid_path.write_text(str(proc.pid), encoding="utf-8")
        deadline = time.monotonic() + 5
        health: dict[str, Any] = {"ok": False}
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log_f.close()
                return {
                    "ok": False,
                    "error": f"adapter exited early (code {proc.returncode})",
                    "log": str(log_path),
                }
            health = _http_ok(
                f"http://{self.adapter_host}:{self.adapter_port}/api/health"
            )
            if health.get("ok"):
                break
            time.sleep(0.25)
        log_f.close()
        return {
            "ok": True,
            "pid": proc.pid,
            "log": str(log_path),
            "health": health,
        }

    def _stop_adapter(self) -> dict[str, Any]:
        if self.layout is None:
            return {"ok": True, "skipped": True}
        pid_path = _adapter_pid_path(self.layout)
        status = self._adapter_status()
        pid = status.get("pid")
        if not pid:
            return {"ok": True, "already_stopped": True}
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.1)
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": True, "pid": pid, "stopped": True}

    def _stop_webui(self) -> dict[str, Any]:
        if self.layout is None:
            return {"ok": True, "skipped": True}
        pid_path = _webui_pid_path(self.layout)
        status = self._webui_status()
        pid = status.get("pid")
        if not pid:
            return {"ok": True, "already_stopped": True}
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.1)
        pid_path.unlink(missing_ok=True)
        stopped = not _pid_alive(pid)
        return {"ok": stopped, "pid": pid, "stopped": stopped}
