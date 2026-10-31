"""Read-only Machine and Models endpoints for the unified UI.

``GET /v1/machine/logs?source=&lines=&q=&level=`` tails one whitelisted log
file in ``$JAEGER_STATE_DIR/logs`` (default ``~/.jaeger/logs``) with secrets
redacted. ``GET /v1/machine/logs/sources`` lists the sources. ``GET
/v1/usage?days=`` is the unified alias of the legacy usage insights.

There is no write path and no arbitrary file access: ``source`` must be one
of :data:`SOURCES`; nothing else on disk is reachable.
"""
from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs

SOURCES = {
    "gateway": "gateway.log", "webui": "webui.log", "jobs": "jobs.log", "runner": "runner.log",
    "agent": "agent.log", "ollama": "ollama.log", "ollama-bridge": "ollama-bridge.log",
    "mcp": "mcp.log", "a2a": "a2a.log", "app": "JaegerAI.log", "hermes": "hermes.log",
}
MAX_LINES = 2000
MAX_SCAN_BYTES = 4 * 1024 * 1024
_REDACT = [
    # key=value / key: value / "key": "value", with an optional "Bearer " scheme before the secret.
    re.compile(r"(?i)\b(authorization|bearer|x-api-key|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|cookie|set-cookie)\b(\"?\s*[:=]\s*\"?|\s+)(?:bearer\s+|basic\s+)?([^\s,;\"']+)"),
    # Well-known token shapes anywhere in the line.
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|gh[ousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+)\b"),
]
_LEVEL = re.compile(r"\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b")


def _logs_dir() -> Path:
    base = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME") or str(Path.home() / ".jaeger")
    return Path(base).expanduser() / "logs"


def redact(line: str) -> str:
    line = _REDACT[1].sub("[redacted]", line)
    return _REDACT[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)


def level_of(line: str) -> str:
    m = _LEVEL.search(line[:200])
    if not m:
        return "info"
    v = m.group(1).lower()
    return {"warning": "warn", "critical": "error", "fatal": "error"}.get(v, v)


def sources() -> list[dict]:
    d = _logs_dir(); out = []
    for name, file in SOURCES.items():
        p = d / file
        try:
            st = p.stat(); out.append({"id": name, "exists": True, "bytes": st.st_size, "mtime": st.st_mtime})
        except OSError:
            out.append({"id": name, "exists": False, "bytes": 0, "mtime": None})
    return out


def tail(source: str, *, lines: int = 300, q: str = "", level: str = "") -> dict:
    if source not in SOURCES:
        raise KeyError(source)
    lines = max(1, min(int(lines), MAX_LINES))
    p = _logs_dir() / SOURCES[source]
    if not p.is_file() or p.is_symlink():
        return {"source": source, "lines": [], "exists": False, "truncated": False}
    size = p.stat().st_size
    with p.open("rb") as fh:
        start = max(0, size - MAX_SCAN_BYTES)
        fh.seek(start)
        raw = fh.read().decode("utf-8", "replace").splitlines()
    if start:
        raw = raw[1:]
    ql = q.lower().strip(); lv = level.lower().strip()
    rows: deque = deque(maxlen=lines); matched = 0
    for text in raw:
        if ql and ql not in text.lower():
            continue
        lvl = level_of(text)
        if lv and lvl != lv:
            continue
        matched += 1
        rows.append({"text": redact(text[:4000]), "level": lvl})
    return {"source": source, "exists": True, "bytes": size, "mtime": p.stat().st_mtime,
            "lines": list(rows), "truncated": matched > len(rows) or bool(start)}


def handles(p: str) -> bool:
    return p in ("/v1/machine/logs", "/v1/machine/logs/sources", "/v1/usage")


def route(handler, parsed, method: str, read_body, j) -> bool:
    p = parsed.path
    if method != "GET":
        return j(handler, {"error": "method not allowed"}, status=405) or True
    qs = parse_qs(parsed.query or "")
    one = lambda k, d="": (qs.get(k) or [d])[0]
    if p == "/v1/machine/logs/sources":
        return j(handler, {"sources": sources()}) or True
    if p == "/v1/machine/logs":
        try:
            n = int(one("lines", "300"))
        except ValueError:
            n = 300
        try:
            return j(handler, tail(one("source", "gateway"), lines=n, q=one("q"), level=one("level"))) or True
        except KeyError:
            return j(handler, {"error": "unknown log source", "sources": list(SOURCES)}, status=404) or True
    if p == "/v1/usage":
        from api.route_insights import _handle_insights
        return _handle_insights(handler, parsed)
    return False
