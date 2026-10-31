"""Hit counter for the legacy Hermes ``/api/*`` routes (removal stage 2).

Every ``/api/*`` request is counted by group and normalised route, so the
legacy surface can be deleted group by group once a week of real traffic
shows which routes nothing calls. Counting only: no request data beyond
method, path shape and remote kind is kept, and query strings, bodies and
headers are never stored.

Counts live in memory and are flushed (atomically) at most every
``FLUSH_S`` seconds to ``$JAEGER_STATE_DIR/logs/legacy-api-hits.json``
(default ``~/.jaeger/logs``). ``python -m api.legacy_hits`` prints a report.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

FLUSH_S = 60.0
_ID = re.compile(r"^(?:[0-9a-f]{8,}|[0-9a-f-]{32,36}|\d+|[A-Za-z0-9_-]{20,})$", re.I)
_lock = threading.Lock()
_counts: dict[str, dict] = {}
_started: str | None = None
_last_flush = 0.0


def _path() -> Path:
    base = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME") or str(Path.home() / ".jaeger")
    return Path(base).expanduser() / "logs" / "legacy-api-hits.json"


def normalise(path: str) -> str:
    """``/api/session/3f2a.../messages`` -> ``/api/session/:id/messages``."""
    parts = [p for p in path.split("?", 1)[0].split("/") if p]
    return "/" + "/".join(":id" if i > 1 and _ID.match(p) else p for i, p in enumerate(parts))


def group(path: str) -> str:
    parts = [p for p in path.split("?", 1)[0].split("/") if p]
    return parts[1] if len(parts) > 1 else "(root)"


def _load() -> None:
    global _started
    if _started is not None:
        return
    _started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        data = json.loads(_path().read_text())
        _counts.update(data.get("routes") or {})
        _started = data.get("since") or _started
    except Exception:
        pass


def record(method: str, path: str, *, now: float | None = None) -> None:
    """Count one request. Never raises; non-``/api/`` paths are ignored."""
    try:
        if not path.startswith("/api/"):
            return
        now = time.time() if now is None else now
        key = f"{method.upper()} {normalise(path)}"
        with _lock:
            _load()
            row = _counts.setdefault(key, {"group": group(path), "hits": 0, "first": now, "last": now})
            row["hits"] += 1
            row["last"] = now
            due = now - _last_flush >= FLUSH_S
        if due:
            flush(now=now)
    except Exception:
        pass


def flush(*, now: float | None = None) -> None:
    global _last_flush
    try:
        with _lock:
            _load()
            _last_flush = time.time() if now is None else now
            payload = {"since": _started, "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "routes": dict(_counts)}
        target = _path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True))
        os.replace(tmp, target)
    except Exception:
        pass


def snapshot() -> dict:
    with _lock:
        _load()
        groups: dict[str, int] = {}
        for row in _counts.values():
            groups[row["group"]] = groups.get(row["group"], 0) + row["hits"]
        return {"since": _started, "groups": dict(sorted(groups.items(), key=lambda kv: -kv[1])), "routes": dict(_counts)}


def _reset_for_tests() -> None:
    global _started, _last_flush
    with _lock:
        _counts.clear()
        _started = None
        _last_flush = 0.0


if __name__ == "__main__":  # pragma: no cover - operator report
    snap = snapshot()
    print(f"legacy /api hits since {snap['since']}")
    for name, hits in snap["groups"].items():
        print(f"  {hits:7d}  {name}")
