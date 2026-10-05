"""Write Jaeger-owned Agentgateway YAML. Never copies ARES secrets or paths."""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Any

import yaml

from .constants import (
    A2A_BACKEND_HOST,
    A2A_BACKEND_PORT,
    A2A_GATEWAY_PORT,
    MCP_GATEWAY_PORT,
    MCP_HTTP_HOST,
    MCP_HTTP_PATH,
    MCP_HTTP_PORT,
    config_path,
    gateway_dir,
    mcp_token_path,
    token_path,
)


def _issue_token(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
    else:
        value = secrets.token_urlsafe(32)
        path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)
    if not value:
        raise RuntimeError(f"Gateway token file is empty: {path}")
    return value


def _api_key_policy(root: Path | None = None) -> dict[str, Any]:
    value = _issue_token(mcp_token_path(root))
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return {
        "mode": "strict",
        "keys": [{"keyHash": f"sha256:{digest}"}],
    }



#: Env vars agentgateway expands into ``backendAuth`` (verified on v1.5.0: the
#: value is sent as ``Authorization: Bearer …`` to that backend only, and the
#: inbound client key is not forwarded). ``service.start`` fills them from the
#: Keychain caller tokens ``mcp`` and ``a2a``; the values never touch disk.
MCP_BACKEND_TOKEN_ENV = "JAEGER_MCP_BACKEND_TOKEN"
A2A_BACKEND_TOKEN_ENV = "JAEGER_A2A_BACKEND_TOKEN"


def _backend_auth(env_name: str) -> dict[str, Any]:
    return {"backendAuth": {"key": f"${env_name}"}}


def default_config(root: Path | None = None) -> dict[str, Any]:
    """Authenticated Agentgateway config targeting loopback Jaeger backends.

    The proxy binds a container-reachable socket, so MCP and A2A require the
    Jaeger-owned API key. Only a SHA-256 hash is stored in this config; the
    token itself remains in a private state file and is never printed.
    """
    state = gateway_dir(root)
    mcp_url = f"http://{MCP_HTTP_HOST}:{MCP_HTTP_PORT}{MCP_HTTP_PATH}"
    a2a_backend = f"{A2A_BACKEND_HOST}:{A2A_BACKEND_PORT}"
    api_key = _api_key_policy(root)
    # Jaeger's A2A server requires the ``a2a`` caller token for JSON-RPC.
    a2a_target = {"host": a2a_backend, "policies": _backend_auth(A2A_BACKEND_TOKEN_ENV)}
    return {
        "config": {
            "database": {"url": f"sqlite://{state / 'data.db'}"},
            "logging": {"format": "json"},
        },
        "mcp": {
            "port": MCP_GATEWAY_PORT,
            "policies": {
                "cors": {
                    "allowOrigins": ["http://127.0.0.1", "http://localhost"],
                    "allowHeaders": [
                        "authorization",
                        "mcp-protocol-version",
                        "content-type",
                        "cache-control",
                        "mcp-session-id",
                    ],
                    "exposeHeaders": ["Mcp-Session-Id"],
                },
                "apiKey": api_key,
            },
            "targets": [
                {
                    "name": "jaeger",
                    "mcp": {"host": mcp_url},
                    # Jaeger's MCP server requires the ``mcp`` caller token.
                    "policies": _backend_auth(MCP_BACKEND_TOKEN_ENV),
                }
            ],
        },
        "binds": [
            {
                "port": A2A_GATEWAY_PORT,
                "listeners": [
                    {
                        "routes": [
                            {
                                "matches": [
                                    {"path": {"exact": "/.well-known/agent-card.json"}}
                                ],
                                "policies": {"a2a": {}, "apiKey": api_key},
                                "backends": [a2a_target],
                            },
                            {
                                # Compatibility for older clients. The A2A
                                # standard path above remains canonical.
                                "matches": [
                                    {"path": {"exact": "/.well-known/agent.json"}}
                                ],
                                "policies": {"a2a": {}, "apiKey": api_key},
                                "backends": [a2a_target],
                            },
                            {
                                "policies": {
                                    "cors": {
                                        "allowOrigins": ["*"],
                                        "allowHeaders": [
                                            "content-type",
                                            "cache-control",
                                            "a2a-version",
                                        ],
                                    },
                                    "a2a": {},
                                    "apiKey": api_key,
                                },
                                "backends": [a2a_target],
                            },
                        ]
                    }
                ],
            }
        ],
    }


def config_is_stale(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return True
    lowered = text.lower()
    if "ares" in lowered or ":8788" in text:
        return True
    if f":{MCP_HTTP_PORT}{MCP_HTTP_PATH}" not in text:
        return True
    if f"{A2A_BACKEND_HOST}:{A2A_BACKEND_PORT}" not in text:
        return True
    if "apiKey:" not in text or "keyHash:" not in text:
        return True
    # Pre-caller-auth configs reach Jaeger's MCP/A2A servers without a token.
    if ("backendAuth:" not in text or f"${MCP_BACKEND_TOKEN_ENV}" not in text
            or f"${A2A_BACKEND_TOKEN_ENV}" not in text):
        return True
    return False


def ensure_config(root: Path | None = None, *, force: bool = False) -> Path:
    """Write ~/.jaeger/gateway/config.yaml if missing or still pointing at archive paths."""
    state = gateway_dir(root)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    output = config_path(root)
    _issue_token(token_path(root))
    _issue_token(mcp_token_path(root))
    if not force and not config_is_stale(output):
        return output
    payload = default_config(root)
    if output.exists():
        try:
            previous = yaml.safe_load(output.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            previous = {}
        if isinstance(previous, dict) and "ares" not in output.read_text(encoding="utf-8").lower():
            old_targets = previous.get("mcp", {}).get("targets", [])
            extras = [
                target for target in old_targets
                if isinstance(target, dict) and target.get("name") != "jaeger"
            ]
            payload["mcp"]["targets"].extend(extras)
    temporary = output.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, output)
    return output
