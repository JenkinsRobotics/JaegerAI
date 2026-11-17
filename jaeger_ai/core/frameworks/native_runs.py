"""Hermes Runs API translation. Native agents retain execution and session ownership.

The journal is a presentation/control receipt, never a replacement agent runtime.
Disconnecting an observer does not replay a turn or discard its pending approval.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import uuid

from .resilience import failure_category, timeout_setting
from .run_ownership import Ownership

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def _profile_config_path(profile):
    """Resolve a profile's config under the shared profile tree, including
    profiles parked under ``profiles/.archive/``."""
    from jaeger_ai.core.runtime.profile_paths import hermes_profile_root

    root = hermes_profile_root() / "profiles"
    for candidate in (root / profile / "config.yaml", root / ".archive" / profile / "config.yaml"):
        if candidate.is_file():
            return candidate
    return root / profile / "config.yaml"


def profile_key(profile):
    import yaml
    path = _profile_config_path(profile)
    try:
        config = yaml.safe_load(path.read_text()) or {}
        return str(config.get("webui_gateway_api_key") or "")
    except (OSError, ValueError, yaml.YAMLError):
        return ""


class Run:
    def __init__(self, root, session, message, *, run_id=None):
        self.root = root
        self.id = run_id or uuid.uuid4().hex
        self.session = session
        self.message = message
        self.created_at = time.time()
        self.condition = threading.Condition(threading.RLock())
        self.cancelled = threading.Event()
        self.cancel_confirmed = False
        self.execution_unknown = False
        self.worker_active = False
        self.native = {}
        self.cancel_native = None
        self.status = "running"
        self.events = []
        self.pending = {}
        self.output = ""
        self.emit("run.started")

    def snapshot(self):
        with self.condition:
            return {"run_id": self.id, "session_id": self.session,
                    "status": self.status, "output": self.output,
                    "created_at": self.created_at, "input": self.message,
                    "cancellation_requested": self.cancelled.is_set(),
                    "cancellation_confirmed": self.cancel_confirmed,
                    "execution_unknown": self.execution_unknown,
                    "native": self.native,
                    "pending_approval_ids": list(self.pending),
                    "last_event_id": f"{self.id}:{len(self.events)}"}

    def emit(self, event, **payload):
        with self.condition:
            if self.status in TERMINAL:
                return
            row = {**payload, "event": event, "run_id": self.id,
                   "seq": len(self.events) + 1}
            self.events.append(row)
            if event == "message.delta":
                self.output += str(payload.get("delta") or "")
            elif event == 'message.replaced':
                self.output = str(payload.get('text') or '')
            if event.startswith("run.") and event[4:] in TERMINAL:
                self.status = event[4:]
                self.pending.clear()
            self.persist()
            self.condition.notify_all()

    def persist(self):
        path = self.root / f"{self.id}.json"
        temporary = path.with_suffix(".tmp")
        # Explicit 0600 creation avoids a window of world-readable prompts.
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump({**self.snapshot(), "events": self.events}, output)
        os.replace(temporary, path)

    def approve(self, approval_id, choice):
        with self.condition:
            pending = self.pending.get(approval_id)
            if not pending or pending["answer"] is not None or self.cancelled.is_set():
                raise KeyError("Approval is no longer active for this run")
            if choice not in pending["choices"]:
                raise ValueError("Choice is not offered by the native agent")
            pending["answer"] = choice
            self.condition.notify_all()

    def request_approval(self, description, *, choices=("once", "deny"), **metadata):
        # IDs are adapter-local and unguessable; native IDs never authorize
        # another run's request (Jaeger's native IDs reset on bridge restart).
        approval_id = uuid.uuid4().hex
        timeout = timeout_setting("JAEGER_WEBUI_APPROVAL_TIMEOUT", default=110)
        with self.condition:
            self.pending[approval_id] = {"answer": None, "choices": list(choices)}
            self.status = "awaiting_approval"
            self.emit("approval.request", approval_id=approval_id, description=description,
                      choices=list(choices), allow_permanent="always" in choices, **metadata)
            deadline = time.monotonic() + timeout
            while not self.cancelled.is_set() and self.pending[approval_id]["answer"] is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(min(remaining, 1))
            answer = self.pending.pop(approval_id)["answer"] or "deny"
            self.status = "cancelling" if self.cancelled.is_set() else "running"
            self.emit("approval.resolved", approval_id=approval_id, choice=answer)
            return answer

    def cancel(self):
        with self.condition:
            if self.status in TERMINAL:
                return False
            if self.cancelled.is_set():
                return True  # Repeat Stop observes existing intent; never resend it.
            self.cancelled.set()
            self.status = "cancelling"
            self.condition.notify_all()
            callback = self.cancel_native
        try:
            if callback:
                callback()  # Do not claim success if the native control fails.
        finally:
            with self.condition:
                self.persist()
        return True

    def dispatch(self, *, session_id, run_id, **recovery):
        """Record ownership before sending, including an ambiguous lost ACK."""
        with self.condition:
            self.execution_unknown = True
            self.native = {'session_id': session_id, 'run_id': run_id, **recovery}
            self.persist()


class Runs:
    def __init__(self, root: Path, backend, *, reconciler=None, run_type=Run):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backend = backend
        self.reconciler = reconciler
        self.run_type = run_type
        self.lock = threading.RLock()
        self.runs = {}
        self.ownership = Ownership(root)

    def start(self, session, message, workspace=None, *, run_id=None, on_admitted=None, model=None, provider=None):
        from .run_input import normalize_input, attachment_prompt
        message, attachments = normalize_input(message)
        for label, value in (("model", model), ("provider", provider)):
            if value is not None and (not isinstance(value, str) or len(value) > 512):
                raise ValueError(f"Invalid {label} override")
        if not isinstance(session, str) or not session:
            raise ValueError("A session_id and non-empty text input are required")
        with self.lock:
            if any(r.session == session and r.status not in TERMINAL for r in self.runs.values()):
                raise RuntimeError("session_busy: native work is still active; observe or stop it first")
            run_id = run_id or uuid.uuid4().hex
            if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
                raise ValueError('Invalid run identity')
            self.ownership.claim(session, run_id)
            lease = None
            run = None
            try:
                lease = self.ownership.observer_lease(run_id)
                message = attachment_prompt(self.root, run_id, message, attachments)
                run = self.run_type(self.root, session, message, run_id=run_id)
                run.model = model if model != "default" else None
                run.provider = provider
                if run.model or run.provider:
                    try:
                        from jaeger_ai.core.sessions import get_store
                        store = get_store()
                        if store is not None:
                            store.stamp_brain(session, model=run.model, provider=run.provider)
                    except Exception:
                        pass
                if on_admitted is not None:
                    on_admitted(run)  # Persist child/control ownership before dispatch.
            except Exception:
                if lease is not None:
                    os.close(lease)
                self.ownership.release(run_id)  # No worker/native dispatch exists.
                if run is not None:
                    run.emit('run.failed', error_category='dispatch_not_started', error='Admission did not complete')
                raise
            self.runs[run.id] = run
            run.worker_active = True
        try:
            threading.Thread(target=self._worker, args=(run, workspace, lease), daemon=True).start()
        except Exception:
            os.close(lease)
            run.worker_active = False
            run.emit('run.failed', error_category='dispatch_not_started', error='Worker did not start')
            self.ownership.release(run.id)
            raise
        return run.snapshot()

    def _worker(self, run, workspace, lease=None):
        try:
            if run.cancelled.is_set():
                run.cancel_confirmed = True  # No native dispatch took place.
                run.emit("run.cancelled")
                return
            run.execution_unknown = True  # Conservative default for other backends.
            run.persist()
            answer = self.backend(run, workspace)
            run.execution_unknown = False
            if run.cancel_confirmed:
                run.emit("run.cancelled")
            else:
                if answer and not run.output:
                    run.emit("message.delta", delta=answer)
                elif answer is not None and answer != run.output:
                    run.emit('message.replaced', text=answer)
                run.emit("run.completed", output=answer or run.output,
                         cancellation_requested=run.cancelled.is_set(), cancellation_confirmed=False)
        except Exception as exc:
            # A disconnect is not proof the native runtime stopped, even if a
            # cancel was requested. Keep that distinction in the failure.
            run.emit("run.failed", error=str(exc), error_category=failure_category(exc))
        finally:
            try:
                if not run.execution_unknown:
                    self.ownership.release(run.id)
            finally:
                if lease is not None:
                    os.close(lease)
                with run.condition:
                    run.worker_active = False
                    run.condition.notify_all()

    def get(self, run_id):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise KeyError("Run not found")
        with self.lock:
            if run_id in self.runs:
                return self.runs[run_id]
        path = self.root / f"{run_id}.json"
        if not path.exists():
            raise KeyError("Run not found")
        saved = json.loads(path.read_text())
        saved.setdefault('execution_unknown', saved['status'] not in {'completed', 'cancelled'})
        # Never restart native work after an adapter restart. Preserve the
        # receipt and report ambiguity, rather than inventing completion.
        if saved["status"] not in TERMINAL:
            saved["status"] = "interrupted"
            saved["execution_unknown"] = True
            saved["events"].append({"event": "run.failed", "run_id": run_id,
                "seq": len(saved["events"]) + 1, "error_category": "adapter_restarted",
                "error": "Adapter restarted; native execution state is unknown. Inspect the native session before retrying."})
        return saved

    def latest(self, sessions):
        """Find a session's latest control receipt, including after restart."""
        # Receipts are atomically replaced; the directory is already private.
        for path in sorted(self.root.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(path.stem) != 32:
                continue
            saved = json.loads(path.read_text())
            if saved.get('session_id') in sessions:
                return self.get(path.stem)
        return None

    def reconcile(self, run_id):
        """Observe the original native execution. Never redispatch or infer an abort."""
        with self.lock:
            run = self.get(run_id)
            if isinstance(run, Run) and run.worker_active:
                raise RuntimeError('observer_busy: wait for the current observer to finish')
            lease = self.ownership.observer_lease(run_id)
            try:
                # Read after acquiring the lease: another observer may just have
                # persisted its terminal result. Other processes cannot overwrite
                # recovery while this lease is held.
                self.runs.pop(run_id, None)
                run = self.get(run_id)
                saved = {**run.snapshot(), 'events': list(run.events)} if isinstance(run, Run) else run
                if saved['execution_unknown']:
                    if self.reconciler is None:
                        raise RuntimeError('Native reconciliation is not supported by this adapter yet')
                    native = saved.get('native') or {}
                    if not native.get('session_id') or not native.get('run_id'):
                        raise RuntimeError('Native identity is unknown; no safe automatic reconciliation is possible')
                    evidence = self.reconciler(dict(native))
                    if (not isinstance(evidence, dict)
                            or evidence.get('session_id') != native['session_id']
                            or evidence.get('run_id') != native['run_id']
                            or evidence.get('execution_unknown') is not False
                            or evidence.get('status') not in {'completed', 'failed', 'cancelled'}):
                        raise RuntimeError('Native execution remains unknown; session ownership is retained')
                    saved.update(status=evidence['status'], execution_unknown=False,
                                 cancellation_confirmed=evidence['status'] == 'cancelled',
                                 pending_approval_ids=[], reconciliation=evidence)
                    if 'output' in evidence:
                        saved['output'] = evidence['output']
                    saved['events'].append({'event': 'run.reconciled', 'run_id': run_id,
                        'seq': len(saved['events']) + 1, 'native_status': evidence['status'],
                        'source': evidence.get('source'), 'output': saved['output']})
                    saved['last_event_id'] = f"{run_id}:{len(saved['events'])}"
                    path = self.root / f'{run_id}.json'
                    fd = os.open(path.with_suffix('.tmp'), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, 'w') as output:
                        json.dump(saved, output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(path.with_suffix('.tmp'), path)
                    directory = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                    # Invalidate the finished in-memory observer; reads now use
                    # the durable receipt including the reconciliation event.
                    self.runs.pop(run_id, None)
                self.ownership.release(run_id)
                if not saved.get('execution_unknown') and saved.get('status') in TERMINAL:
                    try:
                        from jaeger_ai.core.gateway.webapp.service.session_unify import close_reconciled_webui_session
                        close_reconciled_webui_session(str(saved.get('session_id') or ''))
                    except Exception:
                        pass
                return {k: v for k, v in saved.items() if k != 'events'}
            finally:
                os.close(lease)


def jaeger_reconcile(native):
    from jaeger_ai.interfaces.bridge_client import jaeger_bridge
    receipt = jaeger_bridge().query('turn_status', {
        'turn_id': native['run_id'], 'session_id': native['session_id']}, timeout_s=10)
    if not isinstance(receipt, dict):
        raise RuntimeError('Invalid native turn receipt')
    return {**receipt, 'run_id': receipt.get('turn_id'),
            'output': (receipt.get('reply') or {}).get('text', '')}


def _jaeger_gateway_turn(run, session_id: str) -> dict | None:
    """Talk to the resident Gateway OWNER. The AF_UNIX bridge is a client and
    can sit in ``queued`` forever while Roundtable members appear silent."""
    import json
    import time
    import urllib.error
    import urllib.request

    from jaeger_ai.contract.ports import resolve_gateway_url
    gw = resolve_gateway_url().rstrip("/")
    from jaeger_ai.core.gateway.caller_auth import client_headers
    # Native framework runs are Jaeger's own relayed work: the least-privileged
    # ``jaegerd`` caller (read/turn; it cannot approve or administer).
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               **client_headers("jaegerd")}

    def _call(method: str, path: str, payload: dict | None = None, timeout: float = 15):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(gw + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")

    try:
        _call("POST", "/v1/sessions", {
            "session_id": session_id,
            "title": "roundtable-jaeger",
            "profile": "jaeger",
        })
    except urllib.error.HTTPError as exc:
        if exc.code not in {200, 201, 409}:
            return None
    except Exception:
        return None
    request_id = str(getattr(run, "id", "") or "") or None
    model = getattr(run, "model", None)
    body = {"text": run.message, "request_id": request_id}
    if model:
        body["model"] = model
    try:
        admitted = _call("POST", f"/v1/sessions/{session_id}/turns", body)
    except Exception:
        return None
    rid = str((admitted or {}).get("request_id") or request_id or "")
    if not rid:
        return None
    run.emit("native.state", state="running")
    # Roundtable's own stall detector (jaeger_ai/features/roundtable/progress.py)
    # deliberately does not treat a repeated "still here" signal as progress —
    # only a real state change does, and a bare REST poll produces none for the
    # whole wait. Every other member streams real tool/reasoning events the
    # whole time and gets the roomier 300s "tool" budget; this member reported
    # nothing until the end and sat on the 120s "idle" budget instead — Jaeger
    # silently failed to vote in two consecutive live Roundtable rounds this way
    # (audit, 2026-09-22), while the other members correctly kept reporting.
    # This is not a synthetic heartbeat: since the executive defaults every
    # human turn to tool-capable REACT_LOOP, a Gateway-routed Jaeger turn
    # genuinely is real agentic work, so it earns the same budget class.
    run.emit("tool.started", tool="jaeger_gateway_turn", args={"session_id": session_id})
    deadline = time.monotonic() + 300
    last = admitted
    while time.monotonic() < deadline:
        if run.cancelled.is_set():
            try:
                _call("POST", f"/v1/sessions/{session_id}/cancel", {"request_id": rid})
            except Exception:
                pass
            return {"text": "", "cancelled": True, "execution_unknown": False}
        try:
            last = _call("GET", f"/v1/sessions/{session_id}/requests/{rid}", timeout=20)
        except Exception:
            time.sleep(1.5)
            continue
        status = str((last or {}).get("status") or "")
        if status in {"completed", "failed", "cancelled", "execution_unknown"}:
            result = last.get("result") if isinstance(last, dict) else {}
            if isinstance(last.get("result_json"), str) and last.get("result_json"):
                try:
                    result = json.loads(last["result_json"])
                except Exception:
                    pass
            if not isinstance(result, dict):
                result = {}
            text = str(result.get("output") or result.get("text") or "")
            if text:
                run.emit("message.delta", delta=text)
            if status == "failed":
                raise RuntimeError(str(result.get("error") or "Jaeger gateway turn failed"))
            return {"text": text, "cancelled": status == "cancelled", "execution_unknown": status == "execution_unknown"}
        time.sleep(1.5)
    return {"text": "", "execution_unknown": True, "error": "Jaeger gateway turn timed out"}


def jaeger_turn(run, workspace=None):
    """Run a framework/Roundtable turn on Jaeger's own instance: through the
    Gateway, always (one engine, audit D1). The old AF_UNIX bridge hop and the
    in-process EntityRuntime fallback are archived on the Desktop
    (in-process-turn-runners/)."""
    native_session = str(getattr(run, 'native_session', run.session))
    run.execution_unknown = False
    run.dispatch(session_id=native_session, run_id=run.id)
    result = _jaeger_gateway_turn(run, native_session)
    if result is None:
        run.execution_unknown = False
        raise RuntimeError("The Jaeger Gateway did not accept this turn (is it running on :33418?)")
    run.execution_unknown = bool(result.get("execution_unknown"))
    run.cancel_confirmed = bool(result.get("cancelled"))
    if result.get("error") and not run.cancel_confirmed:
        raise RuntimeError(result["error"])
    return result.get("text") or ""


def _in_process_jaeger_turn(run, native_session: str) -> str:
    """Archived 2026-11-16 (audit D1): routed to the Gateway."""
    return jaeger_turn(run)


def host_workspace(workspace):
    """Translate only published mounts; never pass a container path to macOS."""
    home = Path.home()
    roots = {"/workspace": home / "workspace", "/mnt/host/GitHub": home / "GitHub",
             "/mnt/host/Desktop": home / "Desktop", "/mnt/host/Documents": home / "Documents",
             "/mnt/nas/JAEGER_NAS": Path("/Volumes/JAEGER_NAS"),
             "/mnt/nas/Personal-Drive": Path("/Volumes/Personal-Drive")}
    for prefix, host in roots.items():
        if workspace == prefix or workspace.startswith(prefix + "/"):
            mapped = (host / workspace[len(prefix):].lstrip("/")).resolve()
            if not mapped.is_relative_to(host.resolve()):
                raise ValueError("Workspace escapes its published mount")
            return str(mapped)
    raise ValueError("Workspace is not a published Mac mount")
