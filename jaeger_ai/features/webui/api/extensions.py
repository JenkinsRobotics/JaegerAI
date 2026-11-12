"""Opt-in WebUI extension hooks.

This module intentionally provides a small, self-hosted extension surface:
configured same-origin script/style injection plus sandboxed static file serving.
It is disabled by default and never executes or fetches third-party URLs.
"""

import html
import http.client
import json
import math
import logging
import os
import re
import socket
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlsplit
import hashlib
import io
import time
import zipfile
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    build_opener,
)

from api.helpers import _security_headers, j

_log = logging.getLogger(__name__)

# Sane bound on configured URLs — real extensions ship 1-3 files. Higher values
# typically indicate a misconfiguration (one giant unsplit string, or a runaway
# generator script that wrote an env-var template without filtering). Capping
# avoids rendering tens of thousands of <script> tags into every page load.
_MAX_URL_LIST = 32

# Keep extension manifests small and auditable. The manifest is a convenience for
# bundling static assets, not a package manager or dependency lockfile.
_MAX_MANIFEST_BYTES = 64 * 1024



class _ManifestTooLarge(ValueError):
    pass






class ExtensionSidecarProxyError(Exception):
    """Sanitized sidecar proxy error safe to return to the browser."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


EXTENSION_ROUTE_PREFIX = "/extensions/"
_EXTENSION_DIR_ENV = "HERMES_WEBUI_EXTENSION_DIR"
_EXTENSION_MANIFEST_ENV = "HERMES_WEBUI_EXTENSION_MANIFEST"
_SIDECAR_WARNING_SOURCE = "manifest:sidecars"
_DEFAULT_SIDECAR_HEALTH_PATH = "/health"
_LOOPBACK_SIDECAR_HOSTS = {"127.0.0.1", "localhost", "::1"}
_EXTENSION_STATE_FILENAME = "extension-overrides.json"
_MAX_EXTENSION_STATE_BYTES = 32 * 1024
_MAX_DISABLED_EXTENSION_IDS = 512
_MAX_SIDECAR_PROXY_CONSENTS = 512
_EXTENSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EXTENSION_SETTINGS_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_EXTENSION_STATE_WARNING_SOURCE = "extension_state"
_EXTENSION_SETTING_TYPES = {"boolean", "string", "number", "integer", "enum"}

_GALLERY_INSTALL_STATE_FILENAME = "extension-install-manifest.json"
_MAX_INSTALL_MANIFEST_BYTES = 128 * 1024
_MAX_GALLERY_INSTALLED_IDS = 256














_EXTENSION_MIME = {
    "css": "text/css",
    "js": "application/javascript",
    "html": "text/html",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "ico": "image/x-icon",
    "gif": "image/gif",
    "webp": "image/webp",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttf": "font/ttf",
    "otf": "font/otf",
    "wasm": "application/wasm",
}
_TEXT_MIME_TYPES = {"text/css", "application/javascript", "text/html", "image/svg+xml", "text/plain"}


def _default_extension_root() -> Path:
    """WebUI-managed default extension directory under the state dir.

    Used when ``HERMES_WEBUI_EXTENSION_DIR`` is unset so one-click gallery
    install works out of the box on a single-user self-hosted instance with no
    environment setup. It lives alongside sessions/settings in the WebUI-owned
    state dir, which is a different trust domain from "a user-writable directory
    on a shared box" — the loaded code still runs with full session authority,
    so the trust model is unchanged (see docs/EXTENSIONS.md).
    """
    return _extension_state_dir() / "extensions"


def _extension_root() -> Optional[Path]:
    """Return the active extension directory, or None when none is available.

    Resolution order:
    1. ``HERMES_WEBUI_EXTENSION_DIR`` when set — must be an existing directory,
       otherwise None (the admin owns that path; we never auto-create it).
    2. Otherwise the WebUI-managed default (``STATE_DIR/extensions``) when it
       already exists. The first gallery install creates it on demand
       (see ``_writable_extension_root``); until then this stays None and the
       UI reports the same "nothing installed yet" state as before.
    """
    raw = os.getenv(_EXTENSION_DIR_ENV, "").strip()
    if raw:
        root = Path(raw).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return None
        return root
    default_root = _default_extension_root()
    try:
        if default_root.is_dir() and not default_root.is_symlink():
            return default_root.resolve()
    except OSError:
        pass
    try:
        from api.config import REPO_ROOT
        repo_ext = (REPO_ROOT.parents[2] / "extensions").resolve()
        if repo_ext.is_dir():
            return repo_ext
    except Exception:
        pass
    return None


def _writable_extension_root() -> Optional[Path]:
    """Resolve the extension root for writes, bootstrapping the managed default.

    When ``HERMES_WEBUI_EXTENSION_DIR`` is set we use it as-is (the admin owns
    it; it must already exist). When unset we create and return the
    WebUI-managed default so a fresh install can install an extension with zero
    configuration — plug and play.
    """
    raw = os.getenv(_EXTENSION_DIR_ENV, "").strip()
    if raw:
        return _extension_root()
    default_root = _default_extension_root()
    try:
        default_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    try:
        if default_root.is_symlink() or not default_root.is_dir():
            return None
        return default_root.resolve()
    except OSError:
        return None




def _new_diagnostics() -> Dict[str, Any]:
    return {"warnings": []}


def _add_diagnostic_warning(
    diagnostics: Optional[Dict[str, Any]], code: str, source: str
) -> None:
    """Record a sanitized diagnostic warning.

    Warnings intentionally carry only stable codes and coarse sources. They never
    include filesystem paths, raw environment values, or rejected URL strings.
    """
    if diagnostics is None:
        return
    warnings = diagnostics.setdefault("warnings", [])
    if not isinstance(warnings, list):
        return
    warning = {"code": code, "source": source}
    if warning not in warnings:
        warnings.append(warning)


def _valid_extension_id(value: object) -> bool:
    return isinstance(value, str) and bool(_EXTENSION_ID_RE.fullmatch(value.strip()))


def _extension_state_dir() -> Path:
    """Return the WebUI-managed state directory for extension overrides."""
    try:
        from api.config import STATE_DIR

        return Path(STATE_DIR)
    except Exception:
        return Path(os.getenv("HERMES_WEBUI_STATE_DIR", str(Path.home() / ".jaeger" / "hermes" / "webui"))).expanduser()


def _extension_state_file() -> Path:
    return _extension_state_dir() / _EXTENSION_STATE_FILENAME


def _empty_extension_state() -> Dict[str, Any]:
    return {"version": 1, "disabled_extensions": [], "sidecar_proxy_consents": {}}


def _load_extension_state(diagnostics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Load UI-managed extension overrides, failing safe without path leaks."""
    state_file = _extension_state_file()
    try:
        if not state_file.exists() or not state_file.is_file():
            return _empty_extension_state()
        with state_file.open("rb") as fh:
            raw = fh.read(_MAX_EXTENSION_STATE_BYTES + 1)
        if len(raw) > _MAX_EXTENSION_STATE_BYTES:
            _add_diagnostic_warning(
                diagnostics, "extension_state_oversized", _EXTENSION_STATE_WARNING_SOURCE
            )
            return _empty_extension_state()
        parsed = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        _add_diagnostic_warning(
            diagnostics, "extension_state_unreadable", _EXTENSION_STATE_WARNING_SOURCE
        )
        return _empty_extension_state()
    if not isinstance(parsed, dict):
        _add_diagnostic_warning(
            diagnostics, "extension_state_invalid", _EXTENSION_STATE_WARNING_SOURCE
        )
        return _empty_extension_state()
    disabled_raw = parsed.get("disabled_extensions", [])
    if not isinstance(disabled_raw, list):
        _add_diagnostic_warning(
            diagnostics, "extension_state_invalid", _EXTENSION_STATE_WARNING_SOURCE
        )
        return _empty_extension_state()
    disabled: List[str] = []
    seen: Set[str] = set()
    invalid = False
    for value in disabled_raw:
        if not _valid_extension_id(value):
            invalid = True
            continue
        ext_id = str(value).strip()
        if ext_id in seen:
            continue
        seen.add(ext_id)
        disabled.append(ext_id)
        if len(disabled) >= _MAX_DISABLED_EXTENSION_IDS:
            _add_diagnostic_warning(
                diagnostics, "extension_state_truncated", _EXTENSION_STATE_WARNING_SOURCE
            )
            break
    consents_raw = parsed.get("sidecar_proxy_consents", {})
    consents: Dict[str, str] = {}
    consents_invalid = False
    if consents_raw is not None:
        if not isinstance(consents_raw, dict):
            invalid = True
            consents_invalid = True
        else:
            for raw_ext_id, raw_origin in consents_raw.items():
                if not _valid_extension_id(raw_ext_id):
                    invalid = True
                    consents_invalid = True
                    continue
                origin = _normalize_loopback_sidecar_origin(raw_origin)
                if origin is None:
                    invalid = True
                    consents_invalid = True
                    continue
                ext_id = str(raw_ext_id).strip()
                if ext_id in consents:
                    continue
                consents[ext_id] = origin
                if len(consents) >= _MAX_SIDECAR_PROXY_CONSENTS:
                    _add_diagnostic_warning(
                        diagnostics, "extension_state_truncated", _EXTENSION_STATE_WARNING_SOURCE
                    )
                    break
    if consents_invalid:
        consents = {}
    if invalid:
        _add_diagnostic_warning(
            diagnostics, "extension_state_invalid_entries", _EXTENSION_STATE_WARNING_SOURCE
        )
    return {
        "version": 1,
        "disabled_extensions": disabled,
        "sidecar_proxy_consents": consents,
    }




