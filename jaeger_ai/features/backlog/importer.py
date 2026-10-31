"""Seed the backlog from ``~/Documents/Jaeger-Backlog.md``.

Insert-only: a task already imported (same section + title) is skipped, so edits
made in Jaeger are never overwritten; after the first import the DB is the source
of truth. Understands bullet lists (``- [ ]`` / ``- [x]`` / ``-`` / ``1.``) under
``#`` headings and markdown tables with a title/task column. Priority (P0..P2),
worker (ARES, Muse, rack PC, Grok Bot) and status words are read from the line,
its table cells or its section heading.

Run: python -m jaeger_ai.features.backlog.importer [path] [--db PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from .store import BacklogStore

DEFAULT_FILE = Path.home() / "Documents" / "Jaeger-Backlog.md"
_PRIO = re.compile(r"\b(P[0-3])\b", re.I)
_WORKERS = (("rackpc", re.compile(r"\brack[\s_-]?pc\b", re.I)), ("ares", re.compile(r"\bares\b", re.I)),
            ("muse", re.compile(r"\bmuse\b", re.I)), ("grokbot", re.compile(r"\bgrok[\s_-]?bot\b", re.I)))
_BULLET = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(?:\[( |x|X|~|-)\]\s+)?(.+)$")
_TAGS = re.compile(r"\s*[(\[](?:P[0-3]|ares|muse|rack ?pc|grok ?bot|done|open|needs|waiting|in progress|blocked)[^)\]]*[)\]]", re.I)


def _status(text: str, box: str | None = None) -> str:
    t = text.lower()
    if box in ("x", "X") or re.search(r"\b(done|shipped|complete[d]?)\b", t) or "✅" in text:
        return "done"
    if box in ("~", "-") or re.search(r"\b(in[ _-]progress|running|working)\b", t):
        return "in_progress"
    if re.search(r"needs?[ _-](your )?ok|waiting on (you|matthew)|needs approval|approval needed", t):
        return "needs_ok"
    return "open"


def _priority(text: str) -> str:
    m = _PRIO.search(text)
    if not m:
        return ""
    p = m.group(1).upper()
    return "P2" if p == "P3" else p


def _worker(text: str) -> str:
    for name, rx in _WORKERS:
        if rx.search(text):
            return name
    return ""


def _title(raw: str) -> tuple[str, str]:
    raw = re.sub(r"\*\*(.+?)\*\*", r"\1", raw).strip()
    title, _, detail = raw.partition(" — ")
    if not detail and ": " in raw and len(raw.split(": ", 1)[0]) <= 80:
        title, detail = raw.split(": ", 1)
    title = _TAGS.sub("", title).strip(" -–:") or raw[:300]
    return title[:300], detail.strip()[:8000]


def parse(text: str) -> list[dict]:
    items: list[dict] = []
    section, header = "", None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            section, header = s.lstrip("#").strip(), None
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            if header is None:
                header = [c.lower() for c in cells]
                continue
            row = dict(zip(header, cells))
            name = next((row[k] for k in header if k in ("title", "task", "item", "name")), cells[0])
            if not name:
                continue
            title, detail = _title(name)
            detail = detail or next((row[k] for k in header if k in ("detail", "details", "notes", "description")), "")
            joined = " ".join(cells)
            items.append({"title": title, "detail": detail, "section": section,
                          "priority": _priority(row.get("priority", "") or joined) or _priority(section),
                          "worker": _worker(row.get("worker", "") or row.get("owner", "") or row.get("assigned", "") or ""),
                          "status": _status(row.get("status", "") or "")})
            continue
        header = None if not s.startswith("|") else header
        m = _BULLET.match(line)
        if not m or line.startswith((" " * 4, "\t")):
            continue  # nested bullets are details of their parent, not tasks
        box, body = m.group(1), m.group(2).strip()
        title, detail = _title(body)
        if len(title) < 3:
            continue
        items.append({"title": title, "detail": detail, "section": section,
                      "priority": _priority(body) or _priority(section), "worker": _worker(body),
                      "status": _status(body, box) if box or _status(body) != "open" else _status(section)})
    return items


def import_file(store: BacklogStore, path: Path = DEFAULT_FILE) -> dict:
    path = Path(path).expanduser()
    if not path.is_file():
        return {"ok": False, "error": f"{path} not found", "added": 0, "skipped": 0}
    added = skipped = 0
    for it in parse(path.read_text(encoding="utf-8", errors="replace")[:2_000_000]):
        key = hashlib.sha256(f"{it['section'].lower()}|{it['title'].lower()}".encode()).hexdigest()[:24]
        res = store.add(it["title"], it["detail"], source=f"{path.name}: {it['section']}"[:300] if it["section"] else path.name,
                        status=it["status"], priority=it["priority"] or "P1", worker=it["worker"], import_key=key)
        if res.get("existing"):
            skipped += 1
        else:
            added += 1
    return {"ok": True, "path": str(path), "added": added, "skipped": skipped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=str(DEFAULT_FILE))
    ap.add_argument("--db", default=None)
    a = ap.parse_args(argv)
    out = import_file(BacklogStore(a.db), Path(a.path))
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
