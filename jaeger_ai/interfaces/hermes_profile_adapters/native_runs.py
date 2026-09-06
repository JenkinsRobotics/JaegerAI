"""Hermes Runs API translation. Native agents retain execution and session ownership.

The journal is a presentation/control receipt, never a replacement agent runtime.
Disconnecting an observer does not replay a turn or discard its pending approval.
"""
from __future__ import annotations

import json
import hmac
import os
from pathlib import Path
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

from .resilience import failure_category, timeout_setting
from .run_ownership import Ownership

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def profile_key(profile):
    import yaml
    path = Path.home() / ".hermes/profiles" / profile / "config.yaml"
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
            row = {"event": event, "run_id": self.id,
                   "seq": len(self.events) + 1, **payload}
            self.events.append(row)
            if event == "message.delta":
                self.output += str(payload.get("delta") or "")
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

    def dispatch(self, *, session_id, run_id):
        """Record ownership before sending, including an ambiguous lost ACK."""
        with self.condition:
            self.execution_unknown = True
            self.native = {'session_id': session_id, 'run_id': run_id}
            self.persist()


class Runs:
    def __init__(self, root: Path, backend, *, reconciler=None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backend = backend
        self.reconciler = reconciler
        self.lock = threading.RLock()
        self.runs = {}
        self.ownership = Ownership(root)

    def start(self, session, message, workspace=None):
        if not isinstance(session, str) or not session or not isinstance(message, str) or not message.strip():
            raise ValueError("A session_id and non-empty text input are required")
        with self.lock:
            if any(r.session == session and r.status not in TERMINAL for r in self.runs.values()):
                raise RuntimeError("session_busy: native work is still active; observe or stop it first")
            run_id = uuid.uuid4().hex
            self.ownership.claim(session, run_id)
            lease = None
            try:
                lease = self.ownership.observer_lease(run_id)
                run = Run(self.root, session, message, run_id=run_id)
            except Exception:
                if lease is not None:
                    os.close(lease)
                self.ownership.release(run_id)  # No worker/native dispatch exists.
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
                run.worker_active = False

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
                return {k: v for k, v in saved.items() if k != 'events'}
            finally:
                os.close(lease)


class RunsHTTP:
    """Mixin for existing profile servers; preserves legacy completion clients."""
    def native_route(self, method):
        parsed = urlsplit(self.path)
        if parsed.path == "/v1/capabilities":
            self.native_json(200, {"streaming": True, "features": {
                "approval_events": True, "run_approval_response": True,
                "approval_identity_v1": True, "tool_events": True,
                "cancellation": True, "event_replay": True}})
            return True
        if not parsed.path.startswith("/v1/runs"):
            return False
        if self.headers.get('Origin'):
            self.close_connection = True
            self.native_json(403, {'error': 'Use the authenticated WebUI server proxy'})
            return True
        expected = self.native_key()
        if not expected or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + expected):
            self.close_connection = True
            self.native_json(401, {"error": "Native run access requires the profile gateway credential"})
            return True
        try:
            runs = self.native_runs()
            parts = parsed.path.strip("/").split("/")
            if parts[:2] != ["v1", "runs"]:
                raise KeyError("Route not found")
            if method == "POST":
                if self.headers.get('Transfer-Encoding'):
                    raise ValueError('Transfer-Encoding is not supported')
                if len(self.headers.get_all('Content-Length', [])) != 1:
                    raise ValueError('Exactly one Content-Length is required')
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Content-Type must be application/json")
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 1_000_000:
                    raise ValueError("Invalid request size")
                self.connection.settimeout(15)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Request must be a JSON object")
                if parts == ["v1", "runs"]:
                    result = runs.start(str(body.get("session_id") or self.headers.get("X-Hermes-Session-Id") or ""),
                                        body.get("input") or body.get("message"), body.get("workspace"))
                    self.native_json(200, result)
                    return True
            if len(parts) not in (3, 4):
                raise KeyError("Route not found")
            run = runs.get(parts[2])
            if method == 'POST' and len(parts) == 4 and parts[3] == 'reconcile':
                self.native_json(200, runs.reconcile(parts[2]))
            elif method == "GET" and len(parts) == 3:
                self.native_json(200, run.snapshot() if isinstance(run, Run) else {k:v for k,v in run.items() if k != "events"})
            elif method == "GET" and len(parts) == 4 and parts[3] == "events":
                cursor = parse_qs(parsed.query).get("after_seq", [self.headers.get("Last-Event-ID", "0")])[0]
                after = max(0, int(cursor.rsplit(":", 1)[-1]))
                self.native_events(run, after)
            elif method == "POST" and len(parts) == 4 and isinstance(run, Run):
                if parts[3] in {"cancel", "stop"}:
                    accepted = run.cancel()
                elif parts[3] == "approval":
                    run.approve(str(body.get("approval_id") or ""), str(body.get("choice") or ""))
                    accepted = True
                else:
                    raise KeyError("Route not found")
                self.native_json(200, {"ok": accepted, "status": "accepted" if accepted else "not-active"})
            else:
                raise KeyError("Route not found")
        except (KeyError, ValueError, RuntimeError) as exc:
            self.close_connection = True
            self.native_json(404 if isinstance(exc, KeyError) else 409 if isinstance(exc, RuntimeError) else 400, {"error": str(exc)})
        except OSError as exc:
            self.native_json(502, {"error": str(exc), "error_category": failure_category(exc)})
        return True

    def native_json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def native_events(self, run, after):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                if isinstance(run, Run):
                    with run.condition:
                        rows = list(run.events[after:])
                        terminal = run.status in TERMINAL
                else:
                    rows, terminal = run["events"][after:], True
                for row in rows:
                    self.wfile.write(f"id: {row['run_id']}:{row['seq']}\ndata: {json.dumps(row)}\n\n".encode())
                    after = row["seq"]
                if terminal:
                    self.wfile.write(b"data: [DONE]\n\n")
                else:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                if terminal:
                    break
                with run.condition:
                    if len(run.events) == after and run.status not in TERMINAL:
                        run.condition.wait(1)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Observer disconnect is not permission to retry the work.


