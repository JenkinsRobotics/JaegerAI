"""Read-only view of Hermes's and OpenClaw's own skills and memory (J-083 A, slice 1).

Jaeger never writes to either engine's state here. Files are read in place, size-capped,
and anything that looks like a credential file is skipped. Served at GET /v1/engines/catalog.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

HOME = Path.home()
MAX_BYTES = 64 * 1024
SKIP = re.compile(r"(^\.env|token|secret|auth\.json|\.key$|credential)", re.I)


def roots() -> dict[str, dict[str, list[Path]]]:
    hermes_home = Path(os.environ.get("JAEGER_HERMES_SKILLS_HOME", HOME / ".hermes"))
    oc_ws = Path(os.environ.get("JAEGER_OPENCLAW_WORKSPACE", HOME / ".jaeger/openclaw/workspace"))
    oc_state = oc_ws.parent
    oc_pkg = Path(os.environ.get("JAEGER_OPENCLAW_PKG", "/opt/homebrew/lib/node_modules/openclaw"))
    return {
        "hermes": {"skills": [hermes_home / "skills"],
                   "memory": [hermes_home / "memories", HOME / ".jaeger/hermes/SOUL.md"]},
        "openclaw": {"skills": [oc_ws / "skills", oc_state / "plugin-skills", oc_state / "skill-workshop",
                                oc_pkg / "skills", oc_pkg / "custodian-skills"],
                     "memory": [oc_ws / "MEMORY.md", oc_ws / "USER.md", oc_ws / "SOUL.md",
                                oc_ws / "IDENTITY.md", oc_ws / "memory"]},
    }


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    out: dict[str, str] = {}
    for line in text[3:end if end > 0 else 0].splitlines():
        key, sep, val = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "\t")):
            out[key.strip()] = val.strip().strip("\"'")
    return out


def _read(path: Path) -> str:
    with open(path, "rb") as fh:
        return fh.read(MAX_BYTES).decode("utf-8", "replace")


def skills(engine: str) -> list[dict]:
    rows = []
    for root in roots()[engine]["skills"]:
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("SKILL.md")):
            if any(SKIP.search(p) for p in f.relative_to(root).parts):
                continue
            try:
                fm = _frontmatter(_read(f))
            except OSError:
                continue
            rel = f.parent.relative_to(root)
            rows.append({"engine": engine, "name": fm.get("name") or f.parent.name,
                         "description": fm.get("description", "")[:500],
                         "category": rel.parts[0] if len(rel.parts) > 1 else "general",
                         "path": str(f), "read_only": True})
    return rows


def memory(engine: str, with_text: bool = False) -> list[dict]:
    files: list[Path] = []
    for p in roots()[engine]["memory"]:
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(x for x in p.rglob("*.md") if x.is_file()))
    rows = []
    for f in files:
        if SKIP.search(f.name):
            continue
        try:
            st = f.stat()
            row = {"engine": engine, "name": f.name, "path": str(f), "bytes": st.st_size,
                   "modified": st.st_mtime, "read_only": True}
            if with_text:
                row["text"] = _read(f)
        except OSError:
            continue
        rows.append(row)
    return rows


def catalog(with_text: bool = False) -> dict:
    out = {}
    for engine in ("hermes", "openclaw"):
        s, m = skills(engine), memory(engine, with_text)
        out[engine] = {"skills": s, "memory": m, "counts": {"skills": len(s), "memory": len(m)}}
    return {"engines": out, "read_only": True}


def register(gateway) -> None:
    from aiohttp import web

    async def route(request):
        return web.json_response(catalog(with_text=request.query.get("text") == "1"))

    gateway.app.router.add_get("/v1/engines/catalog", route)
