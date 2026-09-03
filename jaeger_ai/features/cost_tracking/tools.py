"""Agent-facing budget and usage tools."""

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .store import CostStore


def _store() -> CostStore:
    from jaeger_ai.main import _pipeline

    layout = _pipeline.get("layout")
    if layout is None:
        raise RuntimeError("Jaeger instance is not bound")
    return CostStore(layout.memory_dir / "costs.db")


@register_tool_from_function(side_effect="write")
@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="cost_tracking",
    operation="budget_set",
    summary="change a durable agent spending limit",
)
def budget_set(scope: str, period: str, limit_usd: float) -> dict:
    """Set a durable USD ceiling for global or per-runtime usage."""
    try:
        with _store() as store:
            store.set_limit(scope, period, limit_usd)
        return {"ok": True, "scope": scope, "period": period, "limit_usd": limit_usd}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


@register_tool_from_function(side_effect="read")
def budget_status(scope: str = "global") -> dict:
    """Show recorded token usage, USD cost, and configured budget ceilings."""
    with _store() as store:
        return {"ok": True, **store.summary(scope)}
