"""Compatibility bridge over the reusable :mod:`jaeger_agent` bridge.

New JaegerAI code constructs ``jaeger_agent.AgentBridge`` with a runtime.
This adapter preserves the former ``client=`` / ``run_turn=`` constructor for
0.9 callers without retaining a second queue/session implementation.
"""

from __future__ import annotations

from typing import Any, Callable

from jaeger_agent import AgentBridge as _ReusableAgentBridge
from jaeger_agent.messages import AgentActivity, ToolEvent

TurnFn = Callable[..., dict[str, Any]]


class _BusEventAdapter:
    """Legacy event-name adapter retained for product integrations/tests."""

    def __init__(self, bus: Any) -> None:
        self._bus = bus
        self.current_session = ""

    def publish(self, event: str, **payload: Any) -> None:
        if event == "tool.progress":
            self._bus.publish(
                ToolEvent(
                    name=str(payload.get("name", "")),
                    phase=str(payload.get("phase", "start")),
                    elapsed_s=float(payload.get("elapsed_s") or 0.0),
                    detail=str(payload.get("detail", "")),
                    session=self.current_session,
                )
            )
        elif event == "agent.activity":
            self._bus.publish(
                AgentActivity(
                    kind=str(payload.get("kind", "status")),
                    text=str(payload.get("text", "")),
                    session=self.current_session,
                )
            )


class _CompatibilityRuntime:
    def __init__(self, *, client: Any, run_turn: TurnFn | None) -> None:
        self.client = client
        self._run_turn = run_turn
        self._confirmation: Any = None

    def start(self, *, events: Any, bus: Any) -> None:
        from jaeger_ai.core.mind_runtime import _PipelineEventAdapter
        from jaeger_ai.main import _pipeline

        _pipeline["event_bus"] = _PipelineEventAdapter(events)
        _pipeline["chassis_bus"] = bus
        try:
            from jaeger_agent.loop.bus_confirm import BusConfirmationProvider
            from jaeger_os.core.safety.permissions import AllowAllProvider, current_policy

            policy = current_policy()
            if not isinstance(policy.confirmation, AllowAllProvider):
                self._confirmation = BusConfirmationProvider(bus)
                policy.confirmation = self._confirmation
        except Exception:  # noqa: BLE001 - optional approval routing
            self._confirmation = None

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        if self._confirmation is not None:
            self._confirmation.current_session = session_key
        turn = self._run_turn or _default_turn_fn()
        return turn(self.client, text, session_key=session_key)

    def steer(self, text: str) -> bool:
        return _steer_active_turn(text)

    def context_detail(self, session: str) -> str:
        return _ctx_detail(session)

    def close(self) -> None:
        return None


class AgentBridge(_ReusableAgentBridge):
    """Old constructor shape backed entirely by JaegerAgent's bridge."""

    def __init__(
        self,
        *,
        bus: Any,
        client: Any = None,
        run_turn: TurnFn | None = None,
        session_key: str = "gui",
        max_queue: int = 32,
    ) -> None:
        super().__init__(
            bus=bus,
            runtime=_CompatibilityRuntime(client=client, run_turn=run_turn),
            session_key=session_key,
            max_queue=max_queue,
        )


def _steer_active_turn(text: str) -> bool:
    try:
        from jaeger_ai.main import _pipeline

        agent = _pipeline.get("active_jaeger_agent")
        return bool(agent.steer(text)) if agent is not None else False
    except Exception:  # noqa: BLE001
        return False


def _default_turn_fn() -> TurnFn:
    from jaeger_ai.main import run_for_voice

    return run_for_voice


def _ctx_detail(session: str) -> str:
    try:
        from jaeger_ai.main import last_ctx_snapshot

        snapshot = last_ctx_snapshot(session)
    except Exception:  # noqa: BLE001
        return ""
    return f"ctx {snapshot['pct']}%" if snapshot else ""


__all__ = ["AgentBridge"]