def _fully_unquote_path(path: str) -> str:
    """Decode percent-encoding until stable so encoded dot-segments cannot hide.

    Iterates up to 10 times so even quadruple-encoded inputs like
    ``%2525252e%2525252e`` collapse to literal ``..`` and are rejected by
    the segment-level safety check downstream. URL strings stabilize in
    fewer than 5 iterations in practice; the cap is defensive.
    """
    previous = path
    for _ in range(10):
        current = unquote(previous)
        if current == previous:
            return current
        previous = current
    return previous










def _manifest_path_with_status(root: Path) -> Tuple[Optional[Path], str]:
    raw = os.getenv(_EXTENSION_MANIFEST_ENV, "").strip()
    if not raw:
        return None, "not_configured"
    if raw.startswith(("/", "~")):
        _log.warning("Rejected extension manifest path from %s", _EXTENSION_MANIFEST_ENV)
        return None, "invalid_path"
    rel = _fully_unquote_path(raw)
    if not _is_safe_relative_path(rel):
        _log.warning("Rejected extension manifest path from %s", _EXTENSION_MANIFEST_ENV)
        return None, "invalid_path"
    manifest = (root / rel).resolve()
    try:
        manifest.relative_to(root)
    except ValueError:
        _log.warning("Rejected extension manifest path from %s", _EXTENSION_MANIFEST_ENV)
        return None, "invalid_path"
    return manifest, "configured"






