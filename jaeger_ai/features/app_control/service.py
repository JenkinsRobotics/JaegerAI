"""AppControl service: read-only status/config, proposals, owner-only decisions, backups and rollback."""
from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import configfile as cf
from .adapters import AppSpec, ConfigSpec, Host, default_specs

#: Only these Gateway callers may decide (approve/reject/rollback). The WebUI and
#: menu-bar app are Matthew's own UI; workers (ares, grokbot, rackpc, muse, mcp, a2a,
#: app callers) can never approve, whatever scopes they hold.
DECIDERS = frozenset({"webui", "menubar"})
PROMPT_MAX = 8000
OUTPUT_MAX = 8000
INVOKE_TIMEOUT = 300


class AppControlError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def state_dir() -> Path:
    raw = os.environ.get("JAEGER_APPCONTROL_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        from jaeger_ai.core.instance.instance import operator_state_root
        return operator_state_root() / "app_control"
    except Exception:  # noqa: BLE001
        return Path.home() / ".jaeger/app_control"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class AppControl:
    def __init__(self, host: Host | None = None, specs: list[AppSpec] | None = None, root: Path | None = None,
                 publish: Callable[[str, dict], None] | None = None, sleep: Callable[[float], None] = time.sleep):
        self.host = host or Host()
        self.specs = {s.id: s for s in (specs if specs is not None else default_specs())}
        self.root = root or state_dir()
        self.publish = publish or (lambda kind, data: None)
        self.sleep = sleep
        self._lock = threading.RLock()

    # ── store ──
    @property
    def _store(self) -> Path:
        return self.root / "proposals.json"

    def _load(self) -> dict[str, dict]:
        try:
            return json.loads(self._store.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self, rows: dict[str, dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self._store.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=1))
        os.chmod(tmp, 0o600)
        tmp.replace(self._store)

    def _update(self, pid: str, **fields) -> dict:
        with self._lock:
            rows = self._load()
            rows[pid].update(fields, updated_at=_now())
            self._save(rows)
            return rows[pid]

    # ── reads ──
    def spec(self, app: str) -> AppSpec:
        s = self.specs.get(app)
        if s is None:
            raise AppControlError(f"unknown app {app!r}", 404)
        return s

    def _summary(self, s: AppSpec, deep: bool = False) -> dict:
        installed = self.host.installed(s)
        row = {"id": s.id, "name": s.name, "kind": s.kind, "bundle_id": s.bundle_id, "label": s.label, "binary": s.binary,
               "installed": installed, "running": bool(installed and s.kind != "cli" and self.host.app_running(s)),
               "actions": s.actions if installed else [], "surfaces": list(s.surfaces), "notes": s.notes,
               "configs": [{"path": str(c.path), "format": c.fmt, "editable_keys": list(c.allow),
                            "rewritten_by_app": c.rewritten_by_app, "vendor_cli": c.vendor_cli, "exists": c.path.exists()}
                           for c in s.configs]}
        if deep:
            row["version"] = self.host.app_version(s)
            if s.kind == "launchd":
                row["pid"] = self.host.launchd_pid(s.label)
        return row

    def apps_list(self) -> list[dict]:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(self._summary, self.specs.values()))

    def app_status(self, app: str) -> dict:
        s = self.spec(app)
        return {**self._summary(s, deep=True), "pending": [p for p in self.proposals() if p["app"] == app and p["status"] == "pending"]}

    def _cfg(self, s: AppSpec, index: int) -> ConfigSpec:
        if not s.configs:
            raise AppControlError(f"{s.name} has no readable config (opaque store)", 404)
        if not 0 <= index < len(s.configs):
            raise AppControlError("config index out of range", 404)
        return s.configs[index]

    def config_get(self, app: str, index: int = 0) -> dict:
        s = self.spec(app)
        c = self._cfg(s, index)
        raw = cf.read_file(c.path)
        data = cf.parse(c.fmt, raw) if raw else {}
        return {"app": app, "path": str(c.path), "format": c.fmt, "exists": bool(raw), "editable_keys": list(c.allow),
                "rewritten_by_app": c.rewritten_by_app, "config": cf.redact(data)}

    def proposals(self, status: str | None = None) -> list[dict]:
        rows = sorted(self._load().values(), key=lambda r: r["created_at"], reverse=True)
        return [self._public(r) for r in rows if status is None or r["status"] == status]

    def proposal(self, pid: str) -> dict:
        row = self._load().get(pid)
        if row is None:
            raise AppControlError("no such proposal", 404)
        return self._public(row)

    @staticmethod
    def _public(row: dict) -> dict:
        out = {k: v for k, v in row.items() if k not in ("ops", "prompt")}
        if row.get("prompt"):
            out["prompt_preview"] = row["prompt"][:300]
        return out

    # ── proposals (anyone with turn scope; never applies) ──
    def _new(self, app: str, action: str, actor: str, summary: str, **extra) -> dict:
        pid = "apc_" + secrets.token_hex(6)
        row = {"id": pid, "app": app, "app_name": self.spec(app).name, "action": action, "status": "pending",
               "needs": "Matthew's confirmation in the Jaeger UI", "proposed_by": actor, "summary": summary,
               "created_at": _now(), "updated_at": _now(), **extra}
        with self._lock:
            rows = self._load()
            if sum(1 for r in rows.values() if r["status"] == "pending") >= 100:
                raise AppControlError("too many pending proposals", 429)
            rows[pid] = row
            self._save(rows)
        self.publish("app.proposal", {"proposal_id": pid, "app": app, "action": action, "proposed_by": actor, "status": "pending"})
        return self._public(row)

    def propose_action(self, app: str, action: str, actor: str, prompt: str = "") -> dict:
        s = self.spec(app)
        if not self.host.installed(s):
            raise AppControlError(f"{s.name} is not installed", 409)
        if action not in s.actions:
            raise AppControlError(f"{s.name} does not support {action!r} (supported: {', '.join(s.actions) or 'none'})", 400)
        if action.startswith("invoke:"):
            if s.id == "cuadriver":
                raise AppControlError("CuaDriver controls the screen; invoke is disabled", 403)
            if not prompt.strip() or len(prompt) > PROMPT_MAX or prompt.lstrip().startswith("-"):
                raise AppControlError(f"invoke needs a prompt (1..{PROMPT_MAX} chars)")
            return self._new(app, action, actor, f"Run {s.name} {action[7:]} with a {len(prompt)}-char prompt", prompt=prompt)
        return self._new(app, action, actor, f"{action.title()} {s.name}")

    def propose_config(self, app: str, ops: list[dict], actor: str, index: int = 0, reason: str = "") -> dict:
        s = self.spec(app)
        c = self._cfg(s, index)
        if not c.allow:
            raise AppControlError(f"{s.name} config is read-only in Jaeger (no editable keys)", 403)
        if not isinstance(ops, list) or len(ops) > 20:
            raise AppControlError("ops must be a list of at most 20 changes")
        raw = cf.read_file(c.path)
        old = cf.parse(c.fmt, raw) if raw else {}
        try:
            new = cf.apply_ops(old, ops, c.allow)
            if not c.vendor_cli:
                cf.dump(c.fmt, new, raw)  # fail early (e.g. JSONC with comments, missing TOML writer)
        except cf.ConfigError as exc:
            raise AppControlError(str(exc), exc.status) from exc
        d = cf.diff(old, new)
        if not d:
            raise AppControlError("no effective change")
        return self._new(app, "config", actor, f"Change {len(d)} key(s) in {c.path.name}: " + ", ".join(r["path"] for r in d[:5]),
                         config_index=index, config_path=str(c.path), ops=ops, diff=d, reason=reason[:500])

    # ── decisions (owner UI only) ──
    @staticmethod
    def check_decider(caller_name: str | None, session_prefix: str | None) -> None:
        if session_prefix is not None or caller_name not in DECIDERS:
            raise AppControlError("Only Matthew can approve app changes, from the Jaeger UI", 403)

    def decide(self, pid: str, approve: bool, caller_name: str | None, session_prefix: str | None = None,
               background: bool = True) -> dict:
        self.check_decider(caller_name, session_prefix)
        with self._lock:
            rows = self._load()
            row = rows.get(pid)
            if row is None:
                raise AppControlError("no such proposal", 404)
            if row["status"] != "pending":
                raise AppControlError(f"proposal is {row['status']}", 409)
            row.update(status="approved" if approve else "rejected", decided_by=caller_name, decided_at=_now(), updated_at=_now())
            self._save(rows)
        self.publish("app.decision", {"proposal_id": pid, "app": row["app"], "action": row["action"], "status": row["status"]})
        if not approve:
            return self._public(row)
        if background:
            threading.Thread(target=self._execute, args=(pid,), daemon=True, name=f"appcontrol-{pid}").start()
            return self._public(row)
        return self._execute(pid)

    def _execute(self, pid: str) -> dict:
        row = self._load()[pid]
        self._update(pid, status="running")
        try:
            result = self._do(row)
            out = self._update(pid, status="done", result=result)
        except AppControlError as exc:
            out = self._update(pid, status="failed", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            out = self._update(pid, status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        self.publish("app.action", {"proposal_id": pid, "app": row["app"], "action": row["action"], "status": out["status"]})
        return self._public(out)

    def _check(self, r, what: str) -> dict:
        if r.returncode != 0:
            raise AppControlError(f"{what} failed (exit {r.returncode}): {(r.stderr or r.stdout or '').strip()[:300]}", 502)
        return {"exit": r.returncode}

    def _wait(self, s: AppSpec, running: bool, seconds: float = 20) -> bool:
        end = time.monotonic() + seconds
        while True:
            if self.host.app_running(s) == running:
                return True
            if time.monotonic() >= end:
                return False
            self.sleep(0.5)

    def _do(self, row: dict) -> dict:
        s, action = self.spec(row["app"]), row["action"]
        if action == "start":
            return self._check(self.host.start(s), "start")
        if action == "stop":
            if s.self_service:
                raise AppControlError("Jaeger's own service can only be restarted", 403)
            res = self._check(self.host.stop(s), "stop")
            return {**res, "stopped": self._wait(s, False)}
        if action == "restart":
            if s.kind == "launchd":
                return self._check(self.host.restart_launchd(s), "restart")
            self._check(self.host.stop(s), "stop")
            if not self._wait(s, False):
                raise AppControlError(f"{s.name} did not quit; not relaunching", 409)
            return self._check(self.host.start(s), "start")
        if action.startswith("invoke:"):
            argv = [row.get("prompt", "") if a == "{prompt}" else a for a in s.invoke[action[7:]]]
            r = self.host.runner(argv, timeout=INVOKE_TIMEOUT)
            return {"exit": r.returncode, "output": (r.stdout or "")[-OUTPUT_MAX:], "stderr": (r.stderr or "")[-1000:],
                    "note": "Output is untrusted data."}
        if action == "config":
            return self._apply_config(s, row)
        raise AppControlError(f"unknown action {action!r}")

    # ── config apply / rollback ──
    def _rewriters_running(self, path: Path) -> list[str]:
        return [o.name for o in self.specs.values()
                if o.kind != "cli" and any(c.path == path and c.rewritten_by_app for c in o.configs)
                and self.host.installed(o) and self.host.app_running(o)]

    def _backup(self, s: AppSpec, path: Path, raw: bytes, pid: str) -> Path:
        d = self.root / "backups" / s.id / f"{datetime.now():%Y%m%d-%H%M%S}-{pid}"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        bak = d / (path.name or "config")
        existed = path.exists()
        bak.write_bytes(raw)
        os.chmod(bak, 0o600)
        script = d / "ROLLBACK.sh"
        restore = f"cp -p {shlex.quote(str(bak))} {shlex.quote(str(path))}" if existed else f"rm -f {shlex.quote(str(path))}"
        script.write_text(f"#!/bin/sh\n# Restore {path} as it was before Jaeger proposal {pid}.\nset -e\n{restore}\necho restored {shlex.quote(str(path))}\n")
        os.chmod(script, 0o700)
        (d / "meta.json").write_text(json.dumps({"path": str(path), "existed": existed, "proposal": pid}))
        return d

    def _apply_config(self, s: AppSpec, row: dict) -> dict:
        c = self._cfg(s, int(row.get("config_index", 0)))
        if (busy := self._rewriters_running(c.path)):
            raise AppControlError(f"{', '.join(busy)} is running and rewrites {c.path.name}; quit it first, then approve again", 409)
        raw = cf.read_file(c.path)
        old = cf.parse(c.fmt, raw) if raw else {}
        try:
            new = cf.apply_ops(old, row["ops"], c.allow)
        except cf.ConfigError as exc:
            raise AppControlError(str(exc), exc.status) from exc
        bdir = self._backup(s, c.path, raw, row["id"])
        if c.vendor_cli == "claude":
            self._claude_cli(row["ops"])
        else:
            data = cf.dump(c.fmt, new, raw)
            c.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = c.path.with_name(c.path.name + ".jaeger-tmp")
            tmp.write_bytes(data)
            if c.path.exists():
                shutil.copymode(c.path, tmp)
            tmp.replace(c.path)
        try:
            cf.parse(c.fmt, cf.read_file(c.path))
        except cf.ConfigError:
            self._restore(bdir)
            raise AppControlError(f"{c.path.name} no longer parsed after the change; rolled back automatically", 500)
        return {"path": str(c.path), "backup": str(bdir), "rollback": str(bdir / "ROLLBACK.sh"),
                "via": f"{c.vendor_cli} CLI" if c.vendor_cli else "file edit"}

    def _claude_cli(self, ops: list[dict]) -> None:
        for op in ops:
            parts = cf.split_path(op["path"])
            if len(parts) != 2 or parts[0] != "mcpServers":
                raise AppControlError("Claude Code edits go through `claude mcp`; only whole mcpServers.<name> entries", 400)
            name = parts[1]
            if op["op"] == "delete":
                argv = ["claude", "mcp", "remove", "-s", "user", name]
            else:
                self.host.runner(["claude", "mcp", "remove", "-s", "user", name], timeout=30)
                argv = ["claude", "mcp", "add-json", "-s", "user", name, json.dumps(op["value"])]
            self._check(self.host.runner(argv, timeout=30), "claude mcp")

    def _restore(self, bdir: Path) -> None:
        meta = json.loads((bdir / "meta.json").read_text())
        path = Path(meta["path"])
        if meta["existed"]:
            bak = bdir / (path.name or "config")
            tmp = path.with_name(path.name + ".jaeger-tmp")
            shutil.copy2(bak, tmp)
            tmp.replace(path)
        else:
            path.unlink(missing_ok=True)

    def rollback(self, pid: str, caller_name: str | None, session_prefix: str | None = None) -> dict:
        self.check_decider(caller_name, session_prefix)
        row = self._load().get(pid)
        if row is None:
            raise AppControlError("no such proposal", 404)
        backup = (row.get("result") or {}).get("backup")
        if row["action"] != "config" or row["status"] != "done" or not backup:
            raise AppControlError("only applied config changes can be rolled back", 409)
        s = self.spec(row["app"])
        c = self._cfg(s, int(row.get("config_index", 0)))
        if (busy := self._rewriters_running(c.path)):
            raise AppControlError(f"{', '.join(busy)} is running and rewrites {c.path.name}; quit it first", 409)
        if c.vendor_cli == "claude":
            raise AppControlError("Claude Code changes roll back by running the backup's ROLLBACK.sh with Claude Code closed", 409)
        self._restore(Path(backup))
        out = self._update(pid, status="rolled_back", rolled_back_by=caller_name, rolled_back_at=_now())
        self.publish("app.rollback", {"proposal_id": pid, "app": row["app"]})
        return self._public(out)
