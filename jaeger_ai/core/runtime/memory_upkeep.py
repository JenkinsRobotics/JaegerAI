"""Nightly memory upkeep + periodic memory review (native user model).

Once a night (default 03:00 local) Jaeger reads the owner's messages from the
last day and updates the owner profile (memory/USER.md): adds durable
preferences/facts, corrects stale ones, keeps it short. During the day, every
``REVIEW_EVERY`` owner turns a smaller review looks at the latest messages of
that chat. Both run as background turns limited to memory tools; runs are
logged to memory/upkeep_runs.jsonl and visible in Settings › Memory.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULTS = {"enabled": True, "hour": 3}
REVIEW_EVERY = 10
UPKEEP_SESSION = "memory-upkeep"
TOOLS = ["user_profile", "remember", "recall", "list_facts", "forget"]


def _cfg_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "upkeep.json"


def _runs_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "upkeep_runs.jsonl"


def config(layout: Any) -> dict[str, Any]:
    try:
        data = json.loads(_cfg_path(layout).read_text(encoding="utf-8"))
        return {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def configure(layout: Any, *, enabled: Any = None, hour: Any = None) -> dict[str, Any]:
    cfg = config(layout)
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if hour is not None:
        h = int(hour)
        if not 0 <= h <= 23:
            raise ValueError("hour must be 0-23")
        cfg["hour"] = h
    p = _cfg_path(layout)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return {"ok": True, **status(layout)}


def runs(layout: Any, limit: int = 20) -> list[dict[str, Any]]:
    p = _runs_path(layout)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[::-1]


def log_run(layout: Any, kind: str, result: dict[str, Any], *, messages: int) -> None:
    row = {"kind": kind, "at": time.time(), "messages": messages,
           "status": result.get("status") or ("skipped" if result.get("skipped") else "unknown"),
           "halt_reason": result.get("halt_reason"),
           "error": str(result.get("error"))[:300] if result.get("error") else None,
           "reply": str(result.get("text") or "")[:300]}
    p = _runs_path(layout)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _last_nightly(layout: Any) -> dict[str, Any] | None:
    return next((r for r in runs(layout, 200) if r.get("kind") == "nightly"), None)


def next_run(layout: Any, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    cfg = config(layout)
    target = now.replace(hour=int(cfg["hour"]), minute=0, second=0, microsecond=0)
    last = _last_nightly(layout)
    ran_today = bool(last and datetime.fromtimestamp(last["at"]).date() == now.date())
    if now >= target and not ran_today:
        return now
    return target if now < target else target + timedelta(days=1)


def due(layout: Any, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if not config(layout)["enabled"]:
        return False
    return next_run(layout, now) <= now


def status(layout: Any) -> dict[str, Any]:
    cfg = config(layout)
    nxt = next_run(layout)
    return {**cfg, "next_run": nxt.isoformat(timespec="minutes") if cfg["enabled"] else None,
            "runs": runs(layout, 15), "review_every_turns": REVIEW_EVERY}


def _transcript(messages: list[dict[str, Any]], cap: int = 12000) -> str:
    lines, used = [], 0
    for m in messages:
        text = " ".join(str(m.get("content") or "").split())
        if not text:
            continue
        if len(text) > 500:
            text = text[:497] + "…"
        stamp = datetime.fromtimestamp(float(m.get("timestamp") or 0)).strftime("%a %H:%M")
        line = f"[{stamp}] {text}"
        if used + len(line) > cap:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


_RULES = (
    "Update the owner profile with user_profile: add only DURABLE things (preferences, standing facts, "
    "working-style rules, active projects); correct or remove entries that these messages contradict "
    "(action='replace'); merge near-duplicates so the profile stays short. Do not record one-off task "
    "details, other people's private data, secrets, tokens or codes. Do not message the owner. "
    "Finish with one short line summarising what changed, or exactly NO_REPLY if nothing did."
)


def nightly_prompt(messages: list[dict[str, Any]]) -> str:
    return ("Nightly memory upkeep (background; nobody is waiting).\n"
            "Below are the owner's own messages from the last 24 hours, oldest first. First call "
            "user_profile(action='view').\n\n" + _transcript(messages) + "\n\n" + _RULES)


def review_prompt(messages: list[dict[str, Any]]) -> str:
    return ("Memory review (background; nobody is waiting).\n"
            "These are the owner's latest messages in one chat. First call user_profile(action='view').\n\n"
            + _transcript(messages, 6000) + "\n\n" + _RULES)