def _manifest_asset_value_with_base(value: object, asset_base: str) -> object:
    """Rewrite a manifest asset value so it remains relative to its manifest file."""
    if not isinstance(value, str):
        return value
    item = value.strip()
    if not item:
        return item
    parsed = urlsplit(item)
    if parsed.scheme or parsed.netloc or item.startswith("//") or item.startswith("/"):
        return item
    base = asset_base.strip("/")
    return f"{base}/{item}" if base else item


def _copy_manifest_entry_with_asset_base(entry: Dict[str, object], asset_base: str) -> Dict[str, object]:
    copied = dict(entry)
    for key in ("scripts", "stylesheets"):
        values = copied.get(key)
        if isinstance(values, list):
            copied[key] = [_manifest_asset_value_with_base(value, asset_base) for value in values]
    return copied


def _manifest_entry_text(entry: Dict[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str):
        return ""
    return value.strip()

def _manifest_entry_storage_owned(entry: Dict[str, object]) -> bool:
    permissions = entry.get("permissions")
    if not isinstance(permissions, dict):
        return False
    storage = permissions.get("storage")
    return isinstance(storage, dict) and storage.get("owned") is True

def _settings_text(value: object, *, max_len: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text[:max_len]

def _normalize_enum_options(options: object) -> Optional[List[Dict[str, str]]]:
    if not isinstance(options, list) or not options:
        return None
    normalized: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for option in options:
        if isinstance(option, str):
            value = option.strip()
            label = value
        elif isinstance(option, dict):
            raw_value = option.get("value")
            if not isinstance(raw_value, str):
                return None
            value = raw_value.strip()
            label = _settings_text(option.get("label")) or value
        else:
            return None
        if not value or value in seen:
            return None
        seen.add(value)
        normalized.append({"value": value, "label": label})
    return normalized

_SETTINGS_DEFAULT_MISSING = object()

def _normalize_settings_default(field_type: str, raw_default: object, options: Optional[List[Dict[str, str]]] = None) -> Tuple[bool, object]:
    if field_type == "boolean":
        if raw_default is _SETTINGS_DEFAULT_MISSING:
            return True, False
        return (True, raw_default) if isinstance(raw_default, bool) else (False, None)
    if field_type == "string":
        if raw_default is _SETTINGS_DEFAULT_MISSING:
            return True, ""
        return (True, raw_default) if isinstance(raw_default, str) else (False, None)
    if field_type == "number":
        if raw_default is _SETTINGS_DEFAULT_MISSING:
            return True, 0
        return (
            (True, raw_default)
            if isinstance(raw_default, (int, float)) and not isinstance(raw_default, bool) and math.isfinite(raw_default)
            else (False, None)
        )
    if field_type == "integer":
        if raw_default is _SETTINGS_DEFAULT_MISSING:
            return True, 0
        return (True, raw_default) if isinstance(raw_default, int) and not isinstance(raw_default, bool) else (False, None)
    if field_type == "enum" and options:
        values = [option["value"] for option in options]
        if raw_default is _SETTINGS_DEFAULT_MISSING:
            return True, values[0]
        return (True, raw_default) if isinstance(raw_default, str) and raw_default in values else (False, None)
    return False, None

def _settings_schema_values(raw_schema: object) -> List[object]:
    if isinstance(raw_schema, list):
        return raw_schema
    if isinstance(raw_schema, dict) and isinstance(raw_schema.get("fields"), list):
        return raw_schema["fields"]
    return []

def _sanitize_settings_schema(entry: Dict[str, object]) -> List[Dict[str, object]]:
    if not _manifest_entry_storage_owned(entry):
        return []
    fields: List[Dict[str, object]] = []
    seen_keys: Set[str] = set()
    for raw_field in _settings_schema_values(entry.get("settings_schema")):
        if not isinstance(raw_field, dict):
            continue
        if raw_field.get("sensitive") is True:
            continue
        key = raw_field.get("key")
        if not isinstance(key, str):
            continue
        key = key.strip()
        if not _EXTENSION_SETTINGS_KEY_RE.fullmatch(key):
            continue
        field_type = raw_field.get("type")
        if not isinstance(field_type, str):
            continue
        field_type = field_type.strip().lower()
        if field_type not in _EXTENSION_SETTING_TYPES:
            continue
        options = _normalize_enum_options(raw_field.get("options")) if field_type == "enum" else None
        if field_type == "enum" and options is None:
            continue
        ok, default = _normalize_settings_default(field_type, raw_field.get("default", _SETTINGS_DEFAULT_MISSING), options)
        if not ok:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        field: Dict[str, object] = {
            "key": key,
            "type": field_type,
            "label": _settings_text(raw_field.get("label")) or key,
            "description": _settings_text(raw_field.get("description"), max_len=300),
            "default": default,
        }
        if options is not None:
            field["options"] = options
        fields.append(field)
    return fields


def _normalize_loopback_sidecar_origin(value: object) -> Optional[str]:
    """Return a canonical loopback origin or None when unsafe.

    Only browser-addressable loopback HTTP(S) origins are accepted. The returned
    value is rebuilt from parsed components so rejected raw input is never echoed
    into diagnostics.
    """
    if not isinstance(value, str):
        return None
    origin = value.strip()
    if not origin or any(
        ch in origin for ch in ("\x00", "\r", "\n", '"', "'", "<", ">", "\\")
    ):
        return None
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_SIDECAR_HOSTS:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    display_host = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme}://{display_host}{':' + str(port) if port is not None else ''}"


def _normalize_sidecar_health_path(value: object) -> Optional[str]:
    """Return a safe sidecar health path, or None when unsafe.

    Health paths are same-origin paths relative to the validated sidecar origin.
    Queries are rejected even though they are not cross-origin: health checks are
    diagnostics, and query strings often accidentally carry tokens.
    """
    if not isinstance(value, str):
        return None
    path = value.strip()
    if not path or not path.startswith("/") or path.startswith("//"):
        return None
    if any(ch in path for ch in ("\x00", "\r", "\n", '"', "'", "<", ">", "\\")):
        return None
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return None
    decoded_path = _fully_unquote_path(parsed.path)
    if any(ch in decoded_path for ch in ("\x00", "\r", "\n", '"', "'", "<", ">", "\\")):
        return None
    # #4612 (Codex gate): the raw query/fragment ban above runs BEFORE percent-
    # decoding, so an encoded delimiter (e.g. "/health%3Ftoken=abc" -> "?token=abc"
    # or "/health%23frag" -> "#frag") would survive into the probed URL despite the
    # documented query/fragment ban. Re-reject "?" and "#" on the decoded path.
    if any(ch in decoded_path for ch in ("?", "#")):
        return None
    if any(ch.isspace() for ch in decoded_path):
        return None
    if not decoded_path.startswith("/") or decoded_path.startswith("//"):
        return None
    segments = decoded_path.split("/")[1:]
    if not segments:
        return None
    for segment in segments:
        if not segment or segment in (".", ".."):
            return None
    return decoded_path


def _is_valid_sidecar_proxy_path(decoded_path: str) -> bool:
    if any(ch in decoded_path for ch in ("?", "#")):
        return False
    if any(ch.isspace() for ch in decoded_path):
        return False
    if not decoded_path.startswith("/") or decoded_path.startswith("//"):
        return False
    segments = decoded_path.split("/")[1:]
    if not segments:
        return False
    for segment in segments:
        if not segment or segment in (".", ".."):
            return False
    return True


def _sidecar_from_manifest_entry(
    entry: Dict[str, object], diagnostics: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, str]]:
    raw = entry.get("sidecar")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _add_diagnostic_warning(diagnostics, "sidecar_invalid", _SIDECAR_WARNING_SOURCE)
        return None
    if raw.get("type") != "loopback":
        _add_diagnostic_warning(
            diagnostics, "sidecar_type_unsupported", _SIDECAR_WARNING_SOURCE
        )
        return None
    origin = _normalize_loopback_sidecar_origin(raw.get("origin"))
    if origin is None:
        _add_diagnostic_warning(
            diagnostics, "sidecar_origin_rejected", _SIDECAR_WARNING_SOURCE
        )
        return None
    if "health_path" in raw:
        health_path = _normalize_sidecar_health_path(raw.get("health_path"))
        if health_path is None:
            # Missing health_path defaults to /health; an explicitly invalid path
            # rejects the sidecar so the browser does not probe a declaration the
            # administrator needs to fix.
            _add_diagnostic_warning(
                diagnostics, "sidecar_health_path_rejected", _SIDECAR_WARNING_SOURCE
            )
            return None
    else:
        health_path = _DEFAULT_SIDECAR_HEALTH_PATH
    # proxy_auth negotiation (token-v1). Absent = explicit legacy (unauthenticated
    # proxy→sidecar, unchanged behavior for any pre-existing declaration). token-v1
    # = core mints+injects a per-extension token and the sidecar validates it.
    # Any unknown value fails closed (reject the sidecar) so a typo can never
    # silently downgrade to unauthenticated.
    raw_proxy_auth = raw.get("proxy_auth")
    if raw_proxy_auth is None:
        proxy_auth = "legacy"
    elif raw_proxy_auth in ("legacy", "token-v1"):
        proxy_auth = str(raw_proxy_auth)
    else:
        _add_diagnostic_warning(
            diagnostics, "sidecar_proxy_auth_unsupported", _SIDECAR_WARNING_SOURCE
        )
        return None
    sidecar_id = _manifest_entry_text(entry, "id")
    name = _manifest_entry_text(entry, "name")
    return {
        "id": sidecar_id,
        "name": name,
        "type": "loopback",
        "origin": origin,
        "health_path": health_path,
        "health_url": f"{origin}{health_path}",
        "proxy_auth": proxy_auth,
    }


