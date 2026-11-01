"""Opt-in OpenCode server delegate. No server lifecycle or credentials are managed here."""

from __future__ import annotations

import asyncio
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..contracts import DelegateEvent, DelegateHandle, DelegateRequest, DelegateResult, RuntimeStatus

DEFAULT_BASE_URL = "http://127.0.0.1:4096"
CAPABILITIES = frozenset({"code", "filesystem", "terminal"})


class OpenCodeHTTPRuntime:
    runtime_id = "opencode-http"

    def __init__(self, base_url: str | None = None) -> None:
        url = (base_url or os.environ.get("JAEGER_OPENCODE_HTTP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OpenCode HTTP base URL must be a loopback HTTP URL without credentials")
        self.base_url = url
        self._tasks: dict[str, asyncio.Task[DelegateResult]] = {}
        self._sessions: dict[str, str] = {}

    def _request(self, method: str, path: str, body: dict | None = None, timeout: int = 5) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base_url + path, data=data, method=method,
                          headers={"Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"OpenCode HTTP request failed with status {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("OpenCode HTTP server is unavailable; start it explicitly before using this delegate") from exc

    async def probe(self) -> RuntimeStatus:
        try:
            await asyncio.to_thread(self._request, "GET", "/global/health")
        except (RuntimeError, ValueError, OSError):
            return RuntimeStatus(False, "OpenCode HTTP server is unavailable", CAPABILITIES, True)
        return RuntimeStatus(True, "OpenCode HTTP server available", CAPABILITIES, True)

    async def start(self, request: DelegateRequest) -> DelegateHandle:
        if request.task_id in self._tasks:
            raise ValueError("OpenCode HTTP task already started")
        if request.workspace is not None:
            raise ValueError("OpenCode HTTP delegate does not support per-request workspace selection")
        session = await asyncio.to_thread(self._request, "POST", "/session", {})
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("OpenCode HTTP server returned no session id")
        handle = DelegateHandle(request.task_id, self.runtime_id, session_id)
        self._sessions[request.task_id] = session_id
        self._tasks[request.task_id] = asyncio.create_task(self._run(session_id, request.prompt, request.timeout_seconds))
        return handle

    async def _run(self, session_id: str, prompt: str, timeout: int) -> DelegateResult:
        try:
            response = await asyncio.wait_for(asyncio.to_thread(
                self._request, "POST", f"/session/{session_id}/message",
                {"parts": [{"type": "text", "text": prompt}]}, timeout), timeout=timeout + 1)
            parts = response.get("parts", [])
            answer = "\n".join(part["text"] for part in parts if isinstance(part, dict)
                               and part.get("type") == "text" and isinstance(part.get("text"), str))
            info = response.get("info", {})
            if isinstance(info, dict) and info.get("error"):
                return DelegateResult("failed", "OpenCode HTTP session returned an error", worker_session_id=session_id)
            return DelegateResult("completed", answer or "OpenCode completed without text output", worker_session_id=session_id)
        except TimeoutError:
            return DelegateResult("blocked", "OpenCode HTTP request timed out; execution may continue on the server", worker_session_id=session_id,
                                  metadata={"execution_unknown": True})
        except RuntimeError as exc:
            return DelegateResult("failed", str(exc), worker_session_id=session_id)

    def _task(self, handle: DelegateHandle) -> asyncio.Task[DelegateResult]:
        if handle.runtime_id != self.runtime_id or self._sessions.get(handle.task_id) != handle.worker_session_id:
            raise KeyError("Unknown OpenCode HTTP delegate handle")
        return self._tasks[handle.task_id]

    async def stream(self, handle: DelegateHandle):
        task = self._task(handle)
        yield DelegateEvent(1, "started", {"session_id": handle.worker_session_id})
        result = await task
        yield DelegateEvent(2, result.status, {"summary": result.summary})

    async def result(self, handle: DelegateHandle) -> DelegateResult:
        return await self._task(handle)

    async def cancel(self, handle: DelegateHandle) -> None:
        task = self._task(handle)
        if not task.done():
            await asyncio.to_thread(self._request, "POST", f"/session/{handle.worker_session_id}/abort", {})
            task.cancel()

    async def resume(self, handle: DelegateHandle, message: str) -> DelegateHandle:
        del handle, message
        raise NotImplementedError("OpenCode HTTP resume is not supported")


def create_http_runtime(base_url: str | None = None) -> OpenCodeHTTPRuntime:
    return OpenCodeHTTPRuntime(base_url)
