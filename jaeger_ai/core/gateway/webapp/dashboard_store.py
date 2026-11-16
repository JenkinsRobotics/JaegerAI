"""Workspace dashboard layout (unified UI, 2026-10-30).

Minimal WebUI-owned store for the /workspace widget layout: GET/PUT /v1/dashboard.
The document is the UI's DashboardDoc ({"v": 1, "hosts": {...}}); it is validated
for shape and size only and written atomically to <state>/dashboard.json. It holds
layout and widget parameters, never credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

MAX_BYTES = 256 * 1024
HOSTS = ("page", "float", "overlay", "menubar")


def _path() -> Path:
    root = os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_STATE_DIR") or str(Path.home() / ".jaeger")
    return Path(root) / "dashboard.json"


def empty() -> dict:
    return {"v": 1, "hosts": {h: [] for h in HOSTS}}


def validate(doc: object) -> dict:
    if not isinstance(doc, dict) or doc.get("v") != 1 or not isinstance(doc.get("hosts"), dict):
        raise ValueError("dashboard must be {v: 1, hosts: {...}}")
    hosts = {}
    for name in HOSTS:
        items = doc["hosts"].get(name, [])
        if not isinstance(items, list) or len(items) > 64:
            raise ValueError(f"hosts.{name} must be a list of at most 64 items")
        clean = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("i"), str) or not item["i"] or len(item["i"]) > 120:
                raise ValueError("each item needs a widget id 'i'")
            geo = {k: item.get(k) for k in ("x", "y", "w", "h")}
            if not all(isinstance(v, int) and 0 <= v <= 1000 for v in geo.values()):
                raise ValueError("x, y, w, h must be small non-negative integers")
            entry = {"i": item["i"], **geo}
            if isinstance(item.get("params"), dict):
                entry["params"] = item["params"]
            clean.append(entry)
        hosts[name] = clean
    out = {"v": 1, "hosts": hosts}
    if len(json.dumps(out)) > MAX_BYTES:
        raise ValueError("dashboard too large")
    return out


def read() -> dict:
    try:
        return validate(json.loads(_path().read_text("utf-8")))
    except (OSError, ValueError, json.JSONDecodeError):
        return empty()


def write(doc: object) -> dict:
    clean = validate(doc)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clean, indent=2), "utf-8")
    os.replace(tmp, path)
    return clean