def _manifest_extension_entries(manifest: object) -> List[Tuple[str, int, Dict[str, object]]]:
    extension_entries: object = []
    if isinstance(manifest, dict):
        extension_entries = manifest.get("extensions", [])
    elif isinstance(manifest, list):
        extension_entries = manifest
    entries: List[Tuple[str, int, Dict[str, object]]] = []
    if isinstance(extension_entries, list):
        for index, extension in enumerate(extension_entries):
            if isinstance(extension, dict):
                entries.append((f"manifest.extensions[{index}]", index, extension))
    return entries






def _read_manifest_text(manifest_file: Path) -> str:
    with manifest_file.open("rb") as fh:
        data = fh.read(_MAX_MANIFEST_BYTES + 1)
    if len(data) > _MAX_MANIFEST_BYTES:
        raise _ManifestTooLarge("manifest too large")
    return data.decode("utf-8")


def _empty_manifest_status(path_status: str) -> Dict[str, Any]:
    return {
        "configured": path_status != "not_configured",
        "loaded": False,
        "status": path_status,
        "_asset_base": "",
        "entry_count": 0,
        "script_count": 0,
        "stylesheet_count": 0,
        "sidecar_count": 0,
    }


def _manifest_asset_base(root: Path, manifest_file: Path) -> str:
    try:
        rel_parent = manifest_file.parent.relative_to(root).as_posix()
    except ValueError:
        return ""
    return "" if rel_parent == "." else rel_parent


