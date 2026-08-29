"""Loopback runner adapter for the genuine Hermes WebUI.

This process does not serve a browser application. Hermes WebUI owns the UI on
port 8790 and calls this service through its built-in ``runner-local`` adapter.
Jaeger remains the sole owner of inference, tools, sessions, and approvals.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .bridge_client import BridgeClient, WebBridgeError

MAX_BODY = 1_000_000
_RUN_ROUTE = re.compile(r"^/v1/runs/([^/]+)(?:/(events|cancel|approval|messages))?$")
_CLARIFY_ROUTE = re.compile(r"^/v1/runs/([^/]+)/clarifications/([^/]+)/respond$")
_GOAL_ROUTE = re.compile(r"^/v1/sessions/([^/]+)/goal$")


class ApprovalBroker:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: dict[str, dict[str, Any]] = {}

    def request(self, frame: dict[str, Any]) -> str:
        request_id = str(frame.get("id") or uuid.uuid4().hex)
        with self._condition:
            self._pending[request_id] = {
                **frame,
                "id": request_id,
                "created_at": time.time(),
                "answer": None,
            }
            self._condition.notify_all()
            deadline = time.monotonic() + 120
            while self._pending[request_id]["answer"] is None and time.monotonic() < deadline:
                self._condition.wait(timeout=1)
            answer = str(self._pending[request_id].get("answer") or "deny")
            self._pending.pop(request_id, None)
            return answer

    def list(self) -> list[dict[str, Any]]:
        with self._condition:
            return [
                {key: value for key, value in row.items() if key != "answer"}
                for row in self._pending.values()
            ]

    def respond(self, request_id: str, answer: str) -> bool:
        if answer not in {"once", "always", "deny"}:
            raise ValueError("answer must be once, always, or deny")
        with self._condition:
            if request_id not in self._pending:
                return False
            self._pending[request_id]["answer"] = answer
            self._condition.notify_all()
            return True


class RunStore:
    """Small durable event store owned by the Jaeger instance."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._runs: dict[str, dict[str, Any]] = {}
        for path in self.root.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict) and value.get("run_id"):
                    self._runs[str(value["run_id"])] = value
            except (OSError, json.JSONDecodeError):
                continue

    def create(self, *, run_id: str, session_id: str, prompt: str) -> dict[str, Any]:
        now = time.time()
        record = {
            "run_id": run_id,
            "session_id": session_id,
            "prompt": prompt,
            "status": "running",
            "terminal_state": None,
            "active_controls": ["cancel", "approval"],
            "pending_approval_id": None,
            "events": [],
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._runs[run_id] = record
            self._persist(record)
            return dict(record)

    def append(self, run_id: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = self._require(run_id)
            seq = len(record["events"]) + 1
            row = {
                "event_id": f"{run_id}:{seq}",
                "seq": seq,
                "event": event,
                "payload": payload,
            }
            record["events"].append(row)
            record["updated_at"] = time.time()
            self._persist(record)
            return dict(row)

    def set_state(self, run_id: str, **changes: Any) -> None:
        with self._lock:
            record = self._require(run_id)
            record.update(changes)
            record["updated_at"] = time.time()
            self._persist(record)

    def events_after(self, run_id: str, cursor: str | None) -> dict[str, Any]:
        with self._lock:
            record = self._require(run_id)
            after = self._cursor_seq(cursor)
            rows = [dict(row) for row in record["events"] if int(row.get("seq") or 0) > after]
            next_cursor = str(rows[-1]["seq"]) if rows else str(after)
            return {
                "run_id": run_id,
                "events": rows,
                "cursor": next_cursor,
                "last_event_id": rows[-1]["event_id"] if rows else None,
            }

    def status(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._require(run_id)
            events = record.get("events") or []
            return {
                "run_id": run_id,
                "session_id": record["session_id"],
                "status": record["status"],
                "terminal_state": record.get("terminal_state"),
                "last_event_id": events[-1]["event_id"] if events else None,
                "active_controls": list(record.get("active_controls") or []),
                "pending_approval_id": record.get("pending_approval_id"),
            }

    def _require(self, run_id: str) -> dict[str, Any]:
        if run_id not in self._runs:
            raise KeyError("run not found")
        return self._runs[run_id]

    def _persist(self, record: dict[str, Any]) -> None:
        path = self.root / f"{record['run_id']}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    @staticmethod
    def _cursor_seq(cursor: str | None) -> int:
        text = str(cursor or "").strip()
        if not text:
            return 0
        if ":" in text:
            text = text.rsplit(":", 1)[-1]
        try:
            return max(0, int(text))
        except ValueError:
            return 0


class RunnerBroker:
    def __init__(self, bridge: BridgeClient, approvals: ApprovalBroker, store: RunStore) -> None:
        self.bridge = bridge
        self.approvals = approvals
        self.store = store

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(request.get("message") or "").strip()
        session_id = str(request.get("session_id") or "").strip()
        if not text or not session_id:
            raise ValueError("message and session_id are required")
        run_id = uuid.uuid4().hex
        self.store.create(run_id=run_id, session_id=session_id, prompt=text)
        threading.Thread(
            target=self._worker,
            args=(run_id, request),
            daemon=True,
            name=f"jaeger-runner-{run_id[:8]}",
        ).start()
        return {
            "run_id": run_id,
            "stream_id": run_id,
            "session_id": session_id,
            "status": "running",
            "started_at": time.time(),
            "active_controls": ["cancel", "approval"],
        }

    def _worker(self, run_id: str, request: dict[str, Any]) -> None:
        text = str(request["message"])
        session_id = str(request["session_id"])
        emitted_text = False
        try:
            model = str(request.get("model") or "").strip()
            provider = str(request.get("provider") or "").strip()
            if model:
                self.bridge.command("configure_model", {
                    "provider": self._jaeger_provider(provider, model),
                    "model": model,
                })

            def on_event(frame: dict[str, Any]) -> None:
                nonlocal emitted_text
                event, payload = self._translate_frame(run_id, session_id, frame)
                if event:
                    if event == "token" and payload.get("text"):
                        emitted_text = True
                    self.store.append(run_id, event, payload)

            def on_request(frame: dict[str, Any]) -> str:
                approval_id = str(frame.get("id") or uuid.uuid4().hex)
                self.store.set_state(run_id, pending_approval_id=approval_id)
                try:
                    on_event({**frame, "id": approval_id, "type": "request"})
                    return self.approvals.request({**frame, "id": approval_id, "run_id": run_id})
                finally:
                    self.store.set_state(run_id, pending_approval_id=None)

            result = self.bridge.turn(text, session_id, on_event, on_request)
            error = str(result.get("error") or "").strip()
            answer = str(result.get("text") or "")
            if error:
                self.store.append(run_id, "apperror", {
                    "type": "error",
                    "message": error,
                    "session_id": session_id,
                    "stream_id": run_id,
                })
                self.store.set_state(run_id, status="failed", terminal_state="failed", active_controls=[])
                return
            if answer and not emitted_text:
                self.store.append(run_id, "token", {"text": answer})
            session = self._session_snapshot(session_id, text, answer)
            self.store.append(run_id, "done", {
                "status": "completed",
                "session_id": session_id,
                "stream_id": run_id,
                "session": session,
            })
            self.store.set_state(run_id, status="completed", terminal_state="completed", active_controls=[])
        except Exception as exc:  # noqa: BLE001
            self.store.append(run_id, "apperror", {
                "type": "error",
                "message": str(exc),
                "session_id": session_id,
                "stream_id": run_id,
            })
            self.store.set_state(run_id, status="failed", terminal_state="failed", active_controls=[])

    def _jaeger_provider(self, requested: str, model: str) -> str:
        """Translate a WebUI transport provider into Jaeger's model owner."""
        requested = requested.strip().lower()
        if requested in {"ollama-local", "ollama-cloud"}:
            # The genuine Hermes WebUI splits the Mac Ollama daemon's catalog
            # into user-facing local/cloud lanes.  Both lanes still execute
            # through that one local daemon; cloud tags are Ollama-authenticated
            # proxies, not a second direct https://ollama.com connection.
            return "ollama"
        if requested in {
            "local", "ollama", "ollama-cloud", "lmstudio",
            "openai", "anthropic", "gemini", "xai",
        }:
            return requested
        catalog = self.bridge.query("model_catalog")
        rows = catalog.get("models") if isinstance(catalog, dict) else []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if model in {str(row.get("id") or ""), str(row.get("model") or ""), str(row.get("name") or "")}:
                owner = str(row.get("provider") or "").strip().lower()
                if owner:
                    return owner
        # Hermes custom OpenAI-compatible providers commonly arrive as
        # ``openai-api``. Jaeger owns endpoint selection, so unresolved models
        # default to the Mac's local Ollama instead of inheriting Hermes state.
        return "ollama"

    def _session_snapshot(self, session_id: str, prompt: str, answer: str) -> dict[str, Any]:
        rows = self.bridge.query("load_session", {"id": session_id, "resume": False})
        messages = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                messages.append({
                    "role": str(row.get("role") or "assistant"),
                    "content": str(row.get("text") or row.get("content") or ""),
                    "_ts": row.get("ts") or row.get("timestamp") or time.time(),
                })
        if not messages:
            messages = [
                {"role": "user", "content": prompt, "_ts": time.time()},
                {"role": "assistant", "content": answer, "_ts": time.time()},
            ]
        title = next(
            (str(row.get("content") or "")[:80] for row in messages if row.get("role") == "user"),
            "Jaeger conversation",
        )
        return {
            "session_id": session_id,
            "title": title,
            "messages": messages,
            "message_count": len(messages),
            "tool_calls": [],
            "updated_at": time.time(),
        }

    @staticmethod
    def _translate_frame(run_id: str, session_id: str, frame: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        kind = str(frame.get("type") or "")
        if kind == "delta":
            return "token", {"text": str(frame.get("text") or "")}
        if kind == "reasoning":
            return "reasoning", {"text": str(frame.get("text") or "")}
        if kind == "tool":
            status = str(frame.get("status") or "").lower()
            event = "tool_complete" if status in {"complete", "completed", "done", "error", "failed"} else "tool"
            return event, {
                "name": str(frame.get("name") or frame.get("tool") or "tool"),
                "args": frame.get("args") or frame.get("arguments") or {},
                "result": frame.get("result"),
                "is_error": status in {"error", "failed"},
            }
        if kind == "request":
            approval_id = str(frame.get("id") or "")
            return "approval", {
                "approval_id": approval_id,
                "run_id": run_id,
                "description": str(frame.get("prompt") or frame.get("message") or "Tool approval required"),
                "command": str(frame.get("command") or ""),
                "options": frame.get("options") or ["once", "always", "deny"],
                "session_id": session_id,
            }
        return None, {}

    def cancel(self, run_id: str) -> dict[str, Any]:
        status = self.store.status(run_id)
        if status["terminal_state"]:
            return {"ok": False, "status": "not-active", "message": "Run is not active."}
        self.bridge.control("cancel")
        self.store.set_state(run_id, status="cancelling")
        return {"ok": True, "status": "accepted"}

    def approve(self, run_id: str, approval_id: str, choice: str) -> dict[str, Any]:
        self.store.status(run_id)
        bridge_choice = "once" if choice == "session" else choice
        accepted = self.approvals.respond(approval_id, bridge_choice)
        return {
            "ok": accepted,
            "status": "accepted" if accepted else "not-active",
            "message": None if accepted else "Approval is no longer active.",
        }


class WebHandler(BaseHTTPRequestHandler):
    server_version = "JaegerRunner/1"

    @property
    def bridge(self) -> BridgeClient:
        return self.server.bridge  # type: ignore[attr-defined]

    @property
    def runner(self) -> RunnerBroker:
        return self.server.runner  # type: ignore[attr-defined]

    @property
    def store(self) -> RunStore:
        return self.server.store  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/health", "/api/health"}:
                return self._json(self.bridge.health())
            match = _RUN_ROUTE.fullmatch(parsed.path)
            if match:
                run_id, action = match.groups()
                if action == "events":
                    cursor = str(parse_qs(parsed.query).get("cursor", [""])[0] or "") or None
                    return self._json(self.store.events_after(run_id, cursor))
                if action is None:
                    return self._json(self.store.status(run_id))
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            return self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except (WebBridgeError, ValueError) as exc:
            return self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/v1/runs":
                return self._json(self.runner.start(body), HTTPStatus.CREATED)
            if _CLARIFY_ROUTE.fullmatch(parsed.path):
                return self._json({
                    "ok": False,
                    "status": "unsupported",
                    "message": "Jaeger clarification relay is not implemented.",
                }, HTTPStatus.CONFLICT)
            if _GOAL_ROUTE.fullmatch(parsed.path):
                return self._json({
                    "ok": False,
                    "status": "unsupported",
                    "message": "Jaeger goals remain Jaeger-owned.",
                }, HTTPStatus.CONFLICT)
            match = _RUN_ROUTE.fullmatch(parsed.path)
            if match:
                run_id, action = match.groups()
                if action == "cancel":
                    return self._json(self.runner.cancel(run_id))
                if action == "approval":
                    return self._json(self.runner.approve(
                        run_id,
                        str(body.get("approval_id") or ""),
                        str(body.get("choice") or "deny"),
                    ))
                if action == "messages":
                    return self._json({
                        "ok": False,
                        "status": "unsupported",
                        "message": "Queued runner messages are not implemented.",
                    }, HTTPStatus.CONFLICT)
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            return self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except (WebBridgeError, ValueError, json.JSONDecodeError) as exc:
            return self._json({"error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValueError("request body is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[jaeger-runner] {self.address_string()} {fmt % args}", flush=True)


class JaegerWebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        instance: str | None = None,
        *,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__(address, WebHandler)
        self.bridge = BridgeClient(instance)
        self.approvals = ApprovalBroker()
        state_root = Path(run_dir) if run_dir is not None else self.bridge.layout.root / "run" / "hermes-webui-adapter"
        self.store = RunStore(state_root)
        self.runner = RunnerBroker(self.bridge, self.approvals, self.store)
        self.chats = self.runner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Jaeger Hermes-WebUI runner adapter")
    parser.add_argument("--host", default=os.environ.get("JAEGER_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("JAEGER_WEB_PORT", "8791")))
    parser.add_argument("--instance", default=os.environ.get("JAEGER_INSTANCE_NAME") or None)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Jaeger runner binds to loopback only")
    server = JaegerWebServer((args.host, args.port), args.instance)
    print(f"[jaeger-runner] http://{args.host}:{args.port} · instance={server.bridge.instance}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
