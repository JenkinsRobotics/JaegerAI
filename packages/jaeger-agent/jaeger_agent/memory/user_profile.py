"""Native owner profile — ``<instance>/memory/USER.md``.

A short, human-readable document of who the owner is and how they like to
work: preferences, standing facts, style. Jaeger keeps it current from
conversations (``user_profile`` tool, periodic review, nightly upkeep); the
owner can read and edit it in Settings › Memory. It is injected into the
system prompt of user-facing turns. Every change keeps the previous text in
``memory/profile_history/`` so edits are reversible. Replaces the retired
Honcho user model.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

MAX_CHARS = 3000
KEEP_HISTORY = 100
SECTIONS = ("About", "Preferences", "Working style", "Projects")
_SEED_CATEGORIES = ("identity", "profile", "preferences")
_SECRETISH = re.compile(r"(api[_-]?key|token|password|secret|passcode|codename|ssn|credit card)", re.I)


def profile_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "USER.md"


def history_dir(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "profile_history"


def log_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "profile_changes.jsonl"


def _template() -> str:
    return "# About the owner\n\n" + "\n\n".join(f"## {s}\n" for s in SECTIONS)


def _seed_from_facts(layout: Any) -> str:
    import sqlite3
    sql = ("SELECT key, value, category FROM facts WHERE subject='user' AND category IN (%s) "
           "ORDER BY updated_at DESC LIMIT 30" % ",".join("?" * len(_SEED_CATEGORIES)))
    try:
        conn = sqlite3.connect(str(Path(layout.root) / "memory" / "state.db"), timeout=5)
        try:
            rows = conn.execute(sql, _SEED_CATEGORIES).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — seeding is best-effort
        return ""
    about, prefs = [], []
    for key, value, cat in rows:
        text = " ".join(str(value).split())
        if not text or _SECRETISH.search(str(key)) or _SECRETISH.search(text):
            continue
        # Preference rows include old test probes ("teal", "VENUS"); keep real sentences only.
        if cat == "preferences" and (len(text.split()) < 4 or re.search(r"\b(probe|test|json)\b", text, re.I)):
            continue
        if len(text.split()) <= 3:  # bare values ("Seattle") read better with their key
            text = f"{str(key).replace('_', ' ').capitalize()}: {text}"
        if len(text) > 220:
            text = text[:217].rstrip() + "…"
        (about if cat in ("identity", "profile") else prefs).append(f"- {text}")
    if not about and not prefs:
        return ""
    body = _template()
    body = body.replace("## About\n", "## About\n" + "\n".join(about) + "\n", 1)
    body = body.replace("## Preferences\n", "## Preferences\n" + "\n".join(prefs) + "\n", 1)
    return body


def load(layout: Any, *, seed: bool = True) -> str:
    p = profile_path(layout)
    try:
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not seed:
        return ""
    text = _seed_from_facts(layout)
    if text:
        save(layout, text, origin="seed", summary="seeded from remembered preferences")
    return text


def _clean(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").strip() + "\n"
    if len(text) > MAX_CHARS:
        raise ValueError(f"Profile is limited to {MAX_CHARS} characters ({len(text)} given); consolidate entries first")
    return text


def save(layout: Any, text: str, *, origin: str, summary: str = "") -> dict[str, Any]:
    """Replace the profile, snapshotting the prior text. origin: owner|jaeger|seed."""
    new = _clean(text)
    p = profile_path(layout)
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text(encoding="utf-8") if p.is_file() else ""
    if old == new:
        return {"ok": True, "changed": False, "chars": len(new)}
    ts = time.strftime("%Y%m%dT%H%M%S")
    if old:
        h = history_dir(layout)
        h.mkdir(parents=True, exist_ok=True)
        (h / f"{ts}.md").write_text(old, encoding="utf-8")
        for stale in sorted(h.glob("*.md"))[:-KEEP_HISTORY]:
            stale.unlink(missing_ok=True)
    tmp = p.with_suffix(".md.tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(p)
    with log_path(layout).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": time.time(), "origin": origin, "summary": summary[:300],
                             "chars": len(new), "previous": f"{ts}.md" if old else None}) + "\n")
    return {"ok": True, "changed": True, "chars": len(new), "origin": origin}


def changes(layout: Any, limit: int = 50) -> list[dict[str, Any]]:
    p = log_path(layout)
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[::-1]


def add(layout: Any, entry: str, section: str = "Preferences", *, origin: str = "jaeger") -> dict[str, Any]:
    entry = " ".join((entry or "").split()).lstrip("- ")
    if not entry:
        raise ValueError("Nothing to add")
    if _SECRETISH.search(entry):
        raise ValueError("Profile must not hold secrets, tokens or codes — use the credential vault")
    text = load(layout) or _template()
    if entry.lower() in text.lower():
        return {"ok": True, "changed": False, "reason": "already in profile"}
    sec = next((s for s in SECTIONS if s.lower() == (section or "").strip().lower()), "Preferences")
    marker = f"## {sec}\n"
    if marker not in text:
        text = text.rstrip() + f"\n\n{marker}"
    head, _, tail = text.partition(marker)
    nxt = tail.find("\n## ")
    block, rest = (tail, "") if nxt == -1 else (tail[:nxt + 1], tail[nxt + 1:])
    block = block.rstrip("\n") + ("\n" if block.strip() else "") + f"- {entry}\n"
    return save(layout, head + marker + block + ("\n" + rest if rest else ""), origin=origin, summary=f"+ {entry}")


def replace(layout: Any, old: str, new: str, *, origin: str = "jaeger") -> dict[str, Any]:
    text = load(layout)
    if not old or text.count(old) != 1:
        raise ValueError("'old' must match exactly once in the profile")
    if new and _SECRETISH.search(new):
        raise ValueError("Profile must not hold secrets, tokens or codes")
    updated = text.replace(old, new, 1)
    if not new:
        updated = re.sub(r"\n- *\n", "\n", updated)
    return save(layout, updated, origin=origin, summary=(f"~ {new}" if new else f"- {old}")[:300])
