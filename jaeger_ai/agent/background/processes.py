"""Background process manager.

``run_python`` / ``run_in_venv`` are SYNCHRONOUS — they block the agent
turn and are capped (10s / 300s) so a turn can't hang. They're for
"test this snippet."

This module is the other primitive: a process that **outlives the
turn**. The agent starts it, gets a handle, and checks on it later —
for things that genuinely take minutes/hours (a long render, a bot
that stays connected, a watcher). Each process:

  • runs detached (``start_new_session=True``) so it survives the
    TUI session that launched it
  • streams stdout+stderr to ``<instance>/processes/<id>/output.log``
  • has metadata in ``<instance>/processes/<id>/meta.json``

Scope: background processes run a Python script against the instance
venv (consistent with ``run_in_venv`` — installed packages are
visible). Generic shell is deliberately out — that's a separate,
higher-risk capability.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any


def _processes_root(layout: Any) -> Path:
    return layout.root / "processes"


def _proc_dir(layout: Any, proc_id: str) -> Path:
    return _processes_root(layout) / proc_id


def _pid_alive(pid: int) -> bool:
    """True when ``pid`` names a live process. ``os.kill(pid, 0)`` is a
    no-op signal that raises if the process is gone."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    return True


def _read_meta(proc_dir: Path) -> dict[str, Any] | None:
    meta_path = proc_dir / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write_meta(proc_dir: Path, meta: dict[str, Any]) -> None:
    (proc_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def _refresh_status(proc_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Reconcile a process's recorded status with reality. If meta says
    'running' but the pid is dead, flip to 'exited' and stamp the
    finish time + exit code (read from the rc file the wrapper drops).

    Also stamps ``notified=False`` on the running→terminal transition so
    ``consume_pending_completions`` can later surface the event to the
    agent exactly once. We never *clear* notified here — only the
    consume call flips it to True."""
    if meta.get("status") != "running":
        return meta
    pid = int(meta.get("pid", 0) or 0)
    if _pid_alive(pid):
        return meta
    # Process is gone — finalize.
    meta["status"] = "exited"
    meta["finished_at"] = meta.get("finished_at") or time.time()
    rc_file = proc_dir / "exit_code"
    if rc_file.is_file():
        try:
            meta["exit_code"] = int(rc_file.read_text().strip())
        except Exception:  # noqa: BLE001
            meta["exit_code"] = meta.get("exit_code")
    # First observation of completion — queue a notification.
    meta.setdefault("notified", False)
    _write_meta(proc_dir, meta)
    return meta


# ── Public API ──────────────────────────────────────────────────────


def start_background(
    layout: Any,
    code: str,
    *,
    name: str = "",
) -> dict[str, Any]:
    """Launch ``code`` as a detached background Python process.

    The code runs against the instance venv (installed packages
    visible). Returns ``{ok, process_id, name, pid}`` or
    ``{ok: False, error: ...}``."""
    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}

    from jaeger_ai.core.runtime.venv import ensure_venv, venv_python
    try:
        ensure_venv(layout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not create instance venv: {exc}"}

    proc_id = "proc_" + uuid.uuid4().hex[:10]
    proc_dir = _proc_dir(layout, proc_id)
    proc_dir.mkdir(parents=True, exist_ok=True)
    script = proc_dir / "script.py"
    script.write_text(cleaned, encoding="utf-8")
    log_path = proc_dir / "output.log"

    py = str(venv_python(layout))
    # A tiny shell wrapper runs the script then records the exit code,
    # so list/status can report it after the process is long gone.
    rc_file = proc_dir / "exit_code"
    wrapper = (
        f'{py} -u "{script}" > "{log_path}" 2>&1; '
        f'echo $? > "{rc_file}"'
    )
    try:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", wrapper],
            cwd=str(proc_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach — survives the TUI session
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"failed to launch: {exc}"}

    meta = {
        "process_id": proc_id,
        "name": name or proc_id,
        "pid": proc.pid,
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "exit_code": None,
        # No notification pending while the process is still running.
        # _refresh_status flips this to False on the running→terminal
        # transition; consume_pending_completions flips it back to True
        # once surfaced to the agent.
        "notified": True,
    }
    _write_meta(proc_dir, meta)
    return {"ok": True, "process_id": proc_id, "name": meta["name"],
            "pid": proc.pid}


def list_background(layout: Any) -> dict[str, Any]:
    """List every background process for this instance with live
    status (running / exited + exit code + elapsed)."""
    root = _processes_root(layout)
    if not root.is_dir():
        return {"processes": [], "count": 0}
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = _read_meta(child)
        if meta is None:
            continue
        meta = _refresh_status(child, meta)
        started = meta.get("started_at") or 0
        finished = meta.get("finished_at")
        elapsed = ((finished or time.time()) - started) if started else 0
        out.append({
            "process_id": meta["process_id"],
            "name": meta["name"],
            "status": meta["status"],
            "pid": meta.get("pid"),
            "exit_code": meta.get("exit_code"),
            "elapsed_s": round(elapsed, 1),
        })
    return {"processes": out, "count": len(out)}


def process_status(
    layout: Any, process_id: str, *, lines: int = 20,
) -> dict[str, Any]:
    """Detailed status for one background process + the last ``lines``
    lines of its output (default 20, max 2000)."""
    proc_dir = _proc_dir(layout, process_id)
    meta = _read_meta(proc_dir)
    if meta is None:
        return {"ok": False, "error": f"no process {process_id!r}"}
    meta = _refresh_status(proc_dir, meta)
    log_path = proc_dir / "output.log"
    n = max(1, min(int(lines or 20), 2000))
    tail = ""
    if log_path.is_file():
        log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(log_lines[-n:])
    started = meta.get("started_at") or 0
    finished = meta.get("finished_at")
    return {
        "ok": True,
        "process_id": meta["process_id"],
        "name": meta["name"],
        "status": meta["status"],
        "pid": meta.get("pid"),
        "exit_code": meta.get("exit_code"),
        "elapsed_s": round(((finished or time.time()) - started)
                           if started else 0, 1),
        "output_tail": tail,
    }


def stop_background(layout: Any, process_id: str) -> dict[str, Any]:
    """Terminate a running background process (SIGTERM the session)."""
    proc_dir = _proc_dir(layout, process_id)
    meta = _read_meta(proc_dir)
    if meta is None:
        return {"ok": False, "error": f"no process {process_id!r}"}
    meta = _refresh_status(proc_dir, meta)
    if meta["status"] != "running":
        return {"ok": True, "process_id": process_id,
                "note": f"already {meta['status']}"}
    pid = int(meta.get("pid", 0) or 0)
    try:
        # The process was started with start_new_session — it's a
        # session leader, so signalling the process group reaps the
        # shell wrapper + the python child together.
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not stop {process_id}: {exc}"}
    meta["status"] = "stopped"
    meta["finished_at"] = time.time()
    # Explicit stops are user-initiated — the agent already knows the
    # process ended, so skip the notification (notified=True).
    meta["notified"] = True
    _write_meta(proc_dir, meta)
    return {"ok": True, "process_id": process_id, "status": "stopped"}


def consume_pending_completions(layout: Any) -> list[dict[str, Any]]:
    """Return every newly-completed background process whose completion
    has not yet been surfaced to the agent — and mark each one notified
    so the next call returns only the newer ones.

    The returned dicts carry just what the heartbeat / status pane needs
    to render a one-line "task X finished with code Y" note. Callers
    that want fuller detail can follow up with ``process_status``.

    Used by the agent's heartbeat / status surface — see
    :mod:`jaeger_os.agent.tools.background.pending_background`. Idempotent
    on an empty queue."""
    root = _processes_root(layout)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = _read_meta(child)
        if meta is None:
            continue
        meta = _refresh_status(child, meta)
        if meta.get("status") == "running":
            continue
        if meta.get("notified", True):
            continue
        out.append({
            "process_id": meta.get("process_id"),
            "name": meta.get("name"),
            "status": meta.get("status"),
            "exit_code": meta.get("exit_code"),
            "finished_at": meta.get("finished_at"),
        })
        meta["notified"] = True
        _write_meta(child, meta)
    return out
