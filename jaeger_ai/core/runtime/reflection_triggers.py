"""Event-driven reflection: salient moments wake Jaeger's heartbeat, not a clock.

Producers append one JSON line per event to ``~/.jaeger/run/reflect/triggers.jsonl``:

* the droid (``features/droid/life.py``): ``person_arrived``, ``owner_returned``
* the gateway push observer: ``job_finished``, ``approval_waiting``

The idle loop asks :func:`due`; a beat consumes everything pending and passes a
compact summary into the heartbeat facts, so the talker can tie a greeting to
something useful, or say nothing. Beats coalesce (at least ``MIN_GAP_S``
apart) except for approvals.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

MIN_GAP_S = 600
STALE_S = 6 * 3600


def _dir() -> Path:
    return Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger") / "run" / "reflect"


def write(event: str, **fields) -> None:
    path = _dir() / "triggers.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps({"event": event, "at": time.time(), **fields}) + "\n")
    except OSError:
        pass


def _cursor() -> dict:
    try:
        return json.loads((_dir() / "cursor.json").read_text())
    except (OSError, ValueError):
        return {}


def pending(now: float | None = None) -> list[dict]:
    now = now or time.time()
    since = float(_cursor().get("consumed_at") or 0)
    try:
        lines = (_dir() / "triggers.jsonl").read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = float(row.get("at") or 0)
        if at > since and now - at < STALE_S:
            rows.append(row)
    return rows


def due(now: float | None = None) -> bool:
    now = now or time.time()
    rows = pending(now)
    if not rows:
        return False
    if any(r.get("event") == "approval_waiting" for r in rows):
        return True
    return now - float(_cursor().get("beat_at") or 0) >= MIN_GAP_S


def consume(now: float | None = None) -> list[dict]:
    """Take every pending trigger and record the beat; old lines are trimmed."""
    now = now or time.time()
    rows = pending(now)
    folder = _dir()
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        (folder / "cursor.json").write_text(json.dumps({"consumed_at": now, "beat_at": now}))
        path = folder / "triggers.jsonl"
        if path.exists() and path.stat().st_size > 256_000:
            keep = [l for l in path.read_text().splitlines()[-500:]]
            path.write_text("\n".join(keep) + "\n")
    except OSError:
        pass
    return rows


def summary(rows: list[dict], now: float | None = None) -> list[dict]:
    """Small, timestamp-free context for the talker (minutes ago, not clock times)."""
    now = now or time.time()
    out = []
    for row in rows[-8:]:
        item = {"event": row.get("event"), "minutes_ago": int((now - float(row.get("at") or now)) / 60)}
        for key in ("away_min", "title", "risk"):
            if row.get(key) is not None:
                item[key] = row[key]
        out.append(item)
    return out
