"""Mind/window runtime that submits turns to the resident Gateway.

``create_runtime`` uses this when a Jaeger Gateway is reachable, so the
windowed app and mind node do not boot a second local agent. The suite's
``JAEGER_NO_ATTACH`` gate covers this path as well as the bridge socket.
"""

from __future__ import annotations

import threading
from typing import Any

from jaeger_ai.core.runtime import attach_policy


class _GatewayApprovalBridge:
    """Route a Gateway approval event over the client bus, then resolve it.

    The Gateway owns the approval record and effect gate. This bridge only
    asks a real surface and forwards the operator's answer back to the owner.
    If no bus surface answers before the timeout, it fails safe by denying.
    """

    def __init__(self, client: Any, bus: Any, timeout_s: float = 300.0) -> None:
        self._client = client
        self._bus = bus
        self._timeout = timeout_s
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self.last_status = "No approval requested"
        if bus is not None:
            from jaeger_agent.core.messages import AgentResponse
            bus.subscribe(AgentResponse.topic, self._on_response)

    def handle(self, data: dict[str, Any]) -> None:
        approval_id = str(data.get("approval_id") or "")
        if not approval_id:
            return
        if self._bus is None:
            self.last_status = "No approval surface available; denied"
            self._client.resolve_approval(approval_id, "deny")
            return

        from jaeger_agent.core.messages import AgentRequest

        event = threading.Event()
        slot: dict[str, Any] = {"answer": None}
        with self._lock:
            self._pending[approval_id] = {"event": event, "slot": slot}
        prompt = str(data.get("prompt") or data.get("description") or "")
        tool = str(data.get("tool") or data.get("operation") or "")
        if not prompt:
            prompt = f"Allow {tool}?" if tool else "Allow this action?"
        options = tuple(data.get("options") or ("once", "always", "deny"))
        self._bus.publish(AgentRequest(
            id=approval_id,
            kind="approval",
            prompt=prompt,
            options=options,
            tool=tool,
            session=str(data.get("session_id") or ""),
        ))
        if not event.wait(self._timeout):
            answer = "deny"
            self.last_status = "Approval surface did not answer in time; denied"
        else:
            answer = str(slot.get("answer") or "deny").strip().lower()
        decision = "always" if answer in {"always", "allow", "yes", "y"} else (
            "once" if answer in {"once", "approve", "true", "1"} else "deny"
        )
        with self._lock:
            self._pending.pop(approval_id, None)
        self._client.resolve_approval(approval_id, decision)
        self.last_status = f"Approval resolved as {decision}"

    def _on_response(self, response: Any) -> None:
        approval_id = str(getattr(response, "id", "") or "")
        with self._lock:
            pending = self._pending.get(approval_id)
            if pending is None:
                return
            pending["slot"]["answer"] = getattr(response, "answer", "")
            pending["event"].set()


class GatewayRuntime:
    """AgentRuntime that talks only to the Gateway's public API."""

    attached = True
    gateway = True

    def __init__(self, client: Any, health: dict[str, Any]) -> None:
        self.client = client
        self.health_report = health
        self.boot = _GatewayBoot(self)
        self._closed = False
        self._events: Any = None
        self._approvals: _GatewayApprovalBridge | None = None
        self._current_session = ""
        self._current_request_id = ""
        self.steer_status = "No active Gateway turn"
        diagnostics = health.get("diagnostics") if isinstance(health.get("diagnostics"), dict) else {}
        self.model_name = diagnostics.get("model") or health.get("model")

    def start(self, *, events: Any, bus: Any) -> None:
        self._events = events
        self._approvals = _GatewayApprovalBridge(self.client, bus)

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        session = session_key or "gui"
        self._current_session = session
        self._current_request_id = ""
        self.steer_status = "Waiting for Gateway request admission"
        try:
            self.client.ensure_session(session, title=session, source="mind")
        except Exception as exc:  # noqa: BLE001 — an existing session is fine
            if "HTTP 409" not in str(exc) and "already" not in str(exc).lower():
                return {"text": "", "error": str(exc)}

        def _on_event(name: str, data: dict[str, Any]) -> None:
            if name == "approval.request" and self._approvals is not None:
                self._approvals.handle(data)
                return
            if data.get("request_id"):
                self._current_request_id = str(data["request_id"])
                self.steer_status = "Gateway turn active"

        try:
            result = self.client.stream_turn(session, text, on_event=_on_event)
        except Exception as exc:  # noqa: BLE001
            return {"text": "", "error": str(exc)}
        finally:
            self._current_request_id = ""
            self.steer_status = "No active Gateway turn"
        return {
            "text": result.text or "",
            "error": result.error,
            "halt_reason": "interrupted" if result.status == "cancelled" else None,
            "execution_unknown": result.status == "execution_unknown",
        }

    def steer(self, text: str) -> bool:
        text = str(text or "").strip()
        if not self._current_session or not self._current_request_id or not text:
            self.steer_status = "No active Gateway turn to steer"
            return False
        try:
            result = self.client.steer(self._current_session, self._current_request_id, text)
        except Exception as exc:  # noqa: BLE001 — caller may queue the turn
            self.steer_status = f"Gateway steering unavailable: {exc}"
            return False
        accepted = bool(result.get("steered"))
        self.steer_status = "Gateway steering accepted" if accepted else "Gateway rejected steering"
        return accepted

    def context_detail(self, session: str) -> str:
        del session
        return "gateway"

    def health(self) -> dict[str, Any]:
        return {
            "implementation": "jaeger-ai-gateway",
            "model": self.model_name,
            "attached": True,
            "gateway": True,
            "entity_id": (self.health_report.get("diagnostics") or {}).get("entity_id"),
            "steer_status": self.steer_status,
            "approval_status": self._approvals.last_status if self._approvals is not None else "No approval surface",
        }

    def close(self) -> None:
        self._closed = True


class _GatewayBoot:
    def __init__(self, runtime: GatewayRuntime) -> None:
        self.client = runtime
        self.layout = None

    def cleanup(self) -> None:
        self.client.close()


def try_gateway_runtime() -> GatewayRuntime | None:
    """Return a Gateway runtime when the resident Gateway answers, else None.

    Refuses when ``JAEGER_NO_ATTACH`` is set, so tests cannot proxy turns
    to the operator's Gateway the way they cannot attach to a live bridge.
    A short probe timeout keeps a down Gateway from stalling boot.
    """
    if attach_policy.attach_disabled():
        return None
    from jaeger_ai.core.gateway.client import GatewayTurnClient, GatewayUnavailable

    client = GatewayTurnClient(request_timeout_s=1.0)
    try:
        report = client.probe()
    except GatewayUnavailable:
        return None
    if report.get("service") != "jaeger-gateway":
        return None
    return GatewayRuntime(client, report)


__all__ = ["GatewayRuntime", "try_gateway_runtime"]
