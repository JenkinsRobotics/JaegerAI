"""A client of the Jaeger Gateway's public REST API.

Anything that is a way *into* Jaeger rather than a part of it — a voice
loop, a one-shot CLI prompt, a future device — reaches the Entity through
the Gateway, the process that owns execution. It must not build its own
agent, pick its own model, or open the Gateway's database; each of those
makes a second Jaeger that happens to share a name.

Standard library only, so a thin client process does not pay for aiohttp.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import time
from typing import Any
import urllib.error
import urllib.request
import uuid

from jaeger_ai.contract.ports import GATEWAY_PORT, LOOPBACK

#: Request states after which the Gateway will not change its answer.
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "execution_unknown"})
#: Event names that end a request's stream.
TERMINAL_EVENTS = frozenset({"turn.finish", "turn.failed", "turn.cancelled", "turn.unknown"})
#: A quiet stream is re-opened from its cursor after this long (the Gateway
#: sends no keep-alives while a model thinks).
STREAM_READ_TIMEOUT_S = 30.0


class GatewayUnavailable(RuntimeError):
    """The Gateway could not be reached or refused the request."""


@dataclass(frozen=True)
class TurnResult:
    """The Gateway's terminal record for one request."""

    request_id: str
    status: str
    text: str
    error: str | None = None
    model: str | None = None
    backend: str | None = None
    verification: dict[str, Any] | None = None
    submitted_at: float = 0.0
    finished_at: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ok(self) -> bool:
        return self.status == "completed" and not self.error


def gateway_base_url() -> str:
    return (os.environ.get("JAEGER_GATEWAY_URL") or f"http://{LOOPBACK}:{GATEWAY_PORT}").rstrip("/")


