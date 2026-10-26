"""Conftest for integration tests — requires running services."""

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
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "jaeger-agent"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "jaeger-os"))

# Service URLs
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:33418")
WEBUI_URL = os.environ.get("WEBUI_URL", "http://127.0.0.1:8790")
WS_URL = os.environ.get("WS_URL", "ws://127.0.0.1:33418/ws")


@pytest.fixture(scope="session")
def gateway_url() -> str:
    """Return the Gateway URL."""
    return GATEWAY_URL


@pytest.fixture(scope="session")
def webui_url() -> str:
    """Return the WebUI URL."""
    return WEBUI_URL


@pytest.fixture(scope="session")
def ws_url() -> str:
    """Return the WebSocket URL."""
    return WS_URL


@pytest.fixture(scope="session")
def running_gateway(gateway_url: str) -> bool:
    """Check if Gateway is running."""
    import httpx
    try:
        r = httpx.get(f"{gateway_url}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def running_webui(webui_url: str) -> bool:
    """Check if WebUI is running."""
    import httpx
    try:
        r = httpx.get(webui_url, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
async def http_client(gateway_url: str):
    """Create an HTTP client for API tests."""
    import httpx
    async with httpx.AsyncClient(base_url=gateway_url, timeout=30) as client:
        yield client


@pytest.fixture(scope="session")
async def ws_client(ws_url: str):
    """Create a WebSocket client."""
    import websockets
    async with websockets.connect(ws_url) as ws:
        yield ws


def pytest_collection_modifyitems(config, items):
    """Skip integration tests if services are not running."""
    # Check if we should skip integration tests
    skip_integration = pytest.mark.skip(reason="Integration tests require running services")
    
    for item in items:
        if "integration" in item.keywords or "requires_gateway" in item.keywords:
            # These will be checked at runtime
            pass
