"""Loopback runtime adapter for Jaeger's pinned Hermes WebUI fork.

This process does not serve the browser application. The pinned WebUI owns port
8790 and calls this service through ``runner-local``. Jaeger remains the sole
owner of inference, tools, sessions, approvals, heartbeat, and schedules.
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
_SCHEDULE_ACTION_ROUTE = re.compile(
    r"^/v1/schedules/([^/]+)/(pause|resume|cancel|run)$"
)


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

    def records_for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = [
                dict(record)
                for record in self._runs.values()
                if str(record.get("session_id") or "") == session_id
            ]
        return sorted(rows, key=lambda row: float(row.get("updated_at") or 0), reverse=True)

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


class ScheduleBroker:
    """Translate Hermes WebUI's job shape onto Jaeger's native scheduler."""

    def __init__(self, bridge_provider, runner: RunnerBroker, store: RunStore) -> None:
        self._bridge_provider = bridge_provider
        self.runner = runner
        self.store = store
        self._manual_runs: dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def bridge(self) -> BridgeClient:
        return self._bridge_provider()

    @staticmethod
    def _job(value: dict[str, Any]) -> dict[str, Any]:
        name = str(value.get("name") or value.get("id") or "").strip()
        expression = str(
            value.get("cron")
            or value.get("schedule_display")
            or value.get("schedule")
            or ""
        ).strip()
        state = "paused" if value.get("paused") or value.get("status") == "paused" else "active"
        enabled = state == "active" and not bool(value.get("cancelled"))
        kind = "once" if expression == "@once" else "cron"
        return {
            "id": name,
            "name": name,
            "prompt": str(value.get("prompt") or ""),
            "schedule": {"kind": kind, "expression": expression},
            "schedule_display": expression,
            "enabled": enabled,
            "state": state,
            "created_at": value.get("created_at"),
            "next_run_at": value.get("next_run_at"),
            "last_run_at": value.get("last_run_at"),
            "last_status": value.get("last_status"),
            "deliver": str(value.get("deliver") or "local"),
            "skills": list(value.get("skills") or []),
            "profile": value.get("profile"),
            "provider": value.get("provider"),
            "model": value.get("model"),
            "no_agent": False,
            "toast_notifications": value.get("toast_notifications") is not False,
        }

    def list(self) -> dict[str, Any]:
        payload = self.bridge.query("list_schedules")
        values = payload.get("schedules") if isinstance(payload, dict) else []
        return {
            "jobs": [self._job(row) for row in values or [] if isinstance(row, dict)],
            "all_profiles": False,
            "active_profile": "jaeger",
            "other_profile_count": 0,
        }

    def scheduler_status(self) -> dict[str, Any]:
        health = self.bridge.health()
        heartbeat = self.bridge.query("heartbeat")
        return {
            "configured": True,
            "running": bool(health.get("ok")),
            "owner": "jaeger",
            "scheduler": "jaeger",
            "heartbeat": heartbeat if isinstance(heartbeat, dict) else {},
        }

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        prompt = str(body.get("prompt") or "").strip()
        schedule = str(body.get("schedule") or "").strip()
        if not prompt or not schedule:
            raise ValueError("prompt and schedule are required")
        name = str(body.get("name") or "").strip() or None
        args = {
            "name": name,
            "schedule": schedule,
            "prompt": prompt,
            "deliver": str(body.get("deliver") or "local"),
        }
        self.bridge.command("create_schedule", args)
        job = self._job({**body, "name": name or "scheduled-job", "cron": schedule})
        try:
            listed = self.list().get("jobs") or []
            match = next((row for row in listed if row.get("id") == name), None)
            if match is not None:
                job = match
        except WebBridgeError:
            pass
        return {"ok": True, "id": job["id"], "job": job}

    def action(self, job_id: str, action: str) -> dict[str, Any]:
        job_id = str(job_id or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        command = {
            "pause": "pause_schedule",
            "resume": "resume_schedule",
            "cancel": "cancel_schedule",
        }.get(action)
        if command:
            self.bridge.command(command, {"id": job_id, "name": job_id})
            return {"ok": True, "job_id": job_id}
        if action != "run":
            raise ValueError(f"unsupported schedule action: {action}")
        job = next((row for row in self.list()["jobs"] if row["id"] == job_id), None)
        if job is None:
            raise KeyError("schedule not found")
        started = self.runner.start({
            "message": job["prompt"],
            "session_id": f"cron:{job_id}",
            "source": "schedule",
        })
        with self._lock:
            self._manual_runs[job_id] = str(started["run_id"])
        return {"ok": True, "job_id": job_id, "status": "running", **started}

    def update(self, body: dict[str, Any]) -> dict[str, Any]:
        job_id = str(body.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        current = next((row for row in self.list()["jobs"] if row["id"] == job_id), None)
        if current is None:
            raise KeyError("schedule not found")
        next_name = str(body.get("name") or current["name"]).strip() or job_id
        next_prompt = str(body.get("prompt") or current["prompt"]).strip()
        next_schedule = str(body.get("schedule") or current["schedule_display"]).strip()
        args = {
            "name": next_name,
            "schedule": next_schedule,
            "prompt": next_prompt,
            "deliver": str(body.get("deliver") or current.get("deliver") or "local"),
        }
        self.bridge.command("create_schedule", args)
        if next_name != job_id:
            self.bridge.command("cancel_schedule", {"id": job_id, "name": job_id})
        job = self._job({**current, **body, "name": next_name, "cron": next_schedule})
        return {"ok": True, "job": job}

    def status(self, job_id: str = "") -> dict[str, Any]:
        running: dict[str, float] = {}
        payload = self.bridge.query("cron")
        if isinstance(payload, dict) and isinstance(payload.get("running"), dict):
            running.update(payload["running"])
        with self._lock:
            manual = dict(self._manual_runs)
        for name, run_id in manual.items():
            try:
                state = self.store.status(run_id)
            except KeyError:
                continue
            if not state.get("terminal_state"):
                running.setdefault(name, time.time())
        if job_id:
            started = running.get(job_id)
            elapsed = max(0.0, time.time() - float(started)) if started else 0.0
            return {"job_id": job_id, "running": bool(started), "elapsed": round(elapsed, 1)}
        return {"running": running}

    def history(self, job_id: str) -> dict[str, Any]:
        rows = self.store.records_for_session(f"cron:{job_id}")
        runs = [{
            "filename": f"{row['run_id']}.md",
            "size": sum(
                len(str(event.get("payload", {}).get("text") or ""))
                for event in row.get("events") or []
            ),
            "modified": float(row.get("updated_at") or row.get("created_at") or 0),
            "usage": {},
        } for row in rows]
        return {"job_id": job_id, "runs": runs, "total": len(runs), "offset": 0}

    def run_detail(self, job_id: str, filename: str) -> dict[str, Any]:
        run_id = str(filename or "").removesuffix(".md")
        row = next(
            (item for item in self.store.records_for_session(f"cron:{job_id}")
             if str(item.get("run_id") or "") == run_id),
            None,
        )
        if row is None:
            raise KeyError("run not found")
        response = "".join(
            str(event.get("payload", {}).get("text") or "")
            for event in row.get("events") or []
            if event.get("event") == "token"
        )
        content = f"# Jaeger scheduled run\n\n## Response\n\n{response}"
        return {
            "job_id": job_id,
            "filename": filename,
            "content": content,
            "snippet": response[:600],
            "usage": {},
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

    @property
    def schedules(self) -> ScheduleBroker:
        return self.server.schedules  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in {"/health", "/api/health"}:
                return self._json(self.bridge.health())
            if parsed.path == "/v1/scheduler/status":
                return self._json(self.schedules.scheduler_status())
            if parsed.path == "/v1/schedules":
                return self._json(self.schedules.list())
            if parsed.path == "/v1/schedules/status":
                job_id = str(parse_qs(parsed.query).get("job_id", [""])[0] or "")
                return self._json(self.schedules.status(job_id))
            if parsed.path == "/v1/schedules/history":
                job_id = str(parse_qs(parsed.query).get("job_id", [""])[0] or "")
                if not job_id:
                    raise ValueError("job_id is required")
                return self._json(self.schedules.history(job_id))
            if parsed.path == "/v1/schedules/run":
                query = parse_qs(parsed.query)
                job_id = str(query.get("job_id", [""])[0] or "")
                filename = str(query.get("filename", [""])[0] or "")
                if not job_id or not filename:
                    raise ValueError("job_id and filename are required")
                return self._json(self.schedules.run_detail(job_id, filename))
            if parsed.path == "/v1/schedules/delivery-options":
                return self._json({
                    "platforms": [{"value": "local", "label": "Local (Jaeger history)"}],
                })
            if parsed.path == "/v1/schedules/recent":
                return self._json({"completions": [], "since": time.time()})
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
            if parsed.path == "/v1/schedules/create":
                return self._json(self.schedules.create(body), HTTPStatus.CREATED)
            if parsed.path == "/v1/schedules/update":
                return self._json(self.schedules.update(body))
            if parsed.path in {
                "/v1/schedules/delete",
                "/v1/schedules/run",
                "/v1/schedules/pause",
                "/v1/schedules/resume",
            }:
                action = parsed.path.rsplit("/", 1)[-1]
                if action == "delete":
                    action = "cancel"
                return self._json(self.schedules.action(
                    str(body.get("job_id") or ""), action,
                ))
            schedule_match = _SCHEDULE_ACTION_ROUTE.fullmatch(parsed.path)
            if schedule_match:
                job_id, action = schedule_match.groups()
                return self._json(self.schedules.action(job_id, action))
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
        self.schedules = ScheduleBroker(lambda: self.bridge, self.runner, self.store)
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
