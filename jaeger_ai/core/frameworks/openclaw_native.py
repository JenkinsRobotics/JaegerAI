"""Opt-in OpenClaw native gateway transport, with native pairing left intact.

Protocol 4 uses signed device authentication. This client never auto-pairs,
modifies grants, or retries a dispatched chat.send after an ambiguous failure.
"""
from __future__ import annotations

import base64
import json
import queue
import threading
import time
import uuid
from pathlib import Path

from .resilience import timeout_setting, ClassifiedError

SCOPES = ["operator.read", "operator.write", "operator.approvals"]


def gateway_error(error):
    code = str(error.get("code") or "request_failed")
    message = str(error.get("message") or "connection rejected")
    category = "native_error"
    if code == "NOT_PAIRED":
        category = "pairing_required"
    elif "missing scope:" in message or code in {"FORBIDDEN", "UNAUTHORIZED"}:
        category = "permission_denied"
    elif code == "INVALID_REQUEST":
        category = "invalid_request"
    return ClassifiedError(category, f"OpenClaw {code}: {message}")


def connect_params(challenge, token, identity, scopes=None):
    scopes = list(scopes or SCOPES)
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(identity["privateKeyPem"].encode(), password=None)
    signed_at = int(challenge.get("ts") or time.time() * 1000)
    nonce = challenge["nonce"]
    payload = "|".join(["v3", identity["deviceId"], "cli", "cli", "operator",
                        ",".join(scopes), str(signed_at), token, nonce, "linux", ""])
    def encode(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")
    return {
        "minProtocol": 4, "maxProtocol": 4,
        "client": {"id": "cli", "version": "jaeger-webui-1", "platform": "linux", "mode": "cli"},
        "role": "operator", "scopes": scopes, "caps": ["tool-events"],
        "auth": {"token": token},
        "device": {"id": identity["deviceId"], "publicKey": encode(key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)),
            "signature": encode(key.sign(payload.encode())), "signedAt": signed_at, "nonce": nonce},
    }


class NativeGateway:
    def __init__(self, url, token_file, identity_file=None, *, scopes=None):
        self.scopes = list(scopes or SCOPES)
        self.url = url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        self.token_file = token_file
        self.identity_file = identity_file or Path(token_file).parent / "identity/device.json"
        self.lock = threading.Lock()
        self.pending = {}
        self.events = queue.Queue(maxsize=4096)
        self.closed = threading.Event()
        self.error = None

    def __enter__(self):
        from websockets.sync.client import connect
        self.ws = connect(self.url, open_timeout=5, close_timeout=2, max_size=4_000_000)
        try:
            challenge = json.loads(self.ws.recv(timeout=5))
            if challenge.get("event") != "connect.challenge":
                raise RuntimeError("OpenClaw did not send an authentication challenge")
            params = connect_params(challenge["payload"], Path(self.token_file).read_text().strip(),
                                    json.loads(Path(self.identity_file).read_text()), self.scopes)
            self.ws.send(json.dumps({"type": "req", "id": "connect", "method": "connect", "params": params}))
            reply = json.loads(self.ws.recv(timeout=10))
            if not reply.get("ok"):
                error = reply.get("error") or {}
                raise gateway_error(error)
            granted = reply.get("payload", {}).get("auth", {}).get("scopes", [])
            if not set(self.scopes).issubset(granted):
                raise ClassifiedError("permission_denied", "OpenClaw pairing lacks native chat/approval permissions; no turn dispatched")
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            return self
        except Exception:
            self.ws.close()
            raise

    def _read(self):
        try:
            while not self.closed.is_set():
                frame = json.loads(self.ws.recv())
                if frame.get("type") == "res":
                    with self.lock:
                        waiter = self.pending.get(frame.get("id"))
                    if waiter:
                        waiter.put_nowait(frame)
                elif frame.get("type") == "event":
                    self.events.put_nowait(frame)
        except Exception as exc:
            self.error = exc
        finally:
            self.closed.set()

    def request(self, method, params):
        rid = uuid.uuid4().hex
        waiter = queue.Queue(maxsize=1)
        with self.lock:
            self.pending[rid] = waiter
        try:
            self.ws.send(json.dumps({"type": "req", "id": rid, "method": method, "params": params}))
            deadline = time.monotonic() + 15
            while True:
                try:
                    reply = waiter.get(timeout=.2)
                    break
                except queue.Empty:
                    if self.closed.is_set():
                        raise ConnectionError("OpenClaw disconnected; native execution state may be unknown")
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"OpenClaw {method} acknowledgement timed out; request not replayed")
            if not reply.get("ok"):
                error = reply.get("error") or {}
                raise gateway_error(error)
            return reply.get("payload") or {}
        finally:
            with self.lock:
                self.pending.pop(rid, None)

    def next_event(self):
        deadline = time.monotonic() + timeout_setting("OPENCLAW_ADAPTER_IDLE_TIMEOUT", 120)
        while True:
            try:
                return self.events.get(timeout=.2)
            except queue.Empty:
                if self.closed.is_set():
                    raise ConnectionError("OpenClaw event connection closed; inspect native session before retrying")
                if time.monotonic() >= deadline:
                    raise TimeoutError("OpenClaw event transport is silent; this is not an outage diagnosis")

    def __exit__(self, *_):
        self.closed.set()
        self.ws.close()
        self.reader.join(3)


