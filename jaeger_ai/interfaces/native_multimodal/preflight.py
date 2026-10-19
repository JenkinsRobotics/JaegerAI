"""Read-only preflight for the JaegerAI multimodal face."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _run_json_probe(code: str, *, timeout_s: float = 8.0) -> Any:
    """Run a hardware probe out of process so a driver cannot hang preflight."""
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            check=False,
            env=env,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"probe timed out after {timeout_s:g}s") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail[-500:] or f"probe exited {completed.returncode}")
    try:
        return json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("probe returned invalid output") from exc


def _default_audio_probe() -> dict[str, Any]:
    return _run_json_probe(
        "import json, os, sys, sounddevice as sd; "
        "d=sd.query_devices(kind='input'); "
        "sys.stdout.write(json.dumps({'name': str(d.get('name', '')), "
        "'index': int(d.get('index', -1))})); sys.stdout.flush(); os._exit(0)"
    )


def _default_camera_probe() -> list[str]:
    return _run_json_probe(
        "import json, os, sys; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); "
        "from PySide6.QtWidgets import QApplication; "
        "from PySide6.QtMultimedia import QMediaDevices; "
        "app=QApplication.instance() or QApplication([]); "
        "sys.stdout.write(json.dumps([str(c.description()) for c in QMediaDevices.videoInputs()])); "
        "sys.stdout.flush(); os._exit(0)"
    )


def _path_check(name: str, value: str | Path) -> Check:
    path = Path(value).expanduser()
    return Check(name, path.is_file(), str(path))


def run_preflight(
    *,
    audio_mode: str = "structured",
    audio_probe: Callable[[], Any] | None = None,
    camera_probe: Callable[[], Any] | None = None,
) -> list[Check]:
    """Check imports, model files, and capture devices without loading models."""
    checks: list[Check] = []
    try:
        import jaeger_agent
        from jaeger_agent import MultimodalConfig
        from jaeger_agent import MultimodalAgent  # noqa: F401

        version = str(getattr(jaeger_agent, "__version__", "unknown"))
        checks.append(Check("engine import", version.startswith("1.2."), version))
        config = MultimodalConfig()
    except Exception as exc:  # noqa: BLE001 — report the import boundary
        checks.append(Check("engine import", False, f"{type(exc).__name__}: {exc}"))
        return checks

    required_modules = ("numpy", "scipy", "soundfile", "onnxruntime", "kokoro")
    missing: list[str] = []
    for module_name in required_modules:
        try:
            if importlib.util.find_spec(module_name) is None:
                missing.append(f"{module_name} (not installed)")
        except Exception as exc:  # noqa: BLE001 — report every broken wheel
            missing.append(f"{module_name} ({type(exc).__name__}: {exc})")
    checks.append(
        Check(
            "multimodal runtime",
            not missing,
            "ready" if not missing else "; ".join(missing),
        )
    )

    if audio_mode in ("quasi", "full"):
        try:
            ready = importlib.util.find_spec("pyaec") is not None
            checks.append(
                Check("duplex AEC", ready, "pyaec ready" if ready else "pyaec missing")
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("duplex AEC", False, f"{type(exc).__name__}: {exc}"))

    checks.append(_path_check("Silero VAD", config.silero_model_path))
    checks.append(_path_check("vision projector", config.vision_mmproj_path))

    try:
        from pywhispercpp.constants import MODELS_DIR

        model = Path(config.stt_model).expanduser()
        if not model.is_file():
            model = Path(MODELS_DIR) / f"ggml-{config.stt_model}.bin"
        checks.append(Check("Whisper model", model.is_file(), str(model)))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("Whisper model", False, f"{type(exc).__name__}: {exc}"))

    try:
        from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir
        from jaeger_ai.core.instance.schemas import Config, load_yaml

        layout = InstanceLayout(root=resolve_instance_dir())
        app_config = load_yaml(layout.config_path, Config)
        external = getattr(app_config, "external_model", None)
        if external is not None and getattr(external, "enabled", False):
            detail = str(getattr(external, "model", "external model configured"))
            checks.append(Check("agent model", True, detail))
        else:
            path = Path(app_config.model.model_path).expanduser()
            checks.append(Check("agent model", path.is_file(), str(path)))
    except Exception:
        checks.append(_path_check("agent model", config.fallback_llm_model_path))

    try:
        if audio_probe is None:
            audio_probe = _default_audio_probe
        device = audio_probe()
        detail = str(device.get("name", device) if isinstance(device, dict) else device)
        checks.append(Check("microphone", device is not None, detail or "not found"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("microphone", False, f"{type(exc).__name__}: {exc}"))

    try:
        if camera_probe is None:
            camera_probe = _default_camera_probe
        cameras = list(camera_probe() or [])
        names = [
            str(camera.description() if hasattr(camera, "description") else camera)
            for camera in cameras
        ]
        checks.append(Check("camera", bool(cameras), ", ".join(names) or "not found"))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("camera", False, f"{type(exc).__name__}: {exc}"))
    return checks


def print_preflight(checks: list[Check]) -> int:
    width = max((len(check.name) for check in checks), default=0)
    for check in checks:
        status = "PASS" if check.ok else "FAIL"
        print(f"{status:4}  {check.name:<{width}}  {check.detail}")
    failures = sum(not check.ok for check in checks)
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed")
    return 1 if failures else 0


def check(*, audio_mode: str = "structured") -> int:
    return print_preflight(run_preflight(audio_mode=audio_mode))


__all__ = ["Check", "check", "print_preflight", "run_preflight"]
