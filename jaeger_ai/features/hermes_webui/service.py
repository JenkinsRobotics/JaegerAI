"""Lifecycle helpers for Hermes WebUI as Jaeger's temporary browser UI.

Settings (``containers.use_hermes_webui`` and friends) are the plugin-style
toggle surface. This module starts/stops the Apple container and the
loopback ``hermes-webui-adapter`` so the browser can reach Jaeger.

Port map (coherent defaults):
  * Hermes WebUI container (browser) — ``containers.hermes_webui_port`` (8787)
  * Jaeger-branded vendor WebUI fork — 8790 via ``scripts/run-jaeger-webui.sh``
  * Hermes WebUI adapter (runner-local) — ``containers.adapter_port`` (8791)
  * Instance webhooks — 8793 (moved off 8791 to avoid clashing with the adapter)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jaeger_ai.core.runtime import container_service as cs

DEFAULT_CONTAINER = "hermes-webui-hermes-webui"
DEFAULT_WEBUI_PORT = 8787
DEFAULT_ADAPTER_PORT = 8791
DEFAULT_ADAPTER_HOST = "127.0.0.1"
VENDOR_WEBUI_PORT = 8790


@dataclass(frozen=True, slots=True)
class HermesWebUIUrls:
    container_ui: str
    adapter: str
    vendor_ui: str


def hermes_webui_urls(
    *,
    webui_port: int = DEFAULT_WEBUI_PORT,
    adapter_port: int = DEFAULT_ADAPTER_PORT,
    adapter_host: str = DEFAULT_ADAPTER_HOST,
) -> HermesWebUIUrls:
    return HermesWebUIUrls(
        container_ui=f"http://127.0.0.1:{webui_port}/",
        adapter=f"http://{adapter_host}:{adapter_port}/",
        vendor_ui=f"http://127.0.0.1:{VENDOR_WEBUI_PORT}/",
    )


def _load_containers_config(instance: str | None = None) -> dict[str, Any]:
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
            "use_hermes_webui": False,
            "hermes_webui_container": DEFAULT_CONTAINER,
            "hermes_webui_port": DEFAULT_WEBUI_PORT,
            "adapter_port": DEFAULT_ADAPTER_PORT,
            "layout": None,
            "instance": name,
        }
    cfg = load_yaml(layout.config_path, Config)
    containers = getattr(cfg, "containers", None)
    return {
        "use_hermes_webui": bool(getattr(containers, "use_hermes_webui", False)),
        "hermes_webui_container": str(
            getattr(containers, "hermes_webui_container", DEFAULT_CONTAINER)
            or DEFAULT_CONTAINER
        ),
        "hermes_webui_port": int(
            getattr(containers, "hermes_webui_port", DEFAULT_WEBUI_PORT)
            or DEFAULT_WEBUI_PORT
        ),
        "adapter_port": int(
            getattr(containers, "adapter_port", DEFAULT_ADAPTER_PORT)
            or DEFAULT_ADAPTER_PORT
        ),
        "layout": layout,
        "instance": name,
    }


def _adapter_run_dir(layout: Any) -> Path:
    root = Path(layout.root) / "run" / "hermes-webui-adapter"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _adapter_pid_path(layout: Any) -> Path:
    return _adapter_run_dir(layout) / "adapter.pid"


def _adapter_log_path(layout: Any) -> Path:
    return _adapter_run_dir(layout) / "adapter.log"


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


class HermesWebUIService:
    """Start/stop/status for container + adapter under the settings toggle."""

    def __init__(self, instance: str | None = None) -> None:
        self._cfg = _load_containers_config(instance)
        self.instance = str(self._cfg["instance"])
        self.enabled = bool(self._cfg["use_hermes_webui"])
        self.container_name = str(self._cfg["hermes_webui_container"])
        self.webui_port = int(self._cfg["hermes_webui_port"])
        self.adapter_port = int(self._cfg["adapter_port"])
        self.adapter_host = DEFAULT_ADAPTER_HOST
        self.layout = self._cfg["layout"]

    def urls(self) -> HermesWebUIUrls:
        return hermes_webui_urls(
            webui_port=self.webui_port,
            adapter_port=self.adapter_port,
            adapter_host=self.adapter_host,
        )

    def status(self) -> dict[str, Any]:
        urls = self.urls()
        container_info = cs.container_status(self.container_name)
        details = container_info.get("details") or {}
        if not container_info.get("found"):
            container_state = "missing"
        else:
            container_state = cs.normalize_state(
                details.get("state") or details.get("status")
            )
        adapter = self._adapter_status()
        container_health = _http_ok(urls.container_ui.rstrip("/") + "/", timeout=5.0)
        adapter_health = _http_ok(urls.adapter.rstrip("/") + "/api/health")
        if not adapter_health.get("ok"):
            adapter_health = _http_ok(urls.adapter)
        return {
            "enabled": self.enabled,
            "instance": self.instance,
            "container": {
                "id": self.container_name,
                "found": bool(container_info.get("found")),
                "state": container_state,
                "url": urls.container_ui,
                "health": container_health,
            },
            "adapter": {
                **adapter,
                "url": urls.adapter,
                "health": adapter_health,
            },
            "vendor_ui_url": urls.vendor_ui,
            "ports": {
                "container_webui": self.webui_port,
                "adapter": self.adapter_port,
                "vendor_webui": VENDOR_WEBUI_PORT,
                "webhooks": 8793,
            },
        }

    def start(self, *, force: bool = False) -> dict[str, Any]:
        if not self.enabled and not force:
            return {
                "ok": False,
                "error": (
                    "containers.use_hermes_webui is false — enable with "
                    "`jaeger settings set containers.use_hermes_webui true` "
                    "or pass --force"
                ),
            }
        if self.layout is None:
            return {"ok": False, "error": f"instance {self.instance!r} not found"}

        container_res = cs.start_container(self.container_name)
        adapter_res = self._start_adapter()
        status = self.status()
        ok = bool(container_res.get("ok")) and bool(adapter_res.get("ok"))
        return {
            "ok": ok,
            "container": container_res,
            "adapter": adapter_res,
            "status": status,
            "open": status["container"]["url"],
        }

    def stop(self, *, stop_container: bool = True) -> dict[str, Any]:
        adapter_res = self._stop_adapter()
        container_res: dict[str, Any] = {"ok": True, "skipped": True}
        if stop_container:
            container_res = cs.stop_container(self.container_name)
        return {
            "ok": bool(adapter_res.get("ok")) and bool(container_res.get("ok")),
            "adapter": adapter_res,
            "container": container_res,
            "status": self.status(),
        }

    def _adapter_status(self) -> dict[str, Any]:
        if self.layout is None:
            return {"running": False, "pid": None}
        pid_path = _adapter_pid_path(self.layout)
        pid = _read_pid(pid_path)
        running = bool(pid and _pid_alive(pid))
        if pid and not running:
            try:
                pid_path.unlink(missing_ok=True)
            except OSError:
                pass
            pid = None
        return {"running": running, "pid": pid, "pid_file": str(pid_path)}

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
            "jaeger_ai.interfaces.hermes_webui_adapter",
            "--host",
            self.adapter_host,
            "--port",
            str(self.adapter_port),
            "--instance",
            self.instance,
        ]
        log_f = open(log_path, "a", encoding="utf-8")
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
        pid = _read_pid(pid_path)
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
