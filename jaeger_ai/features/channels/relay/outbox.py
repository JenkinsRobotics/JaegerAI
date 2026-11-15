"""Cross-process outbound spool: any Jaeger process queues, the relay sends.

Files are ``~/.jaeger/channels/outbox/<ts>-<id>.json``; the relay moves each to
``sent/`` or ``failed/`` after one attempt per live channel (no blind retries of
an uncertain send). ``dedupe_key`` drops repeats (e.g. one approval, one cron
occurrence) for 24 h.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .config import state_dir, write_json

KINDS = ("reply", "schedule", "approval", "notification", "test")


def outbox_dir() -> Path:
    path = state_dir() / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _seen_path() -> Path:
    return state_dir() / "outbox_seen.json"


def _seen(key: str) -> bool:
    try:
        data = json.loads(_seen_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    now = time.time()
    data = {k: v for k, v in data.items() if now - float(v) < 86400}
    hit = key in data
    data[key] = now
    write_json(_seen_path(), data)
    return hit


def enqueue(text: str, *, kind: str = "notification", title: str | None = None,
            dedupe_key: str | None = None, channels: list[str] | None = None,
            meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Queue ``text`` for the owner's phone channels. Never raises."""
    try:
        body = (text or "").strip()
        if not body:
            return {"queued": False, "error": "empty"}
        if kind not in KINDS:
            kind = "notification"
        if dedupe_key:
            digest = hashlib.sha256(dedupe_key.encode()).hexdigest()[:24]
            if _seen(digest):
                return {"queued": False, "duplicate": True}
        item = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "title": (title or "").strip() or None,
            "text": body[:12000],
            "channels": channels,
            "meta": meta or {},
            "created_at": time.time(),
        }
        write_json(outbox_dir() / f"{int(time.time() * 1000)}-{item['id']}.json", item)
        return {"queued": True, "id": item["id"]}
    except Exception as exc:  # noqa: BLE001
        return {"queued": False, "error": f"{type(exc).__name__}: {exc}"}


def pending() -> list[Path]:
    return sorted(outbox_dir().glob("*.json"))


def settle(path: Path, outcome: str, detail: dict[str, Any] | None = None) -> None:
    dest = state_dir() / ("sent" if outcome == "sent" else "failed")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data["settled"] = {"outcome": outcome, "at": time.time(), **(detail or {})}
    write_json(dest / path.name, data)
    try:
        path.unlink()
    except OSError:
        pass
    # Keep the settled folders bounded.
    files = sorted(dest.glob("*.json"))
    for old in files[:-500]:
        try:
            old.unlink()
        except OSError:
            pass
