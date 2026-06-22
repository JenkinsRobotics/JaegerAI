"""Bus-backed permission confirmation — the windowed/remote equivalent of
the console's ``ConsoleConfirmationProvider``.

When a tier-gated tool needs approval mid-turn, the agent loop calls
``confirm(request)`` on the worker thread. The console provider prints a
prompt; this one instead publishes an :class:`AgentRequest` on the chassis
bus and **blocks the turn** until a surface answers with an
:class:`AgentResponse` (matched by id) — the Hermes interactive
request/response pattern. Any surface (PySide6 window, Swift app via the
bridge, voice) can render the prompt and answer.

Grants mirror the console provider's two zones: ``allow`` approves this
call; ``always`` approves the skill for the rest of the session (so a
multi-step computer_use job isn't a wall of identical prompts). Timeout or
a missing surface fails safe → deny.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from jaeger_os.core.messages import AgentRequest, AgentResponse

_ALLOW = {"allow", "always", "yes", "y", "approve"}
_DEFAULT_TIMEOUT_S = 300.0


class BusConfirmationProvider:
    """A :class:`ConfirmationProvider` that asks over the bus."""

    def __init__(self, bus: Any, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
        self._bus = bus
        self._timeout = timeout_s
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}   # id → {event, answer}
        self._granted_skills: set[str] = set()          # "always" grants (session)
        self.current_session = ""                        # set by the bridge per turn
        bus.subscribe(AgentResponse.topic, self._on_response)

    def confirm(self, request: Any) -> bool:
        skill = getattr(request, "skill", "") or ""
        # Session-scoped "always" grant — stop re-asking for an approved skill.
        with self._lock:
            if skill and skill in self._granted_skills:
                return True

        rid = uuid.uuid4().hex[:12]
        event = threading.Event()
        with self._lock:
            self._pending[rid] = {"event": event, "answer": None}

        op = getattr(request, "operation", "") or "this action"
        summary = getattr(request, "summary", "") or ""
        prompt = f"Allow {skill + '.' if skill else ''}{op}?"
        if summary:
            prompt += f"  ({summary})"

        self._bus.publish(AgentRequest(
            id=rid,
            kind="approval",
            prompt=prompt,
            options=("allow", "always", "deny"),
            tool=op,
            session=self.current_session,
        ))

        answered = event.wait(self._timeout)
        with self._lock:
            answer = (self._pending.pop(rid, {}) or {}).get("answer")

        if not answered or answer is None:
            return False                                 # timeout / no surface → deny
        answer = str(answer).strip().lower()
        if answer == "always" and skill:
            with self._lock:
                self._granted_skills.add(skill)
        return answer in _ALLOW

    def _on_response(self, msg: Any) -> None:
        rid = getattr(msg, "id", "")
        with self._lock:
            slot = self._pending.get(rid)
            if slot is not None:
                slot["answer"] = getattr(msg, "answer", "")
                slot["event"].set()
