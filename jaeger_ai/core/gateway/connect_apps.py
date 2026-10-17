"""Connect Apps: a static registry plus read-only probes and one owner-only install.

Nothing here takes a path, argument or flag from a request. The ``code`` CLI
comes from a fixed candidate list, the vsix only from :data:`APPS_IDE_DIR`
(realpath-checked, size-capped, sha256 recorded), ``argv.json`` is read for
one key and never written, and the install is a fixed argv with
``shell=False``. Probes never create directories.

Test/smoke overrides (gateway env, never a request): ``JAEGER_CONNECT_APPS_CODE_CLI``
(the only CLI tried when set), ``JAEGER_CONNECT_APPS_ARGV``, ``JAEGER_CONNECT_APPS_DIR``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "assets" / "connect_apps" / "registry.json"
APPS_IDE_DIR = Path("~/.jaeger/apps/ide")
ARGV_PATH = Path("~/.vscode/argv.json")
CODE_CLI_CANDIDATES = (
    "/usr/local/bin/code",
    "/opt/homebrew/bin/code",
    "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
    "~/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
)
VSIX_MAX_BYTES = 50 * 1024 * 1024
PINNED_VSCODE = "1.142."
PROBE_TTL_S = 30.0
INSTALL_TIMEOUT_S = 120
PROBE_TIMEOUT_S = 15
OWNER_INSTALL_CALLERS = frozenset({"webui", "menubar", "cli"})
_VSIX_RE = re.compile(r"^jaeger-chat-(\d+)\.(\d+)\.(\d+)\.vsix$")

Runner = Callable[..., subprocess.CompletedProcess]


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for app in data.get("apps", []):
        if str(app.get("icon") or "").lower().startswith("http"):
            raise ValueError(f"connect app {app.get('id')!r}: icons must be local")
        if app.get("status") == "coming_soon" and app.get("actions"):
            raise ValueError(f"connect app {app.get('id')!r}: coming_soon apps have no actions")
    return data


def _redact(text: str) -> str:
    return text.replace(str(Path.home()), "~")[-2048:]


def _strip_jsonc(text: str) -> str:
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True; out.append(ch)
        elif text.startswith("//", i):
            j = text.find("\n", i); i = n if j < 0 else j; continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        else:
            out.append(ch)
        i += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(out))


class ConnectApps:
    def __init__(self, *, registry_path: Path = REGISTRY_PATH, runner: Runner = subprocess.run,
                 environ: dict[str, str] | None = None, clock: Callable[[], float] = time.time) -> None:
        self.registry_path = registry_path
        self.runner = runner
        self.env = os.environ if environ is None else environ
        self.clock = clock
        self._cache: dict[str, dict[str, Any]] = {}
        self._installing: set[str] = set()
        self._lock = threading.Lock()

    # ── paths (fixed; env overrides are gateway-side only) ──────────────
    def apps_dir(self) -> Path:
        return Path(self.env.get("JAEGER_CONNECT_APPS_DIR") or APPS_IDE_DIR).expanduser()

    def argv_path(self) -> Path:
        return Path(self.env.get("JAEGER_CONNECT_APPS_ARGV") or ARGV_PATH).expanduser()

    def code_cli(self) -> str | None:
        override = self.env.get("JAEGER_CONNECT_APPS_CODE_CLI")
        candidates = [override] if override else [*CODE_CLI_CANDIDATES, shutil.which("code") or ""]
        for raw in candidates:
            if not raw:
                continue
            path = Path(raw).expanduser()
            if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
                return str(path)
        return None

    # ── registry ────────────────────────────────────────────────────────
    def registry(self) -> dict[str, Any]:
        return load_registry(self.registry_path)

    def app(self, app_id: str) -> dict[str, Any] | None:
        return next((a for a in self.registry().get("apps", []) if a.get("id") == app_id), None)

    # ── probes (read-only) ──────────────────────────────────────────────
    def find_vsix(self) -> dict[str, Any] | None:
        root = self.apps_dir()
        if not root.is_dir():
            return None
        real_root = root.resolve()
        best = None
        for entry in root.iterdir():
            match = _VSIX_RE.match(entry.name)
            if not match:
                continue
            real = entry.resolve()
            if real.parent != real_root or not real.is_file() or real.stat().st_size > VSIX_MAX_BYTES:
                continue
            ver = tuple(int(x) for x in match.groups())
            if best is None or ver > best[0]:
                best = (ver, real)
        if best is None:
            return None
        ver, real = best
        return {"path": str(real), "name": real.name, "version": ".".join(map(str, ver)),
                "sha256": hashlib.sha256(real.read_bytes()).hexdigest()}

    def argv_has_proposed_api(self, extension_id: str) -> bool | None:
        path = self.argv_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return False
        allowed = data.get("enable-proposed-api") if isinstance(data, dict) else None
        return isinstance(allowed, list) and extension_id in allowed

    def _probe_vscode(self, app: dict[str, Any]) -> dict[str, Any]:
        ext = app["state_probe"]["extension_id"]
        now = self.clock()
        code = self.code_cli()
        if code is None:
            return {"value": "needs_setup", "detail": "code_cli_missing", "checked_at": now}
        try:
            listed = self.runner([code, "--list-extensions", "--show-versions"], shell=False,
                                 capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
            version_out = self.runner([code, "--version"], shell=False, capture_output=True,
                                      text=True, timeout=PROBE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"value": "error", "detail": _redact(str(exc)), "checked_at": now}
        installed = None
        for line in (listed.stdout or "").splitlines():
            name, _, ver = line.strip().partition("@")
            if name.lower() == ext.lower():
                installed = ver or None
        state: dict[str, Any] = {"checked_at": now}
        vscode_version = ((version_out.stdout or "").splitlines() or [""])[0].strip()
        if installed:
            state.update(value="installed", version=installed)
        elif not self.apps_dir().is_dir():
            state.update(value="needs_setup", detail="apps_dir_missing")
        elif self.find_vsix() is None:
            state.update(value="needs_setup", detail="vsix_missing")
        elif not self.argv_has_proposed_api(app["state_probe"].get("argv_proposed_api") or ext):
            state.update(value="needs_setup", detail="argv_missing")
        elif vscode_version and not vscode_version.startswith(PINNED_VSCODE):
            state.update(value="needs_setup", detail="vscode_version_mismatch")
        else:
            state.update(value="not_installed")
        if vscode_version:
            state["vscode_version"] = vscode_version
        return state

    def state(self, app_id: str, *, refresh: bool = False) -> dict[str, Any] | None:
        app = self.app(app_id)
        if app is None:
            return None
        with self._lock:
            if app_id in self._installing:
                return {"value": "installing", "checked_at": self.clock()}
            cached = self._cache.get(app_id)
        if cached and not refresh and self.clock() - cached["checked_at"] < PROBE_TTL_S:
            return cached
        if app.get("status") == "coming_soon" or app.get("kind") == "placeholder":
            state = {"value": "coming_soon", "checked_at": self.clock()}
        elif app.get("kind") == "vscode_extension":
            state = self._probe_vscode(app)
        else:
            state = {"value": "error", "detail": "unknown_kind", "checked_at": self.clock()}
        with self._lock:
            self._cache[app_id] = state
        return state

    def listing(self) -> dict[str, Any]:
        reg = self.registry()
        apps = [{**app, "state": self.state(app["id"])} for app in reg.get("apps", [])]
        return {"version": reg.get("version"), "categories": reg.get("categories", []), "apps": apps,
                "connected_count": sum(1 for a in apps if a["state"]["value"] == "installed")}

    # ── install (owner-only, confirmed, one at a time) ──────────────────
    def begin_install(self, app_id: str) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
        """Admission. Returns (status, body, plan); a plan means: run :meth:`run_install`."""
        app = self.app(app_id)
        if app is None:
            return 404, {"error": "Unknown app"}, None
        if app.get("status") == "coming_soon" or "install" not in (app.get("actions") or []):
            return 409, {"error": "App cannot be installed", "state": self.state(app_id)}, None
        with self._lock:
            if self._installing:
                return 409, {"error": "An install is already running",
                             "state": {"value": "installing", "checked_at": self.clock()}}, None
        state = self.state(app_id, refresh=True) or {}
        code, vsix = self.code_cli(), self.find_vsix()
        if code is None:
            return 409, {"error": "VS Code 'code' CLI not found", "state": state}, None
        if vsix is None:
            return 409, {"error": "Jaeger Chat vsix not found", "state": state}, None
        if state.get("value") == "installed" and state.get("version") == vsix["version"]:
            return 200, {"id": app_id, "changed": False, "state": state}, None
        with self._lock:
            if self._installing:
                return 409, {"error": "An install is already running"}, None
            self._installing.add(app_id)
        return 202, {"id": app_id, "state": "installing", "vsix": vsix["name"],
                     "version": vsix["version"]}, {"code": code, "vsix": vsix}

    def run_install(self, app_id: str, plan: dict[str, Any], *, caller: str) -> dict[str, Any]:
        """Run the fixed argv; returns {state, audit}. Always clears the in-flight flag."""
        started = self.clock()
        argv = [plan["code"], "--install-extension", plan["vsix"]["path"]]
        exit_code: int | None = None
        try:
            done = self.runner(argv, shell=False, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S)
            exit_code = done.returncode
            failure = None if done.returncode == 0 else _redact(done.stderr or done.stdout or "")
        except subprocess.TimeoutExpired:
            failure = "timeout"
        except (OSError, subprocess.SubprocessError) as exc:
            failure = _redact(str(exc))
        finally:
            with self._lock:
                self._installing.discard(app_id)
                self._cache.pop(app_id, None)
        state = ({"value": "error", "detail": failure, "checked_at": self.clock()}
                 if failure is not None else self.state(app_id, refresh=True))
        audit = {"caller": caller, "app_id": app_id, "vsix": plan["vsix"]["name"],
                 "sha256": plan["vsix"]["sha256"], "version": plan["vsix"]["version"],
                 "exit_code": exit_code, "duration_ms": int((self.clock() - started) * 1000),
                 "at": started}
        return {"state": state, "audit": audit}


__all__ = ["APPS_IDE_DIR", "ConnectApps", "OWNER_INSTALL_CALLERS", "load_registry"]
