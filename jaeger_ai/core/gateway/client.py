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

    def entity_id(self) -> str:
        return str((self.health().get("diagnostics") or {}).get("entity_id") or "")

    def ensure_session(self, session_id: str, *, title: str, source: str) -> dict[str, Any]:
        return self._call("POST", "/v1/sessions", {
            "session_id": session_id, "title": title, "profile": "jaeger", "source": source,
        })

    def submit(self, session_id: str, text: str, *, request_id: str | None = None) -> str:
        rid = request_id or uuid.uuid4().hex
        self._call("POST", f"/v1/sessions/{session_id}/turns", {"text": text, "request_id": rid})
        return rid

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
