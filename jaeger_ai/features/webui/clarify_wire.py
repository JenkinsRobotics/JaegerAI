"""Wire mid-turn clarify into native WebUI adapter runs.

Vendor Hermes WebUI still owns the chat-face routes on :8790
(``/api/clarify/*`` via ``vendor/hermes-webui/api/clarify.py``). Jaeger's
native runner adapter (:8791) previously stubbed clarification respond as
unsupported — this module provides the broker the adapter uses so a
``clarify`` / ``ask_user`` tool call mid-turn is no longer dead code.

Flow (native runs):
  bridge request frame kind=clarify
    → ClarifyBroker.submit + wait
    → SSE/event ``clarification`` on the run
    → POST /v1/runs/{run}/clarifications/{id}/respond
    → ClarifyBroker.respond unblocks the turn
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

# Public routes already served by vendor hermes-webui (chat UI :8790):
CLARIFY_PENDING_PATH = "/api/clarify/pending"
CLARIFY_RESPOND_PATH = "/api/clarify/respond"
CLARIFY_STREAM_PATH = "/api/clarify/stream"

# Native adapter route (Jaeger-owned runner on :8791):
ADAPTER_CLARIFY_RESPOND_PATH = "/v1/runs/{run_id}/clarifications/{clarify_id}/respond"

DEFAULT_TIMEOUT_SECONDS = 120


def vendor_clarify_module() -> str:
    """Import path of the authoritative chat-face clarify state module."""
    return "api.clarify"  # resolved inside vendor/hermes-webui runtime


class ClarifyBroker:
    """In-process pending clarify queue for native adapter runs.

    Mirrors the vendor clarify semantics (submit → wait → free-form respond)
    without importing the vendored ``api.clarify`` package into the adapter
    process.
    """

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = float(timeout_s)
        self._condition = threading.Condition()
        self._pending: dict[str, dict[str, Any]] = {}

    def submit(
        self,
        *,
        session_key: str,
        question: str,
        run_id: str = "",
        clarify_id: str | None = None,
        choices: list[str] | None = None,
    ) -> dict[str, Any]:
        """Queue one pending clarify and return the public payload."""
        cid = str(clarify_id or uuid.uuid4().hex[:12]).strip() or uuid.uuid4().hex[:12]
        now = time.time()
        with self._condition:
            entry = {
                "clarify_id": cid,
                "session_key": str(session_key or ""),
                "run_id": str(run_id or ""),
                "question": str(question or ""),
                "choices_offered": list(choices or []),
                "requested_at": now,
                "timeout_seconds": int(self._timeout),
                "expires_at": now + self._timeout if self._timeout > 0 else 0,
                "answer": None,
            }
            self._pending[cid] = entry
            self._condition.notify_all()
            return {k: v for k, v in entry.items() if k != "answer"}

    def wait(self, clarify_id: str) -> str:
        """Block until respond() or timeout. Empty string on timeout."""
        cid = str(clarify_id or "").strip()
        if not cid:
            return ""
        deadline = time.monotonic() + self._timeout if self._timeout > 0 else None
        with self._condition:
            while True:
                entry = self._pending.get(cid)
                if entry is None:
                    return ""
                answer = entry.get("answer")
                if answer is not None:
                    self._pending.pop(cid, None)
                    return str(answer)
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._pending.pop(cid, None)
                    return ""
                self._condition.wait(timeout=remaining)

    def respond(self, clarify_id: str, response: str) -> bool:
        """Resolve one pending clarify with a free-form answer."""
        cid = str(clarify_id or "").strip()
        text = str(response or "")
        if not cid:
            return False
        with self._condition:
            entry = self._pending.get(cid)
            if entry is None:
                return False
            entry["answer"] = text
            self._condition.notify_all()
            return True

    def get_pending(self, session_key: str | None = None) -> dict[str, Any] | None:
        """Oldest unresolved clarify (optionally filtered by session)."""
        with self._condition:
            rows = list(self._pending.values())
        if session_key:
            rows = [r for r in rows if r.get("session_key") == session_key]
        if not rows:
            return None
        rows.sort(key=lambda r: float(r.get("requested_at") or 0.0))
        return {k: v for k, v in rows[0].items() if k != "answer"}

    def list_pending(self) -> list[dict[str, Any]]:
        with self._condition:
            rows = [
                {k: v for k, v in row.items() if k != "answer"}
                for row in self._pending.values()
            ]
        rows.sort(key=lambda r: float(r.get("requested_at") or 0.0))
        return rows


def describe_wire() -> dict[str, Any]:
    """Machine-readable note for adapters / docs / tests."""
    return {
        "mode": "wire",
        "authority": "vendor/hermes-webui/api/clarify.py",
        "native_broker": "jaeger_ai.features.webui.clarify_wire.ClarifyBroker",
        "chat_port": 8790,
        "adapter_port": 8791,
        "routes": {
            "pending": CLARIFY_PENDING_PATH,
            "respond": CLARIFY_RESPOND_PATH,
            "stream": CLARIFY_STREAM_PATH,
            "adapter_respond": ADAPTER_CLARIFY_RESPOND_PATH,
        },
        "donor_tools": [
            "hermes-agent/tools/clarify_tool.py",
            "hermes-agent/tools/clarify_gateway.py",
        ],
        "status": "native adapter clarify broker live; vendor chat-face API remains authoritative on :8790",
    }
