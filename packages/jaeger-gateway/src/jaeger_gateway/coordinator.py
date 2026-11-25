"""OpenCode single-fiber RunCoordinator with doorbell wake and zombie-fenced event publishing."""

from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .store import GatewayStore
from .stream import SessionEventHub

RunExecutor = Callable[[str, str, int, SessionEventHub], Mapping[str, Any]]


@dataclass
class _QueuedRun:
    session_id: str
    request_id: str
    prompt: str
    future: Future[Mapping[str, Any]]
    enqueued_at: float = field(default_factory=time.time)


class RunCoordinator:
    """Single-fiber per-session run scheduler with zero-polling doorbell wake (OpenCode pattern).

    Guarantees at most one active run per session, preserves FIFO queue order,
    mints a fresh writer generation per run on ``SessionEventHub`` so stale
    workers can never corrupt a newer turn, and wakes immediately via a
    Condition doorbell.
    """

    def __init__(
        self,
        *,
        store: GatewayStore,
        hub: SessionEventHub,
        executor: RunExecutor,
    ) -> None:
        self._store = store
        self._hub = hub
        self._executor = executor
        self._lock = threading.Lock()
        self._doorbell = threading.Condition(self._lock)
        self._queues: dict[str, deque[_QueuedRun]] = {}
        self._active_sessions: set[str] = set()
        self._closed = False
        self._fiber = threading.Thread(target=self._loop, name="jaeger-run-coordinator", daemon=True)
        self._fiber.start()

    def submit(
        self,
        session_id: str,
        prompt: str,
        *,
        request_id: str | None = None,
    ) -> tuple[str, Future[Mapping[str, Any]]]:
        """Admit a request idempotently, enqueue on the session fiber, and ring the doorbell."""
        req, is_replay = self._store.admit_request(session_id, prompt, request_id=request_id)
        rid = req["request_id"]
        fut: Future[Mapping[str, Any]] = Future()
        if is_replay and req["status"] in ("completed", "failed"):
            fut.set_result(req["result"])
            return rid, fut

        item = _QueuedRun(session_id=session_id, request_id=rid, prompt=prompt, future=fut)
        with self._doorbell:
            self._queues.setdefault(session_id, deque()).append(item)
            self._doorbell.notify_all()
        return rid, fut

    def _pop_next_ready(self) -> _QueuedRun | None:
        for sid, q in self._queues.items():
            if q and sid not in self._active_sessions:
                self._active_sessions.add(sid)
                return q.popleft()
        return None

    def _run_item(self, item: _QueuedRun) -> None:
        gen = self._hub.open_generation(item.session_id)
        try:
            self._store.set_session_status(item.session_id, "running")
            self._store.append_message(item.session_id, "user", item.prompt, metadata={"request_id": item.request_id})
            self._hub.publish(
                item.session_id,
                "run.started",
                {"request_id": item.request_id, "generation": gen},
                generation=gen,
            )
            result = dict(self._executor(item.session_id, item.prompt, gen, self._hub))
            content = str(result.get("content") or "")
            self._store.append_message(
                item.session_id,
                "assistant",
                content,
                metadata={"request_id": item.request_id, "verdict": result.get("verdict")},
            )
            self._store.settle_request(item.request_id, "completed", result)
            self._store.set_session_status(item.session_id, "idle")
            self._hub.publish(
                item.session_id,
                "run.completed",
                {"request_id": item.request_id, "verdict": result.get("verdict", "complete")},
                generation=gen,
            )
            with self._doorbell:
                self._active_sessions.discard(item.session_id)
                self._doorbell.notify_all()
            item.future.set_result(result)
        except Exception as exc:  # noqa: BLE001
            err_payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            self._store.settle_request(item.request_id, "failed", err_payload)
            self._store.set_session_status(item.session_id, "idle")
            try:
                self._hub.publish(
                    item.session_id,
                    "run.failed",
                    {"request_id": item.request_id, "error": err_payload["error"]},
                    generation=gen,
                )
            except Exception:  # noqa: BLE001
                pass
            with self._doorbell:
                self._active_sessions.discard(item.session_id)
                self._doorbell.notify_all()
            item.future.set_exception(exc)

    def _loop(self) -> None:
        while True:
            with self._doorbell:
                while not self._closed:
                    item = self._pop_next_ready()
                    if item is not None:
                        break
                    self._doorbell.wait(timeout=0.5)
                else:
                    return
            worker = threading.Thread(target=self._run_item, args=(item,), daemon=True)
            worker.start()

    def close(self) -> None:
        with self._doorbell:
            self._closed = True
            self._doorbell.notify_all()
        self._fiber.join(timeout=2.0)


__all__ = ["RunCoordinator", "RunExecutor"]
