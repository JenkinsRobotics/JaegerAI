"""Subscription CLIs as model providers (no API keys).

Jaeger runs the CLIs Matthew already installed and signed in to (Codex, Claude Code, Cursor agent,
Gemini) as subprocesses, the same way he would from a terminal. It never reads, copies or prints their
credentials: sign-in state comes from each CLI's own status command, or (Gemini, which has none) from
whether its credential file exists, checked with os.path.exists only. Jaeger never runs a login.

State: <state>/providers/cli.json  {id: {"enabled": bool, "models": [..]}} (written only when changed).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

HOME = Path.home()
EXTRA_PATH = [str(HOME / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\[\]=,-]{0,80}$")
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}
_last_error: dict[str, str] = {}
TTL = 60


def _env() -> dict:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(EXTRA_PATH + [p for p in env.get("PATH", "").split(os.pathsep) if p not in EXTRA_PATH])
    env.setdefault("NO_COLOR", "1")
    return env


def _which(binary: str) -> str | None:
    return shutil.which(binary, path=_env()["PATH"])


def _run(args: list[str], timeout: float = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_env(), stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir())
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, exc.__class__.__name__


def _first_line(s: str) -> str:
    return next((ln.strip() for ln in s.splitlines() if ln.strip()), "")[:120]


# ── per-CLI knowledge ────────────────────────────────────────────────

def _codex_signin(path: str) -> tuple[bool | None, str]:
    code, out = _run([path, "login", "status"])
    ok = code == 0 and "logged in" in out.lower() and "not logged in" not in out.lower()
    return ok, (_first_line(out) if ok else "Run `codex login` in Terminal")


def _claude_signin(path: str) -> tuple[bool | None, str]:
    code, out = _run([path, "auth", "status"])
    m = re.search(r'"loggedIn"\s*:\s*(true|false)', out)
    if m:
        ok = m.group(1) == "true"
        meth = re.search(r'"authMethod"\s*:\s*"([^"]+)"', out)
        return ok, (f"Signed in ({meth.group(1)})" if ok and meth else "Signed in" if ok else "Run `claude` then /login in Terminal")
    return None, "Couldn't read `claude auth status`"


def _cursor_signin(path: str) -> tuple[bool | None, str]:
    code, out = _run([path, "status"], timeout=20)
    low = out.lower()
    if "not logged in" in low:
        return False, "Run `cursor-agent login` in Terminal"
    if code == 0 and ("logged in" in low or "@" in out):
        return True, "Signed in"
    return None, _first_line(out) or "Unknown"


def _gemini_signin(path: str) -> tuple[bool | None, str]:
    # Gemini CLI has no status command; presence of its credential file only (never opened).
    gdir = HOME / ".gemini"
    auth_type = None
    try:
        auth_type = (json.loads((gdir / "settings.json").read_text("utf-8")).get("security", {}).get("auth", {}) or {}).get("selectedType")
    except (OSError, ValueError, AttributeError):
        pass
    if os.path.exists(gdir / "oauth_creds.json") or auth_type:
        return True, f"Credentials present ({auth_type or 'oauth'}); verified on first run"
    return False, "Run `gemini` in Terminal and sign in with Google"


def _codex_models(path: str) -> list[dict]:
    try:
        data = json.loads((HOME / ".codex" / "models_cache.json").read_text("utf-8"))
    except (OSError, ValueError):
        return []
    return [{"id": m["slug"], "label": m.get("display_name") or m["slug"], "context": m.get("context_window")}
            for m in data.get("models", []) if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list"]


def _cursor_models(path: str) -> list[dict]:
    code, out = _run([path, "models"], timeout=30)
    if code != 0:
        return []
    ids = []
    for ln in out.splitlines():
        m = re.match(r"^\s*[-*]?\s*([A-Za-z0-9][A-Za-z0-9._-]+)\b(?:\s+-\s+(.*))?$", ln)
        if m and not ln.lower().startswith(("available", "tip", "loading")):
            ids.append({"id": m.group(1), "label": (m.group(2) or m.group(1)).strip()})
    return ids


SPECS: dict[str, dict] = {
    "codex": {"label": "OpenAI Codex", "bin": "codex", "signin": _codex_signin, "models": _codex_models,
              "login": "codex login", "streams": "messages"},
    "claude": {"label": "Claude Code", "bin": "claude", "signin": _claude_signin,
               # Aliases documented by `claude --help` ("an alias for the latest model, e.g. 'sonnet' or 'opus'").
               "models": lambda p: [{"id": a, "label": f"Claude {a.title()} (latest)"} for a in ("sonnet", "opus", "haiku")],
               "login": "claude, then /login", "streams": "tokens"},
    "cursor": {"label": "Cursor Agent", "bin": "cursor-agent", "signin": _cursor_signin, "models": _cursor_models,
               "login": "cursor-agent login", "streams": "tokens"},
    "gemini": {"label": "Gemini CLI", "bin": "gemini", "signin": _gemini_signin,
               "models": lambda p: [{"id": "auto", "label": "Gemini CLI default"}],
               "login": "gemini, then Sign in with Google", "streams": "tokens"},
}


# ── VS Code Copilot bridge (Jaeger IDE extension ≥ 0.3.0) ─────────────
# The extension writes ~/.jaeger/run/vscode-bridge.json (0600) with a per-start token. Jaeger reads it to
# call the bridge on 127.0.0.1; the token never leaves this process (not returned, not logged).
VSCODE_EXT_GLOB = "jenkins-robotics.jaeger-ide-*"
CODE_PLIST = Path("/Applications/Visual Studio Code.app/Contents/Info.plist")


def _bridge_file() -> Path:
    return HOME / ".jaeger" / "run" / "vscode-bridge.json"


def _bridge_installed() -> bool:
    return any((d / "copilot-bridge.js").exists() for d in (HOME / ".vscode" / "extensions").glob(VSCODE_EXT_GLOB))


def _vscode_version() -> str | None:
    try:
        import plistlib
        with CODE_PLIST.open("rb") as f:
            return "VS Code " + str(plistlib.load(f).get("CFBundleShortVersionString"))
    except (OSError, ValueError):
        return None


def _bridge_info() -> dict | None:
    try:
        info = json.loads(_bridge_file().read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict) or not isinstance(info.get("port"), int) or not isinstance(info.get("token"), str):
        return None
    pid = info.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None  # stale file from a VS Code that quit
        except PermissionError:
            pass
    return info


def _bridge_req(info: dict, method: str, path: str, body: dict | None = None, timeout: float = 3):
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{info['port']}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {info['token']}", "Content-Type": "application/json", "Host": f"127.0.0.1:{info['port']}"})
    return urllib.request.urlopen(req, timeout=timeout)


def _vscode_row() -> dict:
    code = _which("code")
    row = {"id": "vscode", "label": "VS Code Copilot", "kind": "vscode", "installed": False, "path": code, "version": _vscode_version(),
           "signed_in": None, "status_note": "", "login_command": "", "streams": "tokens", "models": [], "bridge": "not-installed",
           "install_command": None}
    vsix = sorted((HOME / ".jaeger" / "ide-dist").glob("jaeger-ide-*.vsix"), key=lambda p: p.stat().st_mtime)
    row["install_command"] = f'code --install-extension "{vsix[-1]}"' if vsix else None
    if not _bridge_installed():
        row.update(status_note="Bridge not installed: install the Jaeger IDE extension 0.3.0+ in VS Code", bridge="not-installed")
        return row
    row["installed"] = True
    info = _bridge_info()
    if not info:
        row.update(status_note="VS Code not running (or the Copilot bridge is turned off in VS Code)", bridge="not-running")
        return row
    try:
        with _bridge_req(info, "GET", "/health") as r:
            health = json.loads(r.read())
        with _bridge_req(info, "GET", "/models", timeout=8) as r:
            models = json.loads(r.read()).get("models", [])
    except Exception as exc:  # noqa: BLE001
        row.update(status_note=f"VS Code bridge not answering ({exc.__class__.__name__})", bridge="not-running")
        return row
    row["models"] = [{"id": m["id"], "label": m.get("name") or m["id"], "context": m.get("max_input_tokens")} for m in models if isinstance(m, dict) and m.get("id")]
    consent = health.get("consent")
    if not row["models"]:
        row.update(signed_in=False, status_note="No Copilot models in VS Code: sign in to GitHub Copilot there", bridge="running", login_command="VS Code → Accounts → Sign in with GitHub")
    elif consent == "needed":
        row.update(signed_in=True, status_note="Waiting for your OK: in VS Code run “Jaeger: Allow Copilot for Jaeger” and click Allow", bridge="needs-consent")
    else:
        row.update(signed_in=True, status_note=f"Bridge running in {health.get('vscode') and 'VS Code ' + health['vscode'] or 'VS Code'}" + ("" if consent == "granted" else "; VS Code asks for consent on first use"), bridge="running")
    return row


def _vscode_stream(row: dict, model: str, prompt: str, timeout: float = 300):
    info = _bridge_info()
    if not info:
        yield {"type": "error", "error": "VS Code not running, or the Copilot bridge is off"}
        return
    import urllib.error
    t0 = time.perf_counter()
    try:
        with _bridge_req(info, "POST", "/chat", {"model": model, "prompt": prompt}, timeout=timeout) as r:
            for line in r:
                if not line.strip():
                    continue
                ev = json.loads(line)
                if ev.get("type") == "start":
                    yield {"type": "start", "model": f"cli:vscode:{model}", "local": False}
                elif ev.get("type") == "delta":
                    yield {"type": "delta", "text": ev.get("text", "")}
                elif ev.get("type") == "done":
                    _last_error.pop("vscode", None)
                    yield {**{k: ev.get(k) for k in ("elapsed_s", "ttft_s", "eval_count", "prompt_eval_count", "tokens_per_s")}, "type": "done", "model": f"cli:vscode:{model}", "load_s": None, "cost_usd": None, "source": "VS Code Copilot"}
                    return
                elif ev.get("type") == "error":
                    msg = f"Copilot: {ev.get('error')}"[:300]
                    _last_error["vscode"] = msg
                    yield {"type": "error", "error": msg}
                    return
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error")
        except ValueError:
            msg = None
        yield {"type": "error", "error": f"VS Code bridge {exc.code}: {msg or exc.reason}"}
        return
    except (OSError, ValueError) as exc:
        yield {"type": "error", "error": f"VS Code bridge unreachable ({exc.__class__.__name__})"}
        return
    yield {"type": "error", "error": f"VS Code bridge ended without an answer after {time.perf_counter() - t0:.1f}s"}


def known(pid: str) -> bool:
    return pid in SPECS or pid == "vscode"


def _state_path() -> Path:
    root = Path(os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_STATE_DIR") or HOME / ".jaeger")
    return root / "providers" / "cli.json"


def _settings() -> dict:
    try:
        d = json.loads(_state_path().read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}



_bg: dict = {"thread": None}


def _probe_all() -> list[dict]:
    data = []
    for pid, spec in SPECS.items():
        path = _which(spec["bin"])
        row = {"id": pid, "label": spec["label"], "kind": "cli", "installed": bool(path), "path": path, "version": None,
               "signed_in": None, "status_note": "Not installed", "login_command": spec["login"], "streams": spec["streams"], "models": []}
        if path:
            code, out = _run([path, "--version"], timeout=10)
            row["version"] = _first_line(out) if code == 0 else None
            row["signed_in"], row["status_note"] = spec["signin"](path)
            row["models"] = spec["models"](path) if row["signed_in"] is not False else []
        data.append(row)
    data.append(_vscode_row())
    return data


def _placeholder() -> list[dict]:
    """Instant first answer: PATH lookup only (no subprocesses); filled in by the background probe."""
    return [{"id": pid, "label": spec["label"], "kind": "cli", "installed": bool(_which(spec["bin"])), "path": _which(spec["bin"]),
             "version": None, "signed_in": None, "status_note": "Checking…", "login_command": spec["login"],
             "streams": spec["streams"], "models": []} for pid, spec in SPECS.items()]


def _refresh_bg() -> bool:
    """Start one background probe unless one is running. Returns True while a probe is in flight."""
    with _lock:
        t = _bg["thread"]
        if t is not None and t.is_alive():
            return True

        def run():
            try:
                data = _probe_all()
                with _lock:
                    _cache.update(at=time.time(), data=data)
            finally:
                _bg["thread"] = None
        t = threading.Thread(target=run, name="cli-providers-probe", daemon=True)
        _bg["thread"] = t
        t.start()
        return True


def detect_status(refresh: bool = False) -> dict:
    """Fast GET: cached rows (possibly stale) + a background refresh. refresh=True probes synchronously."""
    if refresh:
        detect(refresh=True)
    with _lock:
        data, at = _cache["data"], _cache["at"]
        running = _bg["thread"] is not None and _bg["thread"].is_alive()
    stale = data is None or time.time() - at >= TTL
    if stale and not running:
        running = _refresh_bg()
    rows = _decorate(data) if data is not None else [{**r, "state": "checking"} for r in _decorate(_placeholder())]
    return {"providers": rows, "stale": stale,
            "refreshing": running, "checked_at": at or None}


def detect(refresh: bool = False) -> list[dict]:
    with _lock:
        fresh = not refresh and _cache["data"] is not None and time.time() - _cache["at"] < TTL
        data = _cache["data"] if fresh else None
    if data is None:
        data = _probe_all()
        with _lock:
            _cache.update(at=time.time(), data=data)
    return _decorate(data)


def _decorate(data: list[dict]) -> list[dict]:
    st = _settings()
    out = []
    for row in data:
        s = st.get(row["id"], {})
        enabled = bool(s.get("enabled", bool(row["signed_in"])))
        chosen = [m for m in s.get("models", []) if isinstance(m, str)] or [m["id"] for m in row["models"]]
        bridge = row.get("bridge")
        state = ("not-installed" if not row["installed"] else "not-running" if bridge == "not-running" else "needs-consent" if bridge == "needs-consent"
                 else "needs-sign-in" if row["signed_in"] is False else "error" if row["id"] in _last_error else "ready")
        out.append({**row, "enabled": enabled and row["installed"], "selected_models": chosen, "state": state,
                    "last_error": _last_error.get(row["id"])})
    return out


def update(pid: str, body: dict) -> dict:
    if not known(pid):
        raise KeyError(pid)
    # Validate requested fields before reading state or creating lock files.
    patch = {}
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise ValueError("enabled must be a boolean")
        patch["enabled"] = body["enabled"]
    if "models" in body:
        ms = body["models"]
        if not isinstance(ms, list) or not all(isinstance(m, str) and MODEL_RE.match(m) for m in ms) or len(ms) > 40:
            raise ValueError("models must be a list of model ids")
        patch["models"] = list(dict.fromkeys(ms))

    import hashlib
    from jaeger_ai.core.instance.atomic_files import mutate_json

    p = _state_path()
    try:
        try:
            raw = p.read_bytes()
        except FileNotFoundError:
            raw = None
        # Decode the exact bytes whose revision fences the transaction. The
        # generic JSON helper also accepts UTF-16/BOM; this owner's contract does not.
        st = json.loads(raw.decode("utf-8")) if raw is not None else {}
        if not isinstance(st, dict):
            raise ValueError("expected a settings object")
    except (OSError, ValueError):
        raise ValueError("Existing CLI provider settings could not be read; no changes saved") from None
    if not isinstance(st.get(pid, {}), dict):
        raise ValueError("Existing CLI provider settings entry must be an object; no changes saved")
    revision = hashlib.sha256(raw).hexdigest() if raw is not None else "missing"

    def change(current):
        # mutate_json has checked the exact revision and holds the document lock.
        return {**current, pid: {**current.get(pid, {}), **patch}}

    try:
        mutate_json(p, change, expected_revision=revision, default={})
    except ValueError:
        raise ValueError("CLI provider settings changed or writer is busy; refresh before saving again") from None
    except OSError:
        # Replacement may precede a directory-fsync failure. Never claim that
        # nothing was saved, or replay a command with an uncertain outcome.
        raise ValueError("CLI provider settings save could not be confirmed; reload saved settings before trying again") from None
    try:
        return next(r for r in detect() if r["id"] == pid)
    except Exception:
        raise ValueError("CLI provider settings saved, but provider status could not be read; refresh before saving again") from None


# ── running a prompt ─────────────────────────────────────────────────

def command(pid: str, path: str, model: str, prompt: str, cwd: str) -> list[str]:
    m = [] if model in ("", "auto") else ["--model", model]
    if pid == "codex":
        return [path, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", cwd, *(["-m", model] if model not in ("", "auto") else []), prompt]
    if pid == "claude":
        return [path, "-p", prompt, "--output-format", "stream-json", "--verbose", "--include-partial-messages", *m]
    if pid == "cursor":
        return [path, "-p", "--output-format", "stream-json", "--stream-partial-output", *m, prompt]
    if pid == "gemini":
        return [path, "-p", prompt, "-o", "stream-json", *(["-m", model] if model not in ("", "auto") else [])]
    raise KeyError(pid)


def parse(pid: str, ev: dict) -> list[dict]:
    """Map one CLI JSON line to compare events: delta / usage (merged into done) / error."""
    t = ev.get("type")
    if pid == "codex":
        item = ev.get("item") or {}
        if t == "item.completed" and item.get("type") == "agent_message":
            return [{"type": "delta", "text": item.get("text", "")}]
        if t == "item.completed" and item.get("type") == "reasoning" and item.get("text"):
            return [{"type": "thinking", "text": item["text"]}]
        if t == "turn.completed":
            u = ev.get("usage") or {}
            return [{"type": "usage", "eval_count": u.get("output_tokens"), "prompt_eval_count": u.get("input_tokens")}]
        if t in ("turn.failed", "error"):
            msg = (ev.get("error") or {}).get("message") if t == "turn.failed" else ev.get("message")
            try:
                msg = json.loads(msg)["error"]["message"]
            except (TypeError, ValueError, KeyError):
                pass
            return [{"type": "error", "error": f"Codex: {msg}"[:300]}]
        return []
    if pid == "claude":
        if t == "stream_event":
            d = (ev.get("event") or {}).get("delta") or {}
            if d.get("type") == "text_delta":
                return [{"type": "delta", "text": d.get("text", "")}]
            if d.get("type") == "thinking_delta":
                return [{"type": "thinking", "text": d.get("thinking", "")}]
            return []
        if t == "result":
            if ev.get("is_error"):
                return [{"type": "error", "error": f"Claude Code: {ev.get('result') or ev.get('subtype')}"[:300]}]
            u = ev.get("usage") or {}
            return [{"type": "usage", "eval_count": u.get("output_tokens"), "prompt_eval_count": u.get("input_tokens"), "cost_usd": ev.get("total_cost_usd")}]
        return []
    if pid == "cursor":
        if t == "assistant":
            parts = ((ev.get("message") or {}).get("content")) or []
            return [{"type": "delta", "text": "".join(p.get("text", "") for p in parts if isinstance(p, dict))}]
        if t == "result":
            if ev.get("is_error"):
                return [{"type": "error", "error": f"Cursor: {ev.get('result')}"[:300]}]
            return [{"type": "usage"}]
        return []
    if pid == "gemini":
        if t == "message" and ev.get("role") == "assistant":
            return [{"type": "delta", "text": ev.get("content", "")}]
        if t == "result":
            if ev.get("status") not in (None, "success"):
                return [{"type": "error", "error": f"Gemini: {(ev.get('error') or {}).get('message') or ev.get('status')}"[:300]}]
            s = (ev.get("stats") or {})
            return [{"type": "usage", "eval_count": s.get("output_tokens"), "prompt_eval_count": s.get("input_tokens")}]
        if t == "error":
            return [{"type": "error", "error": f"Gemini: {ev.get('message')}"[:300]}]
    return []


def _stderr_reason(tail: str) -> str:
    m = re.search(r"reasonMessage:\s*'([^']+)'", tail) or re.search(r"(?:Error[^:\n]*|error):\s*([^\n]{8,})", tail)
    return (m.group(1) if m else _first_line(tail))[:240]


def stream(pid: str, model: str, prompt: str, popen=subprocess.Popen, timeout: float = 600):
    rows = {r["id"]: r for r in detect()}
    row = rows.get(pid)
    if not row or not row["installed"]:
        yield {"type": "error", "error": f"{row['label']}: {row['status_note']}" if row and pid == "vscode" else f"{pid} CLI is not installed"}
        return
    if row.get("bridge") == "not-running":
        yield {"type": "error", "error": f"{row['label']}: {row['status_note']}"}
        return
    if row["signed_in"] is False:
        yield {"type": "error", "error": f"{row['label']} needs sign-in: {row['status_note'] if pid == 'vscode' else 'run `' + row['login_command'] + '` in Terminal'}"}
        return
    if not row["enabled"]:
        yield {"type": "error", "error": f"{row['label']} is turned off in Settings → Providers"}
        return
    if pid == "vscode":
        yield from _vscode_stream(row, model, prompt)
        return
    t0 = time.perf_counter(); ttft = None; usage: dict = {}; got_text = False; failed = None
    yield {"type": "start", "model": f"cli:{pid}:{model}", "local": False}
    with tempfile.TemporaryDirectory(prefix="jaeger-compare-") as cwd:
        try:
            proc = popen(command(pid, row["path"], model, prompt, cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                         cwd=cwd, env=_env(), text=True, bufsize=1)
        except OSError as exc:
            yield {"type": "error", "error": f"{row['label']}: could not start ({exc.__class__.__name__})"}
            return
        timer = threading.Timer(timeout, proc.kill); timer.start()
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                for out in parse(pid, ev):
                    if out["type"] == "usage":
                        usage.update({k: v for k, v in out.items() if k != "type" and v is not None})
                    elif out["type"] == "error":
                        failed = out["error"]
                    else:
                        if ttft is None and out.get("text"):
                            ttft = time.perf_counter() - t0
                        got_text = got_text or (out["type"] == "delta" and bool(out.get("text")))
                        yield out
            proc.wait()
            err_tail = (proc.stderr.read() if proc.stderr else "")[-4000:]
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
    if failed or (proc.returncode not in (0, None) and not got_text):
        msg = failed or f"{row['label']} exited {proc.returncode}: {_stderr_reason(err_tail) or 'no output'}"
        _last_error[pid] = msg
        yield {"type": "error", "error": msg}
        return
    _last_error.pop(pid, None)
    elapsed = time.perf_counter() - t0
    ec = usage.get("eval_count")
    gen = elapsed - (ttft or 0)
    yield {"type": "done", "model": f"cli:{pid}:{model}", "elapsed_s": round(elapsed, 2), "ttft_s": None if ttft is None else round(ttft, 2),
           "eval_count": ec, "prompt_eval_count": usage.get("prompt_eval_count"),
           # CLIs report totals, not generation time; tok/s is output tokens over wall time after the first token.
           "tokens_per_s": round(ec / gen, 1) if ec and gen > 0.05 and SPECS[pid]["streams"] == "tokens" else None, "load_s": None,
           "cost_usd": usage.get("cost_usd"), "source": row["label"]}
