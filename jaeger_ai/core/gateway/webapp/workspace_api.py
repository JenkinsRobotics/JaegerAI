"""The ``/api/*`` routes the UI still calls that used to live in the Hermes
code: workspace files, Git, checkpoints, the operator terminal, notes, and
the model picker. Rewritten small on top of the Gateway (R11)."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import pty
import select
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

from api.helpers import bad, j, read_body, _sanitize_error

MAX_FILE = 2 * 1024 * 1024


def _q(parsed) -> dict:
    return {k: v[0] for k, v in parse_qs(parsed.query or "").items()}


def _workspace(session_id: str) -> Path:
    if not session_id:
        raise ValueError("session_id is required")
    from api.gateway_read_workspace import gateway_read_workspace
    return gateway_read_workspace(session_id)


def _inside(root: Path, rel: str) -> Path:
    target = (root / (rel or "")).resolve()
    if target != root and not target.is_relative_to(root):
        raise ValueError("path escapes the workspace")
    return target


def _git(root: Path, *args: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout)


# ── files ────────────────────────────────────────────────────────────────

def _list(handler, q):
    root = _workspace(q.get("session_id", ""))
    folder = _inside(root, q.get("path", ""))
    if not folder.is_dir():
        return bad(handler, "Not a folder", 404)
    entries = []
    for child in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:2000]:
        if child.name in (".git", ".DS_Store"):
            continue
        rel = str(child.relative_to(root)) if child.resolve().is_relative_to(root) else child.name
        outside = child.is_symlink() and not child.resolve().is_relative_to(root)
        entries.append({"name": child.name, "path": rel, "type": "dir" if child.is_dir() else "file",
                        "is_dir": child.is_dir(), "target_outside_workspace": outside})
    return j(handler, {"entries": entries, "path": q.get("path", ""), "workspace": str(root)})


def _file(handler, q, raw: bool):
    root = _workspace(q.get("session_id", ""))
    target = _inside(root, q.get("path", ""))
    if not target.is_file():
        return bad(handler, "File not found", 404)
    size = target.stat().st_size
    if size > MAX_FILE:
        return j(handler, {"path": q.get("path"), "size": size, "too_large": True})
    data = target.read_bytes()
    if raw:
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        handler.send_response(200)
        handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        from api.helpers import _security_headers
        _security_headers(handler)
        handler.end_headers()
        handler.wfile.write(data)
        handler._jg_responded = True
        return True
    try:
        return j(handler, {"path": q.get("path"), "size": size, "content": data.decode("utf-8")})
    except UnicodeDecodeError:
        return j(handler, {"path": q.get("path"), "size": size, "binary": True,
                           "content_base64": base64.b64encode(data).decode("ascii")})


# ── git ──────────────────────────────────────────────────────────────────

def _git_status(handler, q):
    root = _workspace(q.get("session_id", ""))
    if _git(root, "rev-parse", "--is-inside-work-tree").returncode != 0:
        return j(handler, {"git": {"is_git": False}})
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    out = _git(root, "status", "--porcelain=v1", "-uall").stdout.splitlines()
    nums = {}
    for line in _git(root, "diff", "--numstat", "HEAD").stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            nums[parts[2]] = (int(parts[0]) if parts[0].isdigit() else 0, int(parts[1]) if parts[1].isdigit() else 0)
    files = []
    for line in out[:500]:
        x, y, path = line[0], line[1], line[3:]
        add, dele = nums.get(path, (0, 0))
        files.append({"path": path, "status": (x + y).strip() or "?", "staged": x not in " ?",
                      "unstaged": y not in " ", "untracked": x == "?", "ignored": x == "!",
                      "additions": add, "deletions": dele})
    return j(handler, {"git": {"is_git": True, "branch": branch, "files": files, "truncated": len(out) > 500}})


def _git_branches(handler, q):
    root = _workspace(q.get("session_id", ""))
    res = _git(root, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes")
    if res.returncode != 0:
        return bad(handler, "Not a Git repository", 400)
    refs = [r for r in res.stdout.splitlines() if r and not r.endswith("/HEAD")]
    current = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return j(handler, {"branches": {"current": current,
                                    "local": [{"name": r[len("refs/heads/"):]} for r in refs if r.startswith("refs/heads/")],
                                    "remote": [{"name": r[len("refs/remotes/"):]} for r in refs if r.startswith("refs/remotes/")]}})


def _git_diff(handler, q):
    root = _workspace(q.get("session_id", ""))
    path = q.get("path", "")
    _inside(root, path)
    kind = q.get("kind", "unstaged")
    args = ["diff", "--cached", "--", path] if kind == "staged" else ["diff", "--", path]
    if kind == "untracked":
        args = ["diff", "--no-index", "--", "/dev/null", path]
    diff = _git(root, *args).stdout
    return j(handler, {"diff": {"diff": diff[:400_000], "too_large": len(diff) > 400_000, "binary": "Binary files" in diff[:400]}})


# ── checkpoints (the Gateway's file-change checkpoints for the session) ─

def _checkpoints(handler, q, diff: bool):
    root = _workspace(q.get("session_id", ""))
    shadow = Path.home() / ".jaeger/checkpoints"
    repo = None
    for cand in (root / ".jaeger-checkpoints", shadow / root.name):
        if (cand / "HEAD").exists():
            repo = cand
            break
    if repo is None:
        return j(handler, {"checkpoints": []} if not diff else {"diff": "", "total_changes": 0})
    gitdir = ["git", f"--git-dir={repo}", f"--work-tree={root}"]
    if not diff:
        log = subprocess.run([*gitdir, "log", "-50", "--format=%H%x09%s%x09%cI%x09%cr", "--shortstat"],
                             capture_output=True, text=True, timeout=15).stdout
        rows, cur = [], None
        for line in log.splitlines():
            if "\t" in line:
                h, msg, iso, rel = line.split("\t", 3)
                cur = {"id": h, "message": msg, "date": iso, "date_display": rel, "files": 0, "files_changed": 0}
                rows.append(cur)
            elif cur and "changed" in line:
                n = int(line.strip().split(" ")[0])
                cur["files"] = cur["files_changed"] = n
        return j(handler, {"checkpoints": rows})
    cp = q.get("checkpoint", "")
    if not cp or not all(c in "0123456789abcdef" for c in cp):
        return bad(handler, "checkpoint id required")
    out = subprocess.run([*gitdir, "diff", cp, "--stat", "--patch"], capture_output=True, text=True, timeout=20).stdout
    return j(handler, {"diff": out[:400_000], "total_changes": out.count("\n+") + out.count("\n-")})


# ── operator terminal (one PTY per conversation) ─────────────────────────

class _Term:
    def __init__(self, cwd: Path, rows: int, cols: int):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # child
            os.chdir(str(cwd))
            shell = os.environ.get("SHELL") or "/bin/zsh"
            os.execvpe(shell, [shell, "-l"], {**os.environ, "TERM": "xterm-256color"})
        self.buf: list[str] = []
        self.cond = threading.Condition()
        self.closed = False
        self.seq = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            try:
                r, _, _ = select.select([self.fd], [], [], 1.0)
                if not r:
                    if self._dead():
                        break
                    continue
                data = os.read(self.fd, 65536)
                if not data:
                    break
            except OSError:
                break
            with self.cond:
                self.buf.append(data.decode("utf-8", "replace"))
                self.buf = self.buf[-2000:]
                self.seq += 1
                self.cond.notify_all()
        with self.cond:
            self.closed = True
            self.cond.notify_all()

    def _dead(self) -> bool:
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid != 0
        except ChildProcessError:
            return True

    def write(self, data: str):
        os.write(self.fd, data.encode("utf-8"))

    def close(self):
        try:
            os.kill(self.pid, signal.SIGHUP)
        except OSError:
            pass


_TERMS: dict[str, _Term] = {}
_TERMS_LOCK = threading.Lock()


def _terminal_allowed(handler) -> bool:
    peer = (getattr(handler, "client_address", None) or ("",))[0]
    return peer in ("127.0.0.1", "::1")


def _terminal_start(handler):
    body = read_body(handler)
    sid = str(body.get("session_id") or "")
    root = _workspace(sid)
    with _TERMS_LOCK:
        term = _TERMS.get(sid)
        if term is None or term.closed:
            term = _TERMS[sid] = _Term(root, int(body.get("rows") or 24), int(body.get("cols") or 80))
    return j(handler, {"session_id": sid, "running": not term.closed, "workspace": str(root)})


def _terminal_input(handler):
    body = read_body(handler)
    term = _TERMS.get(str(body.get("session_id") or ""))
    if term is None or term.closed:
        return bad(handler, "Terminal is not running", 409)
    term.write(str(body.get("data") or "")[:8000])
    return j(handler, {"ok": True})


def _terminal_close(handler):
    body = read_body(handler)
    term = _TERMS.pop(str(body.get("session_id") or ""), None)
    if term:
        term.close()
    return j(handler, {"ok": True})


def _terminal_output(handler, q):
    if not q.get("session_id"):
        return bad(handler, "session_id is required")
    term = _TERMS.get(q.get("session_id", ""))
    if term is None:
        return bad(handler, "Terminal is not running", 404)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()
    handler._jg_responded = True
    handler.close_connection = True
    sent = 0
    with term.cond:
        backlog = "".join(term.buf)
        sent = term.seq
    def emit(event: str, payload: dict):
        handler.wfile.write(f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode("utf-8"))
        handler.wfile.flush()
    if backlog:
        emit("output", {"text": backlog})
    last_ping = time.time()
    while True:
        with term.cond:
            term.cond.wait(timeout=10)
            if term.seq > sent:
                chunk = "".join(term.buf[-(term.seq - sent):])
                sent = term.seq
            else:
                chunk = ""
            closed = term.closed
        if chunk:
            emit("output", {"text": chunk})
        if closed:
            emit("terminal_closed", {})
            return True
        if time.time() - last_ping > 15:
            handler.wfile.write(b": ping\n\n"); handler.wfile.flush(); last_ping = time.time()


# ── notes (Joplin bridge is off by default) ──────────────────────────────

def _notes(handler, path, q):
    if path == "/api/notes/sources":
        return j(handler, {"enabled": False, "sources": [], "source": "disabled", "inventory_scope": "disabled_by_default",
                           "attach_supported": False, "automatic_recall_unchanged": True, "recent_ai_notes": []})
    return bad(handler, "Notes sources are disabled", 404)


# ── model picker ─────────────────────────────────────────────────────────

def _gateway_json(method: str, path: str, body: dict | None = None, timeout: int = 60):
    from urllib.request import Request, urlopen
    from api.jaeger_sessions import gateway_base
    from jaeger_ai.core.gateway.caller_auth import client_headers
    req = Request(gateway_base() + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                  headers={"Accept": "application/json", "Content-Type": "application/json", **client_headers("webui")})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


_CLI_LANES = {"grok", "chatgpt", "codex", "gemini-cli", "agy", "claude"}


def _models(handler):
    data = _gateway_json("GET", "/v1/runtime/models")
    return j(handler, data.get("webui_catalog") or {"groups": []})


def _providers(handler):
    data = _gateway_json("GET", "/v1/runtime/models")
    rows = [{"id": p.get("id"), "display_name": p.get("display_name"), "has_key": bool(p.get("configured")),
             "key_source": "configured" if p.get("configured") else "none", "is_oauth": p.get("location") == "cli",
             "configurable": False, "models": [], "models_total": len(p.get("models") or [])}
            for p in data.get("providers") or []]
    return j(handler, {"providers": rows, "active_provider": (data.get("active") or {}).get("provider")})


def _edit_external_model(cfg_path: Path, values: dict) -> None:
    """Set keys under the top-level ``external_model:`` block in place, keeping comments and order."""
    lines = cfg_path.read_text().splitlines(keepends=True)
    try:
        start = next(i for i, l in enumerate(lines) if l.rstrip() == "external_model:")
    except StopIteration:
        lines += ["external_model:\n"]
        start = len(lines) - 1
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
        end += 1
    todo = dict(values)
    for i in range(start + 1, end):
        key = lines[i].strip().split(":", 1)[0]
        if lines[i].startswith("  ") and not lines[i].startswith("   ") and key in todo:
            lines[i] = f"  {key}: {json.dumps(todo.pop(key)) if key != 'enabled' else todo.pop(key)}\n"
    for key, val in todo.items():
        lines.insert(end, f"  {key}: {json.dumps(val) if key != 'enabled' else val}\n")
    tmp = cfg_path.with_suffix(".yaml.tmp")
    tmp.write_text("".join(lines))
    os.replace(tmp, cfg_path)


def _set_default_model(handler):
    body = read_body(handler)
    model, provider = str(body.get("model") or "").strip(), str(body.get("provider") or "").strip()
    if not model:
        return bad(handler, "model is required")
    if model.startswith("@") and ":" in model:
        provider, model = model[1:].split(":", 1)
    lane = provider.lower()
    if lane in _CLI_LANES or lane.startswith("cli"):
        values = {"provider": "cli", "model": lane if lane != "cli" else model}
    elif lane in ("ollama-local", "ollama"):
        values = {"provider": "ollama", "model": model}
    else:
        values = {"provider": lane or "ollama", "model": model}
    from jaeger_ai.core.instance.instance import resolve_instance_dir
    cfg_path = Path(resolve_instance_dir()) / "config.yaml"
    backup = cfg_path.with_name(f"config.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}-model")
    shutil.copy2(cfg_path, backup)
    _edit_external_model(cfg_path, {"enabled": "true", **values})
    ext = values
    return j(handler, {"ok": True, "model": ext["model"], "provider": ext["provider"], "backup": backup.name})


# ── dispatch ─────────────────────────────────────────────────────────────

def route(handler, parsed, method: str) -> bool:
    path, q = parsed.path, _q(parsed)
    try:
        if method == "GET":
            if path == "/api/list":
                return _list(handler, q)
            if path in ("/api/file", "/api/file/raw"):
                return _file(handler, q, raw=path.endswith("/raw"))
            if path == "/api/git/status":
                return _git_status(handler, q)
            if path == "/api/git/branches":
                return _git_branches(handler, q)
            if path == "/api/git/diff":
                return _git_diff(handler, q)
            if path in ("/api/checkpoints/list", "/api/checkpoints/diff"):
                return _checkpoints(handler, q, diff=path.endswith("diff"))
            if path == "/api/terminal/output":
                return _terminal_output(handler, q) if _terminal_allowed(handler) else bad(handler, "Terminal is local only", 403)
            if path.startswith("/api/notes/"):
                return _notes(handler, path, q)
            if path == "/api/models":
                return _models(handler)
            if path == "/api/providers":
                return _providers(handler)
            if path in ("/api/health", "/health"):
                return j(handler, {"status": "ok", "service": "jaeger-webapp", "served_by": "gateway"})
            if path == "/api/settings":
                return j(handler, {"bot_name": os.environ.get("JAEGER_WEBUI_BOT_NAME", "JaegerAI"), "served_by": "gateway"})
        if method == "POST":
            if path == "/api/terminal/start":
                return _terminal_start(handler) if _terminal_allowed(handler) else bad(handler, "Terminal is local only", 403)
            if path == "/api/terminal/input":
                return _terminal_input(handler) if _terminal_allowed(handler) else bad(handler, "Terminal is local only", 403)
            if path == "/api/terminal/close":
                return _terminal_close(handler)
            if path == "/api/default-model":
                return _set_default_model(handler)
            if path == "/api/csp-report":
                read_body(handler)
                return j(handler, {"ok": True})
    except KeyError:
        return bad(handler, "Session not found", 404)
    except ValueError as exc:
        return bad(handler, _sanitize_error(exc), 400)
    return False
