"""Reusable host capability report for commissioning.

Expands the OS 1 hardware bench into a structured snapshot of what this
Mac (or other host) can actually do. Optional capabilities that are
absent are recorded as unavailable — they never fail commissioning.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _now() -> float:
    return time.time()


def _run(cmd: list[str], *, timeout: float = 2.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return proc.returncode, (proc.stdout or proc.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _gb(num: float) -> float:
    return round(float(num), 1)


@dataclass
class HostCapabilityReport:
    """Structured snapshot of the host Jaeger is being commissioned on."""

    system: dict[str, Any] = field(default_factory=dict)
    compute: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    vision: dict[str, Any] = field(default_factory=dict)
    ai: dict[str, Any] = field(default_factory=dict)
    development: dict[str, Any] = field(default_factory=dict)
    jaeger: dict[str, Any] = field(default_factory=dict)
    discovered_at: float = field(default_factory=_now)
    duration_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _macos_version() -> str:
    if platform.system() != "Darwin":
        return platform.platform()
    ver, _, _ = _run(["sw_vers", "-productVersion"])
    return ver or platform.mac_ver()[0] or ""


def _apple_silicon_generation() -> str | None:
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        return None
    code, out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    if code == 0 and out:
        return out
    return None


def _unified_memory_gb() -> float:
    try:
        from jaeger_ai.core.models.host_recommendation import detect_total_memory_gb
        return _gb(detect_total_memory_gb())
    except Exception:
        return 0.0


def _disk_free_gb(path: Path | None = None) -> float:
    target = path or Path.home()
    try:
        usage = shutil.disk_usage(str(target))
        return _gb(usage.free / (1024 ** 3))
    except OSError:
        return 0.0


def _network_available() -> bool:
    if _port_open("1.1.1.1", 443, timeout=0.6):
        return True
    if _port_open("8.8.8.8", 53, timeout=0.6):
        return True
    return False


def _metal_available() -> bool:
    if platform.system() != "Darwin":
        return False
    if platform.machine() in {"arm64", "aarch64"}:
        return True
    code, out = _run(["system_profiler", "SPDisplaysDataType"], timeout=8.0)
    return "Metal" in out if code == 0 else False


def _audio_devices() -> dict[str, Any]:
    mic = False
    output = False
    if platform.system() == "Darwin":
        code, out = _run(["system_profiler", "SPAudioDataType"], timeout=6.0)
        lowered = out.lower()
        output = "output" in lowered or "speaker" in lowered or "headphone" in lowered
        mic = "input" in lowered or "microphone" in lowered or "mic" in lowered
        if not (mic or output) and code == 0 and out:
            output = True
    else:
        output = True
    return {
        "microphone": mic,
        "audio_output": output,
        "stt_capability": True,
        "tts_capability": True,
    }


def _vision_devices() -> dict[str, Any]:
    camera = False
    screen = platform.system() == "Darwin"
    permission: dict[str, Any] = {}
    if platform.system() == "Darwin":
        try:
            from jaeger_ai.core.diagnostics.tcc_permissions import status as tcc_status
            permission = {k: v for k, v in tcc_status().items()}
            screen_state = permission.get("screen_recording")
            if screen_state is False:
                screen = False
        except Exception:
            permission = {}
        code, out = _run(["system_profiler", "SPCameraDataType"], timeout=6.0)
        camera = code == 0 and bool(out) and "camera" in out.lower()
    return {
        "camera_available": camera,
        "screen_capture_capability": screen,
        "permission_state": permission,
    }


def _ai_services() -> dict[str, Any]:
    ollama: dict[str, Any] = {"online": False, "endpoint": "", "models": []}
    try:
        from jaeger_ai.core.models.discovery import discover_ollama
        raw = discover_ollama()
        ollama = {
            "online": bool(raw.get("online")),
            "endpoint": str(raw.get("endpoint") or ""),
            "models": list(raw.get("models") or []),
        }
    except Exception:
        pass

    lmstudio_online = _port_open("127.0.0.1", 1234)
    hermes = _port_open("127.0.0.1", 8645)

    local_files: list[dict[str, Any]] = []
    try:
        from jaeger_ai.core.models.discovery import discover_local_gguf_files
        for item in discover_local_gguf_files()[:40]:
            local_files.append({
                "filename": getattr(item, "filename", ""),
                "path": str(getattr(item, "path", "")),
                "size_gb": getattr(item, "size_gb", None),
                "source": getattr(item, "source", ""),
            })
    except Exception:
        pass

    cloud: dict[str, bool] = {}
    try:
        from jaeger_ai.core.models.model_resolver import _resolve_provider_key
        for name in ("anthropic", "openai", "gemini", "xai", "ollama-cloud"):
            cloud[name] = bool(_resolve_provider_key(name))
    except Exception:
        cloud = {}

    return {
        "ollama": ollama,
        "lm_studio": {"online": lmstudio_online, "endpoint": "http://127.0.0.1:1234"},
        "hermes_local": {"online": hermes, "endpoint": "http://127.0.0.1:8645"},
        "configured_cloud_providers": cloud,
        "installed_local_model_files": local_files,
        "local_inference_available": bool(
            ollama.get("online") or lmstudio_online or local_files
        ),
    }


def _development_tools() -> dict[str, Any]:
    git = shutil.which("git") is not None
    python_ok = True
    xcode = None
    github = None
    if shutil.which("xcode-select"):
        code, out = _run(["xcode-select", "-p"])
        xcode = bool(code == 0 and out)
    if shutil.which("gh"):
        code, out = _run(["gh", "auth", "status"], timeout=3.0)
        github = code == 0
    return {
        "git": git,
        "python": python_ok,
        "python_version": sys.version.split()[0],
        "xcode": xcode,
        "github_auth": github,
    }


def _jaeger_services(*, gateway_port: int | None = None) -> dict[str, Any]:
    from jaeger_ai.contract.ports import GATEWAY_PORT, WEBUI_ADAPTER_PORT, WEBUI_PORT

    gw = int(gateway_port or os.environ.get("JAEGER_GATEWAY_PORT") or GATEWAY_PORT)
    gateway = _port_open("127.0.0.1", gw)
    webui = _port_open("127.0.0.1", WEBUI_PORT)
    bridge_http = _port_open("127.0.0.1", WEBUI_ADAPTER_PORT)
    fabric = False
    memory = False
    try:
        from jaeger_ai.core.instance.instance import (
            default_instance_name,
            resolve_instance_dir,
            InstanceLayout,
        )
        layout = InstanceLayout(root=resolve_instance_dir(default_instance_name()))
        fabric = layout.event_store_path.is_file()
        memory = layout.memory_dir.is_dir()
    except Exception:
        pass
    return {
        "gateway": {"reachable": gateway, "port": gw},
        "bridge": {"reachable": bridge_http, "port": WEBUI_ADAPTER_PORT},
        "webui": {"reachable": webui, "port": WEBUI_PORT},
        "event_fabric": {"present": fabric},
        "memory_store": {"present": memory},
    }


def discover_host(*, include_ai: bool = True, quick: bool | None = None) -> HostCapabilityReport:
    """Probe the current host. Never raises. Optional gaps stay optional."""
    t0 = time.time()
    report = HostCapabilityReport()
    if quick is None:
        quick = "PYTEST_CURRENT_TEST" in os.environ
    try:
        report.system = {
            "os": platform.system(),
            "macos_version": platform.mac_ver()[0] if platform.system() == "Darwin" else "",
            "architecture": platform.machine(),
            "apple_silicon_generation": None if quick else _apple_silicon_generation(),
            "unified_memory_gb": _unified_memory_gb(),
            "cpu_cores": os.cpu_count() or 1,
            "available_disk_gb": _disk_free_gb(),
            "network_available": False if quick else _network_available(),
            "hostname": platform.node(),
        }
        if not quick and platform.system() == "Darwin":
            report.system["macos_version"] = _macos_version()
    except Exception as exc:
        report.system = {"error": str(exc)[:200]}
    try:
        report.compute = {
            "metal": (platform.system() == "Darwin" and platform.machine() in {"arm64", "aarch64"})
            if quick else _metal_available(),
            "local_inference_availability": True,
        }
    except Exception as exc:
        report.compute = {"error": str(exc)[:200]}
    try:
        report.audio = {
            "microphone": False, "audio_output": True,
            "stt_capability": True, "tts_capability": True,
        } if quick else _audio_devices()
    except Exception as exc:
        report.audio = {"error": str(exc)[:200]}
    try:
        report.vision = {
            "camera_available": False,
            "screen_capture_capability": platform.system() == "Darwin",
            "permission_state": {},
        } if quick else _vision_devices()
    except Exception as exc:
        report.vision = {"error": str(exc)[:200]}
    try:
        report.ai = {} if (quick or not include_ai) else _ai_services()
    except Exception as exc:
        report.ai = {"error": str(exc)[:200]}
    try:
        report.development = {
            "git": shutil.which("git") is not None,
            "python": True,
            "python_version": sys.version.split()[0],
            "xcode": None,
            "github_auth": None,
        } if quick else _development_tools()
    except Exception as exc:
        report.development = {"error": str(exc)[:200]}
    try:
        report.jaeger = _jaeger_services()
    except Exception as exc:
        report.jaeger = {"error": str(exc)[:200]}
    if report.ai:
        report.compute["local_inference_availability"] = bool(
            (report.ai.get("local_inference_available"))
            or report.compute.get("metal")
        )
    report.duration_ms = int((time.time() - t0) * 1000)
    report.discovered_at = time.time()
    return report


def detect_candidate_knowledge_folders(*, home: Path | None = None) -> list[dict[str, str]]:
    """Folders a person might want indexed. Never includes $HOME itself.

    Skips the operator home during pytest unless
    ``JAEGER_COMMISSIONING_SCAN_HOME=1``.
    """
    if "PYTEST_CURRENT_TEST" in os.environ and os.environ.get(
        "JAEGER_COMMISSIONING_SCAN_HOME", ""
    ).strip() not in {"1", "true", "yes"}:
        return []
    root = Path(home) if home is not None else Path.home()
    names = ("Projects", "Documents", "Notes", "Desktop")
    found: list[dict[str, str]] = []
    for name in names:
        path = root / name
        try:
            if path.is_dir():
                found.append({"name": name, "path": str(path)})
        except OSError:
            continue
    return found


def jaeger_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


__all__ = [
    "HostCapabilityReport",
    "detect_candidate_knowledge_folders",
    "discover_host",
    "jaeger_repo_root",
]
