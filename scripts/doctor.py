#!/usr/bin/env python3
"""JaegerAI Doctor: verifies modular packages, 32 GB RAM budget, local tools, and live Gateway."""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_MODULES = (
    "jaeger_contracts",
    "jaeger_events",
    "jaeger_reliability",
    "jaeger_models",
    "jaeger_authority",
    "jaeger_memory",
    "jaeger_tools",
    "jaeger_loop",
    "jaeger_orchestration",
    "jaeger_skills",
    "jaeger_mcp",
    "jaeger_cognition",
    "jaeger_avatar",
    "jaeger_gateway",
)

OPTIONAL_MODULES = (
    "jaeger_business",
    "jaeger_youtube",
    "jaeger_channels",
    "jaeger_embodiment_minecraft",
    "jaeger_droid",
    "jaeger_hardware",
    "jaeger_realtime",
    "jaeger_vision",
    "jaeger_evals",
    "jaeger_protocols",
    "jaeger_kokoro_tts",
    "jaeger_whisper_stt",
)


def _probe_http(url: str, timeout: float = 4.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return {"ok": resp.status == 200, "status": resp.status, "data": json.loads(resp.read().decode("utf-8"))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def run_doctor(*, json_output: bool = False) -> int:
    missing_core = []
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            missing_core.append(mod)

    installed_optional = []
    for mod in OPTIONAL_MODULES:
        try:
            importlib.import_module(mod)
            installed_optional.append(mod)
        except Exception:  # noqa: BLE001
            pass

    tools = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "node": bool(shutil.which("node")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "yt_dlp": bool(shutil.which("yt-dlp")),
        "whisper_cli": bool(shutil.which("whisper-cli")),
        "ollama_cli": bool(shutil.which("ollama")),
    }

    gw_port = int(os.environ.get("JAEGER_GATEWAY_PORT") or "33418")
    gw = _probe_http(f"http://127.0.0.1:{gw_port}/health", timeout=4.0)
    res = _probe_http(f"http://127.0.0.1:{gw_port}/v1/system/resources", timeout=4.0)
    gateway_live = bool(gw["ok"] or res["ok"])
    ui_dist = Path.home() / ".cache" / "jaeger" / "ui-rebuild-mainscreen" / "dist" / "index.html"

    report = {
        "ok": len(missing_core) == 0,
        "core_packages_ok": len(missing_core) == 0,
        "missing_core_packages": missing_core,
        "optional_packages_installed": installed_optional,
        "tools": tools,
        "ui_bundle_built": ui_dist.is_file(),
        "gateway_live": gateway_live,
        "resources": res.get("data", {}).get("resources", {}) if res["ok"] else {},
    }

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        print("=== JaegerAI Doctor ===")
        print(f"Python:   {tools['python']} ({tools['platform']})")
        print(f"Core:     {'OK' if report['core_packages_ok'] else 'MISSING: ' + ', '.join(missing_core)}")
        print(f"Optional: {len(installed_optional)}/{len(OPTIONAL_MODULES)} installed ({', '.join(installed_optional)})")
        print(
            f"Binaries: node={tools['node']} ffmpeg={tools['ffmpeg']} yt-dlp={tools['yt_dlp']} "
            f"whisper={tools['whisper_cli']} ollama={tools['ollama_cli']}"
        )
        print(f"WebUI:    {'Built' if report['ui_bundle_built'] else 'Not built yet'}")
        if gateway_live:
            r = report["resources"]
            ram_str = (
                f" | RAM {r.get('host_available_gb', '?')}/{r.get('host_total_gb', '?')} GB free"
                if r
                else ""
            )
            pid = gw.get("data", {}).get("pid", "?") if gw["ok"] else "?"
            print(f"Gateway:  LIVE on :{gw_port} (pid={pid}){ram_str}")
        else:
            err = gw.get("error") or res.get("error") or ""
            suffix = f" ({err})" if err else ""
            print(f"Gateway:  Not running on :{gw_port}{suffix}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run_doctor(json_output="--json" in sys.argv))