def message_text(message):
    content = (message or {}).get("content", [])
    if isinstance(content, str):
        return content
    return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")


def native_session_key(session):
    return f"agent:main:openai-user:hermes:{session}"


def _terminal_from_agent_wait(native_id, session_id, receipt):
    if receipt.get("runId") not in {None, native_id}:
        raise ClassifiedError("invalid_response", "OpenClaw returned a receipt for another run")
    status = receipt.get("status")
    stop_reason = str(receipt.get("stopReason") or "").lower()
    confirmed_cancel = (
        status == "timeout"
        and stop_reason in {"aborted", "cancelled", "rpc", "stop", "user"}
        and isinstance(receipt.get("endedAt"), (int, float))
    )
    if status in {"timeout", "pending"} and not confirmed_cancel:
        raise RuntimeError(f"OpenClaw native run is not terminal: {status}")
    if status not in {"ok", "error", "timeout"}:
        raise ClassifiedError("invalid_response", f"OpenClaw returned an invalid run status: {status}")
    terminal = "cancelled" if confirmed_cancel else (
        "completed" if status == "ok" else "failed"
    )
    terminal_reply = receipt.get("terminalReply") or {}
    output = terminal_reply.get("text", "") if terminal_reply.get("disposition") == "visible" else ""
    return {
        "run_id": native_id,
        "session_id": session_id,
        "status": terminal,
        "execution_unknown": False,
        "output": output,
        "source": "openclaw_agent_wait",
    }