class GatewayTurnClient:
    """Submit turns to the resident Entity and wait for their terminal result."""

    def __init__(self, base_url: str | None = None, *, request_timeout_s: float = 15.0) -> None:
        self.base_url = (base_url or gateway_base_url()).rstrip("/")
        self.request_timeout_s = request_timeout_s

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise GatewayUnavailable(f"{method} {path}: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GatewayUnavailable(f"{method} {path}: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/health")

    def probe(self) -> dict[str, Any]:
        """Is the Gateway there to take turns? Returns its health report.

        ``/health`` answers 503 whenever any backend check is not green,
        even though the Gateway itself is up and admitting turns, so a
        report from the Gateway counts as reachable (``degraded`` says
        whether it was all green). Only a transport failure — nothing
        answering, or something that is not the Gateway — raises.
        """
        req = urllib.request.Request(self.base_url + "/health", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_s) as resp:
                report = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                report = json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                report = {}
            if report.get("service") != "jaeger-gateway":
                raise GatewayUnavailable(f"GET /health: HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise GatewayUnavailable(f"GET /health: {exc}") from exc
        return {**report, "degraded": not report.get("all_green", report.get("status") == "healthy")}

    def entity_id(self) -> str:
        return str((self.health().get("diagnostics") or {}).get("entity_id") or "")

    def ensure_session(self, session_id: str, *, title: str, source: str) -> dict[str, Any]:
        return self._call("POST", "/v1/sessions", {
            "session_id": session_id, "title": title, "profile": "jaeger", "source": source,
        })

    def submit(self, session_id: str, text: str, *, request_id: str | None = None,
               **choices: Any) -> str:
        return self._submit(session_id, text, request_id=request_id, **choices)["request_id"]

    def _submit(self, session_id: str, text: str, *, request_id: str | None = None,
                **choices: Any) -> dict[str, Any]:
        """POST a turn. ``choices`` are the admission's explicit execution
        inputs (model, provider, attachment_ids, workspace, options); a
        retry must repeat them exactly or the Gateway answers 409."""
        rid = request_id or uuid.uuid4().hex
        # Only absent/None values are dropped. [] is meaningful for a tool
        # grant or attachment list (no tools / no files) and must never be
        # widened to "unrestricted". Empty display_text is also meaningful
        # (persist nothing visible) and must not become the execution text.
        body = {"text": text, "request_id": rid}
        for key, value in choices.items():
            if value is None:
                continue
            if value == "" and key != "display_text":
                continue
            body[key] = value
        receipt = self._call("POST", f"/v1/sessions/{session_id}/turns", body)
        return {**receipt, "request_id": rid}

    def list_sessions(self) -> list[dict[str, Any]]:
        return list(self._call("GET", "/v1/sessions").get("sessions") or [])

    def get_session(self, session_id: str) -> dict[str, Any]:
        from urllib.parse import quote

        return self._call("GET", f"/v1/sessions/{quote(session_id, safe='')}")

    def cancel(self, session_id: str, request_id: str) -> dict[str, Any]:
        return self._call("POST", f"/v1/sessions/{session_id}/cancel", {"request_id": request_id})

    def steer(self, session_id: str, request_id: str, text: str) -> dict[str, Any]:
        """Inject guidance into the active admitted ReAct request."""
        return self._call("POST",
                          f"/v1/sessions/{session_id}/requests/{request_id}/steer",
                          {"text": text})

    def resolve_approval(self, approval_id: str, decision: str) -> dict[str, Any]:
        """Answer one approval: ``once`` / ``always`` / ``deny``."""
        return self._call("POST", f"/v1/approvals/{approval_id}",
                          {"decision": decision, "approved": decision != "deny"})

    def stream_turn(
        self,
        session_id: str,
        text: str,
        *,
        on_event: Any,
        request_id: str | None = None,
        timeout_s: float = 3600.0,
        **choices: Any,
    ) -> TurnResult:
        """Submit a turn and follow its durable events until the terminal one.

        ``on_event(name, data)`` receives every event of THIS request in
        order (``turn.delta``, ``turn.reasoning``, ``approval.request`` …),
        including the terminal event. The stream resumes from the last seen
        event id if the connection drops, so nothing is lost or repeated.
        """
        submitted_at = time.time()
        receipt = self._submit(session_id, text, request_id=request_id, **choices)
        rid = receipt["request_id"]
        if str(receipt.get("status") or "") in TERMINAL_STATUSES:
            return self.wait(session_id, rid, timeout_s=5, submitted_at=submitted_at)
        cursor = max(int(receipt.get("start_event_id") or 1) - 1, 0)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                for event_id, name, data in self._events(session_id, cursor):
                    cursor = event_id
                    if data.get("request_id") != rid:
                        continue
                    on_event(name, data)
                    if name in TERMINAL_EVENTS:
                        return self.wait(session_id, rid, timeout_s=5, submitted_at=submitted_at)
            except GatewayUnavailable:
                raise
            except (OSError, ValueError):
                time.sleep(0.2)   # dropped stream: resume from ``cursor``
        return TurnResult(rid, "timeout", "", error=f"no terminal result in {timeout_s:.0f}s",
                          submitted_at=submitted_at, finished_at=time.time())

    def _events(self, session_id: str, since: int):
        """Yield ``(event_id, event, data)`` from the session's SSE stream."""
        req = urllib.request.Request(
            f"{self.base_url}/v1/sessions/{session_id}/stream?last_event_id={since}",
            headers={"Accept": "text/event-stream"},
        )
        try:
            stream = urllib.request.urlopen(req, timeout=STREAM_READ_TIMEOUT_S)
        except urllib.error.HTTPError as exc:
            raise GatewayUnavailable(f"stream {session_id}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise GatewayUnavailable(f"stream {session_id}: {exc.reason}") from exc
        with stream:
            for raw in stream:
                if not raw.startswith(b"data: "):
                    continue
                record = json.loads(raw[6:])
                data = record.get("data") if isinstance(record.get("data"), dict) else {}
                yield int(record.get("event_id") or since), str(record.get("event") or ""), data

    def wait(self, session_id: str, request_id: str, *, timeout_s: float = 600.0,
             poll_s: float = 0.5, submitted_at: float | None = None) -> TurnResult:
        started = submitted_at if submitted_at is not None else time.time()
        deadline = time.monotonic() + timeout_s
        row: dict[str, Any] = {}
        while time.monotonic() < deadline:
            row = self._call("GET", f"/v1/sessions/{session_id}/requests/{request_id}")
            if str(row.get("status") or "") in TERMINAL_STATUSES:
                break
            time.sleep(poll_s)
        else:
            return TurnResult(request_id, "timeout", "", error=f"no terminal result in {timeout_s:.0f}s",
                              submitted_at=started, finished_at=time.time(), raw=row)
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        return TurnResult(
            request_id=request_id,
            status=str(row.get("status")),
            text=str(result.get("output") or ""),
            error=result.get("error"),
            model=result.get("model"),
            backend=result.get("backend"),
            verification=result.get("verification"),
            submitted_at=started,
            finished_at=time.time(),
            raw=row,
        )

    def turn(self, session_id: str, text: str, *, timeout_s: float = 600.0) -> TurnResult:
        submitted_at = time.time()
        rid = self.submit(session_id, text)
        return self.wait(session_id, rid, timeout_s=timeout_s, submitted_at=submitted_at)
