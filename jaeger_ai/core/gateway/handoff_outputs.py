"""G2 handoff check defaults and G3 typed outputs (artifact_refs) for handoff results."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

TERMINAL = {"completed", "completed_verified", "failed", "cancelled", "denied", "rejected", "execution_unknown"}
FAILED = {"failed", "cancelled", "denied", "rejected", "execution_unknown"}
CHECK_STATES = ("unchecked", "pending", "passed", "failed")
KINDS = ("file", "commit", "session", "task", "url")
MAX_REFS = 50
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
COMMIT_WORD = re.compile(r"\bcommit(?:ted)?\b[^0-9a-f]{0,20}([0-9a-f]{7,40})\b", re.I)
URL = re.compile(r"https?://[^\s<>()\"']+")
EVIDENCE_REF = re.compile(r"^(task|handoff):[\w.:-]{1,200}$|^url:https?://\S{1,2000}$|^file:\S{1,1000}$")


# ── G2 ───────────────────────────────────────────────────────────────
def default_check(record: dict) -> dict:
    status = str(record.get("status") or "")
    if status in FAILED:
        return {"state": "failed", "evidence_ref": f"handoff:{record.get('id')}", "checked_by": "gateway",
                "checked_at": record.get("updated_at"), "note": None}
    return {"state": "pending" if status in TERMINAL else "unchecked", "evidence_ref": None,
            "checked_by": None, "checked_at": None, "note": None}


def check_of(record: dict) -> dict:
    saved = (record.get("metadata") or {}).get("check")
    return {**default_check(record), **saved} if isinstance(saved, dict) else default_check(record)


# ── G3 ───────────────────────────────────────────────────────────────
def _git(ws: str, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", ws, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def web_base(ws: str | None) -> str | None:
    """https web base of the workspace's origin remote, credentials stripped; None if not derivable."""
    if not ws:
        return None
    raw = _git(ws, "remote", "get-url", "origin")
    if not raw:
        return None
    m = re.match(r"^(?:ssh://)?[^@/\s]+@([^:/\s]+)[:/](.+?)(?:\.git)?/?$", raw)
    if m and not raw.startswith(("http://", "https://")):
        host, path = m.group(1), m.group(2)
    else:
        u = urlsplit(raw)
        if u.scheme not in ("http", "https") or not u.hostname:
            return None
        host, path = u.hostname + (f":{u.port}" if u.port else ""), u.path.strip("/").removesuffix(".git")
    return urlunsplit(("https", host, "/" + path.strip("/"), "", "")) if path else None


def _commit(ws: str | None, sha: str, title: str | None = None, base: str | None = None) -> dict:
    full = _git(ws, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}") if ws else None
    ref = {"kind": "commit", "ref": full or sha, "sha": full or sha, "title": title or (full or sha)[:12],
           "verified": bool(full)}
    if full and base:
        ref["url"] = f"{base}/commit/{full}"
    return ref


def _file(ws: str | None, path: str, title: str | None = None) -> dict | None:
    if not ws:
        return None
    root = Path(ws).resolve()
    p = (root / path).resolve()
    if root not in p.parents or not p.is_file():
        return None
    return {"kind": "file", "ref": str(p.relative_to(root)), "sha": hashlib.sha256(p.read_bytes()).hexdigest(),
            "title": title or p.name, "verified": True}


def normalize(record: dict, *, task_exists=None) -> list[dict]:
    """artifact_refs for a terminal handoff (see shapes G3)."""
    result = record.get("result") or {}
    meta = record.get("metadata") or {}
    ws = meta.get("workspace") or record.get("workspace")
    ws = ws if ws and Path(str(ws)).is_dir() else None
    base = web_base(ws) if ws else None
    refs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(ref: dict | None) -> None:
        if ref and (ref["kind"], ref["ref"]) not in seen and len(refs) < MAX_REFS:
            seen.add((ref["kind"], ref["ref"])); refs.append(ref)

    if result.get("worker_session_id"):
        add({"kind": "session", "ref": str(result["worker_session_id"]), "sha": None,
             "title": "Worker session", "verified": True})
    tid = meta.get("task_id")
    if tid:
        add({"kind": "task", "ref": str(tid), "sha": None, "title": f"Task {tid}",
             "verified": bool(task_exists(str(tid))) if task_exists else False})
    explicit = list(result.get("artifact_refs") or []) + list((result.get("metadata") or {}).get("artifact_refs") or [])
    for r in explicit:
        if not isinstance(r, dict) or r.get("kind") not in KINDS or not str(r.get("ref") or "").strip():
            continue
        kind, val, title = r["kind"], str(r["ref"]).strip(), (str(r["title"])[:200] if r.get("title") else None)
        if kind == "commit" and SHA.fullmatch(val):
            add(_commit(ws, val, title, base))
        elif kind == "file":
            add(_file(ws, val, title))
        elif kind == "url" and URL.fullmatch(val):
            add({"kind": "url", "ref": val, "sha": None, "title": title or val[:80], "verified": False})
        elif kind in ("session", "task"):
            add({"kind": kind, "ref": val, "sha": None, "title": title or val, "verified": False})
    text = " ".join(str(x) for x in [result.get("summary") or ""] + list(result.get("evidence") or []) if x)
    for sha in COMMIT_WORD.findall(text):
        add(_commit(ws, sha, None, base))
    for ev in result.get("evidence") or []:
        if isinstance(ev, str) and not URL.match(ev) and "/" in ev or (isinstance(ev, str) and Path(ev).suffix):
            add(_file(ws, ev))
    for u in URL.findall(text):
        add({"kind": "url", "ref": u.rstrip(".,;"), "sha": None, "title": u[:80], "verified": False})
    return refs