def _terminal_from_trajectory(native_id, session_id):
    """Read OpenClaw's durable local receipt when its gateway is unavailable."""
    from .openclaw import _openclaw_home

    terminal = None
    output = ""
    for path in (_openclaw_home() / "agents/main/sessions").glob("*.trajectory.jsonl"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as rows:
                for line in rows:
                    try:
                        row = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if row.get("runId") != native_id or row.get("sessionKey") != session_id:
                        continue
                    data = row.get("data") if isinstance(row.get("data"), dict) else {}
                    texts = data.get("assistantTexts")
                    if isinstance(texts, list):
                        output = "\n".join(str(text) for text in texts if text is not None)
                    if row.get("type") == "session.ended":
                        terminal = data
        except OSError:
            continue
    if terminal is None:
        raise RuntimeError("OpenClaw native run has no terminal trajectory receipt")
    if terminal.get("aborted") or terminal.get("externalAbort"):
        status = "cancelled"
    elif terminal.get("status") == "success":
        status = "completed"
    else:
        status = "failed"
    return {
        "run_id": native_id,
        "session_id": session_id,
        "status": status,
        "execution_unknown": False,
        "output": output,
        "source": "openclaw_trajectory_receipt",
    }


def openclaw_reconcile(native):
    """Resolve from live ``agent.wait`` or OpenClaw's durable trajectory."""
    from .openclaw import OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE

    native_id = str(native.get("run_id") or "")
    session_id = str(native.get("session_id") or "")
    if not native_id or not session_id:
        raise ClassifiedError("invalid_response", "Native identity missing for reconciliation")
    try:
        with NativeGateway(OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE) as gateway:
            receipt = gateway.request("agent.wait", {"runId": native_id, "timeoutMs": 1})
    except (OSError, ConnectionError, TimeoutError):
        return _terminal_from_trajectory(native_id, session_id)
    return _terminal_from_agent_wait(native_id, session_id, receipt)


def openclaw_turn(run, workspace=None):
    from .openclaw import OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE
    # Identical to the existing REST adapter's user=hermes:<session> mapping.
    session_key = native_session_key(run.session)
    run.execution_unknown = False  # Authentication failure cannot execute a turn.
    with NativeGateway(OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE) as gateway:
        if run.cancelled.is_set():
            run.cancel_confirmed = True
            return ""
        model = getattr(run, "model", None)
        if model:
            catalog = gateway.request("models.list", {}).get("models", [])
            matches = [row for row in catalog if model in {row.get("id"), str(row.get("provider")) + "/" + str(row.get("id"))}]
            provider = getattr(run, "provider", None)
            exact = [row for row in matches if row.get("provider") == provider]
            if exact:
                matches = exact
            elif provider and provider not in {
                'ollama', 'ollama-mac', 'ollama-rack', 'ollama-cloud', 'ollama-local',
                'ollama-cloud-via-host',
            }:
                matches = []
            # WebUI picker IDs are Jaeger catalog names. If OpenClaw does not
            # have that exact row, keep the session's configured primary model
            # instead of failing the whole Roundtable seat.
            if len(matches) == 1:
                chosen = matches[0]
                inventory = gateway.request("sessions.list", {"limit": 1000})
                current = next((row for row in inventory.get("sessions", []) if row.get("key") == session_key), inventory.get("defaults", {}))
                if (current.get("modelProvider"), current.get("model")) != (chosen["provider"], chosen["id"]):
                    try:
                        with NativeGateway(OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE,
                                           scopes=[*SCOPES, "operator.admin"]) as settings:
                            settings.request("sessions.patch", {"key": session_key,
                                "model": chosen["provider"] + "/" + chosen["id"]})
                    except Exception:
                        pass
            else:
                run.emit('native.state', state='running',
                         message='OpenClaw kept its configured model; the WebUI picker id is not in its catalog')
        run.dispatch(session_id=session_key, run_id=run.id)
        sent = gateway.request("chat.send", {"sessionKey": session_key, "message": run.message,
                                              "idempotencyKey": run.id})
        native_id = sent.get("runId") or run.id
        run.dispatch(session_id=session_key, run_id=native_id)
        run.cancel_native = lambda: gateway.request("chat.abort", {"sessionKey": session_key, "runId": native_id})
        if run.cancelled.is_set():
            run.cancel_native()
        seen_approvals = set()
        while True:
            frame = gateway.next_event()
            event, payload = frame.get("event"), frame.get("payload") or {}
            if event in {"exec.approval.requested", "plugin.approval.requested"}:
                request = payload.get("request") or {}
                # Never relay an approval for another session or concurrent run.
                if request.get("sessionKey") != session_key or request.get("runId") != native_id:
                    continue
                native_approval = payload.get("id")
                if not native_approval or native_approval in seen_approvals:
                    continue
                seen_approvals.add(native_approval)
                allowed = request.get("allowedDecisions") or ["allow-once", "deny"]
                mapping = {"allow-once": "once", "allow-always": "always", "deny": "deny"}
                choices = tuple(mapping[c] for c in allowed if c in mapping)
                answer = run.request_approval(request.get("description") or request.get("command") or "OpenClaw tool approval",
                    choices=choices, tool=request.get("toolName", "exec"), command=request.get("command", ""))
                gateway.request(event.replace("requested", "resolve"),
                                {"id": native_approval, "decision": {v:k for k,v in mapping.items()}[answer]})
                continue
            if payload.get("runId") != native_id:
                continue
            if event == 'agent' and payload.get('stream') == 'lifecycle' and (payload.get('data') or {}).get('phase') == 'start':
                run.emit('native.state', state='running')
            if event == "agent" and payload.get("stream") == "tool":
                data = payload.get("data") or {}
                done = data.get("phase") in {"result", "error"}
                run.emit("tool.completed" if done else "tool.started", tool=data.get("name", "tool"),
                    tool_call_id=data.get("toolCallId"), args=data.get("args", {}),
                    status="error" if data.get("isError") else "completed" if done else "running")
            elif event == "chat":
                state = payload.get("state")
                if state == "delta":
                    if payload.get("replace"):
                        # Full snapshot replacement is not an append operation.
                        continue
                    run.emit("message.delta", delta=payload.get("deltaText") or "")
                elif state == "final":
                    run.execution_unknown = False
                    return message_text(payload.get("message")) or run.output
                elif state == "aborted":
                    run.execution_unknown = False
                    run.cancelled.set()
                    run.cancel_confirmed = True
                    return run.output
                elif state == "error":
                    run.execution_unknown = False
                    raise RuntimeError(payload.get("errorMessage") or "OpenClaw native run failed")
