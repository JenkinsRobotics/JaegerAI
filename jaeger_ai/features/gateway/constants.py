"""Pinned Agentgateway identity and Jaeger loopback ports."""

from __future__ import annotations

import os
from pathlib import Path

VERSION = "1.5.0"
ASSET = "agentgateway-darwin-arm64"
SHA256 = "da432d35bd696da0564f7b2b6bbc783542b6b9c616d6c0c4d4c3daef9dfa11a1"
RELEASE_URL = (
    f"https://github.com/agentgateway/agentgateway/releases/download/"
    f"v{VERSION}/{ASSET}"
)

MCP_GATEWAY_PORT = 8811
A2A_GATEWAY_PORT = 8812
MCP_HTTP_HOST = "127.0.0.1"
MCP_HTTP_PORT = 8792
MCP_HTTP_PATH = "/mcp"
A2A_BACKEND_HOST = "127.0.0.1"
A2A_BACKEND_PORT = 8796
A2A_PUBLIC_URL = "http://127.0.0.1:8812"

STATS_ADDR = "127.0.0.1:15020"
READINESS_ADDR = "127.0.0.1:15021"


def jaeger_home(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("JAEGER_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".jaeger"


def bin_dir(root: Path | None = None) -> Path:
    return jaeger_home(root) / "bin"


def gateway_dir(root: Path | None = None) -> Path:
    return jaeger_home(root) / "gateway"


def binary_path(root: Path | None = None) -> Path:
    return bin_dir(root) / f"agentgateway-v{VERSION}"


def binary_link(root: Path | None = None) -> Path:
    return bin_dir(root) / "agentgateway"


def config_path(root: Path | None = None) -> Path:
    return gateway_dir(root) / "config.yaml"


def token_path(root: Path | None = None) -> Path:
    return gateway_dir(root) / "client.token"


def mcp_token_path(root: Path | None = None) -> Path:
    return gateway_dir(root) / "mcp.token"


def pid_path(root: Path | None = None) -> Path:
    return gateway_dir(root) / "agentgateway.pid"
