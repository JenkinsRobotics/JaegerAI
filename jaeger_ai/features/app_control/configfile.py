"""Config file formats, dotted-path edits, allow-lists and secret redaction."""
from __future__ import annotations

import copy
import json
import plistlib
import re
import tomllib
from pathlib import Path
from typing import Any

REDACTED = "«redacted»"
_SECRET_KEY = re.compile(r"(token|secret|passw|api[_-]?key|authorization|bearer|cookie|credential|private|session[_-]?key)", re.I)
_SECRET_CONTAINERS = {"headers", "http_headers", "env", "environment"}
_SECRET_VALUE = re.compile(r"^(bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{10,}|xox[abpr]-\S+|AIza[0-9A-Za-z_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.)", re.I)


class ConfigError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def redact(value: Any, key: str = "", inside_secret: bool = False) -> Any:
    """Copy of ``value`` with secret-looking keys and values replaced."""
    if isinstance(value, dict):
        hide = inside_secret or key.lower() in _SECRET_CONTAINERS
        return {k: redact(v, str(k), hide or bool(_SECRET_KEY.search(str(k)))) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key, inside_secret) for v in value]
    if isinstance(value, str):
        if inside_secret or _SECRET_VALUE.search(value.strip()) or re.search(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}", value):
            return REDACTED
        return value
    if inside_secret and value is not None and not isinstance(value, bool):
        return REDACTED
    return value


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas outside strings."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i); i = n if j < 0 else j; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        out.append(c); i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def has_comments(text: str) -> bool:
    return strip_jsonc(text) != re.sub(r",(\s*[}\]])", r"\1", text)


def parse(fmt: str, raw: bytes) -> Any:
    try:
        if fmt == "json":
            return json.loads(raw.decode("utf-8") or "{}")
        if fmt == "jsonc":
            return json.loads(strip_jsonc(raw.decode("utf-8")) or "{}")
        if fmt == "toml":
            return tomllib.loads(raw.decode("utf-8"))
        if fmt == "plist":
            return plistlib.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"{fmt} parse failed: {type(exc).__name__}", 422) from exc
    raise ConfigError(f"unsupported format {fmt}")


def dump(fmt: str, data: Any, original: bytes = b"") -> bytes:
    if fmt == "json":
        return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    if fmt == "jsonc":
        if has_comments(original.decode("utf-8", "replace")):
            raise ConfigError("file has comments; Jaeger will not rewrite it (comments would be lost) - edit by hand", 409)
        return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    if fmt == "toml":
        try:
            import tomli_w
        except ImportError as exc:
            raise ConfigError("TOML writer (tomli-w) not installed", 501) from exc
        return tomli_w.dumps(data).encode()
    if fmt == "plist":
        return plistlib.dumps(data)
    raise ConfigError(f"unsupported format {fmt}")


def split_path(path: str) -> list[str]:
    parts = [p for p in str(path).split(".")]
    if not path or any(p == "" for p in parts) or len(parts) > 8:
        raise ConfigError("invalid key path")
    return parts


def allowed(path: str, allow: tuple[str, ...]) -> bool:
    for pat in allow:
        if pat.endswith(".*"):
            pre = pat[:-2]
            if path.startswith(pre + ".") and len(path) > len(pre) + 1:
                return True
        elif path == pat:
            return True
    return False


def get_path(data: Any, path: str) -> Any:
    cur = data
    for p in split_path(path):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def apply_ops(data: Any, ops: list[dict], allow: tuple[str, ...]) -> Any:
    if not isinstance(data, dict):
        raise ConfigError("config root is not an object", 422)
    new = copy.deepcopy(data)
    if not ops:
        raise ConfigError("no changes")
    for op in ops:
        kind, path = op.get("op"), str(op.get("path") or "")
        if not allowed(path, allow):
            raise ConfigError(f"key {path!r} is not on this app's editable allow-list", 403)
        parts = split_path(path)
        cur = new
        for p in parts[:-1]:
            nxt = cur.get(p)
            if nxt is None and kind == "set":
                nxt = cur[p] = {}
            if not isinstance(nxt, dict):
                if kind == "delete":
                    break
                raise ConfigError(f"{p!r} is not an object", 422)
            cur = nxt
        else:
            if kind == "set":
                if "value" not in op:
                    raise ConfigError("set needs a value")
                cur[parts[-1]] = op["value"]
            elif kind == "delete":
                cur.pop(parts[-1], None)
            else:
                raise ConfigError(f"unknown op {kind!r}")
    return new


def diff(old: Any, new: Any, prefix: str = "") -> list[dict]:
    """Redacted key-level diff."""
    rows: list[dict] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new), key=str):
            p = f"{prefix}.{k}" if prefix else str(k)
            if k not in old:
                rows.append({"path": p, "change": "added", "after": redact(new[k], str(k))})
            elif k not in new:
                rows.append({"path": p, "change": "removed", "before": redact(old[k], str(k))})
            elif old[k] != new[k]:
                rows.extend(diff(old[k], new[k], p))
        return rows
    key = prefix.rsplit(".", 1)[-1]
    return [{"path": prefix, "change": "changed", "before": redact(old, key), "after": redact(new, key)}]


def read_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""
