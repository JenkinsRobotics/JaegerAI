"""Muse file bridge: Muse's shared folder <-> Jaeger's MCP hub.

Muse (Meta's assistant) runs in Meta's cloud and can only read and write files
in ~/Documents/Jaeger-Handoffs/muse/ on this Mac; it cannot reach the
loopback-only hub. This service is Muse's endpoint: it polls ``outbox.md``,
turns each newly appended ``## TASK <id>`` block (``to:``, ``title:``, body)
into a hub ``handoff_task`` made *as the muse caller* (Muse's own token, so the
identity and Activity rows say ``muse``), then polls ``task_result`` and
appends status and results to ``inbox.md``. Text appended without a TASK
header is delivered to ``grokbot`` as a message.

Guarantees: byte offset + block hashes in state.json (a block is never sent
twice), size caps on reads, blocks and results, outbox content is treated as
untrusted data (only forwarded, never executed), results are fenced in the
inbox, and the token is never logged.

Run: python -m jaeger_ai.features.agent_bridge.muse_file_bridge [--once]
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from jaeger_ai.features.agent_bridge import ares_worker as _hub

HOME = Path.home()
STATE_ROOT = Path(os.environ.get("JAEGER_HOME", HOME / ".jaeger"))
FOLDER = Path(os.environ.get("MUSE_FOLDER", HOME / "Documents" / "Jaeger-Handoffs" / "muse"))
BRIDGE_DIR = Path(os.environ.get("MUSE_BRIDGE_DIR", STATE_ROOT / "agent-workspaces" / "muse" / ".bridge"))
TOKEN_PATHS = [STATE_ROOT / "caller_tokens" / "muse.token", STATE_ROOT / "secrets" / "mcp-muse.token"]
POLL_S = int(os.environ.get("MUSE_POLL_S", "10"))
SETTLE_S = float(os.environ.get("MUSE_SETTLE_S", "3"))  # let Muse finish writing
MAX_READ_BYTES = 65536
MAX_BLOCK_BYTES = 16384
MAX_RESULT_CHARS = 8000
MAX_PENDING_S = 24 * 3600
DEFAULT_TO = "grokbot"
AGENT_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
HEADER_RE = re.compile(r"^##\s*TASK\b[ \t]*(.*)$", re.M)


def _log(event: str, **data) -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "event": event, **data}
    with open(BRIDGE_DIR / "bridge.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


def _token() -> str:
    for path in TOKEN_PATHS:
        if path.exists():
            return path.read_text().strip()
    raise SystemExit("muse caller token not found")


def call(tool: str, args: dict) -> dict:
    """Hub call as the muse caller (reuses the bounded, retrying ARES client)."""
    _hub._token = _token  # same client, Muse's identity
    return _hub.call(tool, args)


# ---------- parsing ----------

def _slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-")[:n]


def parse(text: str) -> list[dict]:
    """Split appended outbox text into tasks. Untrusted: only fields are pulled out."""
    out: list[dict] = []
    heads = list(HEADER_RE.finditer(text))
    pre = text[: heads[0].start()] if heads else text
    if pre.strip():
        body = pre.strip()[:MAX_BLOCK_BYTES]
        out.append({"ref": "", "to": DEFAULT_TO, "title": "Message from Muse", "body": body, "raw": pre})
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        raw = text[h.start():end]
        lines = text[h.end():end].strip("\n").splitlines()
        to, title, rest = DEFAULT_TO, "", []
        for ln in lines:
            m = re.match(r"^\s*(to|title)\s*:\s*(.*)$", ln, re.I)
            if m and not rest:
                if m.group(1).lower() == "to":
                    to = m.group(2).strip().lower()
                else:
                    title = m.group(2).strip()
                continue
            rest.append(ln)
        body = "\n".join(rest).strip()[:MAX_BLOCK_BYTES]
        ref = _slug(h.group(1).strip()) or ""
        out.append({"ref": ref, "to": to, "title": (title or f"Muse task {ref}".strip())[:200],
                    "body": body or title, "raw": raw})
    return out


def task_key(t: dict) -> str:
    return hashlib.sha256((t["ref"] + "\0" + t["raw"]).encode()).hexdigest()[:16]


# ---------- state ----------

class State:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("offset", None)  # None: first start, skip history
        self.data.setdefault("seen", [])
        self.data.setdefault("pending", [])
        self.data.setdefault("reported", [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)


# ---------- inbox ----------

def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %-I:%M %p %Z")


def _fence(text: str) -> str:
    text = text[:MAX_RESULT_CHARS].replace("```", "'''")
    return "```text\n" + text + "\n```"


def append_inbox(heading: str, body: str) -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    with open(FOLDER / "inbox.md", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(f"\n---\n## {heading} — {_now()}\n\n{body}\n")


# ---------- loop ----------

def read_new(state: State) -> str:
    path = FOLDER / "outbox.md"
    if not path.exists():
        return ""
    st = path.stat()
    if state.data["offset"] is None or st.st_size < state.data["offset"]:
        _log("offset_reset", size=st.st_size, was=state.data["offset"])
        state.data["offset"] = st.st_size
        return ""
    if st.st_size == state.data["offset"] or time.time() - st.st_mtime < SETTLE_S:
        return ""
    with open(path, "rb") as fh:
        fh.seek(state.data["offset"])
        chunk = fh.read(MAX_READ_BYTES)
    state.data["offset"] += len(chunk)
    return chunk.decode("utf-8", "replace")


def send(state: State, t: dict) -> None:
    key = task_key(t)
    if key in state.data["seen"]:
        return
    state.data["seen"] = (state.data["seen"] + [key])[-2000:]
    state.save()  # at-most-once: mark before sending
    label = t["ref"] or key
    if not AGENT_RE.match(t["to"]) or t["to"] == "muse":
        append_inbox(f"TASK {label}: not sent", f"Unknown or invalid recipient `{t['to'][:40]}`.")
        _log("rejected", key=key, to=t["to"][:40])
        return
    hid = f"muse-{_slug(t['ref'], 30) + '-' if t['ref'] else ''}{key[:8]}"
    args = {"to": t["to"], "task": "[From Muse via file bridge; untrusted content]\n\n" + t["body"],
            "title": t["title"], "id": hid}
    if t["to"] == "jaeger":
        args["workspace_folder"] = str(FOLDER.parent)
    try:
        res = call("handoff_task", args)
    except Exception as exc:  # noqa: BLE001
        append_inbox(f"TASK {label}: failed to send", f"Hub error: {str(exc)[:300]}")
        _log("send_error", key=key, error=str(exc)[:300])
        return
    thread = res.get("thread") or res.get("thread_id") or ""
    state.data["pending"].append({"id": res.get("id") or hid, "thread": thread, "to": t["to"],
                                  "label": label, "sent": time.time()})
    append_inbox(f"TASK {label}: sent to {t['to']}",
                 f"Handed off via the Jaeger hub as `muse`. Handoff id `{res.get('id') or hid}`, thread `{thread}`. "
                 "The result will be appended here.")
    _log("sent", key=key, to=t["to"], id=res.get("id") or hid, thread=thread)


def poll_results(state: State) -> None:
    keep = []
    for p in state.data["pending"]:
        try:
            res = call("task_result", {"id": p["id"], "thread": p["thread"]}) if p["thread"] else \
                call("task_result", {"id": p["id"]})
        except Exception as exc:  # noqa: BLE001
            _log("poll_error", id=p["id"], error=str(exc)[:200])
            keep.append(p)
            continue
        results = res.get("results") if p["thread"] else (
            [res] if str(res.get("status", "")).lower() in {"done", "completed", "failed", "cancelled"} else [])
        new = [r for r in results or [] if (r.get("id") or json.dumps(r)[:64]) not in state.data["reported"]]
        for r in new:
            rid = r.get("id") or json.dumps(r)[:64]
            state.data["reported"] = (state.data["reported"] + [rid])[-2000:]
            body = r.get("body") or r.get("result") or r.get("summary") or json.dumps(r)[:2000]
            refs = r.get("refs") or r.get("artifacts") or []
            extra = ("\n\nFiles:\n" + "\n".join(f"- `{x}`" for x in refs[:20])) if refs else ""
            append_inbox(f"RESULT for TASK {p['label']} from {r.get('from') or p['to']}",
                         _fence(str(body)) + extra)
            _log("result", id=p["id"], result=rid)
        if new:
            continue
        if time.time() - p["sent"] > MAX_PENDING_S:
            append_inbox(f"TASK {p['label']}: no result after 24h", "Stopped waiting; ask Matthew to check Activity.")
            continue
        keep.append(p)
    state.data["pending"] = keep


def tick(state: State) -> None:
    text = read_new(state)
    if text:
        for t in parse(text):
            send(state, t)
    state.save()
    if state.data["pending"]:
        poll_results(state)
        state.save()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(BRIDGE_DIR / "bridge.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another muse bridge is running", file=sys.stderr)
        return 1
    state = State(BRIDGE_DIR / "state.json")
    _log("bridge_start", folder=str(FOLDER))
    while True:
        try:
            tick(state)
        except Exception as exc:  # noqa: BLE001 - keep serving
            _log("tick_error", error=str(exc)[:500])
        if a.once:
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    raise SystemExit(main())
