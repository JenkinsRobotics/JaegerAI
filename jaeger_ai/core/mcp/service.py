"""Validated, instance-owned MCP configuration and live tool inventory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SECRET = re.compile(r"(token|secret|password|api[_-]?key|credential)", re.I)
_MASK = "********"


class MCPServiceError(ValueError):
    pass


def _path(layout: Any) -> Path:
    if layout is None:
        raise MCPServiceError("no Jaeger instance is selected")
    return Path(getattr(layout, "mcp_config_path", Path(layout.root) / "mcp.json"))


def _load(layout: Any) -> dict[str, Any]:
    path = _path(layout)
    if not path.exists():
        return {"version": 1, "servers": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MCPServiceError(f"invalid MCP configuration: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("servers", []), list):
        raise MCPServiceError("invalid MCP configuration: servers must be a list")
    return data


def _credential_name(server: str, env_name: str) -> str:
    raw = f"mcp.{server}.{env_name}"
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", raw)
    if len(clean) <= 64:
        return clean
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]
    return f"{clean[:53]}.{digest}"


def _secret_ref(value: Any) -> str | None:
    if not isinstance(value, dict) or set(value) != {"secret_ref"}:
        return None
    ref = value.get("secret_ref")
    return str(ref).strip() if isinstance(ref, str) and ref.strip() else None


def _migrate_inline_secrets(layout: Any, data: dict[str, Any]) -> bool:
    """Move legacy inline secret-looking env values to the credential store."""
    from jaeger_agent import credentials

    changed = False
    for server in data.get("servers", []):
        if not isinstance(server, dict) or not isinstance(server.get("env"), dict):
            continue
        server_name = str(server.get("name") or "server")
        for key, value in list(server["env"].items()):
            if _SECRET.search(str(key)) and isinstance(value, str) and value and value != _MASK:
                ref = _credential_name(server_name, str(key))
                credentials.set_credential(layout, ref, value)
                server["env"][key] = {"secret_ref": ref}
                changed = True
    return changed


def migrate_inline_secrets(layout: Any) -> bool:
    """Secure legacy config explicitly during boot/reload or mutation."""
    data = _load(layout)
    changed = _migrate_inline_secrets(layout, data)
    if changed:
        _write(layout, data)
    return changed


def resolve_server_env(layout: Any, server: dict[str, Any]) -> dict[str, str]:
    """Resolve credential references only for the child-process launch."""
    from jaeger_agent import credentials

    env = server.get("env") if isinstance(server.get("env"), dict) else {}
    resolved: dict[str, str] = {}
    for key, value in env.items():
        if isinstance(value, str):
            resolved[str(key)] = value
            continue
        ref = _secret_ref(value)
        if ref is None:
            raise MCPServiceError(f"invalid environment value for {key!r}")
        try:
            resolved[str(key)] = credentials.get_credential(layout, ref)
        except Exception as exc:
            raise MCPServiceError(f"missing MCP credential {ref!r} for {key}") from exc
    return resolved


def _write(layout: Any, data: dict[str, Any]) -> None:
    path = _path(layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".mcp-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _name(value: Any) -> str:
    name = str(value or "").strip()
    if not _NAME.fullmatch(name):
        raise MCPServiceError("server name must use 1-64 letters, numbers, dots, dashes, or underscores")
    return name


def _runtime() -> tuple[dict[str, list[Any]], dict[str, str], bool]:
    from jaeger_ai.plugins.mcp import client
    registry = client.get_registry()
    tools: dict[str, list[Any]] = {}
    if registry is not None:
        for spec in registry.list_tools():
            tools.setdefault(spec.server_name, []).append(spec)
    return tools, client.connection_errors(), registry is not None


def list_servers(layout: Any) -> dict[str, Any]:
    tools, errors, running = _runtime()
    rows = []
    for raw in _load(layout).get("servers", []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "")
        active_tools = tools.get(name, [])
        env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
        masked_env = {}
        for key, value in env.items():
            masked_env[str(key)] = _MASK if _secret_ref(value) or (_SECRET.search(str(key)) and value) else str(value)
        rows.append({
            "name": name, "transport": "stdio", "command": raw.get("command", ""),
            "args": list(raw.get("args") or []),
            "env": masked_env,
            "enabled": bool(raw.get("enabled", True)), "active": bool(active_tools),
            "status": "error" if name in errors else ("active" if active_tools else "configured"),
            "error": errors.get(name), "tool_count": len(active_tools),
        })
    return {"ok": True, "owner": "jaeger", "servers": rows,
            "total": len(rows), "toggle_supported": True,
            "reload_required": any(row["enabled"] and not row["active"] for row in rows),
            "runtime_initialized": running}


def list_tools(layout: Any) -> dict[str, Any]:
    tools, errors, _ = _runtime()
    rows = []
    for server, specs in tools.items():
        for spec in specs:
            properties = spec.input_schema.get("properties") or {}
            required = set(spec.input_schema.get("required") or [])
            summary = [{"name": str(name),
                        "type": str(meta.get("type") or "unknown") if isinstance(meta, dict) else "unknown",
                        "required": name in required,
                        "description": str(meta.get("description") or "") if isinstance(meta, dict) else ""}
                       for name, meta in properties.items()]
            rows.append({"name": spec.agent_name or spec.qualified_name,
                         "qualified_name": spec.qualified_name, "server": server,
                         "description": spec.description, "active": True,
                         "enabled": True, "status": "active",
                         "input_schema": spec.input_schema,
                         "schema_summary": summary})
    configured = list_servers(layout)["servers"]
    unavailable = [row["name"] for row in configured if row["enabled"] and not row["active"]]
    return {"ok": True, "owner": "jaeger", "tools": rows, "total": len(rows),
            "unavailable_servers": unavailable, "connection_errors": errors}


def configure_server(layout: Any, name: Any, payload: Any) -> dict[str, Any]:
    name = _name(name)
    if not isinstance(payload, dict):
        raise MCPServiceError("server configuration must be an object")
    if payload.get("url"):
        raise MCPServiceError("Jaeger currently supports stdio MCP servers only")
    data = _load(layout)
    existing = next((x for x in data["servers"] if isinstance(x, dict) and x.get("name") == name), {})
    command = str(payload.get("command", existing.get("command", ""))).strip()
    if not command:
        raise MCPServiceError("command is required for a stdio MCP server")
    args = payload.get("args", existing.get("args", []))
    env = payload.get("env", existing.get("env", {}))
    if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
        raise MCPServiceError("args must be a list of strings")
    if not isinstance(env, dict) or not all(isinstance(k, str) for k in env):
        raise MCPServiceError("env must be an object with string keys")
    old_env = existing.get("env") if isinstance(existing.get("env"), dict) else {}
    normalized_env: dict[str, Any] = {}
    for key, value in env.items():
        if value == _MASK:
            if key not in old_env:
                raise MCPServiceError(f"masked value for {key!r} has no existing secret")
            normalized_env[key] = old_env[key]
        elif isinstance(value, str):
            normalized_env[key] = value
        elif _secret_ref(value):
            normalized_env[key] = {"secret_ref": _secret_ref(value)}
        else:
            raise MCPServiceError(f"env value for {key!r} must be a string or secret_ref")
    env = normalized_env
    row = {"name": name, "command": command, "args": args, "env": env,
           "enabled": bool(payload.get("enabled", existing.get("enabled", True)))}
    data["servers"] = [x for x in data["servers"] if not isinstance(x, dict) or x.get("name") != name] + [row]
    _migrate_inline_secrets(layout, data)
    _write(layout, data)
    return {"ok": True, "server": name, "reload_required": True}


def set_server_enabled(layout: Any, name: Any, enabled: bool) -> dict[str, Any]:
    name = _name(name)
    data = _load(layout)
    row = next((x for x in data["servers"] if isinstance(x, dict) and x.get("name") == name), None)
    if row is None:
        raise MCPServiceError(f"unknown MCP server: {name}")
    row["enabled"] = bool(enabled)
    _write(layout, data)
    return {"ok": True, "server": name, "enabled": bool(enabled), "reload_required": True}


def remove_server(layout: Any, name: Any) -> dict[str, Any]:
    name = _name(name)
    data = _load(layout)
    before = len(data["servers"])
    data["servers"] = [x for x in data["servers"] if not isinstance(x, dict) or x.get("name") != name]
    if len(data["servers"]) == before:
        raise MCPServiceError(f"unknown MCP server: {name}")
    _write(layout, data)
    return {"ok": True, "server": name, "removed": True, "reload_required": True}


def reload_tools(layout: Any) -> dict[str, Any]:
    from jaeger_ai.main import _agent_cache, _pipeline
    from jaeger_ai.plugins.mcp import client
    path = _path(layout)
    migrate_inline_secrets(layout)
    if not path.exists():
        _write(layout, _load(layout))
    registry = client.reload_from_config(path, layout=layout)
    specs = registry.list_tools()
    _pipeline["mcp_specs"] = specs
    _pipeline["with_mcp"] = True
    _agent_cache.clear()
    result = list_tools(layout)
    result["reloaded"] = True
    return result