def _gallery_installed_runtime_manifest(
    root: Path, diagnostics: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, object]]:
    install_manifest = _load_install_manifest()
    installed = install_manifest.get("installed", {})
    candidate_ids = set()
    if isinstance(installed, dict):
        candidate_ids.update(ext_id for ext_id in installed if _valid_extension_id(ext_id))
    try:
        if root and root.is_dir():
            for child in root.iterdir():
                if child.is_dir() and _valid_extension_id(child.name) and (child / "manifest.json").is_file():
                    candidate_ids.add(child.name)
    except OSError:
        pass
    entries: List[Dict[str, object]] = []
    for ext_id in sorted(candidate_ids):
        if not _valid_extension_id(ext_id):
            continue
        manifest_file = root / ext_id / "manifest.json"
        try:
            if not manifest_file.exists() or not manifest_file.is_file():
                _add_diagnostic_warning(diagnostics, "gallery_manifest_missing", "gallery")
                continue
            manifest = json.loads(_read_manifest_text(manifest_file))
        except _ManifestTooLarge:
            _add_diagnostic_warning(diagnostics, "gallery_manifest_oversized", "gallery")
            continue
        except json.JSONDecodeError:
            _add_diagnostic_warning(diagnostics, "gallery_manifest_malformed", "gallery")
            continue
        except RecursionError:
            _add_diagnostic_warning(diagnostics, "gallery_manifest_too_deeply_nested", "gallery")
            continue
        except (OSError, UnicodeDecodeError):
            _add_diagnostic_warning(diagnostics, "gallery_manifest_unreadable", "gallery")
            continue
        asset_base = ext_id
        if isinstance(manifest, dict):
            top_entry: Dict[str, object] = {"id": ext_id}
            for key in (
                "name", "enabled", "scripts", "stylesheets", "sidecar", "permissions",
                "settings_schema", "tab", "tools", "category", "description", "version",
                "homepage", "author", "capabilities"
            ):
                if key in manifest:
                    top_entry[key] = manifest[key]
            if any(
                key in top_entry
                for key in ("scripts", "stylesheets", "sidecar", "permissions", "settings_schema")
            ):
                entries.append(_copy_manifest_entry_with_asset_base(top_entry, asset_base))
        for _source, _index, entry in _manifest_extension_entries(manifest):
            copied = _copy_manifest_entry_with_asset_base(entry, asset_base)
            if not _valid_extension_id(copied.get("id")):
                copied["id"] = ext_id
            entries.append(copied)
    if not entries:
        return None
    return {"extensions": entries}


