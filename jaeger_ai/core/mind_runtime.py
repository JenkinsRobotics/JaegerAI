"""JaegerAI's product runtime adapter for the reusable JaegerAgent module.

JaegerAgent owns lifecycle, sessions, bus routing, the turn loop, and provider
contracts. JaegerAI owns the concrete product configuration, tools, prompts,
memory, and personality pipeline supplied through this adapter.
"""

from __future__ import annotations

from typing import Any, Mapping


def _install_bus_confirmation(bus: Any) -> Any:
    """Install approval routing without mutating JaegerOS's deny-all default."""
    from jaeger_agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider,
        PermissionPolicy,
        current_policy,
        install_policy,
    )

    policy = current_policy()
    if isinstance(policy.confirmation, AllowAllProvider):
        return None
    confirmation = BusConfirmationProvider(bus)
    install_policy(PermissionPolicy(mode=policy.mode, confirmation=confirmation))
    return confirmation


class _PipelineEventAdapter:
    """Map the JaegerAI pipeline event hook onto JaegerAgent runtime events."""

    def __init__(self, events: Any) -> None:
        self.events = events

    def publish(self, event: str, **payload: Any) -> None:
        if event == "tool.progress":
            self.events.tool(
                str(payload.get("name", "")),
                str(payload.get("phase", "start")),
                elapsed_s=float(payload.get("elapsed_s") or 0.0),
                detail=str(payload.get("detail", "")),
            )
        elif event == "agent.activity":
            self.events.activity(
                str(payload.get("kind", "status")),
                str(payload.get("text", "")),
            )


class JaegerAIRuntime:
    """Adapt JaegerAI's existing pipeline to ``jaeger_agent.AgentRuntime``."""

    def __init__(self, *, bus: Any, config: Mapping[str, Any] | None = None) -> None:
        from jaeger_ai.main import boot_for_tui

        self.bus = bus
        self.config = dict(config or {})
        self.boot = boot_for_tui(
            instance_name=self.config.get("instance_name"),
            with_memory=bool(self.config.get("with_memory", True)),
            warmup=bool(self.config.get("warmup", False)),
            prewarm_model=bool(self.config.get("prewarm_model", True)),
        )
        self.client = self.boot.client
        self._confirmation: Any = None
        self._closed = False

    def start(self, *, events: Any, bus: Any) -> None:
        from jaeger_ai.main import _pipeline

        _pipeline["event_bus"] = _PipelineEventAdapter(events)
        _pipeline["chassis_bus"] = bus
        try:
            self._confirmation = _install_bus_confirmation(bus)
        except Exception:  # noqa: BLE001 - confirmation routing is best effort
            self._confirmation = None

    def run_turn(self, text: str, *, session_key: str) -> dict[str, Any]:
        from jaeger_ai.main import run_for_voice

        if self._confirmation is not None:
            self._confirmation.current_session = session_key
        return run_for_voice(self.client, text, session_key=session_key)

    def steer(self, text: str) -> bool:
        try:
            from jaeger_ai.main import _pipeline

            agent = _pipeline.get("active_jaeger_agent")
            return bool(agent.steer(text)) if agent is not None else False
        except Exception:  # noqa: BLE001 - steering falls back to the next queued turn
            return False

    def context_detail(self, session: str) -> str:
        try:
            from jaeger_ai.main import last_ctx_snapshot

            snapshot = last_ctx_snapshot(session)
        except Exception:  # noqa: BLE001 - status enrichment is best effort
            return ""
        return f"ctx {snapshot['pct']}%" if snapshot else ""

    def health(self) -> dict[str, Any]:
        return {
            "implementation": "jaeger-ai",
            "model": str(getattr(self.client, "model_name", "")),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.boot.cleanup()


def create_runtime(*, bus: Any, config: Mapping[str, Any] | None = None) -> Any:
    """Factory consumed by JaegerAgent's manifest/programmatic API.

    If another first-party process (ARES, ``jaeger bridge``) already holds
    the instance lock and is listening on ``run/bridge.sock``, attach to
    that brain instead of calling ``boot_for_tui`` and crashing on the flock.
    """

    cfg = dict(config or {})
    from jaeger_ai.core.runtime.attached import try_attach_runtime

    attached = try_attach_runtime(instance_name=cfg.get("instance_name"))
    if attached is not None:
        return attached
    try:
        return JaegerAIRuntime(bus=bus, config=cfg)
    except RuntimeError as exc:
        if "locked by pid" not in str(exc):
            raise
        attached = try_attach_runtime(instance_name=cfg.get("instance_name"))
        if attached is not None:
            return attached
        raise


__all__ = ["JaegerAIRuntime", "create_runtime"]
