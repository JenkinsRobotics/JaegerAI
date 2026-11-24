"""Extracted Gateway turn deadline & cancellation guard (Strangler-Fig Phase 5/6).

Ensures a stalled model or tool call cannot wedge the Gateway or linger past
its configured wall-clock budget by signalling both the Gateway cancellation
registry and the live ``JaegerAgent.interrupt()`` handle immediately on timeout.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from typing import Any, Callable

# Dedicated turn worker pool so an abandoned/timed-out model turn thread NEVER
# starves asyncio's default threadpool used by session/request/health endpoints.
_TURN_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="jaeger-turn")


def resolve_turn_timeout_s() -> float | None:
    """Resolve optional per-turn wall-clock timeout from environment."""
    raw = os.environ.get("JAEGER_TURN_TIMEOUT_S", "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            return None
    if os.environ.get("JAEGER_TEST_HEADLESS", "").strip() in {"1", "true", "yes"}:
        return 300.0
    return None


async def run_turn_with_deadline(
    fn: Callable[..., dict[str, Any]],
    *args: Any,
    request_id: str,
    cancellations: Any,
    active_agents: dict[str, Any] | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Execute a synchronous turn function on the isolated turn pool with hard deadline."""
    loop = asyncio.get_running_loop()
    coro = loop.run_in_executor(_TURN_EXECUTOR, fn, *args)
    if timeout_s is None:
        return await coro
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            cancellations.cancel(str(request_id))
        except Exception:  # noqa: BLE001
            pass
        if active_agents is not None:
            agent = active_agents.get(str(request_id))
            if agent is not None and hasattr(agent, "interrupt"):
                try:
                    agent.interrupt()
                except Exception:  # noqa: BLE001
                    pass
        return {
            "error": f"Turn exceeded wall-clock timeout ({timeout_s:.0f}s)",
            "halt_reason": "timeout",
        }