def _load_manifest_with_status(
    root: Path, diagnostics: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[object], Dict[str, Any]]:
    """Load the configured manifest once, returning sanitized status/warnings."""
    manifest_file, path_status = _manifest_path_with_status(root)
    manifest_status = _empty_manifest_status(path_status)
    if manifest_file is None:
        if path_status == "invalid_path":
            _add_diagnostic_warning(diagnostics, "manifest_invalid_path", "manifest")
        elif path_status == "not_configured":
            manifest = _gallery_installed_runtime_manifest(root, diagnostics)
            if manifest is not None:
                manifest_status.update(
                    {
                        "loaded": True,
                        "status": "gallery_installed",
                        "_asset_base": "",
                    }
                )
                return manifest, manifest_status
        return None, manifest_status
    try:
        if not manifest_file.exists() or not manifest_file.is_file():
            _log.warning("Configured extension manifest was not found")
            manifest_status["status"] = "missing"
            _add_diagnostic_warning(diagnostics, "manifest_missing", "manifest")
            return None, manifest_status
        manifest = json.loads(_read_manifest_text(manifest_file))
        manifest_status.update(
            {
                "loaded": True,
                "status": "loaded",
                "_asset_base": _manifest_asset_base(root, manifest_file),
            }
        )
        return manifest, manifest_status
    except _ManifestTooLarge:
        _log.warning("Configured extension manifest exceeds %d bytes", _MAX_MANIFEST_BYTES)
        manifest_status["status"] = "oversized"
        _add_diagnostic_warning(diagnostics, "manifest_oversized", "manifest")
    except json.JSONDecodeError:
        _log.warning("Configured extension manifest is not valid JSON")
        manifest_status["status"] = "malformed"
        _add_diagnostic_warning(diagnostics, "manifest_malformed", "manifest")
    except RecursionError:
        # A <=64KB but deeply-nested manifest makes json.loads exceed the
        # interpreter recursion limit. Without this, the RecursionError escapes
        # into the app-shell route and every page load 503s. Fail safe.
        _log.warning("Configured extension manifest is too deeply nested")
        manifest_status["status"] = "too_deeply_nested"
        _add_diagnostic_warning(diagnostics, "manifest_too_deeply_nested", "manifest")
    except (OSError, UnicodeDecodeError):
        _log.warning("Configured extension manifest could not be read")
        manifest_status["status"] = "unreadable"
        _add_diagnostic_warning(diagnostics, "manifest_unreadable", "manifest")
    return None, manifest_status