def jaeger_reconcile(native):
    from jaeger_ai.interfaces.hermes_webui_adapter.bridge_client import BridgeClient
    receipt = BridgeClient('jaeger').query('turn_status', {
        'turn_id': native['run_id'], 'session_id': native['session_id']}, timeout_s=10)
    if not isinstance(receipt, dict):
        raise RuntimeError('Invalid native turn receipt')
    return {**receipt, 'run_id': receipt.get('turn_id'),
            'output': (receipt.get('reply') or {}).get('text', '')}


def jaeger_turn(run, workspace=None):
    from jaeger_ai.interfaces.hermes_webui_adapter.bridge_client import BridgeClient
    run.execution_unknown = False
    bridge = BridgeClient("jaeger")
    if workspace:
        workspace = host_workspace(workspace)
    accepted = threading.Event()

    def cancel():
        if accepted.is_set():
            bridge.control("cancel", turn_id=run.id)

    run.cancel_native = cancel

    def event(frame):
        kind = frame.get("type")
        if kind in {"queued", "state"}:
            accepted.set()
            if run.cancelled.is_set():
                cancel()
        if kind == "delta":
            run.emit("message.delta", delta=frame.get("text", ""))
        elif kind == "reasoning":
            run.emit("reasoning.available", text=frame.get("text", ""))
        elif kind == "tool":
            done = frame.get("phase") in {"done", "error"}
            run.emit("tool.completed" if done else "tool.started", tool=frame.get("name"),
                     args=frame.get("args", {}), preview=frame.get("detail", ""),
                     status="error" if frame.get("phase") == "error" else "completed" if done else "running")

    def approval(frame):
        if frame.get("kind") != "approval":
            run.emit("reasoning.available", text="Native clarification needs a reply in Jaeger's native session.")
            return "deny"
        return run.request_approval(frame.get("prompt", "Tool approval required"),
                                    choices=tuple(frame.get("options") or ["once", "deny"]))

    run.dispatch(session_id=run.session, run_id=run.id)
    result = bridge.turn(run.message, run.session, event, approval, turn_id=run.id, workspace=workspace)
    run.execution_unknown = result.get("execution_unknown", False) is not False
    if run.execution_unknown:
        raise RuntimeError(result.get("error") or "Native terminal receipt is uncertain; reconcile before retrying")
    run.cancel_confirmed = bool(result.get("cancelled"))
    if result.get("error") and not run.cancel_confirmed:
        raise RuntimeError(result["error"])
    return result.get("text") or ""


def host_workspace(workspace):
    """Translate only published mounts; never pass a container path to macOS."""
    home = Path.home()
    roots = {"/workspace": home / "workspace", "/mnt/host/GitHub": home / "GitHub",
             "/mnt/host/Desktop": home / "Desktop", "/mnt/host/Documents": home / "Documents",
             "/mnt/nas/Jenkins_Robotics": Path("/Volumes/Jenkins_Robotics"),
             "/mnt/nas/Personal-Drive": Path("/Volumes/Personal-Drive")}
    for prefix, host in roots.items():
        if workspace == prefix or workspace.startswith(prefix + "/"):
            mapped = (host / workspace[len(prefix):].lstrip("/")).resolve()
            if not mapped.is_relative_to(host.resolve()):
                raise ValueError("Workspace escapes its published mount")
            return str(mapped)
    raise ValueError("Workspace is not a published Mac mount")
