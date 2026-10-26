"""Conftest for E2E tests — full stack required."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def running_system():
    """Ensure the full system is running for E2E tests."""
    import httpx
    
    gateway_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:33418")
    webui_url = os.environ.get("WEBUI_URL", "http://127.0.0.1:8790")
    
    # Check if already running
    try:
        r = httpx.get(f"{gateway_url}/health", timeout=5)
        if r.status_code == 200:
            yield {"gateway": gateway_url, "webui": webui_url, "running": True}
            return
    except Exception:
        pass
    
    # Start services
    print("\n🚀 Starting test environment...")
    
    # Start Gateway
    gateway_proc = subprocess.Popen(
        [sys.executable, "-m", "jaeger_ai", "gateway", "daemon"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    # Wait for Gateway
    for _ in range(30):
        try:
            r = httpx.get(f"{gateway_url}/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    else:
        gateway_proc.terminate()
        pytest.skip("Gateway did not start")
    
    # Start WebUI
    webui_proc = subprocess.Popen(
        [sys.executable, "-m", "jaeger_ai", "webui", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    # Wait for WebUI
    for _ in range(30):
        try:
            r = httpx.get(webui_url, timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    
    yield {
        "gateway": gateway_url,
        "webui": webui_url,
        "ws": f"ws://127.0.0.1:33418/ws",
        "running": True,
    }
    
    # Cleanup
    print("\n🛑 Stopping test environment...")
    gateway_proc.terminate()
    webui_proc.terminate()
    gateway_proc.wait(timeout=10)
    webui_proc.wait(timeout=10)
