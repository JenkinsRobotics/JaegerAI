"""Log retention for a Jaeger instance.

Two policies, both pulled from config.retention:

  1. Daily rotation. `audit.log` and `latency.jsonl` get rolled into
     dated archives once the calendar day in their first line is older
     than today. Archives are named `<base>.YYYY-MM-DD` so a sort-by-
     filename is also chronological.

  2. Retention cap. Any rotated archive older than `logs_keep_days` is
     deleted. After that, if the logs/ directory still exceeds
     `logs_max_total_mb`, the oldest archives are deleted until it
     fits under the cap.

The active (un-rotated) log files are never deleted by this module —
they're the live tail. Rotation runs at startup AND on a cron schedule
(daily); both paths are idempotent.

Best-effort throughout: if a single file can't be rotated/deleted we
log the failure to stderr and continue, because the agent process
shouldn't die over a log housekeeping issue.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_os.core.instance.instance import InstanceLayout


ROTATE_TARGETS = ("audit.log", "latency.jsonl")


def _first_line_date(path: Path) -> date | None:
    """Read the ISO timestamp from the first line of `path` and return its
    UTC date. Returns None when the file is empty, malformed, or doesn't
    carry a `ts`/`timestamp` field we know how to parse."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            first = fh.readline().strip()
        if not first:
            return None
        # Two known shapes: audit (ts) + latency (timestamp).
        try:
            row = json.loads(first)
        except json.JSONDecodeError:
            return None
        for key in ("ts", "timestamp"):
            val = row.get(key)
            if isinstance(val, str) and val:
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00")).date()
                except ValueError:
                    continue
        return None
    except OSError:
        return None


def _rotate_one(layout: InstanceLayout, basename: str) -> Path | None:
    """If `<logs>/basename` carries entries from before today, move it to
    `<logs>/basename.YYYY-MM-DD` (using the first-entry date as the
    archive label). Returns the new path, or None if no rotation needed."""
    src = layout.logs_dir / basename
    if not src.exists():
        return None
    today = datetime.now(timezone.utc).date()
    first_day = _first_line_date(src)
    if first_day is None or first_day >= today:
        return None
    archive = layout.logs_dir / f"{basename}.{first_day.isoformat()}"
    suffix = 0
    while archive.exists():
        suffix += 1
        archive = layout.logs_dir / f"{basename}.{first_day.isoformat()}.{suffix}"
    try:
        os.replace(src, archive)
    except OSError as exc:
        print(f"[jaeger-rotate] {basename}: rotate failed: {exc}", file=sys.stderr, flush=True)
        return None
    return archive


def _archive_files(layout: InstanceLayout) -> list[Path]:
    """Return every rotated archive currently on disk for any target."""
    out: list[Path] = []
    if not layout.logs_dir.exists():
        return out
    for entry in layout.logs_dir.iterdir():
        if not entry.is_file():
            continue
        for base in ROTATE_TARGETS:
            # An archive is `<base>.YYYY-MM-DD[.N]` — i.e. starts with
            # base+'.', and the rest contains at least one dash (the date).
            if entry.name.startswith(base + ".") and "-" in entry.name[len(base) + 1:]:
                out.append(entry)
                break
    return out


def _archive_date(path: Path) -> date | None:
    """Parse the YYYY-MM-DD that follows the basename."""
    for base in ROTATE_TARGETS:
        prefix = base + "."
        if path.name.startswith(prefix):
            tail = path.name[len(prefix):]
            try:
                return date.fromisoformat(tail.split(".", 1)[0])
            except ValueError:
                return None
    return None


def _prune_old_archives(layout: InstanceLayout, keep_days: int) -> int:
    """Delete archives older than `keep_days`. Returns the count deleted."""
    if keep_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc).date()
    deleted = 0
    for arc in _archive_files(layout):
        d = _archive_date(arc)
        if d is None:
            continue
        age_days = (cutoff - d).days
        if age_days > keep_days:
            try:
                arc.unlink()
                deleted += 1
            except OSError as exc:
                print(f"[jaeger-rotate] couldn't delete {arc.name}: {exc}",
                      file=sys.stderr, flush=True)
    return deleted


def _enforce_size_cap(layout: InstanceLayout, max_total_mb: int) -> int:
    """If the logs/ directory exceeds max_total_mb, delete oldest archives
    until under the cap. Active logs are never touched."""
    if max_total_mb <= 0 or not layout.logs_dir.exists():
        return 0
    cap_bytes = max_total_mb * 1024 * 1024
    total = sum(p.stat().st_size for p in layout.logs_dir.iterdir() if p.is_file())
    if total <= cap_bytes:
        return 0
    # Sort archives oldest-first; the date in the filename is reliable.
    archives = sorted(
        _archive_files(layout),
        key=lambda p: (_archive_date(p) or date.min, p.name),
    )
    deleted = 0
    for arc in archives:
        if total <= cap_bytes:
            break
        try:
            sz = arc.stat().st_size
            arc.unlink()
            total -= sz
            deleted += 1
        except OSError:
            continue
    return deleted


def rotate_now(layout: InstanceLayout, retention: Any) -> dict[str, Any]:
    """Public entry point. Idempotent — safe to call at startup AND from
    a daily cron schedule."""
    rotated = []
    for base in ROTATE_TARGETS:
        new_path = _rotate_one(layout, base)
        if new_path:
            rotated.append(new_path.name)
    pruned = _prune_old_archives(layout, getattr(retention, "logs_keep_days", 30))
    sized = _enforce_size_cap(layout, getattr(retention, "logs_max_total_mb", 1024))
    return {"rotated": rotated, "pruned_by_age": pruned, "pruned_by_size": sized}
