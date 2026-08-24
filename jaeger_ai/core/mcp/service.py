"""Validated, instance-owned MCP configuration and live tool inventory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SECRET = re.compile(
    r"(authorization|cookie|token|secret|password|api[_-]?key|credential)", re.IGNORECASE)
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


def _credential_name(server: str, value_name: str, *, scope: str = "") -> str:
    # Preserve the existing environment reference format for compatibility.
    raw = f"mcp.{server}.{scope + '.' if scope else ''}{value_name}"
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
    """Move inline environment and HTTP-header secrets to the credential store."""
    from jaeger_agent import credentials

    changed = False
    for server in data.get("servers", []):
        if not isinstance(server, dict):
            continue
        server_name = str(server.get("name") or "server")
        for field, scope in (("env", ""), ("headers", "header")):
            values = server.get(field)
            if not isinstance(values, dict):
                continue
            for key, value in list(values.items()):
                should_secure = field == "headers" or _SECRET.search(str(key))
                if should_secure and isinstance(value, str) and value and value != _MASK:
                    ref = _credential_name(server_name, str(key), scope=scope)
                    credentials.set_credential(layout, ref, value)
                    values[key] = {"secret_ref": ref}
                    changed = True
    return changed


def migrate_inline_secrets(layout: Any) -> bool:
    """Secure legacy config explicitly during boot/reload or mutation."""
    data = _load(layout)
    changed = _migrate_inline_secrets(layout, data)
    if changed:
        _write(layout, data)
    return changed


def _resolve_values(layout: Any, server: dict[str, Any], field: str) -> dict[str, str]:
    """Resolve one config mapping only at the transport boundary."""
    from jaeger_agent import credentials

    values = server.get(field) if isinstance(server.get(field), dict) else {}
    resolved: dict[str, str] = {}
    for key, value in values.items():
        if isinstance(value, str):
            resolved[str(key)] = value
            continue
        ref = _secret_ref(value)
        if ref is None:
            raise MCPServiceError(f"invalid {field} value for {key!r}")
        try:
            resolved[str(key)] = credentials.get_credential(layout, ref)
        except Exception as exc:
            raise MCPServiceError(f"missing MCP credential {ref!r} for {key}") from exc
    return resolved


def resolve_server_env(layout: Any, server: dict[str, Any]) -> dict[str, str]:
    """Resolve environment credential references only for child-process launch."""
    return _resolve_values(layout, server, "env")


def resolve_server_headers(layout: Any, server: dict[str, Any]) -> dict[str, str]:
    """Resolve HTTP header credential references only while opening the connection."""
    return _resolve_values(layout, server, "headers")


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


def _owned_secret_refs(server: dict[str, Any]) -> set[str]:
    name = str(server.get("name") or "")
    prefix = f"mcp.{name}."
    refs: set[str] = set()
    for field in ("env", "headers"):
        values = server.get(field) if isinstance(server.get(field), dict) else {}
        for value in values.values():
            if (ref := _secret_ref(value)) and ref.startswith(prefix):
                refs.add(ref)
    return refs


def _delete_credentials(layout: Any, refs: set[str]) -> None:
    from jaeger_agent import credentials

    for ref in refs:
        credentials.delete_credential(layout, ref)


def _name(value: Any) -> str:
    name = str(value or "").strip()
    if not _NAME.fullmatch(name):
        raise MCPServiceError("server name must use 1-64 letters, numbers, dots, dashes, or underscores")
    return name


def _url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MCPServiceError("HTTP MCP URL must use http:// or https:// and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise MCPServiceError("HTTP MCP URL must not contain embedded credentials")
    if parsed.fragment:
        raise MCPServiceError("HTTP MCP URL must not contain a fragment")
    loopback = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "http" and not loopback:
        raise MCPServiceError("remote HTTP MCP servers must use https://")
    return url


def _mapping(payload: Any, existing: Any, *, field: str) -> dict[str, Any]:
    values = payload if payload is not None else existing
    if values is None:
        values = {}
    if not isinstance(values, dict) or not all(isinstance(key, str) for key in values):
        raise MCPServiceError(f"{field} must be an object with string keys")
    previous = existing if isinstance(existing, dict) else {}
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if field == "headers" and not _HEADER_NAME.fullmatch(key):
            raise MCPServiceError(f"invalid HTTP header name: {key!r}")
        if value == _MASK:
            if key not in previous:
                raise MCPServiceError(f"masked value for {key!r} has no existing secret")
            normalized[key] = previous[key]
        elif isinstance(value, str):
            if "\r" in value or "\n" in value:
                raise MCPServiceError(f"{field} value for {key!r} contains a newline")
            normalized[key] = value
        elif _secret_ref(value):
            normalized[key] = {"secret_ref": _secret_ref(value)}
        else:
            raise MCPServiceError(f"{field} value for {key!r} must be a string or secret_ref")
    return normalized


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
        headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
        masked_env = {str(key): _MASK if _secret_ref(value) or
                      (_SECRET.search(str(key)) and value) else str(value)
                      for key, value in env.items()}
        masked_headers = {str(key): _MASK if _secret_ref(value) or
                          (_SECRET.search(str(key)) and value) else str(value)
                          for key, value in headers.items()}
        transport = "http" if raw.get("url") else "stdio"
        enabled = bool(raw.get("enabled", True))
        rows.append({
            "name": name, "transport": transport, "command": raw.get("command", ""),
            "args": list(raw.get("args") or []),
            "env": masked_env, "url": raw.get("url", ""), "headers": masked_headers,
            "enabled": enabled, "active": bool(active_tools),
            "status": ("disabled" if not enabled else
                       ("error" if name in errors else
                        ("active" if active_tools else "configured"))),
            "error": errors.get(name), "tool_count": len(active_tools),
        })
    return {"ok": True, "owner": "jaeger", "servers": rows,
            "total": len(rows), "toggle_supported": True,
            "reload_required": any(row["enabled"] and not row["active"] for row in rows),
            "runtime_initialized": running}


def list_tools(layout: Any) -> dict[str, Any]:
    # ``running`` (the third element) says whether the MCP registry exists in
    # THIS process at all. Discarding it made an uninitialized runtime
    # indistinguishable from a genuinely broken server: with no registry there
    # are no tools and every configured server computes as not-active, so this
    # returned ok=True, total=0, and listed healthy servers under
    # ``unavailable_servers``. A caller querying from a process that never
    # booted the MCP client — the bridge's own list_tools path does exactly
    # this — was told its working servers were unavailable.
    #
    # ``list_servers`` in this same module already reports the flag as
    # ``runtime_initialized``; this mirrors it so both answers agree, and
    # reserves ``unavailable_servers`` for what it is supposed to mean: the
    # runtime IS up and these enabled servers failed to connect.
    tools, errors, running = _runtime()
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
    # Only claim a server is unavailable when the runtime is actually up to
    # judge it. Otherwise report nothing as unavailable and let
    # ``runtime_initialized`` carry the real state, so a caller can tell
    # "this server is broken" from "I cannot answer that from here".
    unavailable = (
        [row["name"] for row in configured if row["enabled"] and not row["active"]]
        if running else []
    )
    return {"ok": True, "owner": "jaeger", "tools": rows, "total": len(rows),
            "runtime_initialized": running,
            "unavailable_servers": unavailable, "connection_errors": errors}


def configure_server(layout: Any, name: Any, payload: Any) -> dict[str, Any]:
    name = _name(name)
    if not isinstance(payload, dict):
        raise MCPServiceError("server configuration must be an object")
    data = _load(layout)
    existing = next((x for x in data["servers"] if isinstance(x, dict) and x.get("name") == name), {})
    explicit_url = str(payload.get("url") or "").strip() if "url" in payload else ""
    explicit_command = str(payload.get("command") or "").strip() if "command" in payload else ""
    if explicit_url and explicit_command:
        raise MCPServiceError("configure exactly one MCP transport: url or command")
    use_http = bool(explicit_url or (not explicit_command and existing.get("url")))
    enabled = bool(payload.get("enabled", existing.get("enabled", True)))
    if use_http:
        url = _url(explicit_url or existing.get("url"))
        headers = _mapping(payload.get("headers"), existing.get("headers"), field="headers")
        row = {"name": name, "url": url, "headers": headers, "enabled": enabled}
    else:
        command = explicit_command or str(existing.get("command") or "").strip()
        if not command:
            raise MCPServiceError("command is required for a stdio MCP server")
        args = payload.get("args", existing.get("args", []))
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise MCPServiceError("args must be a list of strings")
        env = _mapping(payload.get("env"), existing.get("env"), field="env")
        row = {"name": name, "command": command, "args": args, "env": env,
               "enabled": enabled}
    data["servers"] = [x for x in data["servers"] if not isinstance(x, dict) or x.get("name") != name] + [row]
    _migrate_inline_secrets(layout, data)
    _write(layout, data)
    saved = next(x for x in data["servers"] if isinstance(x, dict) and x.get("name") == name)
    _delete_credentials(layout, _owned_secret_refs(existing) - _owned_secret_refs(saved))
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
    row = next((x for x in data["servers"]
                if isinstance(x, dict) and x.get("name") == name), None)
    if row is None:
        raise MCPServiceError(f"unknown MCP server: {name}")
    before = len(data["servers"])
    data["servers"] = [x for x in data["servers"] if not isinstance(x, dict) or x.get("name") != name]
    assert len(data["servers"]) < before
    _write(layout, data)
    _delete_credentials(layout, _owned_secret_refs(row))
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


def sync_ares_mcp_servers(layout: Any) -> dict[str, Any]:
    """Sync external MCP servers from ARES into Jaeger's instance mcp.json.

    Reads MCP server declarations from ARES profiles / configuration and registers
    or updates them in Jaeger's MCP server inventory.
    """
    from jaeger_ai.core.ares_interop import ares_shared_artifact

    # Routed through ares_interop — see the note in prompt_documents.
    candidates = [
        ares_shared_artifact("profile_config"),
        ares_shared_artifact("mcp_config"),
        ares_shared_artifact("mcp_config_legacy"),
    ]
    imported = 0
    synced_names = []

    for c_path in candidates:
        if not c_path.exists():
            continue
        try:
            if c_path.suffix in (".yaml", ".yml"):
                import yaml
                data = yaml.safe_load(c_path.read_text(encoding="utf-8")) or {}
                servers = data.get("mcp_servers", {})
                if isinstance(servers, dict):
                    for s_name, s_cfg in servers.items():
                        if isinstance(s_cfg, dict) and s_name not in synced_names:
                            configure_server(layout, s_name, s_cfg)
                            imported += 1
                            synced_names.append(s_name)
            elif c_path.suffix == ".json":
                data = json.loads(c_path.read_text(encoding="utf-8")) or {}
                servers = data.get("servers", [])
                if isinstance(servers, list):
                    for s_cfg in servers:
                        if isinstance(s_cfg, dict) and s_cfg.get("name"):
                            s_name = s_cfg["name"]
                            if s_name not in synced_names:
                                configure_server(layout, s_name, s_cfg)
                                imported += 1
                                synced_names.append(s_name)
        except Exception:
            pass

    return {
        "ok": True,
        "synced_count": imported,
        "servers": synced_names,
        "inventory": list_servers(layout),
    }