def _manifest_extension_state(
    manifest: object,
    disabled_ids: Set[str],
    diagnostics: Optional[Dict[str, Any]] = None,
    consent_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Return sanitized per-extension state for manifest extension entries."""
    extension_entries: List[Dict[str, Any]] = []
    known_ids: Set[str] = set()
    manifest_disabled_ids: Set[str] = set()
    seen_ids: Set[str] = set()
    invalid_seen = False
    duplicate_seen = False
    for _source, _index, entry in _manifest_extension_entries(manifest):
        raw_id = _manifest_entry_text(entry, "id")
        if not _valid_extension_id(raw_id):
            invalid_seen = True
            continue
        ext_id = raw_id.strip()
        if ext_id in seen_ids:
            duplicate_seen = True
            continue
        seen_ids.add(ext_id)
        known_ids.add(ext_id)
        name = _manifest_entry_text(entry, "name")
        manifest_enabled = entry.get("enabled", True) is not False
        user_disabled = ext_id in disabled_ids
        can_toggle = manifest_enabled
        effective_enabled = manifest_enabled and not user_disabled
        if not manifest_enabled:
            manifest_disabled_ids.add(ext_id)
        settings_schema = _sanitize_settings_schema(entry)
        extension_entries.append(
            {
                "id": ext_id,
                "name": name or ext_id,
                "manifest_enabled": manifest_enabled,
                "user_enabled": (not user_disabled) if can_toggle else False,
                "user_disabled": user_disabled,
                "effective_enabled": effective_enabled,
                "can_toggle": can_toggle,
                "reload_required": True,
                "storage_owned": _manifest_entry_storage_owned(entry),
                "settings_schema": settings_schema,
                "status": (
                    "manifest_disabled"
                    if not manifest_enabled
                    else ("user_disabled" if user_disabled else "enabled")
                ),
            }
        )
    if invalid_seen:
        _add_diagnostic_warning(diagnostics, "manifest_extension_id_invalid", "manifest:extensions")
    if duplicate_seen:
        _add_diagnostic_warning(diagnostics, "manifest_extension_id_duplicate", "manifest:extensions")
    stale_ids = sorted((disabled_ids | (consent_ids or set())) - known_ids)
    if stale_ids:
        _add_diagnostic_warning(diagnostics, "extension_state_unknown_ids", _EXTENSION_STATE_WARNING_SOURCE)
    return {
        "extensions": extension_entries,
        "known_ids": known_ids,
        "manifest_disabled_ids": manifest_disabled_ids,
    }


def _extension_sidecar_proxy_path(extension_id: str) -> str:
    return f"/api/extensions/{extension_id}/sidecar/"


def _sidecar_proxy_public_status(
    extension_id: str,
    origin: str,
    approved_origin: Optional[str],
    *,
    available: bool,
    proxy_auth: str = "legacy",
) -> Dict[str, Any]:
    consented = bool(available and approved_origin == origin)
    origin_changed = bool(available and approved_origin and approved_origin != origin)
    payload: Dict[str, Any] = {
        "available": available,
        "consented": consented,
        "consent_required": bool(available and not consented),
        "path": _extension_sidecar_proxy_path(extension_id),
        "origin_changed": origin_changed,
    }
    # proxy_auth / posture are token-v1-only fields. Legacy sidecars keep the
    # original payload shape byte-for-byte (the public status contract tests pin
    # it), so a token-v1 negotiation field never leaks onto a legacy record.
    # (Frank #6331 blocker 2 — fields were previously emitted on every record and
    # broke the legacy exact-shape contract on shard 4.)
    if proxy_auth == "token-v1":
        # token-v1 posture (§9.1). "protected" = WebUI auth ON (the only posture
        # in which token-v1 proxying is permitted; auth-off is now fail-closed at
        # both consent and resolution, so "local_unprotected" signals the panel
        # to tell the operator to enable authentication before the proxy will work).
        posture = None
        if available:
            try:
                from api.auth import is_auth_enabled
                posture = "protected" if is_auth_enabled() else "local_unprotected"
            except Exception:
                posture = None
        payload["proxy_auth"] = proxy_auth
        payload["posture"] = posture
    return payload


def _extension_sidecar_records(
    manifest: object,
    disabled_ids: Optional[Set[str]] = None,
    state: Optional[Dict[str, Any]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    disabled_ids = disabled_ids or set()
    consent_map = {}
    if isinstance(state, dict) and isinstance(state.get("sidecar_proxy_consents"), dict):
        consent_map = state["sidecar_proxy_consents"]
    id_counts: Dict[str, int] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for _source, _index, entry in _manifest_extension_entries(manifest):
        raw_id = _manifest_entry_text(entry, "id")
        if not _valid_extension_id(raw_id):
            continue
        ext_id = raw_id.strip()
        id_counts[ext_id] = id_counts.get(ext_id, 0) + 1
        if ext_id in by_id:
            continue
        manifest_enabled = entry.get("enabled", True) is not False
        user_disabled = ext_id in disabled_ids
        effective_enabled = manifest_enabled and not user_disabled
        sidecar = _sidecar_from_manifest_entry(entry, diagnostics) if effective_enabled else None
        approved_origin = consent_map.get(ext_id) if isinstance(consent_map.get(ext_id), str) else None
        by_id[ext_id] = {
            "id": ext_id,
            "name": _manifest_entry_text(entry, "name"),
            "manifest_enabled": manifest_enabled,
            "user_disabled": user_disabled,
            "effective_enabled": effective_enabled,
            "sidecar": sidecar,
            "approved_origin": approved_origin,
        }
    records: List[Dict[str, Any]] = []
    for ext_id, item in by_id.items():
        sidecar = item.get("sidecar")
        if sidecar is None:
            continue
        available = bool(item["effective_enabled"] and id_counts.get(ext_id, 0) == 1)
        proxy = _sidecar_proxy_public_status(
            ext_id,
            sidecar["origin"],
            item.get("approved_origin"),
            available=available,
            proxy_auth=sidecar.get("proxy_auth", "legacy"),
        )
        item["duplicate_id"] = id_counts.get(ext_id, 0) > 1
        item["proxy"] = proxy
        if len(records) < _MAX_URL_LIST:
            # Build the PUBLIC sidecar record explicitly. The internal `sidecar`
            # dict carries a top-level `proxy_auth` for the consent/resolution
            # logic, but the public status contract only exposes proxy_auth (and
            # posture) INSIDE `proxy`, and only for token-v1 records — legacy
            # sidecars keep their original public shape byte-for-byte. Spreading
            # `**sidecar` leaked a top-level `proxy_auth: legacy` and broke the
            # exact-shape contract tests (Frank #6331 blocker 2).
            public_record = {k: v for k, v in sidecar.items() if k != "proxy_auth"}
            public_record["proxy"] = proxy
            records.append(public_record)
        else:
            _add_diagnostic_warning(diagnostics, "sidecar_list_truncated", _SIDECAR_WARNING_SOURCE)
            break
    return records, by_id


def _normalize_sidecar_proxy_path(value: object) -> Optional[str]:
    if value is None:
        return "/"
    raw = str(value)
    if raw == "":
        return "/"
    if raw.startswith("/"):
        return None
    candidate = f"/{raw}"
    if not _is_valid_sidecar_proxy_path(_fully_unquote_path(candidate)):
        return None
    return candidate
















def resolve_extension_sidecar_proxy_target(
    extension_id: object,
    proxy_path: object,
    query: str = "",
) -> Dict[str, Any]:
    """Resolve the current approved sidecar proxy target for an extension."""
    if not _valid_extension_id(extension_id):
        raise ExtensionSidecarProxyError("Invalid extension id", status=400)
    normalized_path = _normalize_sidecar_proxy_path(proxy_path)
    if normalized_path is None:
        raise ExtensionSidecarProxyError("Invalid sidecar proxy path", status=400)
    ext_id = str(extension_id).strip()
    root = _extension_root()
    if root is None:
        raise ExtensionSidecarProxyError("Extensions are not configured", status=404)
    diagnostics = _new_diagnostics()
    state = _load_extension_state(diagnostics)
    disabled_ids = set(state.get("disabled_extensions") or [])
    manifest, manifest_status = _load_manifest_with_status(root, diagnostics)
    if manifest is None or not manifest_status.get("loaded", False):
        raise ExtensionSidecarProxyError("Extension manifest is not loaded", status=409)
    consent_ids = set((state.get("sidecar_proxy_consents") or {}).keys())
    extension_state = _manifest_extension_state(
        manifest,
        disabled_ids,
        diagnostics,
        consent_ids=consent_ids,
    )
    if ext_id not in extension_state["known_ids"]:
        raise ExtensionSidecarProxyError("Extension not found", status=404)
    _sidecars, by_id = _extension_sidecar_records(
        manifest,
        disabled_ids=disabled_ids,
        state=state,
        diagnostics=diagnostics,
    )
    item = by_id.get(ext_id) or {}
    sidecar = item.get("sidecar")
    proxy = item.get("proxy") or {}
    if sidecar is None or proxy.get("available") is not True:
        raise ExtensionSidecarProxyError("Extension sidecar proxy is unavailable", status=409)
    if proxy.get("consented") is not True:
        raise ExtensionSidecarProxyError("Extension sidecar proxy consent required", status=403)
    upstream_url = f"{sidecar['origin']}{normalized_path}"
    if query:
        upstream_url = f"{upstream_url}?{query}"

    # token-v1 auth (§9.1/§9.2). Legacy sidecars proxy unchanged; token-v1
    # sidecars get a per-extension secret injected, and only proxy when the
    # trust posture is sound.
    proxy_auth = sidecar.get("proxy_auth", "legacy")
    inject_token: Optional[str] = None
    if proxy_auth == "token-v1":
        from api.auth import is_auth_enabled
        from api import extension_sidecar_auth as _sc_auth

        # token-v1 REQUIRES configured WebUI authentication — fail closed
        # regardless of the upstream origin (loopback included). The consent
        # endpoint and this resolution path are both unauthenticated when auth is
        # off, so a caller that can reach the WebUI listener could otherwise drive
        # a token-bearing proxy to the sidecar (a forwarding oracle). Loopback is
        # NOT a sufficient guard: another local UID can reach the listener without
        # ever reading the 0600 token file. (Frank #6331 blocker 1 — this
        # mirrors the consent-time check so a pre-existing consent granted while
        # auth was enabled cannot be exercised after auth is turned off.)
        if not is_auth_enabled():
            raise ExtensionSidecarProxyError(
                "Sidecar token-v1 proxy requires WebUI authentication; "
                "set a password in Settings.",
                status=403,
            )
        token = _sc_auth.current_token(ext_id) or _sc_auth.ensure_token(ext_id)
        if not token:
            # Token could not be persisted+read → fail closed rather than proxy
            # unauthenticated (never inject an ephemeral secret).
            raise ExtensionSidecarProxyError(
                "Sidecar proxy auth token is unavailable", status=503
            )
        inject_token = token
    return {
        "extension_id": ext_id,
        "origin": sidecar["origin"],
        "proxy_path": proxy["path"],
        "upstream_url": upstream_url,
        "proxy_auth": proxy_auth,
        "auth_token": inject_token,
    }


def _install_manifest_file() -> Path:
    return _extension_state_dir() / _GALLERY_INSTALL_STATE_FILENAME


def _empty_install_manifest() -> Dict[str, Any]:
    return {"version": 1, "installed": {}}


def _load_install_manifest() -> Dict[str, Any]:
    """Load gallery install manifest, failing safe on any error."""
    mfile = _install_manifest_file()
    try:
        if not mfile.exists() or not mfile.is_file():
            return _empty_install_manifest()
        with mfile.open("rb") as fh:
            raw = fh.read(_MAX_INSTALL_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_INSTALL_MANIFEST_BYTES:
            return _empty_install_manifest()
        parsed = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return _empty_install_manifest()
    if not isinstance(parsed, dict) or not isinstance(parsed.get("installed"), dict):
        return _empty_install_manifest()
    installed: Dict[str, Any] = {}
    for ext_id, entry in parsed["installed"].items():
        if not _valid_extension_id(ext_id):
            continue
        if not isinstance(entry, dict):
            continue
        files = entry.get("files", [])
        if not isinstance(files, list):
            continue
        installed[ext_id] = {
            "version": str(entry.get("version", "unknown")),
            "files": [f for f in files if isinstance(f, str)],
            "installed_at": str(entry.get("installed_at", "")),
        }
        if len(installed) >= _MAX_GALLERY_INSTALLED_IDS:
            break
    return {"version": 1, "installed": installed}












def _is_safe_relative_path(rel: str) -> bool:
    if not rel or "\x00" in rel or "\\" in rel:
        return False
    for segment in rel.split("/"):
        if not segment or segment in (".", "..") or segment.startswith("."):
            return False
    return True


def _not_found(handler) -> bool:
    j(handler, {"error": "not found"}, status=404)
    return True


def serve_extension_static(handler, parsed) -> bool:
    """Serve a file from the configured extension directory.

    The function always returns True for /extensions/* requests: either a file
    response or a 404. It never reveals why a request failed, which avoids
    leaking local paths or extension configuration details.
    """
    root = _extension_root()
    if root is None:
        return _not_found(handler)

    rel = unquote(parsed.path[len(EXTENSION_ROUTE_PREFIX) :])
    if not _is_safe_relative_path(rel):
        return _not_found(handler)

    static_file = (root / rel).resolve()
    try:
        static_file.relative_to(root)
    except ValueError:
        return _not_found(handler)

    if not static_file.exists() or not static_file.is_file():
        return _not_found(handler)

    ct = _EXTENSION_MIME.get(static_file.suffix.lower().lstrip("."), "text/plain")
    ct_header = "{}; charset=utf-8".format(ct) if ct in _TEXT_MIME_TYPES else ct
    try:
        raw = static_file.read_bytes()
    except OSError:
        return _not_found(handler)

    handler.send_response(200)
    handler.send_header("Content-Type", ct_header)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(raw)))
    _security_headers(handler)
    handler.end_headers()
    handler.wfile.write(raw)
    return True
