"""Mind/window runtime that submits turns to the resident Gateway.

``create_runtime`` uses this when a Jaeger Gateway is reachable, so the
windowed app and mind node do not boot a second local agent. The suite's
``JAEGER_NO_ATTACH`` gate covers this path as well as the bridge socket.
"""

from __future__ import annotations

from typing import Any

from jaeger_ai.core.runtime import attach_policy


class GatewayRuntime:
    """AgentRuntime that talks only to the Gateway's public API."""

    attached = True
    gateway = True

    def __init__(self, client: Any, health: dict[str, Any]) -> None:
        self.client = client
        self.health_report = health
        self.boot = _GatewayBoot(self)
        self._closed = False
        diagnostics = health.get("diagnostics") if isinstance(health.get("diagnostics"), dict) else {}
        self.model_name = diagnostics.get("model") or health.get("model")

    def start(self, *, events: Any, bus: Any) -> None:
        del events, bus

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        session = session_key or "gui"
        try:
            self.client.ensure_session(session, title=session, source="mind")
        except Exception as exc:  # noqa: BLE001 — an existing session is fine
            if "HTTP 409" not in str(exc) and "already" not in str(exc).lower():
                return {"text": "", "error": str(exc)}

        def _on_event(name: str, data: dict[str, Any]) -> None:
            if name == "approval.request":
                approval_id = str(data.get("approval_id") or "")
                if approval_id:
                    try:
                        self.client.resolve_approval(approval_id, "deny")
                    except Exception:  # noqa: BLE001
                        pass

        try:
            result = self.client.stream_turn(session, text, on_event=_on_event)
        except Exception as exc:  # noqa: BLE001
            return {"text": "", "error": str(exc)}
        return {
            "text": result.text or "",
            "error": result.error,
            "halt_reason": "interrupted" if result.status == "cancelled" else None,
            "execution_unknown": result.status == "execution_unknown",
        }

    def steer(self, text: str) -> bool:
        del text
        return False

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
